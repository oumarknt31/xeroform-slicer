"""Command-line entry point:  slicerkit input.stl -o output.cli"""
from __future__ import annotations
import argparse

from .pipeline import slice_file
from .config import SliceConfig


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="slicerkit",
        description="SLS slicer: turn an STL model into laser tool-paths (.cli).",
    )
    ap.add_argument("input", help="input mesh (.stl)")
    ap.add_argument("-o", "--output", required=True, help="output file (.cli)")
    ap.add_argument("--layer", type=float, default=0.1, help="layer thickness in mm")
    ap.add_argument("--hatch-distance", type=float, default=0.2, help="hatch spacing in mm")
    ap.add_argument("--hatch-angle", type=float, default=67.0, help="first-layer hatch angle in deg")
    ap.add_argument("--hatch-rotation", type=float, default=67.0,
                    help="hatch angle added per layer in deg (0 = fixed)")
    ap.add_argument("--units", type=float, default=1.0, help="mm per .cli coordinate unit")
    args = ap.parse_args(argv)

    try:
        cfg = SliceConfig(
            layer_thickness=args.layer,
            hatch_distance=args.hatch_distance,
            hatch_angle=args.hatch_angle,
            hatch_angle_increment=args.hatch_rotation,
            units=args.units,
        )
    except ValueError as e:
        ap.error(str(e))
    layers = slice_file(args.input, args.output, cfg)
    vectors = sum(l.num_hatch_vectors for l in layers)
    print(f"Sliced {len(layers)} layers ({vectors} hatch vectors) -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
