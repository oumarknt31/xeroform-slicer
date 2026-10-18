"""Nesting: packing several parts into one build."""

import itertools

import numpy as np
import pytest
import trimesh
from scipy.spatial import cKDTree

from xeroform import SliceConfig
from xeroform.__main__ import main
from xeroform.nesting import (
    NestingError,
    _turned,
    arrange,
    conflicts,
    pack_boxes,
    pack_shapes,
    placement_at,
    plan,
)
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


# --- packing by shape ---------------------------------------------------------


def _bracket(arm=40, width=12, height=10):
    """An L-shaped bracket, lying flat."""
    a = trimesh.creation.box(bounds=[[0, 0, 0], [arm, width, height]])
    b = trimesh.creation.box(bounds=[[0, width, 0], [width, arm, height]])
    return trimesh.util.concatenate([a, b])


def _cup(radius=18, wall=2, height=25):
    walls = trimesh.creation.annulus(r_min=radius - wall, r_max=radius, height=height)
    walls.apply_translation([0, 0, height / 2])
    base = trimesh.creation.cylinder(radius=radius - wall, height=wall)
    base.apply_translation([0, 0, wall / 2])
    return trimesh.util.concatenate([walls, base])


def _placed(meshes, placements):
    return [_turned(meshes[p.item], p.turn).apply_translation(p.position) for p in placements]


def _surface(mesh, n=6000):
    """Points on the surface. Distances measured between them are never less
    than the true ones."""
    points, _ = trimesh.sample.sample_surface(mesh, n, seed=0)
    return np.vstack([points, mesh.vertices])


def _near_pairs(parts, gap, axes=slice(0, 3)):
    """Pairs of parts whose boxes come closer than `gap` (along `axes`)."""
    for a, b in itertools.combinations(range(len(parts)), 2):
        lo, hi = parts[a].bounds, parts[b].bounds
        apart = np.maximum(lo[0] - hi[1], hi[0] - lo[1])[axes]
        if (apart < gap).all():
            yield a, b


def _assert_apart(parts, spacing, volume):
    X, Y, Z = volume
    for m in parts:
        assert (m.bounds[0][:2] >= np.array([-X / 2, -Y / 2]) + spacing - 1e-6).all()
        assert (m.bounds[1][:2] <= np.array([X / 2, Y / 2]) - spacing + 1e-6).all()
        assert m.bounds[0][2] >= -1e-9 and m.bounds[1][2] <= Z + 1e-6
    clouds = {}
    for a, b in _near_pairs(parts, spacing):
        for i in (a, b):
            clouds.setdefault(i, _surface(parts[i]))
        gap, _ = cKDTree(clouds[a]).query(clouds[b])
        assert gap.min() >= spacing - 0.05, (a, b, gap.min())


def _assert_liftable(parts):
    """No two parts each have material above the other: lifting them straight
    out, top one first, never hits anything."""
    clouds = {}

    def above(a, b):  # some point of a directly above some point of b
        tree = cKDTree(clouds[b][:, :2])
        for i, near in enumerate(tree.query_ball_point(clouds[a][:, :2], 0.3)):
            if near and clouds[a][i, 2] > clouds[b][near, 2].min() + 1e-6:
                return True
        return False

    for a, b in _near_pairs(parts, 0.3, axes=slice(0, 2)):
        for i in (a, b):
            clouds.setdefault(i, _surface(parts[i], 3000))
        assert not (above(a, b) and above(b, a)), (a, b)


def test_shapes_keep_spacing_and_walls():
    meshes = [_bracket()] * 10 + [trimesh.creation.annulus(r_min=6, r_max=10, height=6)] * 6
    volume = (120, 120, 60)
    placements = pack_shapes(meshes, volume, spacing=3)
    assert {p.turn for p in placements} <= {0, 90, 180, 270}
    parts = _placed(meshes, placements)
    _assert_apart(parts, 3, volume)
    _assert_liftable(parts)


def test_part_drops_into_a_ring():
    ring = trimesh.creation.annulus(r_min=14, r_max=20, height=8)
    pin = trimesh.creation.box(extents=[10, 10, 8])
    volume = (46, 46, 10)  # room for the ring only - the pin has to go in the middle
    with pytest.raises(NestingError):
        pack_boxes([ring.extents, pin.extents], volume, spacing=3)
    merged, placements = arrange([ring, pin], volume, spacing=3)
    ring_at, pin_at = placements
    centre = np.add(ring_at.position[:2], 20)
    corners = np.add(pin_at.position[:2], [[0, 0], [10, 0], [0, 10], [10, 10]])
    assert (np.linalg.norm(corners - centre, axis=1) <= 14 - 3 + 1e-6).all()  # in the hole
    assert pin_at.position[2] == 0
    _assert_apart(_placed([ring, pin], placements), 3, volume)


