"""Hatch/contour settings, wrapped around PySLM's Hatcher."""
from __future__ import annotations
from dataclasses import dataclass
from pyslm import hatching


@dataclass
class HatchSettings:
    """Laser scan-fill settings.

    hatch_angle           : first-layer hatch angle (deg), PySLM convention: the
                            fill lines run perpendicular to it (angle + 90).
    hatch_angle_increment : rotation added each layer (deg). Rotating the fill
                            spreads heat and stress evenly; 0 keeps it fixed.
    hatch_distance        : spacing between fill lines (mm).
    num_inner/outer       : number of contour passes tracing each outline.
    """
    hatch_angle: float = 67.0
    hatch_angle_increment: float = 67.0
    hatch_distance: float = 0.2
    num_inner_contours: int = 1
    num_outer_contours: int = 1

    def angle_for_layer(self, index: int) -> float:
        """Hatch angle (deg, in [0, 180)) for the layer at position `index`."""
        return (self.hatch_angle + index * self.hatch_angle_increment) % 180.0

    def make_hatcher(self):
        h = hatching.Hatcher()
        h.hatchAngle = self.hatch_angle
        h.hatchDistance = self.hatch_distance
        h.numInnerContours = self.num_inner_contours
        h.numOuterContours = self.num_outer_contours
        return h
