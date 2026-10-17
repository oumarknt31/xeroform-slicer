"""Laser settings and scan-time estimates (independent of the output format)."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from .layers import Layer, ScanParams


@dataclass(frozen=True)
class LaserSettings:
    """Scan parameters per vector type, plus the laser-off (jump) speed in mm/s."""
    contour: ScanParams
    hatch: ScanParams
    jump_speed: float

    def __post_init__(self):
        if not self.jump_speed > 0:
            raise ValueError(f"jump speed must be > 0 mm/s, got {self.jump_speed!r}")


@dataclass(frozen=True)
class PathLengths:
    """Distances (mm) the laser covers in one layer."""
    contour: float  # laser on, tracing outlines
    hatch: float    # laser on, filling
    jump: float     # laser off, moving between vectors


def _polyline_length(points) -> float:
    pts = np.asarray(points, dtype=float)
    return float(np.sum(np.hypot(*np.diff(pts, axis=0).T)))


def _segments_length(segments) -> float:
    segs = np.asarray(segments, dtype=float).reshape(-1, 2, 2)
    return float(np.sum(np.hypot(*(segs[:, 1] - segs[:, 0]).T)))


def path_lengths(layer: Layer) -> PathLengths:
    """Measure a layer in scan order: contours first, then hatches (as exported)."""
    starts, ends = [], []  # of every laser-on run, in scan order
    for c in layer.contours:
        pts = np.asarray(c.points, dtype=float)
        starts.append(pts[:1])
        ends.append(pts[-1:])
    for h in layer.hatches:
        segs = np.asarray(h.segments, dtype=float).reshape(-1, 2, 2)
        starts.append(segs[:, 0])
        ends.append(segs[:, 1])
    jump = 0.0
    if starts:
        starts, ends = np.concatenate(starts), np.concatenate(ends)
        jump = float(np.sum(np.hypot(*(starts[1:] - ends[:-1]).T)))
    return PathLengths(
        contour=sum(_polyline_length(c.points) for c in layer.contours),
        hatch=sum(_segments_length(h.segments) for h in layer.hatches),
        jump=jump,
    )


def layer_scan_time(layer: Layer, jump_speed: float) -> float:
    """Seconds to scan one layer at constant speeds (no acceleration, no recoating)."""
    t = path_lengths(layer).jump / jump_speed
    for item, length in [(c, _polyline_length(c.points)) for c in layer.contours] + \
                        [(h, _segments_length(h.segments)) for h in layer.hatches]:
        if item.params is None:
            raise ValueError(f"layer z={layer.z} has vectors without laser params")
        t += length / item.params.speed
    return t


def estimate_scan_time(layers: list[Layer], jump_speed: float) -> float:
    """Total laser scan time in seconds. Excludes powder recoating and heating."""
    return sum(layer_scan_time(layer, jump_speed) for layer in layers)
