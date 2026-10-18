"""The slicer: turn a Part into a list of XeroForm Layers.

This module is the ONLY place PySLM geometry is translated into XeroForm's own
data model. Keeping the translation here is what makes the rest of the engine
independent of PySLM.
"""

from __future__ import annotations
from typing import Callable
import numpy as np

from .part import Part
from .hatching import HatchSettings
from .layers import Layer, Contour, Hatch, ScanParams, signed_area
from .laser import LaserSettings
from .scan_order import order_segments


def slice_part(
    part: Part,
    settings: HatchSettings,
    layer_thickness: float,
    laser: LaserSettings | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> list[Layer]:
    """Slice the whole part, bottom to top, returning XeroForm Layers.

    With `laser`, every contour and hatch carries its scan parameters. Empty
    layers between parts (e.g. the gap between stacked parts in a packed build)
    are kept: the machine still has to spread powder there. Empty slices at the
    very bottom and top are dropped.

    progress(done, total) is called after every slice; raise from it to cancel.
    """
    hatcher = settings.make_hatcher()
    layers: list[Layer] = []
    z_max = part.z_max
    total = max(1, int(z_max / layer_thickness))
    i = 1
    # z from the index, not a running sum, so float error can't accumulate.
    while (z := i * layer_thickness) < z_max:
        boundaries = part.raw_slice(z)
        if boundaries:
            hatcher.hatchAngle = settings.angle_for_layer(i - 1)  # by height, the same for every part
            pyslm_layer = hatcher.hatch(boundaries)
            layer = _to_layer(pyslm_layer, z, laser)
            _order_hatches(layer, settings.scan_order)
            layers.append(layer)
        elif layers:
            layers.append(Layer(z=z))  # powder only
        if progress:
            progress(min(i, total), total)
        i += 1
    while layers and not layers[-1].contours and not layers[-1].hatches:
        layers.pop()
    return layers


def _to_layer(pyslm_layer, z: float, laser: LaserSettings | None = None) -> Layer:
    """Translate one PySLM layer into a XeroForm Layer (the wrapper boundary)."""
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
            hatches.append(Hatch(segments=segments, params=laser and laser.hatch))
    contours = _orient_contours(contour_coords, laser and laser.contour)
    return Layer(z=z, contours=contours, hatches=hatches)


def _order_hatches(layer: Layer, mode: str) -> None:
    """Re-order each hatch's vectors for scanning, starting where the contours end."""
    pos = layer.contours[-1].points[-1] if layer.contours else None
    for h in layer.hatches:
        h.segments = order_segments(h.segments, mode, start=pos)
        if len(h.segments):
            pos = h.segments[-1, 1]


def _orient_contours(contour_coords: list[np.ndarray], params: ScanParams | None = None) -> list[Contour]:
    """Re-orient PySLM contours to XeroForm's convention (outer CCW, holes CW).

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
        contours.append(Contour(points=coords, params=params))
    return contours
