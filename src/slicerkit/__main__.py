"""Command-line entry point:  slicerkit input.stl -o output.cli"""
from __future__ import annotations
import argparse
import os
import sys

from .pipeline import slice_job
from .part import MeshError
from .config import SliceConfig
from .scan_order import SCAN_ORDERS
from .preview import write_preview
from .laser import estimate_scan_time


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="slicerkit",
        description="SLS slicer: turn an STL model into laser tool-paths (.cli).",
    )
    ap.add_argument("input", help="input mesh (.stl, .obj, .3mf, ...)")
    ap.add_argument("-o", "--output", required=True, help="output file (.cli)")
    ap.add_argument("--layer", type=float, default=0.1, help="layer thickness in mm")
    ap.add_argument("--hatch-distance", type=float, default=0.2, help="hatch spacing in mm")
    ap.add_argument("--hatch-angle", type=float, default=67.0, help="first-layer hatch angle in deg")
    ap.add_argument("--hatch-rotation", type=float, default=67.0,
                    help="hatch angle added per layer in deg (0 = fixed)")
    ap.add_argument("--scan-order", choices=SCAN_ORDERS, default="nearest",
                    help="order of fill vectors: nearest = closest next vector (default, least "
                         "laser-off travel), meander = zig-zag, raster = all one direction")
    ap.add_argument("--units", type=float, default=1.0, help="mm per .cli coordinate unit")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="scale the model, e.g. 25.4 if it was made in inches")
    ap.add_argument("--build-volume", type=float, nargs=3, metavar=("X", "Y", "Z"),
                    help="printable size in mm; refuse models that don't fit")
    laser = ap.add_argument_group("laser (placeholder defaults - tune on hardware)")
    defaults = SliceConfig()
    laser.add_argument("--hatch-power", type=float, default=defaults.hatch_power, help="fill power in W")
    laser.add_argument("--hatch-speed", type=float, default=defaults.hatch_speed, help="fill speed in mm/s")
    laser.add_argument("--contour-power", type=float, default=defaults.contour_power, help="outline power in W")
    laser.add_argument("--contour-speed", type=float, default=defaults.contour_speed, help="outline speed in mm/s")
    laser.add_argument("--jump-speed", type=float, default=defaults.jump_speed,
                       help="laser-off move speed in mm/s")
    ap.add_argument("--preview", metavar="HTML", help="also write an interactive layer preview (.html)")
    ap.add_argument("--preview-every", type=int, default=1, metavar="N",
                    help="keep every N-th layer in the preview (smaller file for big parts)")
    args = ap.parse_args(argv)
    if args.preview_every < 1:
        ap.error("--preview-every must be >= 1")

    try:
        cfg = SliceConfig(
            layer_thickness=args.layer,
            hatch_distance=args.hatch_distance,
            hatch_angle=args.hatch_angle,
            hatch_angle_increment=args.hatch_rotation,
            scan_order=args.scan_order,
            units=args.units,
            hatch_power=args.hatch_power,
            hatch_speed=args.hatch_speed,
            contour_power=args.contour_power,
            contour_speed=args.contour_speed,
            jump_speed=args.jump_speed,
            scale=args.scale,
            build_volume=tuple(args.build_volume) if args.build_volume else None,
        )
    except ValueError as e:
        ap.error(str(e))
    try:
        result = slice_job(args.input, args.output, cfg)
    except MeshError as e:
        print(f"slicerkit: error: {e}", file=sys.stderr)
        return 1
    layers, report = result.layers, result.report
    x, y, z = report.size
    bodies = f"{report.bodies} bodies" if report.bodies != 1 else "1 body"
    print(f"Model: {x:.1f} x {y:.1f} x {z:.1f} mm, {report.volume:.0f} mm^3, "
          f"{report.triangles} triangles, {bodies}")
    for repair in report.repairs:
        print(f"  repaired: {repair}")
    for warning in report.warnings:
        print(f"  warning: {warning}")
    vectors = sum(l.num_hatch_vectors for l in layers)
    print(f"Sliced {len(layers)} layers ({vectors} hatch vectors) -> {args.output}")
    seconds = estimate_scan_time(layers, cfg.jump_speed)
    print(f"Estimated laser time: {_hms(seconds)} (scanning only; excludes recoating/heating)")
    print(f"Hatch energy density: {cfg.hatch_energy_density:.4f} J/mm^2")
    if args.preview:
        write_preview(layers, args.preview, title=os.path.basename(args.input),
                      every=args.preview_every, jump_speed=cfg.jump_speed)
        print(f"Preview -> {args.preview}")
    return 0


def _hms(seconds: float) -> str:
    m, s = divmod(round(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"


if __name__ == "__main__":
    raise SystemExit(main())