def test_nothing_trapped_under_an_upturned_cup():
    cup = _cup()
    cup.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))  # opening down
    cube = trimesh.creation.box(extents=[8, 8, 8])
    meshes = [cup] + [cube] * 3
    placements = pack_shapes(meshes, (44, 44, 80), spacing=3)
    top = placements[0].position[2] + placements[0].size[2]
    assert all(p.position[2] >= top + 3 - 1e-6 for p in placements[1:])  # on top, not inside
    _assert_liftable(_placed(meshes, placements))


def test_shapes_pack_lower_than_boxes():
    for meshes in ([_bracket()] * 40, [_cup()] * 20 + [trimesh.creation.box(extents=[12, 12, 12])] * 30):
        volume = (150, 150, 150)
        boxes = pack_boxes([m.extents for m in meshes], volume, spacing=3)
        merged, placements = arrange(meshes, volume, spacing=3)
        box_height = max(p.position[2] + p.size[2] for p in boxes)
        assert merged.bounds[1][2] < 0.9 * box_height
        assert merged.volume == pytest.approx(sum(m.volume for m in meshes), rel=1e-6)
        _assert_apart(_placed(meshes, placements), 3, volume)


# --- parts placed by hand ------------------------------------------------------


def test_spot_round_trip():
    bar = trimesh.creation.box(extents=[30, 10, 5])
    for p in plan([bar] * 3, (100, 100, 100), spacing=3):
        q = placement_at(bar, p.item, p.spot)
        assert (q.item, q.turn) == (p.item, p.turn)
        assert q.position == pytest.approx(p.position) and q.size == pytest.approx(p.size)
    p = placement_at(bar, 0, (10, -5, 2, 90))
    assert p.size == pytest.approx((10, 30, 5)) and p.position == pytest.approx((5, -20, 2))


def test_pinned_parts_stay_and_the_rest_pack_around_them():
    cube, pin = trimesh.creation.box(extents=[20, 20, 20]), trimesh.creation.box(extents=[6, 6, 6])
    meshes, volume = [cube, pin, pin, pin], (130, 130, 100)
    placements = plan(meshes, volume, spacing=3, spots={0: (10, -20, 0, 90)})
    assert placements[0].spot == pytest.approx((10, -20, 0, 90))
    assert conflicts(meshes, placements, volume, 3) == []
    # packed against the pinned cube, not off in a corner
    for p in placements[1:]:
        assert np.hypot(p.spot[0] - 10, p.spot[1] + 20) < 25
    merged, _ = arrange(meshes, volume, spacing=3, spots={0: (10, -20, 0, 90)})
    assert merged.bounds[0] == pytest.approx(np.min([p.position for p in placements], axis=0))


def test_conflicts():
    cube, pin = trimesh.creation.box(extents=[20, 20, 20]), trimesh.creation.box(extents=[4, 4, 4])
    meshes, volume, names = [cube, pin], (130, 130, 100), ["cube", "pin"]

    def check(*spots):
        placements = [placement_at(m, i, spot) for i, (m, spot) in enumerate(zip(meshes, spots))]
        return conflicts(meshes, placements, volume, 3, names)

    assert check((0, 0, 0, 0), (40, 0, 0, 0)) == []
    assert check((0, 0, 0, 0), (0, 0, 8, 0)) == ["cube and pin are inside each other."]
    assert check((0, 0, 0, 0), (12.5, 0, 0, 0)) == ["cube and pin are 0.5 mm apart (spacing 3 mm)."]
    assert check((0, 0, 0, 0), (0, 0, 21, 0)) == ["cube and pin are 1.0 mm apart (spacing 3 mm)."]
    assert check((-60, 0, 0, 0), (40, 0, 0, 0)) == ["cube is closer than 3 mm to the chamber wall."]
    assert check((0, 0, 0, 0), (40, 0, 97, 0)) == ["pin sticks out of the build volume (97.0 to 101.0 mm high)."]


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
