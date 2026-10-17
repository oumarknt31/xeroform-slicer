# slicerkit

An open-source **SLS slicing engine** for the XeroForm low-cost SLS 3D printer.
It turns a 3D model (STL) into laser tool-paths and writes them to a machine
file:

```
load (STL)  ->  slice (layers)  ->  hatch (contour + laser fill)  ->  export (.cli)
```

Built in Python on the open-source [PySLM](https://pyslm.readthedocs.io) library.

## Why it's structured this way

- **Standalone engine/library** — no GUI baked in; a CLI and (later) a Qt GUI
  just call it. (Deliverable decision: standalone engine, per Petr.)
- **Thin wrapper over PySLM** — PySLM's objects are translated into slicerkit's
  own `Layer` model in exactly one place (`slicing.py`). Swapping the slicing
  backend later touches only that file.
- **Pluggable exporter** — the engine writes through the `Exporter` interface,
  so matching the printer's real `.cli` dialect (or adding binary CLI / OVF) is
  a new file in `export/`, nothing else.

## Install

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .            # add [dev] for tests:  pip install -e ".[dev]"
```

The package on PyPI that provides `import pyslm` is **PythonSLM** (installed
automatically as a dependency).

## Use

Command line:

```bash
slicerkit model.stl -o model.cli --layer 0.1 --hatch-distance 0.2 --hatch-rotation 67
# or:  python -m slicerkit model.stl -o model.cli

# also write an interactive layer preview (open it in any browser):
slicerkit model.stl -o model.cli --preview model.html

# model in inches? check it fits the machine?
slicerkit model.stl -o model.cli --scale 25.4 --build-volume 150 150 150

# laser settings (W, mm/s) - defaults are placeholders until the laser is chosen:
slicerkit model.stl -o model.cli --hatch-power 5 --hatch-speed 500 \
          --contour-power 4 --contour-speed 400 --jump-speed 2000
```

### Model checks

Input can be STL, OBJ, PLY or 3MF. Before slicing, slicerkit:

- **repairs** what is safe to fix automatically - zero-area/duplicate triangles,
  small holes in the surface, inside-out faces - and lists what it changed;
- **refuses** models it can't slice correctly (big gaps in the surface, no
  volume, unreadable files) with a message saying what to do;
- **warns** when the size suggests wrong units (STL has none - inch CAD parts
  arrive 25.4x too small); fix with `--scale`;
- **centres** the part on the platform: x = y = 0 is the middle of the plate,
  z = 0 its bottom. With `--build-volume X Y Z` it also refuses parts that
  don't fit.

### Scan order

`--scan-order` sets the order the fill vectors are scanned in. PySLM's own
order (`raster`) points every vector the same way, so the laser jumps back
across the part with the beam off after each one - as far as it travels with
the beam on.

| mode | what it does | laser-off travel on test parts vs `raster` |
|---|---|---|
| `nearest` (default) | always continues with the closest unscanned vector | 94-99% less |
| `meander` | zig-zags line by line across the whole layer, holes and gaps included | 72-99% less (worst with holes) |
| `raster` | every vector the same direction | - |

That made the estimated laser time 17-23% shorter at a 2000 mm/s jump speed,
and matters more on a slow-jumping gantry machine. Turn on *Scan order* and
*Travel moves* in the preview to see the difference.

### Output

Every run prints an estimated laser time (scanning only - no recoating or
heating) and the fill **energy density** `P / (v * h)` in J/mm², the main number
to tune per material.

Laser settings are stored in physical units on each contour/hatch
(`ScanParams`). Each exporter converts them to what its controller wants
(percent, PWM, G-code `S`/`F`); standard ASCII CLI has no field for them.

The preview steps through layers (slider or ← →) and shows outlines (holes in
blue), hatch fill, laser-off travel moves and scan order, plus per-layer
laser-on / travel length. Use `--preview-every N` to keep the file small for big
parts.

From Python:

```python
from slicerkit import slice_file, SliceConfig

layers = slice_file("model.stl", "model.cli",
                    SliceConfig(layer_thickness=0.1, hatch_distance=0.2))
print(len(layers), "layers")

from slicerkit import write_preview
write_preview(layers, "model.html")
```

## Layout

```
src/slicerkit/
  part.py        # load, repair, check + place the mesh (wraps PySLM)
  slicing.py     # part -> layers   (the PySLM -> slicerkit translation lives here)
  hatching.py    # hatch/contour settings (wraps PySLM Hatcher)
  scan_order.py  # order/direction of fill vectors (nearest, meander, raster)
  layers.py      # slicerkit's own Layer / Contour / Hatch / ScanParams data model
  laser.py       # LaserSettings, path lengths, scan-time estimate
  config.py      # SliceConfig + material/machine profiles
  export/
    base.py      # Exporter interface
    cli_ascii.py # ASCII .cli writer
  pipeline.py    # orchestrates the stages
  preview.py     # interactive HTML layer viewer
  __main__.py    # CLI entry point
tests/           # round-trip export, slicing correctness
examples/        # sample_cube.py
```

## Status & next steps

- [x] load -> slice -> hatch -> export pipeline working end to end
- [x] ASCII `.cli` export, verified with a lossless round-trip test
- [x] contours follow the CLI orientation convention (outer CCW / flag 1, holes CW / flag 0)
- [x] hatch angle rotates per layer (`hatch_angle_increment`, default 67°; 0 = fixed)
- [x] interactive HTML layer preview (`--preview`)
- [x] laser power / speed per vector type, scan-time estimate, energy density
- [x] mesh checks/repairs, units warning, platform centring, build-volume check
- [x] scan order (`nearest` / `meander` / `raster`) - cuts laser-off travel 72-99%
- [ ] confirm the exact `.cli` dialect (units, ASCII vs binary) with the STM32 firmware
- [ ] tune layer thickness / hatch parameters for nylon
- [ ] 3D part nesting; PySide/Qt GUI on top of the engine

> The ASCII `.cli` output is structurally valid and self-consistent, and the
> POLYLINE direction flag follows the CLI spec. The `units`, header keywords, and
> how the firmware uses the direction flag still need to be confirmed — all of
> that lives in `export/cli_ascii.py`.
>
> `trimesh` is capped below 6: PySLM 0.6 calls `Path.to_planar`, which trimesh has
> deprecated (it emits a DeprecationWarning on every slice).
