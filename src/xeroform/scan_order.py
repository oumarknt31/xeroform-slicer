"""Hatch scan order: the sequence and direction in which fill vectors are scanned.

PySLM returns hatch vectors line by line, all pointing the same way, so after
every vector the laser jumps back across the part with the beam off. Re-ordering
happens here, on XeroForm's own model, so it doesn't depend on PySLM.

  nearest : always continue with the closest unscanned vector end. The default:
            on real parts it gave the least laser-off travel, especially with
            holes or separate islands, for ~10% more slicing time.
  meander : alternate the direction on each hatch line (zig-zag), sweeping
            evenly across the whole layer, holes and gaps included.
  raster  : PySLM's order - every vector in the same direction.
"""

from __future__ import annotations
import numpy as np
from scipy.spatial import cKDTree

SCAN_ORDERS = ("nearest", "meander", "raster")

# Vectors whose centres are this close across the hatch direction (mm) are on
# the same hatch line. Far below any real hatch spacing, far above clipper noise.
_LINE_TOL = 1e-3


def order_segments(segments: np.ndarray, mode: str = "nearest", start: np.ndarray | None = None) -> np.ndarray:
    """Return the (M, 2, 2) hatch `segments` re-ordered for scanning.

    start : where the laser is before the first vector (used by "nearest").
    """
    if mode not in SCAN_ORDERS:
        raise ValueError(f"Unknown scan order {mode!r}. Available: {list(SCAN_ORDERS)}")
    segs = np.asarray(segments, dtype=float).reshape(-1, 2, 2)
    if len(segs) < 2 or mode == "raster":
        return segs
    if mode == "meander":
        return _meander(segs)
    return _nearest(segs, segs[0, 0] if start is None else np.asarray(start, dtype=float))


def _meander(segs: np.ndarray) -> np.ndarray:
    # unit vector along the hatch lines, and across them
    d = segs[0, 1] - segs[0, 0]
    d /= np.hypot(*d)
    n = np.array([-d[1], d[0]])

    segs = segs.copy()
    backwards = (segs[:, 1] - segs[:, 0]) @ d < 0
    segs[backwards] = segs[backwards, ::-1]  # all vectors point along +d

    mid = segs.mean(axis=1)
    across, along = mid @ n, mid @ d
    by_across = np.argsort(across, kind="stable")
    line = np.concatenate([[0], np.cumsum(np.diff(across[by_across]) > _LINE_TOL)])

    # line by line; within a line along +d on even lines, along -d on odd lines
    along_key = np.where(line % 2 == 0, along[by_across], -along[by_across])
    perm = np.lexsort((along_key, line))
    out = segs[by_across[perm]]
    odd = line[perm] % 2 == 1
    out[odd] = out[odd, ::-1]
    return out


def _nearest(segs: np.ndarray, pos: np.ndarray) -> np.ndarray:
    n = len(segs)
    tree = cKDTree(segs.reshape(-1, 2))  # endpoint 2i = start of vector i, 2i+1 = its end
    done = np.zeros(n, dtype=bool)
    out = np.empty_like(segs)
    for i in range(n):
        k = 8
        while True:  # widen the search until an unscanned vector end turns up
            _, idx = tree.query(pos, k=min(k, 2 * n))
            idx = np.atleast_1d(idx)
            free = idx[~done[idx // 2]]
            if len(free) or k >= 2 * n:
                break
            k *= 4
        j = free[0]
        seg = segs[j // 2] if j % 2 == 0 else segs[j // 2, ::-1]
        out[i] = seg
        done[j // 2] = True
        pos = seg[1]
    return out
