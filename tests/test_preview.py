"""Preview: the HTML viewer carries the same geometry as the in-memory layers."""
import json
import re

import numpy as np
import pytest
import trimesh

from slicerkit import SliceConfig, slice_file, write_preview
from slicerkit.__main__ import main
from slicerkit.layers import Layer
from slicerkit.preview import preview_data


@pytest.fixture(scope="module")
def ring_layers(tmp_path_factory):
    d = tmp_path_factory.mktemp("ring")
    stl = d / "ring.stl"
    trimesh.creation.annulus(r_min=4, r_max=10, height=20).export(str(stl))
    return slice_file(str(stl), str(d / "ring.cli"), SliceConfig(layer_thickness=2.0, hatch_distance=1.0))


def _embedded(html_text):
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', html_text, re.S)
    return json.loads(m.group(1))


def test_preview_matches_layers(ring_layers, tmp_path):
    out = tmp_path / "p.html"
    write_preview(ring_layers, str(out), title="ring <test>")
    text = out.read_text()
    assert "<title>ring &lt;test&gt;</title>" in text
    data = _embedded(text)

    assert len(data["layers"]) == len(ring_layers) == data["total_layers"]
    for layer, pl in zip(ring_layers, data["layers"]):
        assert pl["z"] == pytest.approx(layer.z)
        assert [c["hole"] for c in pl["contours"]] == [c.is_hole for c in layer.contours]
        segs = np.concatenate([h.segments for h in layer.hatches]).ravel()
        assert np.allclose(pl["hatches"], segs, atol=1e-3)

    # bounds enclose the tube (outer radius 10)
    x0, y0, x1, y1 = data["bounds"]
    assert -10.5 < x0 < -9 and 9 < x1 < 10.5 and -10.5 < y0 < -9 and 9 < y1 < 10.5


def test_preview_every(ring_layers):
    data = preview_data(ring_layers, every=3)
    assert data["every"] == 3 and data["total_layers"] == len(ring_layers)
    assert [l["z"] for l in data["layers"]] == pytest.approx([l.z for l in ring_layers[::3]])
    with pytest.raises(ValueError):
        preview_data(ring_layers, every=0)


def test_preview_handles_empty_layers():
    data = preview_data([Layer(z=0.1)])
    assert data["layers"] == [{"z": 0.1, "contours": [], "hatches": []}]
    assert data["bounds"] == [0.0, 0.0, 1.0, 1.0]


def test_cli_writes_preview(tmp_path):
    stl = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(str(stl))
    out, html = tmp_path / "cube.cli", tmp_path / "cube.html"
    assert main([str(stl), "-o", str(out), "--layer", "1", "--preview", str(html), "--preview-every", "2"]) == 0
    data = _embedded(html.read_text())
    assert data["total_layers"] == 9 and len(data["layers"]) == 5
