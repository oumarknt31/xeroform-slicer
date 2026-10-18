"""The parts on the plate as geometry, for drawing and checking: simplified
display meshes, parts posed (scaled and oriented) as the slicer will see them,
and the triangles of each copy where it sits."""

from __future__ import annotations

import numpy as np
import trimesh

from ..nesting import Spot
from ..orient import Angles, rotate_mesh
from ..part import place_on_platform

DISPLAY_FACES = 6000  # triangles per part in the views


def simplified(mesh: trimesh.Trimesh, faces: int = DISPLAY_FACES) -> trimesh.Trimesh:
    """A lighter copy of `mesh` for drawing: vertices close together are merged
    (vertex clustering) until about `faces` triangles are left."""
    if len(mesh.faces) <= faces:
        return mesh.copy()
    cell = float(np.sqrt(mesh.area / faces)) * 1.3
    best = mesh
    for _ in range(5):
        vertices, kept = _cluster(mesh.vertices, mesh.faces, cell)
        if len(kept) and (best is mesh or len(kept) <= len(best.faces) or len(best.faces) > faces):
            best = trimesh.Trimesh(vertices, kept, process=False)
        if len(kept) <= faces * 1.25:
            break
        cell *= np.sqrt(len(kept) / faces)
    return best if best is not mesh else mesh.copy()


def for_drawing(mesh: trimesh.Trimesh, faces: int = DISPLAY_FACES) -> trimesh.Trimesh:
    """`simplified`, with long thin triangles (flat sides of CAD parts) split up: the
    views draw back to front by each triangle's middle, which only works when no
    triangle is much bigger than its neighbours."""
    m = simplified(mesh, faces)
    limit = float(m.extents.max()) / 8
    if len(m.faces) < faces and float(m.edges_unique_length.max(initial=0)) > limit:
        vertices, kept = trimesh.remesh.subdivide_to_size(m.vertices, m.faces, max_edge=limit, max_iter=4)
        if len(kept) <= faces * 1.5:
            m = trimesh.Trimesh(vertices, kept, process=False)
    return m


def _cluster(vertices: np.ndarray, faces: np.ndarray, cell: float) -> tuple[np.ndarray, np.ndarray]:
    keys = np.floor((vertices - vertices.min(axis=0)) / cell).astype(np.int64)
    span = keys.max(axis=0) + 1
    flat = (keys[:, 0] * span[1] + keys[:, 1]) * span[2] + keys[:, 2]
    _, cluster = np.unique(flat, return_inverse=True)
    merged = np.zeros((cluster.max() + 1, 3))
    np.add.at(merged, cluster, vertices)
    merged /= np.bincount(cluster)[:, None]
    f = cluster[faces]
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    _, first = np.unique(np.sort(f, axis=1), axis=0, return_index=True)
    return merged, f[np.sort(first)]


def posed(mesh: trimesh.Trimesh, rotation: Angles, scale: float) -> trimesh.Trimesh:
    """A copy of `mesh` scaled and oriented like the slicer does, then centred on
    the plate with its lowest point at z = 0."""
    m = mesh.copy()
    if scale != 1.0:
        m.apply_scale(scale)
    rotate_mesh(m, rotation)
    place_on_platform(m)
    return m


def at_spot(triangles: np.ndarray, spot: Spot) -> np.ndarray:
    """(n, 3, 3) triangles of a posed part, turned about Z and moved to `spot`."""
    x, y, z, turn = spot
    out = _turned(triangles, int(turn))
    out += (x, y, z)
    return out


def turned_normals(normals: np.ndarray, turn: int) -> np.ndarray:
    return _turned(normals[:, None, :], turn)[:, 0, :]


def _turned(points: np.ndarray, turn: int) -> np.ndarray:
    """Points turned about Z by a multiple of 90 degrees (about the origin)."""
    out = np.array(points, dtype=np.float64)
    x, y = out[..., 0].copy(), out[..., 1].copy()
    if turn % 360 == 90:
        out[..., 0], out[..., 1] = -y, x
    elif turn % 360 == 180:
        out[..., 0], out[..., 1] = -x, -y
    elif turn % 360 == 270:
        out[..., 0], out[..., 1] = y, -x
    return out
