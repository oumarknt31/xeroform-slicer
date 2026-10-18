"""Nesting: pack several parts into one build.

SLS needs no supports - the loose powder holds every part - so parts can go
anywhere in the build volume, stacked as well as side by side. Every layer costs
a powder recoat, so the packer keeps the build as low as it can: it fills the
floor first and only stacks when it has to.

Two packers, `spacing` apart and `spacing` from the chamber walls:

- pack_boxes packs bounding boxes with an extreme-point heuristic; each level
  grows as a compact, square-ish block rather than a long row.
- pack_shapes packs the parts' real shapes on a voxel grid: a part is lowered
  onto the parts already placed until it touches, so it can sit inside a ring,
  in a cup or in the corner of an L. Every part can still be lifted straight
  out, in reverse order, so nothing gets trapped.

arrange runs both and keeps the lower build. Parts may be turned about Z but are
never tipped over (orientation affects print quality). The packed group is
centred on the plate, where the powder bed is most even.
"""

from __future__ import annotations
import itertools
from dataclasses import dataclass

import numpy as np
import trimesh
from scipy.spatial import cKDTree

_TOL = 1e-9


class NestingError(ValueError):
    """The parts don't fit in the build volume."""

    placed = 0  # how many parts did fit
    placements: list = []  # where those went (not centred)


Spot = tuple[float, float, float, int]  # centre x, centre y and bottom z (mm) of a part, turn about Z (deg)


@dataclass(frozen=True)
class Placement:
    item: int  # index into the list of parts
    position: tuple[float, float, float]  # min corner of the part's box (build coords, mm)
    turn: int  # degrees about Z: 0, 90, 180 or 270
    size: tuple[float, float, float] = (0.0, 0.0, 0.0)  # box size as placed (x, y, z), mm

    @property
    def rotated(self) -> bool:
        return self.turn % 360 != 0

    @property
    def spot(self) -> Spot:
        """Where the part is, independent of its size: footprint centre, bottom, turn."""
        (x, y, z), (sx, sy, _) = self.position, self.size
        return (x + sx / 2, y + sy / 2, z, self.turn)


def placement_at(mesh: trimesh.Trimesh, item: int, spot: Spot) -> Placement:
    """The Placement that puts `mesh` (as part `item`) at `spot`."""
    x, y, z, turn = spot
    sx, sy, sz = _turned(mesh, int(turn)).extents
    return Placement(item, (x - sx / 2, y - sy / 2, z), int(turn) % 360, (float(sx), float(sy), float(sz)))


