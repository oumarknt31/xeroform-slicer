"""GUI smoke tests, run headless. Skipped when PySide6 isn't installed."""
import os

import pytest
import trimesh

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

from slicerkit import SliceConfig  # noqa: E402
from slicerkit.gui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def window(app):
    w = MainWindow()
    yield w
    w.close()


@pytest.fixture
def models(tmp_path):
    cube, ring = tmp_path / "cube.stl", tmp_path / "ring.stl"
    trimesh.creation.box(extents=[20, 20, 20]).export(str(cube))
    trimesh.creation.annulus(r_min=4, r_max=10, height=10).export(str(ring))
    return str(cube), str(ring)


def _wait(window):
    loop = QEventLoop()
    window.worker.finished.connect(loop.quit)
    QTimer.singleShot(60000, loop.quit)  # never hang the suite
    if window.worker.isRunning():
        loop.exec()
    QtWidgets.QApplication.processEvents()


def test_defaults_match_slice_config(window):
    cfg, defaults = window.config(), SliceConfig()
    for name in window.spins:
        assert getattr(cfg, name) == pytest.approx(getattr(defaults, name)), name
    assert cfg.scan_order == defaults.scan_order and cfg.allow_rotation == defaults.allow_rotation


def test_parts_and_copies(window, models):
    window.add_models(list(models))
    window.table.cellWidget(1, 1).setValue(3)
    assert window.jobs() == [models[0], models[1], models[1], models[1]]
    assert window.table.item(0, 2).text() == "20.0 × 20.0 × 20.0"
    window.table.selectRow(0)
    window.remove_selected()
    assert window.jobs() == [models[1]] * 3


def test_bad_model_is_refused(window, tmp_path, monkeypatch):
    bad = tmp_path / "bad.stl"
    bad.write_bytes(b"not a mesh")
    shown = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a: shown.append(a[2]))
    window.add_models([str(bad)])
    assert window.table.rowCount() == 0 and "no triangles" in shown[0]


def test_slice_view_and_save(window, models, tmp_path, monkeypatch):
    window.add_models(list(models))
    window.spins["layer_thickness"].setValue(1)
    window.start_slicing()
    _wait(window)
    assert window.result is not None
    assert "Build: 2 parts packed" in window.report.toPlainText()
    assert window.slider.maximum() == len(window.result.layers) - 1 == 18
    window.slider.setValue(5)
    assert window.z_label.text() == "layer 6 / 19 · z 6.000 mm"
    for name in ("show_travel", "scan_order"):
        window.view.set_option(name, True)
    assert not window.view.grab().isNull()  # paints without errors

    out = tmp_path / "gui.cli"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a: (str(out), ""))
    window.save_cli()
    assert out.read_text().count("$$LAYER/") == 19


def test_cancel(window, tmp_path):
    sphere = tmp_path / "sphere.stl"
    trimesh.creation.icosphere(subdivisions=4, radius=40).export(str(sphere))
    window.add_models([str(sphere)])
    window.spins["layer_thickness"].setValue(0.05)
    window.start_slicing()
    window.cancel_slicing()
    _wait(window)
    assert window.result is None and "cancelled" in window.report.toPlainText()
    assert window.slice_button.isEnabled()


def test_error_is_shown(window, models):
    window.add_models(list(models))
    window.use_volume.setChecked(False)  # several parts need a build volume
    window.start_slicing()
    _wait(window)
    assert window.report.toPlainText().startswith("Error:") and "--build-volume" in window.report.toPlainText()
