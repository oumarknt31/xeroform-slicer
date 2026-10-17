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

# Largest model dimension (mm) outside which the units are probably wrong.
# STL has no units; inch CAD parts arrive 25.4x too small (e.g. a 5 mm "bracket").
TINY_MM = 10.0
HUGE_MM = 1000.0


class MeshError(ValueError):
    """The model can't be sliced. The message says why and what to do about it."""


@dataclass
class MeshReport:
    """What was found and fixed while loading a model."""
    triangles: int
    bodies: int
    size: tuple[float, float, float]  # mm (x, y, z), after scaling
    volume: float                     # mm^3 (summed over bodies; overlaps count twice)
    repairs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Part:
    """A 3D model loaded, checked and resting on the build platform.

    Thin wrapper over pyslm.Part so the rest of the engine never touches PySLM
    directly. The part is centred on the platform (x = y = 0 at the middle of
    the plate) with its lowest point at z = 0.

    scale        : multiply the model by this, e.g. 25.4 for a model in inches.
    build_volume : (x, y, z) in mm; a model that doesn't fit raises MeshError.
    """

    def __init__(self, mesh_path: str, name: str = "part", scale: float = 1.0,
                 build_volume: tuple[float, float, float] | None = None):
        mesh, self.report = prepare_mesh(mesh_path, scale)
        check_fits(mesh, build_volume)
        self._part = pyslm.Part(name)
        self._part.setGeometryByMesh(mesh)

    @classmethod
    def from_mesh(cls, mesh: trimesh.Trimesh, name: str = "build") -> "Part":
        """Wrap a mesh that is already checked and placed (e.g. a packed build)."""
        part = cls.__new__(cls)
        part.report = describe(mesh)
        part._part = pyslm.Part(name)
        part._part.setGeometryByMesh(mesh)
        return part

    @property
    def bounding_box(self):
        """[min_x, min_y, min_z, max_x, max_y, max_z] in mm."""
        return self._part.boundingBox

    @property
    def z_max(self) -> float:
        return float(self._part.boundingBox[5])

    def raw_slice(self, z: float):
        """Return the layer's outline polygons at height z (PySLM objects)."""
        return self._part.getVectorSlice(z)


def prepare_mesh(path: str, scale: float = 1.0) -> tuple[trimesh.Trimesh, MeshReport]:
    """Load, repair, scale and centre a model on the platform; report what happened."""
    mesh = load_mesh(path)
    with np.errstate(all="ignore"):  # trimesh divides by zero on degenerate meshes
        repairs = repair_mesh(mesh)
    if scale != 1.0:
        mesh.apply_scale(scale)
    place_on_platform(mesh)
    report = describe(mesh)
    report.repairs, report.warnings = repairs, unit_warnings(mesh)
    return mesh, report


def describe(mesh: trimesh.Trimesh) -> MeshReport:
    return MeshReport(
        triangles=len(mesh.faces),
        bodies=int(mesh.body_count),
        size=tuple(float(e) for e in mesh.extents),
        volume=float(mesh.volume),
    )


def load_mesh(path: str) -> trimesh.Trimesh:
    """Read a mesh file (STL, OBJ, PLY, 3MF, ...) into one trimesh."""
    if not os.path.isfile(path):
        raise MeshError(f"File not found: {path}")
    try:
        mesh = trimesh.load(path, force="mesh", process=False)
    except Exception as e:
        raise MeshError(f"Could not read {path} as a 3D model: {e}") from e
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise MeshError(f"{path} contains no triangles - is it a valid STL/OBJ/3MF file?")
    return mesh


def repair_mesh(mesh: trimesh.Trimesh) -> list[str]:
    """Fix common mesh problems in place. Returns what was fixed."""
    repairs = []
    mesh.merge_vertices()
    n = len(mesh.faces)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    if n != len(mesh.faces):
        repairs.append(f"removed {n - len(mesh.faces)} zero-area or duplicate triangles")
    if len(mesh.faces) == 0:
        raise MeshError("The model has no usable triangles after cleanup.")

    if not mesh.is_watertight:
        open_edges = _count_open_edges(mesh)
        trimesh.repair.fill_holes(mesh)
        if not mesh.is_watertight:
            raise MeshError(
                f"The model's surface has gaps ({open_edges} open edges) that couldn't be "
                "closed automatically, so its inside can't be worked out. Repair it in a mesh "
                "tool (e.g. Meshmixer, Blender's 3D-Print Toolbox, or PrusaSlicer's repair) "
                "and try again."
            )
        repairs.append(f"closed small holes in the surface ({open_edges} open edges)")

    if not mesh.is_winding_consistent or mesh.volume < 0:
        trimesh.repair.fix_normals(mesh, multibody=True)
        repairs.append("fixed inside-out or inconsistently oriented triangles")
    if not mesh.volume > 0:
        raise MeshError("The model encloses no volume - it may be a flat surface, not a solid.")
    return repairs


def place_on_platform(mesh: trimesh.Trimesh) -> None:
    """Centre the mesh on the plate (x = y = 0) with its lowest point at z = 0."""
    (x0, y0, z0), (x1, y1, _) = mesh.bounds
    mesh.apply_translation([-(x0 + x1) / 2, -(y0 + y1) / 2, -z0])


def unit_warnings(mesh: trimesh.Trimesh) -> list[str]:
    """Warn when the size suggests the model's units are wrong."""
    largest = float(mesh.extents.max())
    if largest < TINY_MM:
        return [f"The model is only {largest:.3g} mm across - check its units. If it was made in "
                "inches, use a scale of 25.4 (--scale 25.4); in cm use 10, in metres 1000."]
    if largest > HUGE_MM:
        return [f"The model is {largest:.0f} mm across - check its units (--scale)."]
    return []


def check_fits(mesh: trimesh.Trimesh,
               build_volume: tuple[float, float, float] | None = None) -> None:
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


def _count_open_edges(mesh: trimesh.Trimesh) -> int:
    """Edges used by only one triangle - each one is part of a gap in the surface."""
    return len(trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1))