def pack_boxes(
    sizes, volume, spacing: float = 3.0, allow_rotation: bool = True, names: list[str] | None = None
) -> list[Placement]:
    """Pack boxes of `sizes` [(x, y, z), ...] into `volume` (x, y, z), keeping the build low.

    Returns one Placement per box, in input order. Positions are build
    coordinates: x and y centred on the plate (0 = middle), z from 0.
    names : what to call each part in error messages (e.g. its file name).
    """
    X, Y, Z = volume
    s = spacing
    # Inflate every box by s (so neighbours end up s apart) and shrink the floor by
    # s at the walls; the container then grows by s to absorb the last box's padding.
    W, D, H = X - s, Y - s, Z + s
    sizes = [tuple(float(v) for v in size) for size in sizes]
    names = names or [f"part {i + 1}" for i in range(len(sizes))]
    _check_each_fits(sizes, volume, spacing, allow_rotation, names)
    order = sorted(range(len(sizes)), key=lambda i: -np.prod(sizes[i]))  # biggest first

    boxes = np.empty((0, 6))  # placed, inflated: x0, y0, z0, x1, y1, z1
    points = [(0.0, 0.0, 0.0)]  # extreme points: corners where a box can go
    height = 0.0
    reach_x = reach_y = 0.0  # footprint of everything placed so far
    placements: dict[int, Placement] = {}
    left_out: list[int] = []
    for i in order:
        sx, sy, sz = sizes[i]
        # turning a (nearly) square footprint changes nothing
        turns = (False, True) if allow_rotation and abs(sx - sy) > 0.01 else (False,)
        best = None
        for rotated in turns:
            w, d, h = (sy if rotated else sx) + s, (sx if rotated else sy) + s, sz + s
            for x, y, z in points:
                if x + w > W + _TOL or y + d > D + _TOL or z + h > H + _TOL:
                    continue
                box = np.array([x, y, z, x + w, y + d, z + h])
                if _overlaps(boxes, box):
                    continue
                # keep the build low, fill bottom-up, keep the footprint compact
                rx, ry = max(reach_x, x + w), max(reach_y, y + d)
                key = (max(height, z + h), z, max(rx, ry), rx + ry, y, x)
                if best is None or key < best[0]:
                    best = (key, rotated, box)
        if best is None:
            left_out.append(i)  # keep going: smaller parts may still fit
            continue
        _, rotated, box = best
        boxes = np.vstack([boxes, box])
        height = max(height, box[5])
        reach_x, reach_y = max(reach_x, box[3]), max(reach_y, box[4])
        x0, y0, z0, x1, y1, z1 = box
        points = [p for p in points if p != (x0, y0, z0)]
        points += [(x1, y0, z0), (x0, y1, z0), (x0, y0, z1)]
        placed = (sy, sx, sz) if rotated else (sx, sy, sz)
        placements[i] = Placement(i, (x0 + s - X / 2, y0 + s - Y / 2, z0), 90 if rotated else 0, placed)
    if left_out:
        raise _left_over(left_out, len(sizes), names, volume, spacing, placements)
    return _centre([placements[i] for i in range(len(sizes))])


def _left_over(left_out: list[int], total: int, names: list[str], volume, spacing: float, placed) -> NestingError:
    counts: dict[str, int] = {}
    for i in left_out:
        counts[names[i]] = counts.get(names[i], 0) + 1
    which = ", ".join(f"{n} x{c}" if c > 1 else n for n, c in counts.items())
    X, Y, Z = volume
    error = NestingError(
        f"Only {total - len(left_out)} of {total} parts fit in the {X:g} x {Y:g} x {Z:g} mm "
        f"build volume (with {spacing:g} mm spacing). Left over: {which}. "
        "Use fewer copies, a smaller spacing, or a second build."
    )
    error.placed = total - len(left_out)
    error.placements = [placed[i] for i in sorted(placed)]
    return error


def _check_each_fits(sizes, volume, spacing, allow_rotation, names) -> None:
    X, Y, Z = volume
    for (sx, sy, sz), name in zip(sizes, names):
        footprints = [(sx, sy), (sy, sx)] if allow_rotation else [(sx, sy)]
        if sz > Z or not any(w + 2 * spacing <= X + _TOL and d + 2 * spacing <= Y + _TOL for w, d in footprints):
            hint = "" if allow_rotation else " (turning parts is switched off)"
            raise NestingError(
                f"{name} ({sx:.1f} x {sy:.1f} x {sz:.1f} mm) is too big for the "
                f"{X:g} x {Y:g} x {Z:g} mm build volume with {spacing:g} mm clearance "
                f"to the walls{hint}."
            )


def _overlaps(boxes: np.ndarray, box: np.ndarray) -> bool:
    if not len(boxes):
        return False
    return bool(
        np.any(
            (boxes[:, 0] < box[3] - _TOL)
            & (boxes[:, 3] > box[0] + _TOL)
            & (boxes[:, 1] < box[4] - _TOL)
            & (boxes[:, 4] > box[1] + _TOL)
            & (boxes[:, 2] < box[5] - _TOL)
            & (boxes[:, 5] > box[2] + _TOL)
        )
    )


