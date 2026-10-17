"""slicerkit's own layer data model.

This is the wrapper boundary: PySLM produces its own geometry objects, and we
translate them into these plain, well-named structures exactly once (in
`slicing.py`). Everything downstream - the exporters, the tests - only ever sees
these classes, never PySLM. If PySLM is ever swapped out, only the translation
changes; this model and the exporters do not.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np


@dataclass
class Contour:
    """A closed outline of a layer. `points` is an (N, 2) array of (x, y)."""
    points: np.ndarray


@dataclass
class Hatch:
    """The interior laser fill of a layer.

    `segments` is an (M, 2, 2) array: M line segments, each [[x1, y1], [x2, y2]].
    Every segment is one 'laser on, move start -> end' vector.
    """
    segments: np.ndarray


@dataclass
class Layer:
    """One printed layer at height `z` (mm)."""
    z: float
    contours: list[Contour] = field(default_factory=list)
    hatches: list[Hatch] = field(default_factory=list)

    @property
    def num_hatch_vectors(self) -> int:
        return int(sum(len(h.segments) for h in self.hatches))
