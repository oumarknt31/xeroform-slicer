"""Orchestration: glue the stages into one call.

    load (Part) -> slice + hatch (slice_part) -> export (Exporter)
"""
from __future__ import annotations

from .part import Part
from .hatching import HatchSettings
from .slicing import slice_part
from .export import get_exporter
from .config import SliceConfig


def slice_file(input_path: str, output_path: str, config: SliceConfig | None = None):
    """Slice `input_path` (STL) and write laser tool-paths to `output_path`.

    Returns the list of Layer objects (useful for tests / previews).
    """
    config = config or SliceConfig()

    part = Part(input_path)
    settings = HatchSettings(
        hatch_angle=config.hatch_angle,
        hatch_distance=config.hatch_distance,
        num_inner_contours=config.num_inner_contours,
        num_outer_contours=config.num_outer_contours,
    )
    layers = slice_part(part, settings, config.layer_thickness)

    exporter = get_exporter(config.export_format, units=config.units)
    exporter.write(layers, output_path, part.bounding_box)
    return layers
