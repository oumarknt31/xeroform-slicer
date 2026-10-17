"""Slicing configuration / machine + material profile."""
from __future__ import annotations
from dataclasses import dataclass, replace


@dataclass
class SliceConfig:
    """All the knobs for one slice job. Tune per material (e.g. nylon PA12)."""
    layer_thickness: float = 0.1      # mm
    hatch_angle: float = 67.0         # deg, first layer
    hatch_angle_increment: float = 67.0  # deg added per layer (0 = fixed)
    hatch_distance: float = 0.2       # mm
    num_inner_contours: int = 1
    num_outer_contours: int = 1

    # export
    export_format: str = "cli"        # key in slicerkit.export.EXPORTERS
    units: float = 1.0                # mm per coordinate unit (confirm w/ firmware)

    def __post_init__(self):
        for name in ("layer_thickness", "hatch_distance", "units"):
            if not getattr(self, name) > 0:
                raise ValueError(f"{name} must be > 0, got {getattr(self, name)!r}")


# A couple of starting presets. Numbers are placeholders to be tuned on hardware.
PROFILES = {
    "default": SliceConfig(),
    "pa12_draft": SliceConfig(layer_thickness=0.1, hatch_distance=0.3, hatch_angle=67.0),
}


def get_profile(name: str = "default") -> SliceConfig:
    """Return a copy of a preset, so callers can tweak it without changing the preset."""
    try:
        return replace(PROFILES[name])
    except KeyError:
        raise ValueError(f"Unknown profile {name!r}. Available: {list(PROFILES)}") from None
