"""Project files: round trip, relative paths, bad files."""
import json
import os

import pytest

from slicerkit import SliceConfig
from slicerkit.project import Project, ProjectError, ProjectPart, config_from_dict, config_to_dict


def test_round_trip_with_relative_paths(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    cube = models / "cube.stl"
    cube.write_text("x")
    cfg = SliceConfig(layer_thickness=0.15, scan_order="meander", build_volume=(200, 180, 150))
    path = tmp_path / "job.slicerkit"
    Project([ProjectPart(str(cube), 4)], cfg).save(str(path))

    data = json.loads(path.read_text())
    assert data["parts"] == [{"path": os.path.join("models", "cube.stl"), "copies": 4}]

    loaded = Project.load(str(path))
    assert loaded.parts == [ProjectPart(str(cube), 4)]
    assert loaded.config == cfg


def test_folder_can_move(tmp_path):
    src = tmp_path / "a"
    src.mkdir()
    (src / "part.stl").write_text("x")
    Project([ProjectPart(str(src / "part.stl"))]).save(str(src / "p.slicerkit"))
    dst = tmp_path / "b"
    src.rename(dst)
    assert Project.load(str(dst / "p.slicerkit")).parts[0].path == str(dst / "part.stl")


def test_unknown_settings_are_ignored_missing_get_defaults():
    cfg = config_from_dict({"layer_thickness": 0.2, "from_the_future": 1})
    assert cfg.layer_thickness == 0.2 and cfg.hatch_speed == SliceConfig().hatch_speed
    assert config_from_dict(config_to_dict(SliceConfig(build_volume=(1, 2, 3)))).build_volume == (1, 2, 3)


@pytest.mark.parametrize("content, match", [
    ("not json", "not a valid project"),
    ('{"format": "something-else"}', "not a slicerkit project"),
    ('{"format": "slicerkit-project", "version": 99}', "newer slicerkit"),
    ('{"format": "slicerkit-project", "settings": {"layer_thickness": 0}}', "Invalid settings"),
    ('{"format": "slicerkit-project", "parts": [{"copies": 2}]}', "malformed parts"),
])
def test_bad_files(tmp_path, content, match):
    path = tmp_path / "bad.slicerkit"
    path.write_text(content)
    with pytest.raises(ProjectError, match=match):
        Project.load(str(path))


def test_missing_file(tmp_path):
    with pytest.raises(ProjectError, match="Could not open"):
        Project.load(str(tmp_path / "nope.slicerkit"))


def test_save_is_atomic(tmp_path):
    path = tmp_path / "p.slicerkit"
    Project().save(str(path))
    assert path.exists() and not (tmp_path / "p.slicerkit.tmp").exists()
