"""The slicer: turn a Part into a list of slicerkit Layers.

This module is the ONLY place PySLM geometry is translated into slicerkit's own
data model. Keeping the translation here is what makes the rest of the engine
independent of PySLM.
"""
from __future__ import annotations
import numpy as np

from .part import Part
from .hatching import HatchSettings
from .layers import Layer, Contour, Hatch, signed_area


def slice_part(part: Part, settings: HatchSettings, layer_thickness: float) -> list[Layer]:
    """Slice the whole part, bottom to top, returning slicerkit Layers."""
    hatcher = settings.make_hatcher()
    layers: list[Layer] = []
    z_max = part.z_max
    i = 1
    # z from the index, not a running sum, so float error can't accumulate.
    while (z := i * layer_thickness) < z_max:
        boundaries = part.raw_slice(z)
        if boundaries:  # skip empty slices at the extremes
            hatcher.hatchAngle = settings.angle_for_layer(len(layers))
            pyslm_layer = hatcher.hatch(boundaries)
            layers.append(_to_layer(pyslm_layer, z))
        i += 1
    return layers


def _to_layer(pyslm_layer, z: float) -> Layer:
    """Translate one PySLM layer into a slicerkit Layer (the wrapper boundary)."""
    contour_coords: list[np.ndarray] = []
    hatches: list[Hatch] = []
    for g in pyslm_layer.geometry:
        coords = np.asarray(g.coords, dtype=float)
        kind = type(g).__name__
        if kind == "ContourGeometry":
            contour_coords.append(coords)
        elif kind == "HatchGeometry":
            # PySLM stores hatch points as consecutive start/end pairs.
            segments = coords.reshape(-1, 2, 2)
            hatches.append(Hatch(segments=segments))
    return Layer(z=z, contours=_orient_contours(contour_coords), hatches=hatches)


def _orient_contours(contour_coords: list[np.ndarray]) -> list[Contour]:
    """Re-orient PySLM contours to slicerkit's convention (outer CCW, holes CW).

    PySLM's offsetting gives outers and holes opposite windings, but which one is
    clockwise is a PySLM detail (currently outers are CW). The largest contour in
    a layer is always an outer, so its winding tells us which sign means "outer".
    """
    if not contour_coords:
        return []
    areas = [signed_area(c) for c in contour_coords]
    outer_sign = np.sign(max(areas, key=abs))
    contours = []
    for coords, area in zip(contour_coords, areas):
        is_hole = np.sign(area) != outer_sign
        if (area < 0) != is_hole:  # winding doesn't match the convention
            coords = coords[::-1].copy()
        contours.append(Contour(points=coords))
    return contours
