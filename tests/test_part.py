"""Loading real-world meshes: errors, repairs, units, placement, build volume."""

import numpy as np
import pytest
import trimesh

from xeroform import SliceConfig
from xeroform.__main__ import main
from xeroform.hatching import HatchSettings
from xeroform.part import MeshError, Part
from xeroform.pipeline import slice_job
from xeroform.slicing import slice_part


def _save(tmp_path, mesh, name="m.stl"):
    path = tmp_path / name
    mesh.export(str(path))
    return str(path)


def _box(extents=(20, 20, 20), at=(0, 0, 0)):
    return trimesh.creation.box(extents=extents).apply_translation(at)


# --- files that can't be read ---------------------------------------------


def test_missing_file(tmp_path):
    with pytest.raises(MeshError, match="File not found"):
        Part(str(tmp_path / "nope.stl"))


@pytest.mark.parametrize("content", [b"", b"hello, not a mesh"])
def test_unreadable_file(tmp_path, content):
    path = tmp_path / "bad.stl"
    path.write_bytes(content)
    with pytest.raises(MeshError, match="no triangles"):
        Part(str(path))


def test_reads_3mf(tmp_path):
    part = Part(_save(tmp_path, _box((10, 20, 30)), "box.3mf"))
    assert part.report.size == pytest.approx((10, 20, 30))


# --- repairs ----------------------------------------------------------------


def test_small_hole_is_closed(tmp_path):
    mesh = _box()
    mesh.update_faces(np.arange(len(mesh.faces)) != 0)  # drop one triangle
    part = Part(_save(tmp_path, mesh))
    assert any("closed small holes" in r for r in part.report.repairs)
    assert part.report.volume == pytest.approx(8000)


def test_big_hole_is_refused(tmp_path):
    mesh = trimesh.creation.icosphere(subdivisions=2, radius=10)
    mesh.update_faces(mesh.triangles_center[:, 2] <= 7)  # cut the top off
    mesh.remove_unreferenced_vertices()
    with pytest.raises(MeshError, match="open edges"):
        Part(_save(tmp_path, mesh))


def test_sliver_triangle_that_closes_the_surface_is_kept(tmp_path):
    """A zero-area triangle that closes a seam must survive the clean-up.

    10 mm cube whose front face has an extra vertex M in the middle of its top
    edge; a zero-area sliver (A, M, B) closes the seam against the top face.
    """
    v = [
        (0, 0, 10),
        (10, 0, 10),
        (10, 10, 10),
        (0, 10, 10),  # A B C D (top)
        (0, 0, 0),
        (10, 0, 0),
        (10, 10, 0),
        (0, 10, 0),  # E F G H (bottom)
        (5, 0, 10),
    ]  # M, on edge AB
    f = [
        (0, 1, 2),
        (0, 2, 3),
        (4, 6, 5),
        (4, 7, 6),  # top, bottom
        (4, 5, 8),
        (5, 1, 8),
        (4, 8, 0),  # front, split at M
        (6, 7, 3),
        (6, 3, 2),
        (7, 4, 0),
        (7, 0, 3),
        (5, 6, 2),
        (5, 2, 1),
        (0, 8, 1),
    ]  # the zero-area sliver
    mesh = trimesh.Trimesh(vertices=v, faces=f, process=False)
    part = Part(_save(tmp_path, mesh))
    assert part.report.volume == pytest.approx(1000)
    assert not any("removed" in r for r in part.report.repairs)


def test_touching_shells_are_sliced_with_a_warning(tmp_path):
    """Two boxes sharing one edge: that edge is used by four triangles, which is fine."""
    mesh = trimesh.util.concatenate([_box((10, 10, 10), (5, 5, 5)), _box((10, 10, 10), (15, 15, 5))])
    part = Part(_save(tmp_path, mesh))
    assert part.report.volume == pytest.approx(2000)
    assert any("shared by more than two triangles" in w for w in part.report.warnings)
    layers = slice_part(part, HatchSettings(hatch_distance=1), 1)
    assert len(layers) == 9 and all(sum(not c.is_hole for c in l.contours) >= 2 for l in layers)


def test_inside_out_is_fixed(tmp_path):
    mesh = _box()
    mesh.invert()
    part = Part(_save(tmp_path, mesh))
    assert any("inside-out" in r for r in part.report.repairs)
    assert part.report.volume == pytest.approx(8000)