def _centre(placements: list[Placement]) -> list[Placement]:
    """Shift the packed group so it sits in the middle of the plate."""
    lo = np.min([p.position[:2] for p in placements], axis=0)
    hi = np.max([np.add(p.position[:2], p.size[:2]) for p in placements], axis=0)
    dx, dy = -(lo + hi) / 2
    return [
        Placement(p.item, (p.position[0] + dx, p.position[1] + dy, p.position[2]), p.turn, p.size) for p in placements
    ]


# --- packing by shape ---------------------------------------------------------

_CELLS = 128  # voxel grid cells across the plate's longer side...
_MIN_PITCH = 0.5  # ...but no finer than this (mm)
_EMPTY = -(10**6)  # "no material" in a column


@dataclass
class _Shape:
    """A part, turned, as columns of voxels: where each column starts and ends."""

    size: np.ndarray  # (x, y, z) mm
    bottom: np.ndarray  # (w, d) lowest cell of each column, large where empty
    top: np.ndarray  # (w + 2r, d + 2r) highest cell of the part grown by the spacing, _EMPTY where none


def _turned(mesh: trimesh.Trimesh, turn: int) -> trimesh.Trimesh:
    m = mesh.copy()
    if turn:
        m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(turn), [0, 0, 1]))
    m.apply_translation(-m.bounds[0])
    return m


def _boxes(mesh: trimesh.Trimesh, pitch: float) -> np.ndarray:
    """(n, 2, 3) bounding boxes (min, max corner) of the mesh's triangles, split
    until no edge is longer than half a column: each one then touches at most
    2 x 2 columns, and claims little more than it covers."""
    vertices, faces = mesh.vertices, mesh.faces
    longest = float(np.max(mesh.edges_unique_length)) if len(mesh.edges_unique) else 0.0
    if longest > pitch / 2:
        steps = int(np.ceil(np.log2(longest / (pitch / 2)))) + 2
        vertices, faces = trimesh.remesh.subdivide_to_size(vertices, faces, max_edge=pitch / 2, max_iter=steps)
    tri = vertices[faces]
    return np.stack([tri.min(axis=1), tri.max(axis=1)], axis=1)


