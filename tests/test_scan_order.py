"""Scan order: same vectors, less laser-off travel."""
import numpy as np
import pytest
import trimesh

from xeroform import SliceConfig, slice_file
from xeroform.__main__ import main
from xeroform.hatching import HatchSettings
from xeroform.laser import path_lengths
from xeroform.layers import Hatch, Layer
from xeroform.scan_order import order_segments


def _raster(lines=5, length=10.0, spacing=1.0):
    """Horizontal vectors, all left to right, bottom to top - like PySLM's output."""
    return np.array([[[0, i * spacing], [length, i * spacing]] for i in range(lines)], float)


def _jump(segs):
    return path_lengths(Layer(z=0, hatches=[Hatch(segs)])).jump


def _undirected(segs):
    return sorted(tuple(sorted(map(tuple, np.round(s, 6)))) for s in segs)


@pytest.mark.parametrize("mode", ["nearest", "meander", "raster"])
def test_same_vectors_any_order(mode):
    segs = _raster()
    rng = np.random.default_rng(0)
    shuffled = segs[rng.permutation(len(segs))]
    assert _undirected(order_segments(shuffled, mode)) == _undirected(segs)


def test_raster_is_unchanged():
    segs = _raster()
    assert np.array_equal(order_segments(segs, "raster"), segs)


@pytest.mark.parametrize("mode", ["nearest", "meander"])
def test_zigzag_on_a_rectangle(mode):
    segs = order_segments(_raster(lines=5, spacing=1.0), mode)
    assert _jump(segs) == pytest.approx(4.0)  # only the 1 mm step between lines
    assert _jump(_raster(lines=5)) == pytest.approx(4 * np.hypot(10, 1))


def test_meander_handles_split_lines():
    """A line split by a hole stays together and alternates direction as a whole."""
    left = _raster(lines=4, length=4)
    right = left + [6, 0]
    segs = order_segments(np.concatenate([left, right]), "meander")
    ys = segs[:, 0, 1]
    assert list(ys) == [0, 0, 1, 1, 2, 2, 3, 3]
    assert (segs[0::4, 1, 0] > segs[0::4, 0, 0]).all()  # line 0 left to right
    assert (segs[2::4, 1, 0] < segs[2::4, 0, 0]).all()  # line 1 right to left


def test_nearest_does_one_island_at_a_time():
    left = _raster(lines=4, length=4)
    right = left + [50, 0]
    segs = order_segments(np.concatenate([left, right]), "nearest", start=np.array([0.0, 0.0]))
    assert _jump(segs) < 60  # one jump to the far island (about 46 mm), not one per line
    assert (segs[:4, 0, 0] < 10).all() and (segs[4:, 0, 0] > 40).all()


def test_nearest_starts_near_start():
    segs = order_segments(_raster(), "nearest", start=np.array([10.0, 4.0]))
    assert np.allclose(segs[0, 0], [10, 4])


def test_unknown_mode():
    with pytest.raises(ValueError):
        order_segments(_raster(), "spiral")
    with pytest.raises(ValueError):
        HatchSettings(scan_order="spiral")
    with pytest.raises(ValueError):
        SliceConfig(scan_order="spiral")


def test_tube_travel_by_mode(tmp_path):
    stl = tmp_path / "ring.stl"
    trimesh.creation.annulus(r_min=4, r_max=10, height=10).export(str(stl))
    on, jump = {}, {}
    for mode in ("raster", "meander", "nearest"):
        layers = slice_file(str(stl), str(tmp_path / "r.cli"),
                            SliceConfig(layer_thickness=1, hatch_distance=0.5, scan_order=mode))
        on[mode] = sum(path_lengths(l).hatch for l in layers)
        jump[mode] = sum(path_lengths(l).jump for l in layers)
    assert on["raster"] == pytest.approx(on["meander"]) == pytest.approx(on["nearest"])
    assert jump["nearest"] < jump["meander"] < jump["raster"] / 3


def test_cli_scan_order(tmp_path):
    stl = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(str(stl))
    assert main([str(stl), "-o", str(tmp_path / "c.cli"), "--layer", "2", "--scan-order", "meander"]) == 0
    with pytest.raises(SystemExit):
        main([str(stl), "-o", str(tmp_path / "c.cli"), "--scan-order", "spiral"])
