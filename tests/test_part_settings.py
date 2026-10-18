"""Parts with their own settings, and parts placed by hand, in one build."""

import numpy as np
import pytest
import trimesh

from xeroform import SliceConfig
from xeroform.__main__ import main
from xeroform.config import PART_SETTINGS
from xeroform.laser import estimate_scan_time
from xeroform.pipeline import slice_build, slice_job, slice_project
from xeroform.project import Project, ProjectPart
from xeroform.summary import summary_lines


@pytest.fixture
def models(tmp_path):
    cube, bar = tmp_path / "cube.stl", tmp_path / "bar.stl"
    trimesh.creation.box(extents=[20, 20, 10]).export(str(cube))
    trimesh.creation.box(extents=[30, 8, 6]).export(str(bar))
    return str(cube), str(bar)


def _config(**kw):
    return SliceConfig(layer_thickness=1, hatch_distance=1, build_volume=(100, 100, 100), **kw)


def _powers_by_part(result, x_split):
    """Hatch powers left and right of x = x_split."""
    left, right = set(), set()
    for layer in result.layers:
        for h in layer.hatches:
            x = float(np.mean(h.segments[:, :, 0]))
            (left if x < x_split else right).add(h.params.power)
    return left, right


def test_a_part_with_its_own_laser_power(models):
    spots = [(-25, 0, 0, 0), (25, 0, 0, 0)]
    plain = slice_build(list(models), None, _config(), spots=spots)
    result = slice_build(list(models), None, _config(), spots=spots, settings=[None, {"hatch_power": 9}])
    assert _powers_by_part(result, 0) == ({5.0}, {9.0})
    # the same layers, just different power on the bar
    assert [l.z for l in result.layers] == [l.z for l in plain.layers]
    assert [len(l.contours) for l in result.layers] == [len(l.contours) for l in plain.layers]
    assert result.own_settings == {models[1]: {"hatch_power": 9.0}}
    assert "own settings: fill 9 W" in "\n".join(summary_lines(result, _config()))


def test_own_hatch_spacing_and_speed(models):
    spots = [(-25, 0, 0, 0), (25, 0, 0, 0)]
    own = {"hatch_distance": 0.5, "hatch_speed": 250}
    result = slice_build(list(models), None, _config(), spots=spots, settings=[own, None])
    cube_vectors = sum(len(h.segments) for l in result.layers for h in l.hatches if h.params.speed == 250)
    plain = slice_build(list(models), None, _config(), spots=spots)
    plain_vectors = sum(len(h.segments) for l in plain.layers for h in l.hatches if np.mean(h.segments[..., 0]) < 0)
    assert cube_vectors == pytest.approx(2 * plain_vectors, rel=0.1)  # half the spacing, twice the lines
    assert estimate_scan_time(result.layers, 2000) > estimate_scan_time(plain.layers, 2000)


def test_stacked_parts_with_their_own_settings_keep_every_layer(models):
    cube, _ = models
    spots = [(0, 0, 0, 0), (0, 0, 15, 0)]  # one on top of the other, 5 mm apart
    result = slice_build([cube], None, _config(), copies=2, spots=spots)
    assert [l.z for l in result.layers] == pytest.approx([float(i) for i in range(1, 25)])
    own = slice_build([cube, cube], None, _config(), spots=spots, settings=[None, {"contour_power": 2}])
    assert [l.z for l in own.layers] == [l.z for l in result.layers]
    gap = [l for l in own.layers if 10 < l.z < 15]
    assert gap and all(not l.contours and not l.hatches for l in gap)


def test_settings_equal_to_the_builds_are_not_own_settings(models):
    result = slice_build(list(models), None, _config(), settings=[{"hatch_power": 5.0}, None])
    assert result.own_settings == {}


def test_hand_placed_parts(models):
    result = slice_build(list(models), None, _config(), spots=[(-20, 10, 0, 90), None])
    cube, bar = result.build.placements
    assert cube.spot == pytest.approx((-20, 10, 0, 90))
    assert result.build.warnings == []
    close = slice_build(list(models), None, _config(), spots=[(0, 0, 0, 0), (0, 16, 0, 0)])  # 2 mm gap
    assert close.build.warnings == ["cube.stl and bar.stl are 2.0 mm apart (spacing 3 mm)."]
    assert "warning: cube.stl and bar.stl are 2.0 mm apart" in "\n".join(summary_lines(close, _config()))


def test_single_part_with_its_own_settings(models):
    result = slice_job(models[0], None, _config(), settings={"hatch_power": 7, "contour_speed": 300})
    assert {h.params.power for l in result.layers for h in l.hatches} == {7.0}
    assert {c.params.speed for l in result.layers for c in l.contours} == {300.0}


def test_bad_part_settings(models):
    with pytest.raises(ValueError, match="can't have its own layer_thickness"):
        slice_build(list(models), None, _config(), settings=[{"layer_thickness": 0.2}, None])
    with pytest.raises(ValueError, match="hatch_speed must be > 0"):
        slice_build(list(models), None, _config(), settings=[{"hatch_speed": 0}, None])
    assert "layer_thickness" not in PART_SETTINGS


def test_slice_a_project_from_the_command_line(models, tmp_path, capsys):
    cube, bar = models
    project = Project(
        [ProjectPart(cube, 2, spots=[(-20, -20, 0, 0)]), ProjectPart(bar, 1, (0, 0, 90), {"hatch_power": 9})],
        _config(),
    )
    path = tmp_path / "job.xeroform"
    project.save(str(path))
    result = slice_project(Project.load(str(path)), None)
    assert len(result.build.placements) == 3
    assert result.build.placements[0].spot == pytest.approx((-20, -20, 0, 0))
    assert result.own_settings == {bar: {"hatch_power": 9.0}}

    out = tmp_path / "job.cli"
    assert main([str(path), "-o", str(out)]) == 0
    assert out.exists() and "Build: 3 parts packed" in capsys.readouterr().out


def test_project_mode_rejects_other_inputs(models, tmp_path):
    path = tmp_path / "job.xeroform"
    Project([ProjectPart(models[0])], _config()).save(str(path))
    with pytest.raises(SystemExit):
        main([str(path), models[1], "-o", str(tmp_path / "x.cli")])
    assert main([str(tmp_path / "missing.xeroform"), "-o", str(tmp_path / "x.cli")]) == 1


def test_single_part_project_without_a_plate_is_centred(models):
    result = slice_project(Project([ProjectPart(models[0])], SliceConfig(layer_thickness=1, hatch_distance=1)), None)
    assert result.build is None and result.bounding_box[0] == pytest.approx(-10)