def _columns(boxes: np.ndarray, pitch: float, grid: tuple[int, int] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Lowest and highest cell of the part in each (pitch x pitch) column, from
    its triangles' `boxes`, with their min corner at the origin (or, on a `grid`
    of columns, anywhere: what lies outside it lands on its edge). Errs on the
    side of too much: every triangle claims each column its box touches."""
    lo = np.floor(boxes[:, 0] / pitch).astype(int)
    hi = np.floor(boxes[:, 1] / pitch).astype(int)
    w, d = grid or (max(1, int(np.ceil(e / pitch - 1e-9))) for e in boxes[:, 1, :2].max(axis=0))
    bottom = np.full((w, d), -_EMPTY, dtype=np.int64)
    top = np.full((w, d), _EMPTY, dtype=np.int64)
    for ix in (lo[:, 0], hi[:, 0]):
        for iy in (lo[:, 1], hi[:, 1]):
            cx, cy = np.clip(ix, 0, w - 1), np.clip(iy, 0, d - 1)
            np.minimum.at(bottom, (cx, cy), lo[:, 2])
            np.maximum.at(top, (cx, cy), hi[:, 2])
    return bottom, top


def _gap_offsets(spacing: float, pitch: float) -> list[tuple[int, int, int]]:
    """(dx, dy, dz): for each column offset, how many cells up a neighbour must
    stay clear so that no two cells end up closer than `spacing`."""
    r = int(np.ceil(spacing / pitch)) + 1
    offsets = []
    for a in range(-r, r + 1):
        for b in range(-r, r + 1):
            lateral = (max(abs(a) - 1, 0) ** 2 + max(abs(b) - 1, 0) ** 2) * pitch**2
            if lateral >= spacing**2 and (a, b) != (0, 0):
                continue
            q = np.sqrt(max(spacing**2 - lateral, 0.0)) / pitch
            offsets.append((a, b, int(np.ceil(q - 1e-9))))
    return offsets


def _turn(boxes: np.ndarray, turn: int) -> np.ndarray:
    """Triangle boxes turned about Z, with their min corner moved to the origin."""
    (x0, y0, z0), (x1, y1, z1) = boxes[:, 0].T, boxes[:, 1].T
    x0, y0, x1, y1 = {
        0: (x0, y0, x1, y1),
        90: (-y1, x0, -y0, x1),
        180: (-x1, -y1, -x0, -y0),
        270: (y0, -x1, y1, -x0),
    }[turn % 360]
    boxes = np.stack([np.stack([x0, y0, z0], axis=-1), np.stack([x1, y1, z1], axis=-1)], axis=1)
    return boxes - boxes[:, 0].min(axis=0)


def _grow(top: np.ndarray, offsets, out: np.ndarray, at: tuple[int, int, int] = (0, 0, 0)) -> None:
    """Raise `out` (padded by r) to the top of the part grown by the spacing; the
    part's columns start at column `at[:2]` and cell `at[2]` of `out`'s grid."""
    r = max(abs(a) for a, _, _ in offsets)
    u, v, z = at
    w, d = top.shape
    lifted = np.where(top > _EMPTY, top + z, _EMPTY)
    for a, b, c in offsets:
        view = out[u + r + a : u + r + a + w, v + r + b : v + r + b + d]
        np.maximum(view, np.where(lifted > _EMPTY, lifted + c, _EMPTY), out=view)


def _shape(boxes: np.ndarray, turn: int, pitch: float, offsets) -> _Shape:
    boxes = _turn(boxes, turn)
    bottom, top = _columns(boxes, pitch)
    r = max(abs(a) for a, _, _ in offsets)
    w, d = top.shape
    grown = np.full((w + 2 * r, d + 2 * r), _EMPTY, dtype=np.int64)
    _grow(top, offsets, grown)
    return _Shape(boxes[:, 1].max(axis=0), bottom, grown)


def _distinct_turns(mesh, turns, pitch, offsets) -> list[tuple[int, _Shape]]:
    """The part's shape at each turn, leaving out turns that look the same (a cube's)."""
    boxes = _boxes(mesh, pitch)
    distinct: list[tuple[int, _Shape]] = []
    for turn in turns:
        shape = _shape(boxes, turn, pitch, offsets)
        same = (np.array_equal(shape.bottom, o.bottom) and np.array_equal(shape.top, o.top) for _, o in distinct)
        if not any(same):
            distinct.append((turn, shape))
    return distinct


def pack_shapes(
    meshes: list[trimesh.Trimesh],
    volume,
    spacing: float = 3.0,
    allow_rotation: bool = True,
    names: list[str] | None = None,
    pinned: dict[int, Placement] | None = None,
) -> list[Placement]:
    """Pack `meshes` by their shape (see the module docstring). Same result
    format as pack_boxes; a Placement's size is the part's box as placed.

    pinned : parts that stay where they are (by index); the others are packed
    around them, and the group is not re-centred.

    Each level is filled two ways - growing as a square, and growing the least
    area - and the lower build is kept.
    """
    pinned = pinned or {}
    sizes = [tuple(float(v) for v in m.extents) for m in meshes]
    names = names or [f"part {i + 1}" for i in range(len(meshes))]
    loose = [i for i in range(len(meshes)) if i not in pinned]
    _check_each_fits([sizes[i] for i in loose], volume, spacing, allow_rotation, [names[i] for i in loose])
    shapes: dict[int, list[tuple[int, _Shape]]] = {}  # by id(mesh)
    results, errors = [], []
    for rule in ("square", "area"):
        try:
            results.append(_pack_shapes(meshes, sizes, volume, spacing, allow_rotation, names, rule, shapes, pinned))
        except NestingError as e:
            errors.append(e)
    if not results:
        raise max(errors, key=lambda e: e.placed)
    return min(results, key=_build_size)


def _pack_shapes(meshes, sizes, volume, spacing, allow_rotation, names, rule, shapes, pinned) -> list[Placement]:
    X, Y, Z = volume
    pitch = max(max(X, Y) / _CELLS, _MIN_PITCH)
    offsets = _gap_offsets(spacing, pitch)
    r = max(abs(a) for a, _, _ in offsets)
    floor_x, floor_y = X - 2 * spacing, Y - 2 * spacing  # where parts may go
    gx, gy = int(np.ceil(floor_x / pitch)), int(np.ceil(floor_y / pitch))
    skyline = np.full((gx + 2 * r, gy + 2 * r), _EMPTY, dtype=np.int64)  # top of the grown parts, padded by r
    corner = np.array([spacing - X / 2, spacing - Y / 2, 0.0])  # build coordinates of the grid's origin

    height = 0.0
    group = np.array([np.inf, np.inf, -np.inf, -np.inf])  # footprint of everything placed: x0, y0, x1, y1
    placements: dict[int, Placement] = {}
    boxes: dict[int, np.ndarray] = {}
    for i, p in pinned.items():
        if id(meshes[i]) not in boxes:
            boxes[id(meshes[i])] = _boxes(meshes[i], pitch)
        placed = _turn(boxes[id(meshes[i])], p.turn) + (np.asarray(p.position) - corner)
        _, top = _columns(placed, pitch, (gx, gy))
        _grow(top, offsets, skyline)
        x, y, z = np.asarray(p.position) - corner
        height = max(height, z + p.size[2])
        group = _grown_by(group, x, y, p.size)
        placements[i] = p

    turns = (0, 90, 180, 270) if allow_rotation else (0,)
    loose = [i for i in range(len(meshes)) if i not in pinned]
    order = sorted(loose, key=lambda i: -np.prod(sizes[i]))  # biggest first
    left_out: list[int] = []
    full: set[int] = set()  # meshes a copy of which fitted nowhere: later copies won't either
    for i in order:
        mesh = id(meshes[i])
        if mesh in full:
            left_out.append(i)
            continue
        if mesh not in shapes:
            shapes[mesh] = _distinct_turns(meshes[i], turns, pitch, offsets)
        best = None
        for turn, shape in shapes[mesh]:
            state = (height, group, bool(pinned))
            found = _lowest_spot(shape, skyline, r, (floor_x, floor_y, Z), pitch, state, rule)
            if found is not None and (best is None or found[0] < best[0]):
                best = (*found, turn, shape)
        if best is None:
            full.add(mesh)
            left_out.append(i)
            continue
        _, (u, v, z), turn, shape = best
        w, d = shape.bottom.shape
        view = skyline[u : u + w + 2 * r, v : v + d + 2 * r]
        np.maximum(view, np.where(shape.top > _EMPTY, shape.top + z, _EMPTY), out=view)
        x, y = u * pitch, v * pitch
        height = max(height, z * pitch + shape.size[2])
        group = _grown_by(group, x, y, shape.size)
        position = tuple(float(c) for c in corner + (x, y, z * pitch))
        placements[i] = Placement(i, position, turn, tuple(float(v) for v in shape.size))
    if left_out:
        raise _left_over(left_out, len(meshes), names, volume, spacing, placements)
    placed = [placements[i] for i in range(len(meshes))]
    return placed if pinned else _centre(placed)


def _grown_by(group: np.ndarray, x: float, y: float, size) -> np.ndarray:
    return np.array([min(group[0], x), min(group[1], y), max(group[2], x + size[0]), max(group[3], y + size[1])])


def _lowest_spot(shape: _Shape, skyline, r, room, pitch, state, rule):
    """Best place for `shape`: (sort key, (u, v, z) cells), or None if it fits nowhere.

    Lowest build first, then lowest spot, then the most compact group: the
    squarest ("square") or the smallest ("area"). Then, around parts placed by
    hand, the closest to their middle; otherwise the lowest-left (which leaves
    the free space in one piece)."""
    floor_x, floor_y, Z = room
    height, group, hug = state
    sx, sy, sz = shape.size
    nu = int(np.floor((floor_x - sx) / pitch + 1e-9)) + 1
    nv = int(np.floor((floor_y - sy) / pitch + 1e-9)) + 1
    if nu < 1 or nv < 1:
        return None
    # lowest cell each placement can drop to: above every grown part below it
    z = np.zeros((nu, nv), dtype=np.int64)
    filled = np.argwhere(shape.bottom < -_EMPTY)
    for cx, cy in filled:
        below = skyline[r + cx : r + cx + nu, r + cy : r + cy + nv]
        np.maximum(z, below - shape.bottom[cx, cy] + 1, out=z)
    top = z * pitch + sz
    fits = top <= Z + 1e-9
    if not fits.any():
        return None
    u, v = np.nonzero(fits)
    z, top = z[u, v], top[u, v]
    x, y = u * pitch, v * pitch
    if np.isfinite(group).all():
        x0, y0 = np.minimum(group[0], x), np.minimum(group[1], y)
        x1, y1 = np.maximum(group[2], x + sx), np.maximum(group[3], y + sy)
        middle = np.hypot(x + sx / 2 - (group[0] + group[2]) / 2, y + sy / 2 - (group[1] + group[3]) / 2)
    else:  # the first part: into the corner
        x0, y0, x1, y1 = x, y, x + sx, y + sy
        middle = x + y
    w, d = x1 - x0, y1 - y0
    square, area = np.round(np.maximum(w, d), 6), np.round(w * d, 3)
    compact = (square, np.round(w + d, 6)) if rule == "square" else (area, square)
    near = (np.round(middle, 6),) if hug else ()
    keys = (np.round(np.maximum(height, top), 6), z, *compact, *near, v, u)
    k = np.lexsort(keys[::-1])[0]
    return tuple(float(key[k]) for key in keys), (int(u[k]), int(v[k]), int(z[k]))


def arrange(
    meshes: list[trimesh.Trimesh],
    volume,
    spacing: float = 3.0,
    allow_rotation: bool = True,
    names: list[str] | None = None,
    spots: dict[int, Spot] | None = None,
) -> tuple[trimesh.Trimesh, list[Placement]]:
    """Pack `meshes` into `volume` and merge them into one mesh, ready to slice.

    Packs by box and by shape and keeps the lower build (then the smaller
    footprint). Parts with a `spots` entry stay there and the rest are packed
    around them. The same mesh object may appear several times (copies); each
    gets its own place.
    """
    return place(meshes, placements := plan(meshes, volume, spacing, allow_rotation, names, spots)), placements


def plan(
    meshes: list[trimesh.Trimesh],
    volume,
    spacing: float = 3.0,
    allow_rotation: bool = True,
    names: list[str] | None = None,
    spots: dict[int, Spot] | None = None,
) -> list[Placement]:
    """Where `arrange` puts every part, without moving any mesh."""
    if spots:
        pinned = {i: placement_at(meshes[i], i, spot) for i, spot in spots.items()}
        if len(pinned) == len(meshes):
            return [pinned[i] for i in range(len(meshes))]
        return pack_shapes(meshes, volume, spacing, allow_rotation, names, pinned)
    results, errors = [], []
    try:
        results.append(pack_boxes([m.extents for m in meshes], volume, spacing, allow_rotation, names))
    except NestingError as e:
        errors.append(e)
    tallest = max(m.extents[2] for m in meshes)
    if not results or _build_size(results[0])[0] > tallest + 1e-6:  # shapes might do better
        try:
            results.append(pack_shapes(meshes, volume, spacing, allow_rotation, names))
        except NestingError as e:
            errors.append(e)
    if not results:
        raise max(errors, key=lambda e: e.placed)
    return min(results, key=_build_size)


@dataclass(frozen=True)
class Problem:
    message: str
    parts: tuple[int, ...]  # indices of the parts involved


def problems(
    meshes: list[trimesh.Trimesh],
    placements: list[Placement],
    volume,
    spacing: float,
    names: list[str] | None = None,
    samples: int = 60000,
) -> list[Problem]:
    """What's wrong with a build laid out by hand: parts outside the chamber or
    closer than `spacing` to its walls or to each other. Empty if all is well.

    Distances are measured between points on the surfaces (up to `samples` per
    part, about half a millimetre apart), so a part is never reported too close
    when it isn't, but one closer than the spacing by less than that can be
    missed.
    """
    X, Y, Z = volume
    names = names or [f"part {i + 1}" for i in range(len(placements))]
    parts = [_turned(meshes[p.item], p.turn).apply_translation(p.position) for p in placements]
    found = []
    room = np.array([X / 2 - spacing, Y / 2 - spacing]) + 1e-6
    for i, (name, m) in enumerate(zip(names, parts)):
        (x0, y0, z0), (x1, y1, z1) = m.bounds
        if (np.abs([x0, x1, y0, y1]) > np.repeat(room, 2)).any():
            found.append(Problem(f"{name} is closer than {spacing:g} mm to the chamber wall.", (i,)))
        if z0 < -1e-6 or z1 > Z + 1e-6:
            found.append(Problem(f"{name} sticks out of the build volume ({z0:.1f} to {z1:.1f} mm high).", (i,)))
    clouds: dict[int, tuple[np.ndarray, cKDTree]] = {}

    def cloud(i):
        if i not in clouds:
            m = parts[i]
            count = int(min(max(m.area / 0.25, 2000), samples))
            points, _ = trimesh.sample.sample_surface(m, count, seed=0)
            points = np.vstack([points, m.vertices])
            clouds[i] = (points, cKDTree(points))
        return clouds[i]

    for a, b in itertools.combinations(range(len(parts)), 2):
        lo, hi = parts[a].bounds, parts[b].bounds
        if (np.maximum(lo[0] - hi[1], hi[0] - lo[1]) >= spacing).any():
            continue  # their boxes are far enough apart
        (pa, ta), (pb, _) = cloud(a), cloud(b)
        gap = float(ta.query(pb, distance_upper_bound=spacing)[0].min())
        inside = _inside(parts[b], pa[0]) or _inside(parts[a], pb[0])
        if inside or gap < spacing:
            how = "inside each other" if inside else f"{gap:.1f} mm apart (spacing {spacing:g} mm)"
            found.append(Problem(f"{names[a]} and {names[b]} are {how}.", (a, b)))
    return found


def _inside(mesh: trimesh.Trimesh, point: np.ndarray) -> bool:
    """Is `point` inside the closed `mesh`? Counts the surfaces above it."""
    px, py = point[:2] + (1.234e-7, 2.345e-7)  # off the edges, so no triangle counts twice
    tri = mesh.triangles
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = (tri[:, k].T for k in range(3))
    det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    with np.errstate(divide="ignore", invalid="ignore"):
        u = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / det
        v = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / det
    w = 1 - u - v
    hit = (det != 0) & (u >= 0) & (v >= 0) & (w >= 0)
    z = u * az + v * bz + w * cz
    return bool(np.count_nonzero(hit & (z > point[2])) % 2)


def _build_size(placements: list[Placement]) -> tuple[float, float]:
    lo = np.min([p.position for p in placements], axis=0)
    hi = np.max([np.add(p.position, p.size) for p in placements], axis=0)
    return round(float(hi[2]), 6), float(np.prod(hi[:2] - lo[:2]))


def place(meshes: list[trimesh.Trimesh], placements: list[Placement]) -> trimesh.Trimesh:
    """Merge copies of `meshes` turned and moved to their `placements`."""
    return trimesh.util.concatenate([_turned(meshes[p.item], p.turn).apply_translation(p.position) for p in placements])
