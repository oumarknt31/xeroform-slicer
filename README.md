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
```

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
  part.py        # load + validate mesh (wraps PySLM)
  slicing.py     # part -> layers   (the PySLM -> slicerkit translation lives here)
  hatching.py    # hatch/contour settings (wraps PySLM Hatcher)
  layers.py      # slicerkit's own Layer / Contour / Hatch data model
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
