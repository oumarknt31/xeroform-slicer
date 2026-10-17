"""Round-trip test: slice a cube, export .cli, read it back, check nothing was lost."""

import numpy as np
import trimesh

from xeroform.pipeline import slice_file
from xeroform.config import SliceConfig


def _read_first_layer(cli_path):
    polys, hatches, started = [], [], False
    for line in open(cli_path, encoding="utf-8"):
        line = line.strip()
        if line.startswith("$$LAYER/"):
            if started:
                break
            started = True
        elif started and line.startswith("$$POLYLINE/"):
            p = line.split("/")[1].split(",")
            npts = int(p[2])
            polys.append(np.array(p[3 : 3 + 2 * npts], float).reshape(-1, 2))
        elif started and line.startswith("$$HATCHES/"):
            p = line.split("/")[1].split(",")
            nseg = int(p[1])
            hatches.append(np.array(p[2 : 2 + 4 * nseg], float).reshape(-1, 2, 2))
    return polys, hatches


def test_slice_and_export(tmp_path):
    stl = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[20, 20, 20]).export(str(stl))
    out = tmp_path / "cube.cli"

    layers = slice_file(str(stl), str(out), SliceConfig(layer_thickness=0.5, hatch_distance=0.5))

    # produced a sensible number of layers
    assert len(layers) > 10

    text = out.read_text(encoding="utf-8")
    assert text.startswith("$$HEADERSTART")
    assert text.count("$$LAYER/") == len(layers)
    assert "$$HATCHES/" in text

    # round-trip: first layer read back matches the in-memory layer
    polys, hatches = _read_first_layer(str(out))
    first = layers[0]
    assert len(polys) == len(first.contours)
    assert len(hatches) == len(first.hatches)
    if first.hatches:
        assert len(hatches[0]) == len(first.hatches[0].segments)
        assert np.allclose(hatches[0], first.hatches[0].segments, atol=1e-3)


def test_unknown_format_raises(tmp_path):
    stl = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(str(stl))
    import pytest

    with pytest.raises(ValueError):
        slice_file(str(stl), str(tmp_path / "x.foo"), SliceConfig(export_format="foo"))


def test_cli_file_is_the_same_on_every_os(tmp_path):
    """Plain ASCII with \\n line endings - Windows must not write \\r\\n."""
    stl = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(str(stl))
    out = tmp_path / "cube.cli"
    slice_file(str(stl), str(out), SliceConfig(layer_thickness=2))
    data = out.read_bytes()
    assert b"\r\n" not in data and data.isascii() and data.count(b"\n") > 5
