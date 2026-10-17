"""Hatch/contour settings, wrapped around PySLM's Hatcher."""
from __future__ import annotations
from dataclasses import dataclass
from pyslm import hatching


@dataclass
class HatchSettings:
    """Laser scan-fill settings.

    hatch_angle     : direction of the fill lines (deg). Rotating it per build
                      spreads thermal stress; kept fixed here for a single part.
    hatch_distance  : spacing between fill lines (mm).
    num_inner/outer : number of contour passes tracing each outline.
    """
    hatch_angle: float = 67.0
    hatch_distance: float = 0.2
    num_inner_contours: int = 1
    num_outer_contours: int = 1

    def make_hatcher(self):
        h = hatching.Hatcher()
        h.hatchAngle = self.hatch_angle
        h.hatchDistance = self.hatch_distance
        h.numInnerContours = self.num_inner_contours
        h.numOuterContours = self.num_outer_contours
        return h
