"""Laser settings: scan params on geometry, path lengths, time estimate, energy density."""

import numpy as np
import pytest
import trimesh

from xeroform import SliceConfig, slice_file
from xeroform.__main__ import main
from xeroform.laser import LaserSettings, estimate_scan_time, layer_scan_time, path_lengths
from xeroform.layers import Contour, Hatch, Layer, ScanParams


def _square_layer(contour_params=None, hatch_params=None):
    """10 x 10 mm square outline + two 10 mm fill lines, 1 mm apart, scanned back and forth."""
    square = np.array([[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], float)
    segs = np.array([[[0, 0], [10, 0]], [[10, 1], [0, 1]]], float)
    return Layer(z=0.1, contours=[Contour(square, contour_params)], hatches=[Hatch(segs, hatch_params)])


def test_path_lengths_follow_scan_order():
    lengths = path_lengths(_square_layer())
    assert lengths.contour == pytest.approx(40)
    assert lengths.hatch == pytest.approx(20)
    # contour ends at (0,0) = first fill start; fill 1 ends at (10,0), fill 2 starts at (10,1)
    assert lengths.jump == pytest.approx(1)


def test_layer_scan_time():
    layer = _square_layer(ScanParams(power=3, speed=40), ScanParams(power=5, speed=20))
    # 40 mm / 40 + 20 mm / 20 + 1 mm jump / 1
    assert layer_scan_time(layer, jump_speed=1) == pytest.approx(3)
    assert estimate_scan_time([layer, layer], jump_speed=1) == pytest.approx(6)


def test_scan_time_needs_params():
    with pytest.raises(ValueError):
        layer_scan_time(_square_layer(), jump_speed=1)


@pytest.mark.parametrize("kwargs", [dict(power=-1, speed=100), dict(power=1, speed=0)])
def test_scan_params_validate(kwargs):
    with pytest.raises(ValueError):
        ScanParams(**kwargs)


def test_laser_settings_validate():
    p = ScanParams(power=1, speed=100)
    with pytest.raises(ValueError):
        LaserSettings(contour=p, hatch=p, jump_speed=0)


@pytest.mark.parametrize("field", ["contour_speed", "hatch_speed", "jump_speed"])
def test_config_rejects_bad_speeds(field):
    with pytest.raises(ValueError):
        SliceConfig(**{field: 0})


@pytest.mark.parametrize("field", ["contour_power", "hatch_power"])
def test_config_rejects_negative_power(field):
    with pytest.raises(ValueError):
        SliceConfig(**{field: -0.5})
    SliceConfig(**{field: 0})  # laser off is allowed


def test_hatch_energy_density():
    cfg = SliceConfig(hatch_power=5, hatch_speed=500, hatch_distance=0.2)
    assert cfg.hatch_energy_density == pytest.approx(0.05)


def test_sliced_geometry_carries_params(tmp_path):
    stl = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(str(stl))
    cfg = SliceConfig(
        layer_thickness=1, hatch_distance=1, contour_power=3, contour_speed=300, hatch_power=6, hatch_speed=800
    )
    layers = slice_file(str(stl), str(tmp_path / "cube.cli"), cfg)
    for layer in layers:
        assert all(c.params == ScanParams(3, 300) for c in layer.contours)
        assert all(h.params == ScanParams(6, 800) for h in layer.hatches)
    assert estimate_scan_time(layers, cfg.jump_speed) > 0


def test_cli_reports_time_and_energy(tmp_path, capsys):
    stl = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(str(stl))
    assert (
        main(
            [
                str(stl),
                "-o",
                str(tmp_path / "c.cli"),
                "--layer",
                "1",
                "--hatch-power",
                "4",
                "--hatch-speed",
                "400",
                "--hatch-distance",
                "0.25",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Estimated laser time:" in out
    assert "Hatch energy density: 0.0400 J/mm^2" in out
