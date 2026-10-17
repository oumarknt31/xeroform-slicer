"""Pipeline API used by the GUI: slice without writing, progress, export later."""
import pytest
import trimesh

from slicerkit import SliceConfig
from slicerkit.pipeline import export, slice_build, slice_job


@pytest.fixture
def cube(tmp_path):
    path = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(str(path))
    return str(path)


def test_slice_without_writing_then_export(cube, tmp_path):
    cfg = SliceConfig(layer_thickness=1, hatch_distance=1)
    result = slice_job(cube, None, cfg)
    assert result.layers and not list(tmp_path.glob("*.cli"))
    assert result.bounding_box == pytest.approx((-5, -5, 0, 5, 5, 10))

    later, direct = tmp_path / "later.cli", tmp_path / "direct.cli"
    export(result, str(later), cfg)
    slice_job(cube, str(direct), cfg)
    assert later.read_text() == direct.read_text()


def test_progress_reports_every_layer(cube):
    calls = []
    slice_job(cube, None, SliceConfig(layer_thickness=1), progress=lambda d, t: calls.append((d, t)))
    assert [d for d, _ in calls] == list(range(1, 10)) and {t for _, t in calls} == {10}


def test_raising_from_progress_cancels(cube):
    class Stop(Exception):
        pass

    def stop(done, total):
        if done == 3:
            raise Stop

    with pytest.raises(Stop):
        slice_build([cube, cube], None, SliceConfig(layer_thickness=1, build_volume=(50, 50, 50)),
                    progress=stop)
