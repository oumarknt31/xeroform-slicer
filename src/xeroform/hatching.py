"""Hatch/contour settings, wrapped around PySLM's Hatcher."""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from pyslm import hatching

from .scan_order import SCAN_ORDERS


class _Hatcher(hatching.Hatcher):
    """PySLM's Hatcher, fixed for regions too narrow for any hatch line.

    When no hatch line crosses a fill region (thin walls, small pins), PySLM's
    clipLines returns an empty-but-nested array that hatch() then indexes into
    and crashes. Returning a truly empty array makes hatch() skip the fill, so
    the region is scanned by its contours only - which is what we want.
    """

    @staticmethod
    def clipLines(paths, lines):
        clipped = hatching.Hatcher.clipLines(paths, lines)
        return clipped if clipped.size else np.array([])


@dataclass
class HatchSettings:
    """Laser scan-fill settings.

    hatch_angle           : first-layer hatch angle (deg), PySLM convention: the
                            fill lines run perpendicular to it (angle + 90).
    hatch_angle_increment : rotation added each layer (deg). Rotating the fill
                            spreads heat and stress evenly; 0 keeps it fixed.
    hatch_distance        : spacing between fill lines (mm).
    num_inner/outer       : number of contour passes tracing each outline.
    scan_order            : "nearest", "meander" or "raster" (see scan_order.py).
    """

    hatch_angle: float = 67.0
    hatch_angle_increment: float = 67.0
    hatch_distance: float = 0.2
    num_inner_contours: int = 1
    num_outer_contours: int = 1
    scan_order: str = "nearest"

    def __post_init__(self):
        if self.scan_order not in SCAN_ORDERS:
            raise ValueError(f"Unknown scan order {self.scan_order!r}. Available: {list(SCAN_ORDERS)}")

    def angle_for_layer(self, index: int) -> float:
        """Hatch angle (deg, in [0, 180)) for the layer at position `index`."""
        return (self.hatch_angle + index * self.hatch_angle_increment) % 180.0

    def make_hatcher(self):
        h = _Hatcher()
        h.hatchAngle = self.hatch_angle
        h.hatchDistance = self.hatch_distance
        h.numInnerContours = self.num_inner_contours
        h.numOuterContours = self.num_outer_contours
        return h
