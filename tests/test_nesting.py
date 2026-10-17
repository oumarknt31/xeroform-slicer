"""Nesting: packing several parts into one build."""

import itertools

import numpy as np
import pytest
import trimesh

from xeroform import SliceConfig
from xeroform.__main__ import main
from xeroform.nesting import NestingError, arrange, pack_boxes
from xeroform.part import MeshError
from xeroform.pipeline import slice_build


def _boxes(placements, sizes):
    """Actual (not padded) part boxes as (x0, y0, z0, x1, y1, z1)."""
    out = []
    for p in placements:
        sx, sy, sz = sizes[p.item]
        w, d = (sy, sx) if p.rotated else (sx, sy)
        x, y, z = p.position
        out.append((x, y, z, x + w, y + d, z + sz))
    return np.array(out)


def _assert_valid(placements, sizes, volume, spacing):
    X, Y, Z = volume
    boxes = _boxes(placements, sizes)
    tol = 1e-6
    # inside the chamber, `spacing` from the side walls
    assert (boxes[:, 0] >= -X / 2 + spacing - tol).all() and (boxes[:, 3] <= X / 2 - spacing + tol).all()
    assert (boxes[:, 1] >= -Y / 2 + spacing - tol).all() and (boxes[:, 4] <= Y / 2 - spacing + tol).all()
    assert (boxes[:, 2] >= -tol).all() and (boxes[:, 5] <= Z + tol).all()
    # every pair at least `spacing` apart along some axis
    for a, b in itertools.combinations(boxes, 2):
        gaps = [max(b[k] - a[k + 3], a[k] - b[k + 3]) for k in range(3)]
        assert max(gaps) >= spacing - tol, (a, b)


def test_single_part_is_centred():
    (p,) = pack_boxes([(20, 10, 5)], (100, 100, 100))
    assert np.allclose(p.position, (-10, -5, 0)) and not p.rotated


def test_mixed_parts_valid():
    rng = np.random.default_rng(1)
    sizes = [tuple(rng.uniform(5, 40, 3)) for _ in range(30)]
    placements = pack_boxes(sizes, (150, 150, 150), spacing=3)
    assert [p.item for p in placements] == list(range(30))
    _assert_valid(placements, sizes, (150, 150, 150), 3)


def test_fills_floor_before_stacking():
    sizes = [(10, 10, 10)] * 4
    assert all(p.position[2] == 0 for p in pack_boxes(sizes, (100, 100, 100)))


def test_stacks_when_floor_is_full():
    sizes = [(20, 20, 20)] * 40  # 4 x 4 per level in 100 x 100 with 3 mm gaps
    placements = pack_boxes(sizes, (100, 100, 100), spacing=3)
    _assert_valid(placements, sizes, (100, 100, 100), 3)
    tops = _boxes(placements, sizes)[:, 5]
    assert tops.max() == pytest.approx(3 * 20 + 2 * 3)


def test_compact_footprint():
    placements = pack_boxes([(20, 20, 5)] * 4, (200, 200, 100), spacing=2)
    boxes = _boxes(placements, [(20, 20, 5)] * 4)
    width, depth = boxes[:, 3].max() - boxes[:, 0].min(), boxes[:, 4].max() - boxes[:, 1].min()
    assert width == pytest.approx(42) and depth == pytest.approx(42)  # 2 x 2, not a row of 4
    assert boxes[:, 0].min() == pytest.approx(-21) and boxes[:, 1].min() == pytest.approx(-21)


def test_turns_parts_to_fit():
    sizes = [(127, 63.5, 35)] * 2
    placements = pack_boxes(sizes, (80, 200, 100), spacing=3)
    assert all(p.rotated for p in placements)
    _assert_valid(placements, sizes, (80, 200, 100), 3)
    with pytest.raises(NestingError, match="too big.*turning parts is switched off"):
        pack_boxes(sizes, (80, 200, 100), spacing=3, allow_rotation=False)


def test_part_taller_than_chamber():
    with pytest.raises(NestingError, match="bracket.*too big"):
        pack_boxes([(10, 10, 120)], (100, 100, 100), names=["bracket"])


