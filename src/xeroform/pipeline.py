"""Orchestration: glue the stages into one call.

    load (Part) -> slice + hatch (slice_part) -> export (Exporter)

For a build with several parts, the parts are packed (nesting.plan), or put
where they were placed by hand, and merged into one mesh first; everything after
that is the same. Parts with their own settings are sliced separately with
those, and their layers merged with the rest.
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Callable

from .orient import NO_ROTATION, Angles
from .part import Part, MeshError, MeshReport, prepare_mesh
from .hatching import HatchSettings
from .layers import Layer
from .nesting import Placement, Spot, conflicts, place, plan
from .project import Project
from .slicing import slice_part
from .export import get_exporter
from .config import SliceConfig


@dataclass
class BuildReport:
    """How several parts were packed into one build."""

    placements: list[Placement]
    height: float  # mm, top of the highest part
    density: float  # part volume / (plate area x build height), 0..1
    warnings: list[str] = field(default_factory=list)  # e.g. parts placed by hand too close together


@dataclass
class SliceResult:
    layers: list[Layer]
    reports: list[tuple[str, MeshReport]] = field(default_factory=list)  # per input model
    build: BuildReport | None = None  # set when several parts were packed
    bounding_box: tuple[float, ...] = ()  # [min_x, min_y, min_z, max_x, max_y, max_z] mm
    own_settings: dict[str, dict] = field(default_factory=dict)  # per model, values that differ from the build's

    @property
    def report(self) -> MeshReport:
        """The (first) model's report - convenient for single-part jobs."""
        return self.reports[0][1]


Progress = Callable[[int, int], None]


def slice_job(
    input_path: str,
    output_path: str | None,
    config: SliceConfig | None = None,
    progress: Progress | None = None,
    rotation: Angles = NO_ROTATION,
    settings: dict | None = None,
) -> SliceResult:
    """Slice `input_path` and write laser tool-paths to `output_path` (None = don't write).

    rotation orients the model first (degrees about X, then Y, then Z).
    settings : the part's own values for some settings (see config.PART_SETTINGS).

    Raises MeshError (with a user-facing message) if the model can't be sliced.
    progress(done, total) is called per layer; raise from it to cancel.
    """
    config = (config or SliceConfig()).for_part(settings)
    # Resolve the exporter first so a bad format fails before the slow slicing.
    exporter = get_exporter(config.export_format, units=config.units)
    part = Part(input_path, scale=config.scale, build_volume=config.build_volume, rotation=rotation)
    layers = _slice(part, config, progress)
    if output_path is not None:
        exporter.write(layers, output_path, part.bounding_box)
    return SliceResult(
        layers=layers,
        reports=[(input_path, part.report)],
        bounding_box=tuple(part.bounding_box),
        own_settings={input_path: dict(settings)} if settings else {},
    )


def slice_build(
    input_paths: list[str],
    output_path: str | None,
    config: SliceConfig | None = None,
    copies: int = 1,
    progress: Progress | None = None,
    rotations: list[Angles] | None = None,
    settings: list[dict | None] | None = None,
    spots: list[Spot | None] | None = None,
) -> SliceResult:
    """Pack `copies` of every model in `input_paths` into one build, slice and export it.

    A path listed twice is packed twice. Per path, `rotations` orients the model
    first and `settings` holds its own values for some settings (see
    config.PART_SETTINGS). `spots`, one per part to print (paths x copies), puts
    a part where it was placed by hand; parts without one are packed around
    those. Needs config.build_volume. Raises MeshError / NestingError with a
    user-facing message.
    """
    config = config or SliceConfig()
    if copies < 1:
        raise ValueError(f"copies must be >= 1, got {copies!r}")
    if config.build_volume is None:
        raise MeshError("Packing several parts needs the build volume (--build-volume X Y Z).")
    exporter = get_exporter(config.export_format, units=config.units)

    rotations = [tuple(r) for r in rotations] if rotations else [NO_ROTATION] * len(input_paths)
    settings = list(settings) if settings else [None] * len(input_paths)
    if len(rotations) != len(input_paths) or len(settings) != len(input_paths):
        raise ValueError("rotations and settings need one entry per input path")
    own = [_own(config, s) for s in settings]
    specs = list(zip(input_paths, rotations))
    loaded = {spec: prepare_mesh(spec[0], config.scale, spec[1]) for spec in dict.fromkeys(specs)}
    jobs = [k for k in range(len(specs)) for _ in range(copies)]  # index into specs, once per copy
    if spots is not None and len(spots) != len(jobs):
        raise ValueError("spots needs one entry per part to print")
    meshes = [loaded[specs[k]][0] for k in jobs]
    names = [os.path.basename(input_paths[k]) for k in jobs]
    pinned = {j: spot for j, spot in enumerate(spots or []) if spot is not None}
    placements = plan(meshes, config.build_volume, config.part_spacing, config.allow_rotation, names, pinned)
    warnings = conflicts(meshes, placements, config.build_volume, config.part_spacing, names) if pinned else []

    groups: dict[tuple, list[Placement]] = {}  # parts sliced together: the same settings
    for p in placements:
        groups.setdefault(tuple(sorted(own[jobs[p.item]].items())), []).append(p)
    merged = place(meshes, placements)
    if len(groups) == 1:
        part = Part.from_mesh(merged)
        (key,) = groups
        layers = _slice(part, config.for_part(dict(key)), progress)
    else:
        layers = _slice_groups(meshes, groups, config, progress)

    X, Y, _ = config.build_volume
    height = float(merged.bounds[1][2])
    density = sum(m.volume for m in meshes) / (X * Y * height)
    build = BuildReport(placements=placements, height=height, density=density, warnings=warnings)
    bounding_box = tuple(float(v) for v in merged.bounds.reshape(-1))
    if output_path is not None:
        exporter.write(layers, output_path, bounding_box)
    reports = {}
    for (path, _), (_, report) in loaded.items():
        reports.setdefault(path, report)  # one report per model file
    own_settings = {path: o for path, o in zip(input_paths, own) if o}
    return SliceResult(
        layers=layers, reports=list(reports.items()), build=build, bounding_box=bounding_box, own_settings=own_settings
    )


