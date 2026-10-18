"""Project files: round trip, relative paths, bad files."""

import json
import os

import pytest

from xeroform import SliceConfig
from xeroform.project import Project, ProjectError, ProjectPart, config_from_dict, config_to_dict


def test_round_trip_with_relative_paths(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    cube = models / "cube.stl"
    cube.write_text("x")
    cfg = SliceConfig(layer_thickness=0.15, scan_order="meander", build_volume=(200, 180, 150))
    path = tmp_path / "job.xeroform"
    Project([ProjectPart(str(cube), 4)], cfg).save(str(path))

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["parts"] == [{"path": os.path.join("models", "cube.stl"), "copies": 4}]

    loaded = Project.load(str(path))
    assert loaded.parts == [ProjectPart(str(cube), 4)]
    assert loaded.config == cfg


def test_own_settings_and_positions_round_trip(tmp_path):
    (tmp_path / "bar.stl").write_text("x")
    part = ProjectPart(
        str(tmp_path / "bar.stl"),
        copies=3,
        rotation=(0, 90, 0),
        settings={"hatch_power": 8.0, "hatch_distance": 0.15},
        spots=[(10.0, -5.0, 0.0, 90), (30.0, -5.0, 0.0, 0)],  # the third copy is packed
    )
    path = tmp_path / "job.xeroform"
    Project([part]).save(str(path))
    entry = json.loads(path.read_text(encoding="utf-8"))["parts"][0]
    assert entry["settings"] == {"hatch_power": 8.0, "hatch_distance": 0.15}
    assert entry["spots"] == [[10.0, -5.0, 0.0, 90], [30.0, -5.0, 0.0, 0]]
    assert Project.load(str(path)).parts == [part]


@pytest.mark.parametrize(
    "entry, match",
    [
        ({"settings": {"layer_thickness": 0.2}}, "can't have its own layer_thickness"),
        ({"settings": {"hatch_power": -1}}, "hatch_power must be >= 0"),
        ({"spots": [[0, 0, 0, 45]]}, "malformed parts"),
        ({"spots": [[0, 0]]}, "malformed parts"),
    ],
)
def test_bad_part_settings_or_positions(tmp_path, entry, match):
    path = tmp_path / "bad.xeroform"
    path.write_text(json.dumps({"format": "xeroform-project", "parts": [{"path": "a.stl", **entry}]}))
    with pytest.raises(ProjectError, match=match):
        Project.load(str(path))


def test_folder_can_move(tmp_path):
    src = tmp_path / "a"
    src.mkdir()
    (src / "part.stl").write_text("x")
    Project([ProjectPart(str(src / "part.stl"))]).save(str(src / "p.xeroform"))
    dst = tmp_path / "b"
    src.rename(dst)
    assert Project.load(str(dst / "p.xeroform")).parts[0].path == str(dst / "part.stl")


def test_unknown_settings_are_ignored_missing_get_defaults():
    cfg = config_from_dict({"layer_thickness": 0.2, "from_the_future": 1})
    assert cfg.layer_thickness == 0.2 and cfg.hatch_speed == SliceConfig().hatch_speed
    assert config_from_dict(config_to_dict(SliceConfig(build_volume=(1, 2, 3)))).build_volume == (1, 2, 3)


@pytest.mark.parametrize(
    "content, match",
    [
        ("not json", "not a valid project"),
        ('{"format": "something-else"}', "not a XeroForm project"),
        ('{"format": "xeroform-project", "version": 99}', "newer XeroForm"),
        ('{"format": "xeroform-project", "settings": {"layer_thickness": 0}}', "Invalid settings"),
        ('{"format": "xeroform-project", "parts": [{"copies": 2}]}', "malformed parts"),
    ],
)
def test_bad_files(tmp_path, content, match):
    path = tmp_path / "bad.xeroform"
    path.write_text(content)
    with pytest.raises(ProjectError, match=match):
        Project.load(str(path))


def test_missing_file(tmp_path):
    with pytest.raises(ProjectError, match="Could not open"):
        Project.load(str(tmp_path / "nope.xeroform"))


def test_save_is_atomic(tmp_path):
    path = tmp_path / "p.xeroform"
    Project().save(str(path))
    assert path.exists() and not (tmp_path / "p.xeroform.tmp").exists()


@pytest.mark.parametrize(
    "raw", ["\\\\attacker\\share\\part.stl", "//attacker/share/part.stl", "\\\\?\\UNC\\attacker\\share\\part.stl"]
)
def test_network_paths_are_refused(tmp_path, raw):
    path = tmp_path / "p.xeroform"
    path.write_text(json.dumps({"format": "xeroform-project", "version": 1, "parts": [{"path": raw, "copies": 1}]}))
    with pytest.raises(ProjectError, match="network location"):
        Project.load(str(path))


def test_local_paths_outside_the_folder_still_work(tmp_path):
    (tmp_path / "models").mkdir()
    proj = tmp_path / "projects"
    proj.mkdir()
    model = tmp_path / "models" / "part.stl"
    Project([ProjectPart(str(model))]).save(str(proj / "p.xeroform"))
    assert Project.load(str(proj / "p.xeroform")).parts[0].path == str(model)
