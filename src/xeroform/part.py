"""Mesh loading, checking and placement, wrapped around PySLM's Part.

Real-world STL files are often messy: wrong units, duplicate or zero-area
triangles, inside-out faces, small holes. This module repairs what can be
repaired safely, refuses what can't (with a message saying what to do), and
places the part on the build platform before PySLM ever sees it.
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field

import numpy as np
import pyslm
import trimesh
from pyslm.hatching.utils import poly2Paths
from shapely.geometry import Polygon
from shapely.ops import polygonize, unary_union

from .orient import NO_ROTATION, Angles, rotate_mesh

# Largest model dimension (mm) outside which the units are probably wrong.
# STL has no units; inch CAD parts arrive 25.4x too small (e.g. a 5 mm "bracket").
TINY_MM = 10.0
HUGE_MM = 1000.0


class _NoExternalFiles(trimesh.resolvers.Resolver):
    """Refuse every file a model refers to (OBJ materials, textures, ...).

    Slicing needs only the geometry, which every supported format carries in the
    model file itself. Following references would let a crafted model make us
    open arbitrary paths - on Windows a network path (\\\\host\\share) leaks the
    user's credentials just by being opened.
    """

    def __init__(self):
        self.refused: list[str] = []

    def get(self, name):
        self.refused.append(str(name))
        raise FileNotFoundError(name)  # loaders treat this as "asset not found"

    def write(self, name, data):
        raise PermissionError(name)

    def namespaced(self, namespace):
        return self

    def keys(self):
        return []


class MeshError(ValueError):
    """The model can't be sliced. The message says why and what to do about it."""


@dataclass
class MeshReport:
    """What was found and fixed while loading a model."""

    triangles: int
    bodies: int
    size: tuple[float, float, float]  # mm (x, y, z), after scaling
    volume: float  # mm^3 (summed over bodies; overlaps count twice)
    repairs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Part:
    """A 3D model loaded, checked and resting on the build platform.

    Thin wrapper over pyslm.Part so the rest of the engine never touches PySLM
    directly. The part is centred on the platform (x = y = 0 at the middle of
    the plate) with its lowest point at z = 0.

    scale        : multiply the model by this, e.g. 25.4 for a model in inches.
    rotation     : orientation, degrees about X, then Y, then Z.
    build_volume : (x, y, z) in mm; a model that doesn't fit raises MeshError.
    """

    def __init__(
        self,
        mesh_path: str,
        name: str = "part",
        scale: float = 1.0,
        build_volume: tuple[float, float, float] | None = None,
        rotation: Angles = NO_ROTATION,
    ):
        mesh, self.report = prepare_mesh(mesh_path, scale, rotation)
        check_fits(mesh, build_volume)
        self._set_geometry(mesh, name)

    @classmethod
    def from_mesh(cls, mesh: trimesh.Trimesh, name: str = "build") -> "Part":
        """Wrap a mesh that is already checked and placed (e.g. a packed build)."""
        part = cls.__new__(cls)
        part.report = describe(mesh)
        part._set_geometry(mesh, name)
        return part

    def _set_geometry(self, mesh: trimesh.Trimesh, name: str) -> None:
        """Shells that touch or overlap another (two boxes making an L, a part and
        the cavity inside it) are cut one by one and combined, see _combined_slice;
        cutting them together leaves outlines that don't join up. All the other
        shells are cut in one go."""
        self._bounds = [float(v) for v in mesh.bounds.reshape(-1)]
        self._groups: list[list[tuple[pyslm.Part, float]]] = []
        shells = _shells(mesh)
        groups = [g for g in _touching(*_shell_bounds(mesh, shells)) if len(g) > 1] if shells.max(initial=0) else []
        if not groups:
            self._part = _pyslm_part(mesh, name)
            return
        apart = np.ones(len(mesh.faces), dtype=bool)
        for g in groups:
            bodies = []
            for i in g:
                faces = np.flatnonzero(shells == i)
                apart[faces] = False
                body = mesh.submesh([faces], append=True)
                with np.errstate(all="ignore"):  # a stray open fragment has no volume
                    bodies.append((_pyslm_part(body, name), float(np.sign(body.volume))))
            self._groups.append(bodies)
        self._part = _pyslm_part(mesh.submesh([np.flatnonzero(apart)], append=True), name) if apart.any() else None

    @property
    def bounding_box(self):
        """[min_x, min_y, min_z, max_x, max_y, max_z] in mm."""
        return self._bounds

    @property
    def z_max(self) -> float:
        return self._bounds[5]

    def raw_slice(self, z: float):
        """Return the layer's outline polygons at height z (as PySLM takes them)."""
        try:
            paths = self._part.getVectorSlice(z) if self._part is not None else []
            for group in self._groups:
                paths += _combined_slice(group, z)
            return paths
        except ValueError as e:  # the cut through the surface doesn't join up into outlines
            raise MeshError(
                f"The model's outline at z = {z:.3f} mm can't be worked out ({e}). Its surface probably "
                "crosses itself there. Repair it in a mesh tool and try again."
            ) from e


