"""Slicing correctness: layer heights, contour orientation, hatch rotation, config."""
import numpy as np
import pytest
import trimesh

from xeroform.config import SliceConfig, get_profile, PROFILES
from xeroform.hatching import HatchSettings
from xeroform.layers import signed_area
from xeroform.part import Part
from xeroform.pipeline import slice_file
from xeroform.slicing import slice_part


@pytest.fixture(scope="module")
def ring_stl(tmp_path_factory):
    """A 20 mm tall tube: every layer has one outer outline and one hole."""
    path = tmp_path_factory.mktemp("mesh") / "ring.stl"
    trimesh.creation.annulus(r_min=4, r_max=10, height=20).export(str(path))
    return str(path)


def _hatch_line_angles(layer):
    s = np.concatenate([h.segments for h in layer.hatches])
    d = s[:, 1] - s[:, 0]
    return np.degrees(np.arctan2(d[:, 1], d[:, 0])) % 180


def test_layer_heights_are_exact_multiples(tmp_path):
    stl = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(str(stl))
    t = 0.1
    layers = slice_part(Part(str(stl)), HatchSettings(hatch_distance=1.0), t)
    assert len(layers) == 99  # z = 0.1 .. 9.9; the top face at z = 10 is not a layer
    for i, layer in enumerate(layers, start=1):
        assert layer.z == i * t


def test_outer_ccw_and_holes_cw(ring_stl):
    layers = slice_part(Part(ring_stl), HatchSettings(hatch_distance=1.0), 2.0)
    for layer in layers:
        outers = [c for c in layer.contours if not c.is_hole]
        holes = [c for c in layer.contours if c.is_hole]
        assert outers and holes
        # outer outlines enclose the tube wall (~pi*10^2), holes the bore (~pi*4^2)
        assert all(signed_area(c.points) > 250 for c in outers)
        assert all(-60 < signed_area(c.points) < -40 for c in holes)


def test_cli_direction_flags(ring_stl, tmp_path):
    out = tmp_path / "ring.cli"
    layers = slice_file(ring_stl, str(out), SliceConfig(layer_thickness=2.0, hatch_distance=1.0))
    flags = [line.split("/")[1].split(",")[1]
             for line in out.read_text(encoding="utf-8").splitlines() if line.startswith("$$POLYLINE/")]
    expected = ["0" if c.is_hole else "1" for layer in layers for c in layer.contours]
    assert flags == expected
    assert "0" in flags and "1" in flags


def test_hatch_rotates_each_layer(ring_stl):
    settings = HatchSettings(hatch_angle=67.0, hatch_angle_increment=67.0, hatch_distance=1.0)
    layers = slice_part(Part(ring_stl), settings, 2.0)
    for i, layer in enumerate(layers[:4]):
        # PySLM convention: fill lines run perpendicular to the hatch angle
        expected = (settings.angle_for_layer(i) + 90) % 180
        diff = (_hatch_line_angles(layer) - expected + 90) % 180 - 90
        assert np.allclose(diff, 0, atol=0.01)


def test_zero_increment_keeps_angle_fixed(ring_stl):
    settings = HatchSettings(hatch_angle_increment=0.0, hatch_distance=1.0)
    layers = slice_part(Part(ring_stl), settings, 5.0)
    first = np.median(_hatch_line_angles(layers[0]))
    for layer in layers[1:]:
        assert np.allclose(_hatch_line_angles(layer), first, atol=0.01)


def test_get_profile_returns_copy():
    cfg = get_profile("default")
    cfg.layer_thickness = 0.5
    assert PROFILES["default"].layer_thickness == 0.1
    with pytest.raises(ValueError):
        get_profile("nope")


@pytest.mark.parametrize("field", ["layer_thickness", "hatch_distance", "units"])
@pytest.mark.parametrize("value", [0, -0.1])
def test_config_rejects_non_positive(field, value):
    with pytest.raises(ValueError):
        SliceConfig(**{field: value})
