"""Human-readable summary of a slice result, shared by the CLI and the GUI."""

from __future__ import annotations
import os

from .config import SliceConfig
from .laser import estimate_scan_time
from .pipeline import SliceResult


def summary_lines(result: SliceResult, config: SliceConfig, output: str | None = None) -> list[str]:
    """What was loaded, repaired and packed, and what the slice came to."""
    several = result.build is not None
    lines = []
    for path, report in result.reports:
        x, y, z = report.size
        bodies = f"{report.bodies} bodies" if report.bodies != 1 else "1 body"
        name = f"Model {os.path.basename(path)}" if several else "Model"
        lines.append(
            f"{name}: {x:.1f} x {y:.1f} x {z:.1f} mm, {report.volume:.0f} mm^3, {report.triangles} triangles, {bodies}"
        )
        lines += [f"  repaired: {repair}" for repair in report.repairs]
        lines += [f"  warning: {warning}" for warning in report.warnings]
    if result.build:
        b = result.build
        turned = sum(p.rotated for p in b.placements)
        lines.append(
            f"Build: {len(b.placements)} parts packed {b.height:.1f} mm high "
            f"({turned} turned 90 deg), packing density {b.density:.1%}"
        )
    vectors = sum(layer.num_hatch_vectors for layer in result.layers)
    lines.append(f"Sliced {len(result.layers)} layers ({vectors} hatch vectors)" + (f" -> {output}" if output else ""))
    seconds = estimate_scan_time(result.layers, config.jump_speed)
    lines.append(f"Estimated laser time: {hms(seconds)} (scanning only; excludes recoating/heating)")
    lines.append(f"Hatch energy density: {config.hatch_energy_density:.4f} J/mm^2")
    return lines


def hms(seconds: float) -> str:
    m, s = divmod(round(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"
