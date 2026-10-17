"""Orchestration: glue the stages into one call.

    load (Part) -> slice + hatch (slice_part) -> export (Exporter)
"""
from __future__ import annotations
from dataclasses import dataclass

from .part import Part, MeshError, MeshReport
from .hatching import HatchSettings
from .layers import Layer
from .slicing import slice_part
from .export import get_exporter
from .config import SliceConfig


@dataclass
class SliceResult:
    layers: list[Layer]
    report: MeshReport  # what was found / repaired in the model, plus warnings


def slice_job(input_path: str, output_path: str, config: SliceConfig | None = None) -> SliceResult:
    """Slice `input_path` and write laser tool-paths to `output_path`.

    Raises MeshError (with a user-facing message) if the model can't be sliced.
    """
    config = config or SliceConfig()
    # Resolve the exporter first so a bad format fails before the slow slicing.
    exporter = get_exporter(config.export_format, units=config.units)

    part = Part(input_path, scale=config.scale, build_volume=config.build_volume)
    settings = HatchSettings(
        hatch_angle=config.hatch_angle,
        hatch_angle_increment=config.hatch_angle_increment,
        hatch_distance=config.hatch_distance,
        num_inner_contours=config.num_inner_contours,
        num_outer_contours=config.num_outer_contours,
    )
    layers = slice_part(part, settings, config.layer_thickness, config.laser_settings())
    if not layers:
        height, t = part.report.size[2], config.layer_thickness
        reason = (f"it is {height:.3g} mm tall, thinner than one {t:g} mm layer" if height < t else
                  f"no slice (taken every {t:g} mm) passes through it - its bodies are too thin")
        raise MeshError(" ".join([f"The model produced no layers: {reason}.", *part.report.warnings]))
    exporter.write(layers, output_path, part.bounding_box)
    return SliceResult(layers=layers, report=part.report)


def slice_file(input_path: str, output_path: str, config: SliceConfig | None = None) -> list[Layer]:
    """Slice `input_path` (STL) and write laser tool-paths to `output_path`.

    Returns the list of Layer objects (useful for tests / previews). Use
    `slice_job` to also get the model report (repairs, warnings).
    """
    return slice_job(input_path, output_path, config).layers
