"""Orchestration: glue the stages into one call.

    load (Part) -> slice + hatch (slice_part) -> export (Exporter)

For a build with several parts, the parts are packed (nesting.arrange) and
merged into one mesh first; everything after that is the same.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field

from .part import Part, MeshError, MeshReport, prepare_mesh
from .hatching import HatchSettings
from .layers import Layer
from .nesting import Placement, arrange
from .slicing import slice_part
from .export import get_exporter
from .config import SliceConfig


@dataclass
class BuildReport:
    """How several parts were packed into one build."""
    placements: list[Placement]
    height: float    # mm, top of the highest part
    density: float   # part volume / (plate area x build height), 0..1


@dataclass
class SliceResult:
    layers: list[Layer]
    reports: list[tuple[str, MeshReport]] = field(default_factory=list)  # per input model
    build: BuildReport | None = None  # set when several parts were packed

    @property
    def report(self) -> MeshReport:
        """The (first) model's report - convenient for single-part jobs."""
        return self.reports[0][1]


def slice_job(input_path: str, output_path: str, config: SliceConfig | None = None) -> SliceResult:
    """Slice `input_path` and write laser tool-paths to `output_path`.

    Raises MeshError (with a user-facing message) if the model can't be sliced.
    """
    config = config or SliceConfig()
    # Resolve the exporter first so a bad format fails before the slow slicing.
    exporter = get_exporter(config.export_format, units=config.units)
    part = Part(input_path, scale=config.scale, build_volume=config.build_volume)
    layers = _slice_and_export(part, config, exporter, output_path)
    return SliceResult(layers=layers, reports=[(input_path, part.report)])


def slice_build(input_paths: list[str], output_path: str, config: SliceConfig | None = None,
                copies: int = 1) -> SliceResult:
    """Pack `copies` of every model in `input_paths` into one build, slice and export it.

    Needs config.build_volume. Raises MeshError / NestingError with a user-facing message.
    """
    config = config or SliceConfig()
    if copies < 1:
        raise ValueError(f"copies must be >= 1, got {copies!r}")
    if config.build_volume is None:
        raise MeshError("Packing several parts needs the build volume (--build-volume X Y Z).")
    exporter = get_exporter(config.export_format, units=config.units)

    loaded = {path: prepare_mesh(path, config.scale) for path in dict.fromkeys(input_paths)}
    jobs = [path for path in input_paths for _ in range(copies)]
    meshes = [loaded[path][0] for path in jobs]
    merged, placements = arrange(meshes, config.build_volume, config.part_spacing,
                                 config.allow_rotation, names=[os.path.basename(p) for p in jobs])
    part = Part.from_mesh(merged)
    layers = _slice_and_export(part, config, exporter, output_path)

    X, Y, _ = config.build_volume
    height = part.report.size[2]
    build = BuildReport(placements=placements, height=height,
                        density=sum(m.volume for m in meshes) / (X * Y * height))
    return SliceResult(layers=layers, reports=[(p, r) for p, (_, r) in loaded.items()], build=build)


def _slice_and_export(part: Part, config: SliceConfig, exporter, output_path: str) -> list[Layer]:
    settings = HatchSettings(
        hatch_angle=config.hatch_angle,
        hatch_angle_increment=config.hatch_angle_increment,
        hatch_distance=config.hatch_distance,
        num_inner_contours=config.num_inner_contours,
        num_outer_contours=config.num_outer_contours,
        scan_order=config.scan_order,
    )
    layers = slice_part(part, settings, config.layer_thickness, config.laser_settings())
    if not layers:
        height, t = part.report.size[2], config.layer_thickness
        reason = (f"it is {height:.3g} mm tall, thinner than one {t:g} mm layer" if height < t else
                  f"no slice (taken every {t:g} mm) passes through it - its bodies are too thin")
        raise MeshError(" ".join([f"The model produced no layers: {reason}.", *part.report.warnings]))
    exporter.write(layers, output_path, part.bounding_box)
    return layers


def slice_file(input_path: str, output_path: str, config: SliceConfig | None = None) -> list[Layer]:
    """Slice `input_path` (STL) and write laser tool-paths to `output_path`.

    Returns the list of Layer objects (useful for tests / previews). Use
    `slice_job` to also get the model report (repairs, warnings).
    """
    return slice_job(input_path, output_path, config).layers
