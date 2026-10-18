"""Part orientation: rotations, laying a part flat on a face, lowest build height.

Orientations are angles in degrees about the fixed X, Y and Z axes, applied in
that order. The searches work on the part's convex hull (the surface it rests
on), so they stay fast on large meshes.
"""

from __future__ import annotations
import warnings

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation
from shapely.geometry import MultiPoint

Angles = tuple[float, float, float]
NO_ROTATION: Angles = (0.0, 0.0, 0.0)

_DOWN = np.array([0.0, 0.0, -1.0])
_SAME_HEIGHT_MM = 0.01  # orientations closer than this count as equally low


def matrix(angles: Angles) -> np.ndarray:
    """3 x 3 rotation matrix for `angles` (degrees about X, then Y, then Z)."""
    return Rotation.from_euler("xyz", angles, degrees=True).as_matrix()


def angles_of(rot: np.ndarray | Rotation) -> Angles:
    """The X, Y, Z angles (degrees, each in (-180, 180]) of a rotation.

    Every rotation has two sets of angles; this picks the one with the smallest
    turns, so (0, 90, 0) rather than (180, -90, 180).
    """
    rot = rot if isinstance(rot, Rotation) else Rotation.from_matrix(rot)
    with warnings.catch_warnings():  # at a 90 degree tilt the X and Z turns are one: either form is fine
        warnings.simplefilter("ignore", UserWarning)
        x, y, z = rot.as_euler("xyz", degrees=True)
    other = (x + 180, 180 - y, z + 180)
    options = [tuple(_tidy(_wrap(a)) for a in angles) for angles in ((x, y, z), other)]
    return min(options, key=lambda angles: sum(abs(a) for a in angles))


def _wrap(a: float) -> float:
    """Angle in (-180, 180]."""
    return 180.0 - (180.0 - a) % 360.0


def _tidy(a: float) -> float:
    a = round(float(a), 3)
    if abs(a) < 1e-6:
        return 0.0
    return 180.0 if a <= -180.0 + 1e-6 else a


def is_identity(angles: Angles) -> bool:
    return np.allclose(matrix(angles), np.eye(3), atol=1e-9)


def rotate_mesh(mesh: trimesh.Trimesh, angles: Angles) -> None:
    """Rotate `mesh` in place about its own centre."""
    if is_identity(angles):
        return
    transform = np.eye(4)
    transform[:3, :3] = matrix(angles)
    centre = mesh.bounds.mean(axis=0)
    mesh.apply_translation(-centre)
    mesh.apply_transform(transform)


def turn(angles: Angles, axis: str, degrees: float) -> Angles:
    """`angles` followed by a turn of `degrees` about the fixed `axis` ("x", "y" or "z")."""
    step = Rotation.from_euler(axis, degrees, degrees=True)
    return angles_of(step * Rotation.from_euler("xyz", angles, degrees=True))


def extents(points: np.ndarray, angles: Angles) -> np.ndarray:
    """Size (x, y, z) of `points` after rotating them by `angles`."""
    rotated = np.asarray(points, dtype=float) @ matrix(angles).T
    return np.ptp(rotated, axis=0)


def flat_faces(points: np.ndarray, limit: int = 12) -> list[tuple[np.ndarray, float]]:
    """The faces a part can rest on: (outward normal, area) of its convex hull's
    flat faces, largest first, at most `limit`."""
    hull = trimesh.convex.convex_hull(np.asarray(points, dtype=float))
    in_facet = np.zeros(len(hull.faces), dtype=bool)
    faces = []
    for facet, normal, area in zip(hull.facets, hull.facets_normal, hull.facets_area):
        in_facet[facet] = True
        faces.append((np.asarray(normal), float(area)))
    for i in np.flatnonzero(~in_facet):  # single triangles are flat faces too
        faces.append((hull.face_normals[i], float(hull.area_faces[i])))
    faces.sort(key=lambda f: -f[1])
    distinct: list[tuple[np.ndarray, float]] = []
    for normal, area in faces:
        if all(np.dot(normal, n) < 0.9998 for n, _ in distinct):  # ~1 degree apart
            distinct.append((normal, area))
        if len(distinct) == limit:
            break
    return distinct


def lay_flat(points: np.ndarray, face: int = 0) -> Angles:
    """Orientation that rests the part on its `face`-th largest flat face (0 = largest)."""
    faces = flat_faces(points)
    normal, _ = faces[face % len(faces)]
    return _settle(points, _onto_plate(normal))


def onto_face(points: np.ndarray, normal: np.ndarray) -> Angles:
    """Orientation that rests the part on the face with outward `normal` (in the
    model's own frame), e.g. a face clicked in a 3D view."""
    normal = np.asarray(normal, dtype=float)
    return _settle(points, _onto_plate(normal / np.linalg.norm(normal)))


def lowest(points: np.ndarray) -> Angles:
    """Orientation with the lowest build height (fewest layers). Among equally low
    ones, the one resting on the largest face."""
    points = np.asarray(points, dtype=float)
    best = None
    for normal, area in flat_faces(points, limit=32):
        rot = _onto_plate(normal)
        height = float(np.ptp((points @ rot.as_matrix().T)[:, 2]))
        key = (round(height / _SAME_HEIGHT_MM), -area)
        if best is None or key < best[0]:
            best = (key, rot)
    return _settle(points, best[1])


def _onto_plate(normal: np.ndarray) -> Rotation:
    """Rotation that turns the face with outward `normal` to face straight down."""
    normal = np.asarray(normal, dtype=float)
    if np.dot(normal, _DOWN) < -1 + 1e-9:  # facing straight up: turn over about X
        return Rotation.from_euler("x", 180, degrees=True)
    rot, _ = Rotation.align_vectors([_DOWN], [normal])
    return rot


def _settle(points: np.ndarray, rot: Rotation) -> Angles:
    """`rot`, then turned about Z so the footprint's tightest rectangle lines up
    with the axes, long side along X. That keeps packing boxes small."""
    xy = (np.asarray(points, dtype=float) @ rot.as_matrix().T)[:, :2]
    rect = MultiPoint([tuple(p) for p in xy]).minimum_rotated_rectangle
    if rect.geom_type == "Polygon":
        c = np.asarray(rect.exterior.coords)[:4]
        sides = [c[1] - c[0], c[2] - c[1]]
        longest = max(sides, key=lambda v: np.hypot(*v))
        spin = -np.degrees(np.arctan2(longest[1], longest[0]))
        rot = Rotation.from_euler("z", spin, degrees=True) * rot
    return angles_of(rot)
