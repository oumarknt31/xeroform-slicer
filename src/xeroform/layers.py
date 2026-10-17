"""XeroForm's own layer data model.

This is the wrapper boundary: PySLM produces its own geometry objects, and we
translate them into these plain, well-named structures exactly once (in
`slicing.py`). Everything downstream - the exporters, the tests - only ever sees
these classes, never PySLM. If PySLM is ever swapped out, only the translation
changes; this model and the exporters do not.

Orientation convention (same as the CLI spec): outer outlines run
counter-clockwise, holes run clockwise.

Laser parameters are stored in physical units (W, mm/s). Converting them to what
a controller expects (percent, PWM duty, G-code S/F words) is the exporter's job.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np


def signed_area(points: np.ndarray) -> float:
    """Shoelace area of a closed (N, 2) polyline: > 0 counter-clockwise, < 0 clockwise."""
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


@dataclass(frozen=True)
class ScanParams:
    """How the laser scans one kind of vector: power (W) and speed (mm/s)."""
    power: float
    speed: float

    def __post_init__(self):
        if not self.power >= 0:
            raise ValueError(f"laser power must be >= 0 W, got {self.power!r}")
        if not self.speed > 0:
            raise ValueError(f"scan speed must be > 0 mm/s, got {self.speed!r}")


@dataclass
class Contour:
    """A closed outline of a layer. `points` is an (N, 2) array of (x, y)."""
    points: np.ndarray
    params: ScanParams | None = None

    @property
    def is_hole(self) -> bool:
        """True for a hole (clockwise), False for an outer outline (counter-clockwise)."""
        return signed_area(self.points) < 0


@dataclass
class Hatch:
    """The interior laser fill of a layer.

    `segments` is an (M, 2, 2) array: M line segments, each [[x1, y1], [x2, y2]].
    Every segment is one 'laser on, move start -> end' vector.
    """
    segments: np.ndarray
    params: ScanParams | None = None


@dataclass
class Layer:
    """One printed layer at height `z` (mm)."""
    z: float
    contours: list[Contour] = field(default_factory=list)
    hatches: list[Hatch] = field(default_factory=list)

    @property
    def num_hatch_vectors(self) -> int:
        return int(sum(len(h.segments) for h in self.hatches))