def test_overflow_names_what_is_left_over():
    pack_boxes([(20, 20, 20)] * 64, (100, 100, 100), spacing=3)  # exactly 4 levels of 16
    names = ["cube.stl"] * 64 + ["ring.stl"] * 6
    with pytest.raises(NestingError, match=r"Only 64 of 70 parts fit.*ring\.stl x6"):
        pack_boxes([(20, 20, 20)] * 70, (100, 100, 100), spacing=3, names=names)


def test_arrange_merges_placed_meshes():
    cube = trimesh.creation.box(extents=[20, 20, 20])
    bar = trimesh.creation.box(extents=[60, 10, 5])
    merged, placements = arrange([cube, cube, bar], (100, 100, 100), spacing=3)
    assert merged.body_count == 3 and len(placements) == 3
    assert merged.volume == pytest.approx(2 * 8000 + 3000)
    assert (merged.bounds[0][:2] >= -50 + 3 - 1e-6).all() and (merged.bounds[1][:2] <= 50 - 3 + 1e-6).all()
    assert merged.bounds[0][2] == pytest.approx(0)


# --- pipeline / CLI ---------------------------------------------------------


@pytest.fixture
def two_models(tmp_path):
    cube, ring = tmp_path / "cube.stl", tmp_path / "ring.stl"
    trimesh.creation.box(extents=[20, 20, 20]).export(str(cube))
    trimesh.creation.annulus(r_min=4, r_max=10, height=10).export(str(ring))
    return str(cube), str(ring)


def test_slice_build(two_models, tmp_path):
    cfg = SliceConfig(layer_thickness=1, hatch_distance=1, build_volume=(100, 100, 100))
    result = slice_build(list(two_models), str(tmp_path / "b.cli"), cfg, copies=3)
    assert [p for p, _ in result.reports] == list(two_models)
    assert len(result.build.placements) == 6
    assert result.build.height == pytest.approx(20)
    total = 3 * (8000 + np.pi * (10**2 - 4**2) * 10)
    assert result.build.density == pytest.approx(total / (100 * 100 * 20), rel=0.02)
    assert len(result.layers) == 19
    # 3 cubes in every layer; the 10 mm tubes only in the lower half
    outers = [sum(not c.is_hole for c in l.contours) for l in result.layers]
    assert outers[0] > outers[-1]


def test_stacked_build_keeps_empty_layers(tmp_path):
    """The gap between stacked parts has no geometry but still needs its powder layers."""
    cube = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[20, 20, 20]).export(str(cube))
    cfg = SliceConfig(layer_thickness=1, hatch_distance=2, build_volume=(30, 30, 100), part_spacing=3)
    result = slice_build([str(cube)], str(tmp_path / "b.cli"), cfg, copies=2)  # one on top of the other
    assert result.build.height == pytest.approx(43)
    zs = [l.z for l in result.layers]
    assert zs == pytest.approx([float(i) for i in range(1, 43)])  # every layer, gap included
    empty = [l.z for l in result.layers if not l.contours]
    # cubes span z 0-20 and 23-43; slices strictly inside the gap are powder only
    assert {21.0, 22.0} <= set(empty) and all(20 <= z <= 23 for z in empty)
    text = (tmp_path / "b.cli").read_text(encoding="utf-8")
    assert text.count("$$LAYER/") == 42


def test_slice_build_needs_build_volume(two_models, tmp_path):
    with pytest.raises(MeshError, match="--build-volume"):
        slice_build(list(two_models), str(tmp_path / "b.cli"), SliceConfig())


def test_config_rejects_negative_spacing():
    with pytest.raises(ValueError):
        SliceConfig(part_spacing=-1)


def test_cli_build(two_models, tmp_path, capsys):
    args = [*two_models, "-o", str(tmp_path / "b.cli"), "--layer", "2", "--build-volume", "100", "100", "100"]
    assert main(args + ["--copies", "2"]) == 0
    out = capsys.readouterr().out
    assert "Model cube.stl:" in out and "Model ring.stl:" in out
    assert "Build: 4 parts packed 20.0 mm high" in out
    assert main(args + ["--copies", "70"]) == 1
    assert "Only" in capsys.readouterr().err
