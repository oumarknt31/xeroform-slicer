"""Slicing configuration / machine + material profile."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class SliceConfig:
    """All the knobs for one slice job. Tune per material (e.g. nylon PA12)."""
    layer_thickness: float = 0.1      # mm
    hatch_angle: float = 67.0         # deg
    hatch_distance: float = 0.2       # mm
    num_inner_contours: int = 1
    num_outer_contours: int = 1

    # export
    export_format: str = "cli"        # key in slicerkit.export.EXPORTERS
    units: float = 1.0                # mm per coordinate unit (confirm w/ firmware)


# A couple of starting presets. Numbers are placeholders to be tuned on hardware.
PROFILES = {
    "default": SliceConfig(),
    "pa12_draft": SliceConfig(layer_thickness=0.1, hatch_distance=0.3, hatch_angle=67.0),
}


def get_profile(name: str = "default") -> SliceConfig:
    return PROFILES[name]