def _pyslm_part(mesh: trimesh.Trimesh, name: str) -> pyslm.Part:
    part = pyslm.Part(name)
    part.setGeometryByMesh(mesh)
    return part


def _shells(mesh: trimesh.Trimesh) -> np.ndarray:
    """The shell each face belongs to (0, 1, ...). Faces are in one shell when they share
    an edge used by just the two of them, so shells that only touch stay apart."""
    if not len(mesh.faces):
        return np.zeros(0, dtype=int)
    return trimesh.graph.connected_component_labels(mesh.face_adjacency, node_count=len(mesh.faces))


def _shell_bounds(mesh: trimesh.Trimesh, shells: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(shells, kind="stable")
    starts = np.flatnonzero(np.diff(shells[order], prepend=-1))
    tri = mesh.triangles[order]
    return np.minimum.reduceat(tri.min(axis=1), starts), np.maximum.reduceat(tri.max(axis=1), starts)


def _touching(lo: np.ndarray, hi: np.ndarray) -> list[list[int]]:
    """Group the shells whose bounding boxes (lo, hi) touch or overlap, directly or via others."""
    lo, hi = lo - 1e-6, hi + 1e-6
    count = len(lo)
    group = list(range(count))

    def root(i):
        while group[i] != i:
            group[i] = group[group[i]]
            i = group[i]
        return i

    for i in range(count):
        near = np.flatnonzero(np.all((lo[i + 1 :] <= hi[i]) & (hi[i + 1 :] >= lo[i]), axis=1)) + i + 1
        for j in near:
            group[root(int(j))] = root(i)
    out: dict[int, list[int]] = {}
    for i in range(count):
        out.setdefault(root(i), []).append(i)
    return list(out.values())


def _combined_slice(group: list[tuple[pyslm.Part, float]], z: float) -> list[np.ndarray]:
    """The outlines at z of shells that touch or overlap: solid wherever more
    shells enclose a point than inside-out ones (cavities) do."""
    shapes = []
    for shell, sign in group:
        polygons = shell.getVectorSlice(z, returnCoordPaths=False, fixPolygons=False)
        if polygons:
            shapes.append((sign, unary_union(polygons)))
    if not shapes:
        return []
    if all(sign > 0 for sign, _ in shapes):
        solid = unary_union([shape for _, shape in shapes])
    else:
        pieces = polygonize(unary_union([shape.boundary for _, shape in shapes]))
        solid = unary_union(
            [
                piece
                for piece in pieces
                if sum(sign for sign, shape in shapes if shape.contains(piece.representative_point())) > 0
            ]
        )
    solid = solid.buffer(pyslm.Part.POLYGON_FIX_EPSILON)
    polygons = [solid] if isinstance(solid, Polygon) else list(getattr(solid, "geoms", []))
    return [path for polygon in polygons if not polygon.is_empty for path in poly2Paths(polygon)]


def prepare_mesh(path: str, scale: float = 1.0, rotation: Angles = NO_ROTATION) -> tuple[trimesh.Trimesh, MeshReport]:
    """Load, repair, scale, orient and centre a model on the platform; report what happened.

    rotation : degrees about X, then Y, then Z (see `xeroform.orient`).
    """
    mesh = load_mesh(path)
    with np.errstate(all="ignore"):  # trimesh divides by zero on degenerate meshes
        repairs = repair_mesh(mesh)
    if scale != 1.0:
        mesh.apply_scale(scale)
    rotate_mesh(mesh, rotation)
    place_on_platform(mesh)
    report = describe(mesh)
    report.repairs, report.warnings = repairs, shell_warnings(mesh) + unit_warnings(mesh)
    return mesh, report


def describe(mesh: trimesh.Trimesh) -> MeshReport:
    return MeshReport(
        triangles=len(mesh.faces),
        bodies=int(mesh.body_count),
        size=tuple(float(e) for e in mesh.extents),
        volume=float(abs(mesh.volume)),
    )


def load_mesh(path: str) -> trimesh.Trimesh:
    """Read a mesh file (STL, OBJ, PLY, 3MF, ...) into one trimesh."""
    if not os.path.isfile(path):
        raise MeshError(f"File not found: {path}")
    try:
        mesh = trimesh.load(path, force="mesh", process=False, resolver=_NoExternalFiles())
    except Exception as e:
        raise MeshError(f"Could not read {path} as a 3D model: {e}") from e
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise MeshError(f"{path} contains no triangles - is it a valid STL/OBJ/3MF file?")
    return mesh


def repair_mesh(mesh: trimesh.Trimesh) -> list[str]:
    """Fix common mesh problems in place. Returns what was fixed.

    A surface can be sliced when it is closed: every edge is used by an even
    number of triangles. Two triangles per edge is the clean case; four, six...
    happen where shells touch or overlap, and slice fine. An edge used an odd
    number of times is a gap - the slice outline can't close there.
    """
    repairs = []
    mesh.merge_vertices()

    # Zero-area and duplicate triangles are usually junk, but some exporters rely
    # on them to close seams, so drop them only if that doesn't open a gap.
    keep = mesh.nondegenerate_faces() & mesh.unique_faces()
    if not keep.all():
        cleaned = mesh.copy()
        cleaned.update_faces(keep)
        if len(cleaned.faces) and _count_open_edges(cleaned) <= _count_open_edges(mesh):
            mesh.update_faces(keep)
            mesh.remove_unreferenced_vertices()
            repairs.append(f"removed {int((~keep).sum())} zero-area or duplicate triangles")

    open_edges = _count_open_edges(mesh)
    if open_edges:
        trimesh.repair.fill_holes(mesh)
        if _count_open_edges(mesh):
            raise MeshError(
                f"The model's surface has gaps ({open_edges} open edges) that couldn't be "
                "closed automatically, so its inside can't be worked out. Repair it in a mesh "
                "tool (e.g. Meshmixer, Blender's 3D-Print Toolbox, or PrusaSlicer's repair) "
                "and try again."
            )
        repairs.append(f"closed small holes in the surface ({open_edges} open edges)")

    # Triangle orientation only matters for volume and normals, not for slicing;
    # it can only be fixed reliably on a clean (manifold) surface.
    if mesh.is_watertight and (not mesh.is_winding_consistent or mesh.volume < 0):
        trimesh.repair.fix_normals(mesh, multibody=True)
        repairs.append("fixed inside-out or inconsistently oriented triangles")
    if not abs(mesh.volume) > 0:
        raise MeshError("The model encloses no volume - it may be a flat surface, not a solid.")
    return repairs


def shell_warnings(mesh: trimesh.Trimesh) -> list[str]:
    """Warn when shells touch or overlap (edges shared by more than two triangles)."""
    shared = int(np.count_nonzero(_edge_use_counts(mesh) > 2))
    if not shared:
        return []
    return [
        f"{shared} edges are shared by more than two triangles, where parts of the model "
        "touch or overlap. It is sliced as one solid - check the preview."
    ]


def place_on_platform(mesh: trimesh.Trimesh) -> None:
    """Centre the mesh on the plate (x = y = 0) with its lowest point at z = 0."""
    (x0, y0, z0), (x1, y1, _) = mesh.bounds
    mesh.apply_translation([-(x0 + x1) / 2, -(y0 + y1) / 2, -z0])


def unit_warnings(mesh: trimesh.Trimesh) -> list[str]:
    """Warn when the size suggests the model's units are wrong."""
    largest = float(mesh.extents.max())
    if largest < TINY_MM:
        return [
            f"The model is only {largest:.3g} mm across - check its units. If it was made in "
            "inches, use a scale of 25.4 (--scale 25.4); in cm use 10, in metres 1000."
        ]
    if largest > HUGE_MM:
        return [f"The model is {largest:.0f} mm across - check its units (--scale)."]
    return []


def check_fits(mesh: trimesh.Trimesh, build_volume: tuple[float, float, float] | None = None) -> None:
    """Raise MeshError if the mesh doesn't fit the build volume."""
    if build_volume is None:
        return
    ext = mesh.extents
    over = [axis for axis, e, b in zip("XYZ", ext, build_volume) if e > b]
    if over:
        raise MeshError(
            f"The model is {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm but the build volume "
            f"is {build_volume[0]:g} x {build_volume[1]:g} x {build_volume[2]:g} mm "
            f"(too big in {', '.join(over)}). Scale or rotate it to fit."
        )


def _edge_use_counts(mesh: trimesh.Trimesh) -> np.ndarray:
    """How many triangles use each distinct edge."""
    return np.unique(mesh.edges_sorted, axis=0, return_counts=True)[1]


def _count_open_edges(mesh: trimesh.Trimesh) -> int:
    """Edges used by an odd number of triangles - each one is part of a gap in the surface."""
    return int(np.count_nonzero(_edge_use_counts(mesh) % 2))
