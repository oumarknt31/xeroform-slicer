"""Slicing configuration / machine + material profile."""

from __future__ import annotations
from dataclasses import dataclass, replace

from .laser import LaserSettings
from .layers import ScanParams
from .scan_order import SCAN_ORDERS


@dataclass
class SliceConfig:
    """All the knobs for one slice job. Tune per material (e.g. nylon PA12)."""

    layer_thickness: float = 0.1  # mm
    hatch_angle: float = 67.0  # deg, first layer
    hatch_angle_increment: float = 67.0  # deg added per layer (0 = fixed)
    hatch_distance: float = 0.2  # mm
    num_inner_contours: int = 1
    num_outer_contours: int = 1
    scan_order: str = "nearest"  # "nearest", "meander" or "raster" - see scan_order.py

    # model placement
    scale: float = 1.0  # e.g. 25.4 for a model drawn in inches
    build_volume: tuple[float, float, float] | None = None  # (x, y, z) mm; None = don't check
    part_spacing: float = 3.0  # mm between packed parts, and from the walls
    allow_rotation: bool = True  # let the packer turn parts 90 deg about Z

    # laser - placeholders until the laser is chosen and tuned on hardware
    contour_power: float = 4.0  # W
    contour_speed: float = 400.0  # mm/s
    hatch_power: float = 5.0  # W
    hatch_speed: float = 500.0  # mm/s
    jump_speed: float = 2000.0  # mm/s, laser-off moves between vectors

    # export
    export_format: str = "cli"  # key in xeroform.export.EXPORTERS
    units: float = 1.0  # mm per coordinate unit (confirm w/ firmware)

    def __post_init__(self):
        for name in (
            "layer_thickness",
            "hatch_distance",
            "units",
            "scale",
            "contour_speed",
            "hatch_speed",
            "jump_speed",
        ):
            if not getattr(self, name) > 0:
                raise ValueError(f"{name} must be > 0, got {getattr(self, name)!r}")
        for name in ("contour_power", "hatch_power", "part_spacing"):
            if not getattr(self, name) >= 0:
                raise ValueError(f"{name} must be >= 0, got {getattr(self, name)!r}")
        if self.scan_order not in SCAN_ORDERS:
            raise ValueError(f"scan_order must be one of {list(SCAN_ORDERS)}, got {self.scan_order!r}")
        if self.build_volume is not None:
            if len(self.build_volume) != 3 or not all(v > 0 for v in self.build_volume):
                raise ValueError(f"build_volume must be 3 sizes > 0 (x, y, z), got {self.build_volume!r}")
            self.build_volume = tuple(float(v) for v in self.build_volume)

    def laser_settings(self) -> LaserSettings:
        return LaserSettings(
            contour=ScanParams(power=self.contour_power, speed=self.contour_speed),
            hatch=ScanParams(power=self.hatch_power, speed=self.hatch_speed),
            jump_speed=self.jump_speed,
        )

    @property
    def hatch_energy_density(self) -> float:
        """Energy put into the powder by the fill, P / (v * h), in J/mm^2.

        The usual knob for tuning SLS: too low and the powder doesn't fuse,
        too high and it degrades or warps.
        """
        return self.hatch_power / (self.hatch_speed * self.hatch_distance)


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
