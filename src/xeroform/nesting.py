"""Nesting: pack several parts into one build.

SLS needs no supports - the loose powder holds every part - so parts can go
anywhere in the build volume, stacked as well as side by side. Every layer costs
a powder recoat, so the packer keeps the build as low as it can: it fills the
floor first and only stacks when it has to.

Parts are packed as their bounding boxes, `spacing` apart and `spacing` from the
chamber walls, using an extreme-point heuristic. Each level grows as a compact,
square-ish block rather than a long row. Parts may be turned 90 degrees
about Z but are never tipped over (orientation affects print quality). The
packed group is centred on the plate, where the powder bed is most even.
"""

from __future__ import annotations
from dataclasses import dataclass

import numpy as np
import trimesh

_TOL = 1e-9


class NestingError(ValueError):
    """The parts don't fit in the build volume."""


@dataclass(frozen=True)
class Placement:
    item: int  # index into the list of parts
    position: tuple[float, float, float]  # min corner of the part's box (build coords, mm)
    rotated: bool  # turned 90 degrees about Z
    size: tuple[float, float, float] = (0.0, 0.0, 0.0)  # box size as placed (x, y, z), mm


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
        placements[i] = Placement(i, (x0 + s - X / 2, y0 + s - Y / 2, z0), rotated, placed)
    if left_out:
        counts: dict[str, int] = {}
        for i in left_out:
            counts[names[i]] = counts.get(names[i], 0) + 1
        which = ", ".join(f"{n} x{c}" if c > 1 else n for n, c in counts.items())
        raise NestingError(
            f"Only {len(placements)} of {len(sizes)} parts fit in the {X:g} x {Y:g} x {Z:g} mm "
            f"build volume (with {s:g} mm spacing). Left over: {which}. "
            "Use fewer copies, a smaller spacing, or a second build."
        )
    return _centre([placements[i] for i in range(len(sizes))], sizes)


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


def _footprint(p: Placement, size) -> tuple[float, float]:
    return (size[1], size[0]) if p.rotated else (size[0], size[1])


def _centre(placements: list[Placement], sizes) -> list[Placement]:
    """Shift the packed group so it sits in the middle of the plate."""
    lo = np.min([p.position[:2] for p in placements], axis=0)
    hi = np.max([np.add(p.position[:2], _footprint(p, sizes[p.item])) for p in placements], axis=0)
    dx, dy = -(lo + hi) / 2
    return [
        Placement(p.item, (p.position[0] + dx, p.position[1] + dy, p.position[2]), p.rotated, p.size)
        for p in placements
    ]


def arrange(
    meshes: list[trimesh.Trimesh],
    volume,
    spacing: float = 3.0,
    allow_rotation: bool = True,
    names: list[str] | None = None,
) -> tuple[trimesh.Trimesh, list[Placement]]:
    """Pack `meshes` into `volume` and merge them into one mesh, ready to slice.

    The same mesh object may appear several times (copies); each gets its own place.
    """
    placements = pack_boxes([m.extents for m in meshes], volume, spacing, allow_rotation, names)
    turn = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1])
    placed = []
    for p in placements:
        m = meshes[p.item].copy()
        if p.rotated:
            m.apply_transform(turn)
        m.apply_translation(np.asarray(p.position) - m.bounds[0])
        placed.append(m)
    return trimesh.util.concatenate(placed), placements