def test_clean_mesh_needs_no_repairs(tmp_path):
    part = Part(_save(tmp_path, _box()))
    assert part.report.repairs == [] and part.report.warnings == []
    assert part.report.bodies == 1 and part.report.triangles == 12


def test_multiple_bodies(tmp_path):
    mesh = trimesh.util.concatenate([_box((10, 10, 10), (-15, 0, 0)), _box((10, 10, 10), (15, 0, 0))])
    assert Part(_save(tmp_path, mesh)).report.bodies == 2


# --- units, placement, build volume ----------------------------------------


def test_tiny_model_warns_about_units(tmp_path):
    part = Part(_save(tmp_path, _box((0.8, 0.8, 0.8))))
    assert any("--scale 25.4" in w for w in part.report.warnings)


def test_scale(tmp_path):
    part = Part(_save(tmp_path, _box((1, 2, 0.5))), scale=25.4)
    assert part.report.size == pytest.approx((25.4, 50.8, 12.7))
    assert part.report.warnings == []


def test_part_is_centred_on_platform(tmp_path):
    part = Part(_save(tmp_path, _box((10, 20, 30), at=(100, -40, 55))))
    assert np.allclose(part.bounding_box, [-5, -10, 0, 5, 10, 30])


def test_build_volume(tmp_path):
    path = _save(tmp_path, _box((30, 20, 10)))
    Part(path, build_volume=(30, 30, 30))  # fits exactly
    with pytest.raises(MeshError, match="too big in X"):
        Part(path, build_volume=(25, 30, 30))


def test_model_thinner_than_a_layer(tmp_path):
    path = _save(tmp_path, _box((5, 5, 0.05)))
    with pytest.raises(MeshError, match="no layers.*check its units"):
        slice_job(path, str(tmp_path / "x.cli"), SliceConfig(layer_thickness=0.1))


# --- slicing details found on real parts -----------------------------------


def test_region_too_small_to_hatch(tmp_path):
    """PySLM's own Hatcher crashes when no hatch line crosses a fill region."""
    part = Part(_save(tmp_path, _box((0.8, 0.8, 0.8))))
    layers = slice_part(part, HatchSettings(hatch_distance=0.5), 0.05)
    assert layers and all(layer.contours for layer in layers)


def test_slice_job_returns_report(tmp_path):
    mesh = _box()
    mesh.invert()
    result = slice_job(_save(tmp_path, mesh), str(tmp_path / "x.cli"), SliceConfig(layer_thickness=1))
    assert result.layers and result.report.repairs


@pytest.mark.parametrize("kwargs", [dict(scale=0), dict(build_volume=(10, 10)), dict(build_volume=(10, 0, 10))])
def test_config_rejects_bad_placement(kwargs):
    with pytest.raises(ValueError):
        SliceConfig(**kwargs)


# --- command line -----------------------------------------------------------


def test_cli_reports_model_and_repairs(tmp_path, capsys):
    mesh = _box()
    mesh.invert()
    assert (
        main([_save(tmp_path, mesh), "-o", str(tmp_path / "x.cli"), "--layer", "1", "--build-volume", "50", "50", "50"])
        == 0
    )
    out = capsys.readouterr().out
    assert "Model: 20.0 x 20.0 x 20.0 mm, 8000 mm^3, 12 triangles, 1 body" in out
    assert "repaired: fixed inside-out" in out


def test_cli_mesh_error_exits_cleanly(tmp_path, capsys):
    assert main([str(tmp_path / "nope.stl"), "-o", str(tmp_path / "x.cli")]) == 1
    assert "xeroform: error: File not found" in capsys.readouterr().err


def test_files_referenced_inside_a_model_are_never_opened(tmp_path, monkeypatch):
    """An OBJ may name a material file anywhere - even \\\\host\\share - and must not reach it."""
    import trimesh.resolvers

    opened = []
    monkeypatch.setattr(trimesh.resolvers.FilePathResolver, "get", lambda self, name: opened.append(name))
    obj = tmp_path / "evil.obj"
    obj.write_text(
        "mtllib \\\\attacker\\share\\x.mtl\nv 0 0 0\nv 10 0 0\nv 0 10 0\nv 0 0 10\nf 1 3 2\nf 1 2 4\nf 1 4 3\nf 2 3 4\n"
    )
    part = Part(str(obj))
    assert part.report.triangles == 4 and opened == []