def _own(config: SliceConfig, settings: dict | None) -> dict:
    """A part's own settings, keeping only the values that differ from the build's."""
    part = config.for_part(settings)  # validates them
    return {k: getattr(part, k) for k in settings or {} if getattr(part, k) != getattr(config, k)}


def _slice_groups(meshes, groups: dict[tuple, list[Placement]], config: SliceConfig, progress) -> list[Layer]:
    """Slice each group of parts with its own settings and merge the layers by height."""
    parts = [(Part.from_mesh(place(meshes, ps)), config.for_part(dict(key))) for key, ps in groups.items()]
    totals = [max(1, int(part.z_max / config.layer_thickness)) for part, _ in parts]
    by_index: dict[int, Layer] = {}
    done = 0
    for (part, cfg), total in zip(parts, totals):
        step = (lambda d, t, base=done: progress(base + d, sum(totals))) if progress else None
        for layer in _slice(part, cfg, step):
            i = round(layer.z / config.layer_thickness)
            if i in by_index:
                by_index[i].contours += layer.contours
                by_index[i].hatches += layer.hatches
            else:
                by_index[i] = layer
        done += total
    first, last = min(by_index), max(by_index)
    return [by_index.get(i) or Layer(z=i * config.layer_thickness) for i in range(first, last + 1)]


def slice_project(project: Project, output_path: str | None, progress: Progress | None = None) -> SliceResult:
    """Slice a project as laid out: every part's copies, orientation, own settings
    and the places copies were put by hand. Without a build volume there is no
    plate to lay parts out on, so a single part is centred."""
    parts = [(p, k) for p in project.parts for k in range(p.copies)]
    if not parts:
        raise MeshError("The project has no parts to slice.")
    if len(parts) == 1 and project.config.build_volume is None:
        ((part, _),) = parts
        return slice_job(part.path, output_path, project.config, progress, part.rotation, part.settings)
    return slice_build(
        [p.path for p, _ in parts],
        output_path,
        project.config,
        progress=progress,
        rotations=[p.rotation for p, _ in parts],
        settings=[p.settings for p, _ in parts],
        spots=[p.spots[k] if k < len(p.spots) else None for p, k in parts],
    )


def export(result: SliceResult, output_path: str, config: SliceConfig | None = None) -> None:
    """Write an already-sliced result to `output_path` (e.g. after previewing it)."""
    config = config or SliceConfig()
    get_exporter(config.export_format, units=config.units).write(result.layers, output_path, result.bounding_box)


def _slice(part: Part, config: SliceConfig, progress: Progress | None = None) -> list[Layer]:
    settings = HatchSettings(
        hatch_angle=config.hatch_angle,
        hatch_angle_increment=config.hatch_angle_increment,
        hatch_distance=config.hatch_distance,
        num_inner_contours=config.num_inner_contours,
        num_outer_contours=config.num_outer_contours,
        scan_order=config.scan_order,
    )
    layers = slice_part(part, settings, config.layer_thickness, config.laser_settings(), progress)
    if not layers:
        height, t = part.report.size[2], config.layer_thickness
        reason = (
            f"it is {height:.3g} mm tall, thinner than one {t:g} mm layer"
            if height < t
            else f"no slice (taken every {t:g} mm) passes through it - its bodies are too thin"
        )
        raise MeshError(" ".join([f"The model produced no layers: {reason}.", *part.report.warnings]))
    return layers


def slice_file(input_path: str, output_path: str, config: SliceConfig | None = None) -> list[Layer]:
    """Slice the model at `input_path` and write laser tool-paths to `output_path`.

    Returns the list of Layer objects (useful for tests / previews). Use
    `slice_job` to also get the model report (repairs, warnings).
    """
    return slice_job(input_path, output_path, config).layers
