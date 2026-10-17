"""The slicer: turn a Part into a list of slicerkit Layers.

This module is the ONLY place PySLM geometry is translated into slicerkit's own
data model. Keeping the translation here is what makes the rest of the engine
independent of PySLM.
"""
from __future__ import annotations
import numpy as np

from .part import Part
from .hatching import HatchSettings
from .layers import Layer, Contour, Hatch


def slice_part(part: Part, settings: HatchSettings, layer_thickness: float) -> list[Layer]:
    """Slice the whole part, bottom to top, returning slicerkit Layers."""
    hatcher = settings.make_hatcher()
    layers: list[Layer] = []
    z = layer_thickness
    z_max = part.z_max
    while z < z_max:
        boundaries = part.raw_slice(z)
        if boundaries:  # skip empty slices at the extremes
            pyslm_layer = hatcher.hatch(boundaries)
            layers.append(_to_layer(pyslm_layer, z))
        z += layer_thickness
    return layers


def _to_layer(pyslm_layer, z: float) -> Layer:
    """Translate one PySLM layer into a slicerkit Layer (the wrapper boundary)."""
    contours: list[Contour] = []
    hatches: list[Hatch] = []
    for g in pyslm_layer.geometry:
        coords = np.asarray(g.coords, dtype=float)
        kind = type(g).__name__
        if kind == "ContourGeometry":
            contours.append(Contour(points=coords))
        elif kind == "HatchGeometry":
            # PySLM stores hatch points as consecutive start/end pairs.
            segments = coords.reshape(-1, 2, 2)
            hatches.append(Hatch(segments=segments))
    return Layer(z=z, contours=contours, hatches=hatches)
