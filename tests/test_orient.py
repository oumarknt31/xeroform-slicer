"""Part orientation: rotations, lay flat, lowest height, and their use in slicing."""

import json

import numpy as np
import pytest
import trimesh

from xeroform import SliceConfig
from xeroform import orient as o
from xeroform.__main__ import main
from xeroform.part import prepare_mesh
from xeroform.pipeline import slice_build, slice_job
from xeroform.project import Project, ProjectError, ProjectPart


@pytest.fixture
def tall(tmp_path):
    """A 10 x 20 x 60 mm block, saved standing up."""
    path = tmp_path / "tall.stl"
    trimesh.creation.box(extents=[10, 20, 60]).export(str(path))
    return str(path)


def hull(path):
    mesh, _ = prepare_mesh(path)
    return mesh.convex_hull.vertices


def test_angles_round_trip_and_simplest_form():
    for angles in [(30, -45, 120), (180, -90, 180), (170, 100, 0), (0, 0, 0)]:
        back = o.angles_of(o.matrix(angles))
        assert np.allclose(o.matrix(back), o.matrix(angles), atol=1e-9)
        assert all(-180 < a <= 180 for a in back)
    assert o.angles_of(o.matrix((180, -90, 180))) == (0.0, -90.0, 0.0)


def test_turn_is_about_the_fixed_axes():
    turned = o.turn((0, 0, 90), "x", 90)  # first 90 about Z, then 90 about the fixed X
    expected = o.matrix((90, 0, 0)) @ o.matrix((0, 0, 90))
    assert np.allclose(o.matrix(turned), expected, atol=1e-9)


def test_extents(tall):
    assert o.extents(hull(tall), (90, 0, 0)) == pytest.approx([10, 60, 20])


def test_flat_faces_largest_first(tall):
    faces = o.flat_faces(hull(tall))
    assert len(faces) == 6
    assert [round(a) for _, a in faces] == [1200, 1200, 600, 600, 200, 200]


def test_lay_flat_steps_through_faces(tall):
    pts = hull(tall)
    assert o.extents(pts, o.lay_flat(pts, 0))[2] == pytest.approx(10)  # on a 20 x 60 face
    assert o.extents(pts, o.lay_flat(pts, 2))[2] == pytest.approx(20)  # on a 10 x 60 face
    assert o.extents(pts, o.lay_flat(pts, 4))[2] == pytest.approx(60)  # on its end


def test_lowest_lies_down_with_long_side_along_x(tall):
    size = o.extents(hull(tall), o.lowest(hull(tall)))
    assert size == pytest.approx([60, 20, 10])


def test_lowest_squares_up_a_tilted_part():
    box = trimesh.creation.box(extents=[10, 20, 60])
    box.apply_transform(trimesh.transformations.rotation_matrix(0.5, [1, 1, 0]))
    pts = box.convex_hull.vertices
    assert o.extents(pts, o.lowest(pts)) == pytest.approx([60, 20, 10], abs=0.01)


def test_prepare_mesh_applies_rotation(tall):
    mesh, report = prepare_mesh(tall, rotation=(0, 90, 0))
    assert report.size == pytest.approx((60, 20, 10))
    assert mesh.bounds[0][2] == pytest.approx(0)  # still resting on the plate


def test_slice_job_with_rotation(tall, tmp_path):
    cfg = SliceConfig(layer_thickness=1, hatch_distance=1)
    standing = slice_job(tall, None, cfg)
    lying = slice_job(tall, None, cfg, rotation=(0, 90, 0))
    assert (len(standing.layers), len(lying.layers)) == (59, 9)


def test_slice_build_orients_each_part(tall, tmp_path):
    cfg = SliceConfig(layer_thickness=1, hatch_distance=1, build_volume=(150, 150, 100))
    result = slice_build([tall, tall], None, cfg, rotations=[(0, 0, 0), (0, 90, 0)])
    sizes = sorted(p.size[2] for p in result.build.placements)
    assert sizes == pytest.approx([10, 60])
    assert len(result.reports) == 1  # one report per model file
    with pytest.raises(ValueError):
        slice_build([tall, tall], None, cfg, rotations=[(0, 0, 0)])


def test_project_saves_rotation(tall, tmp_path):
    path = tmp_path / "job.xeroform"
    Project([ProjectPart(tall, 2, (0, 90, 0)), ProjectPart(tall)]).save(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["parts"][0]["rotation"] == [0, 90, 0] and "rotation" not in data["parts"][1]
    loaded = Project.load(str(path))
    assert [p.rotation for p in loaded.parts] == [(0, 90, 0), (0, 0, 0)]


def test_project_rejects_bad_rotation(tmp_path):
    path = tmp_path / "bad.xeroform"
    path.write_text(json.dumps({"format": "xeroform-project", "parts": [{"path": "a.stl", "rotation": [1, 2]}]}))
    with pytest.raises(ProjectError, match="malformed parts"):
        Project.load(str(path))


def test_cli_orientation(tall, tmp_path, capsys):
    out = str(tmp_path / "t.cli")
    assert main([tall, "-o", out, "--layer", "1", "--orient", "lowest"]) == 0
    assert "Sliced 9 layers" in capsys.readouterr().out
    assert main([tall, "-o", out, "--layer", "1", "--rotate", "90", "0", "0"]) == 0
    assert "Model: 10.0 x 60.0 x 20.0 mm" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main([tall, "-o", out, "--rotate", "90", "0", "0", "--orient", "lowest"])
