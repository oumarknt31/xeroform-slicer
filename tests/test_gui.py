"""GUI tests, run headless. Skipped when PySide6 isn't installed."""
import os

import pytest
import trimesh

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QEventLoop, QMimeData, QPointF, QSettings, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from xeroform.gui.panels import gui_defaults  # noqa: E402
from xeroform.gui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path_factory.mktemp("settings")))
    app.setOrganizationName("xeroform-tests")
    app.setApplicationName("xeroform-tests")
    return app


@pytest.fixture
def window(app, monkeypatch):
    QSettings().clear()
    # never block on a modal dialog in tests
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    w = MainWindow()
    yield w
    w.dirty = False
    w.close()
    w.deleteLater()
    QtWidgets.QApplication.processEvents()


@pytest.fixture
def models(tmp_path):
    cube, ring = tmp_path / "cube.stl", tmp_path / "ring.stl"
    trimesh.creation.box(extents=[20, 20, 20]).export(str(cube))
    trimesh.creation.annulus(r_min=4, r_max=10, height=10).export(str(ring))
    return str(cube), str(ring)


def wait(task):
    if task is None:
        return
    loop = QEventLoop()
    task.finished.connect(loop.quit)
    QTimer.singleShot(60000, loop.quit)  # never hang the suite
    if task.isRunning():
        loop.exec()
    for _ in range(3):
        QtWidgets.QApplication.processEvents()


def sliced(window, models, copies=(1, 1)):
    wait(window.add_models(list(models), list(copies)))
    window.settings.spins["layer_thickness"].setValue(1)
    wait(window.start_slicing())


def test_defaults(window):
    assert window.settings.config() == gui_defaults()
    assert window.windowTitle() == "Untitled[*] — XeroForm" and not window.isWindowModified()
    assert window.dirty_dot.isHidden()
    assert not window.act_export.isEnabled()


def test_add_parts_in_background(window, models):
    wait(window.add_models(list(models), [1, 3]))
    assert window.parts.jobs() == [models[0], models[1], models[1], models[1]]
    assert window.parts.table.item(0, 3).text() == "20.0 × 20.0 × 20.0"
    assert window.isWindowModified()
    window.settings.spins["scale"].setValue(2)
    assert window.parts.table.item(0, 3).text() == "40.0 × 40.0 × 40.0"
    window.parts.table.selectRow(0)
    window.parts.remove_selected()
    assert window.parts.jobs() == [models[1]] * 3


def test_bad_model_is_reported_not_added(window, tmp_path, monkeypatch):
    bad = tmp_path / "bad.stl"
    bad.write_bytes(b"not a mesh")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: shown.append(a[2]))
    wait(window.add_models([str(bad)]))
    assert window.parts.table.rowCount() == 0 and "no triangles" in shown[0]


def test_slice_view_layout_and_export(window, models, tmp_path, monkeypatch):
    sliced(window, models)
    assert "Build: 2 parts packed" in window.report.toPlainText()
    assert window.slider.maximum() == len(window.result.layers) - 1 == 18
    window.view.setFocus()
    QtWidgets.QApplication.processEvents()
    window.slider.setValue(5)
    # cube: outer + inner contour pass; ring: the same around its outside and its hole
    assert window.layer_info.text().startswith("Layer 6 of 19 · z 6.000 mm · 6 contours (2 around holes)")
    window._step(10)
    assert window.slider.value() == 15
    window._goto(10 ** 9)
    assert window.slider.value() == 18

    items = window.layout_view.items
    assert sorted(i[1] for i in items) == ["cube.stl", "ring.stl"]
    rect = next(i[0] for i in items if i[1] == "ring.stl")
    assert window.layout_view.item_at(window.layout_view.transform().map(rect.center()))[1] == "ring.stl"
    for name in ("show_travel", "scan_order"):
        window.view.set_option(name, True)
    assert not window.view.grab().isNull() and not window.layout_view.grab().isNull()

    out = tmp_path / "gui.cli"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a: (str(out), ""))
    assert window.act_export.isEnabled()
    window.export_cli()
    assert out.read_text(encoding="utf-8").count("$$LAYER/") == 19


def test_changes_after_slicing_make_it_stale(window, models):
    sliced(window, models)
    assert not window.stale and window.banner.isHidden()
    window.settings.spins["hatch_distance"].setValue(0.5)
    assert window.stale and not window.banner.isHidden() and not window.act_export.isEnabled()
    wait(window.start_slicing())
    assert not window.stale and window.banner.isHidden() and window.act_export.isEnabled()
    window.parts.table.cellWidget(0, 2).setValue(2)  # copies count too
    assert window.stale


def test_project_save_and_open(window, models, tmp_path, monkeypatch):
    wait(window.add_models(list(models), [2, 1]))
    window.settings.spins["layer_thickness"].setValue(0.25)
    path = str(tmp_path / "job.xeroform")
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a: (path[:-len(".xeroform")], ""))
    assert window.save_project()  # adds the extension
    assert os.path.exists(path) and not window.isWindowModified()
    assert window.windowTitle() == "job[*] — XeroForm" and window.title_label.text() == "job"

    window.new_project()
    assert window.parts.table.rowCount() == 0 and window.settings.config() == gui_defaults()
    wait(window.open_project(path))
    assert window.parts.jobs() == [models[0], models[0], models[1]]
    assert window.settings.spins["layer_thickness"].value() == 0.25
    assert not window.isWindowModified() and window._recent()[0] == os.path.abspath(path)


def test_open_project_with_missing_model(window, models, tmp_path):
    from xeroform.project import Project, ProjectPart
    path = str(tmp_path / "p.xeroform")
    Project([ProjectPart(models[0]), ProjectPart(str(tmp_path / "gone.stl"))]).save(path)
    wait(window.open_project(path))
    assert window.parts.jobs() == [models[0]] and window.isWindowModified()


def test_unsaved_changes_prompt(window, models, monkeypatch):
    wait(window.add_models([models[0]]))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    window.new_project()
    assert window.parts.table.rowCount() == 1  # cancelled: nothing lost


def test_drop_models(window, models):
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(m) for m in models])
    window.dropEvent(QDropEvent(QPointF(10, 10), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
    wait(next(iter(window.tasks), None))
    assert window.parts.table.rowCount() == 2


def test_settings_remembered(app, window):
    window.settings.spins["hatch_speed"].setValue(777)
    window.dirty = False
    window.close()
    again = MainWindow()
    assert again.settings.spins["hatch_speed"].value() == 777
    again.close()


def test_cancel(window, tmp_path):
    sphere = tmp_path / "sphere.stl"
    trimesh.creation.icosphere(subdivisions=4, radius=40).export(str(sphere))
    wait(window.add_models([str(sphere)]))
    window.settings.spins["layer_thickness"].setValue(0.05)
    task = window.start_slicing()
    window.cancel()
    wait(task)
    assert window.result is None and "cancelled" in window.report.toPlainText()
    assert window.slice_button.isEnabled()


def test_error_is_shown(window, models):
    wait(window.add_models(list(models)))
    window.settings.use_volume.setChecked(False)  # several parts need a build volume
    wait(window.start_slicing())
    assert window.report.toPlainText().startswith("Slicing failed:")
    assert "--build-volume" in window.report.toPlainText()


def test_unexpected_error_shows_details(window, models, monkeypatch):
    import xeroform.gui.window as win
    monkeypatch.setattr(win, "slice_job", lambda *a, **k: 1 / 0)
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.detailedText()))
    wait(window.add_models([models[0]]))
    wait(window.start_slicing())
    assert "Unexpected error" in window.report.toPlainText()
    assert "ZeroDivisionError" in shown[0]


# --- look & feel, new views ---------------------------------------------------

def test_theme_switching(window):
    from xeroform.gui import theme
    assert theme.mode() == "dark"  # XeroForm is dark-first
    window.set_theme("light")
    assert theme.current()["bg"] == theme.LIGHT["bg"] and QSettings().value("theme") == "light"
    assert QtWidgets.QApplication.instance().palette().window().color().name() == theme.LIGHT["bg"]
    assert "#ffffff" not in theme.LIGHT.values()  # soft greys, never white
    window._cycle_theme()  # light -> system
    assert theme.mode() == "system"
    window.set_theme("dark")


def test_empty_states(window, models):
    assert window.pages.currentIndex() == 0 and window.empty.title.text() == "Drop models here"
    assert window.parts.table.isHidden() and not window.parts.empty_hint.isHidden()
    wait(window.add_models([models[0]]))
    assert window.empty.title.text() == "Ready to slice" and window.parts.empty_hint.isHidden()
    window.settings.spins["layer_thickness"].setValue(1)
    wait(window.start_slicing())
    assert window.pages.currentIndex() == 1


def test_stat_tiles(window, models):
    sliced(window, models, copies=(2, 1))
    tiles = {k: t.value.text() for k, t in window.tiles.items()}
    assert tiles["layers"] == "19" and tiles["parts"] == "3" and tiles["height"] == "20.0 mm"
    assert tiles["density"].endswith("%") and tiles["energy"] == "0.050 J/mm²"
    window.new_project()
    assert window.tiles["layers"].value.text() == "–"


def test_3d_stack_view(window, models):
    sliced(window, models)
    window.view_switch.set_index(1)
    assert window.views.currentWidget() is window.stack_view
    assert len(window.stack_view.layers) == 19
    window.slider.setValue(7)
    assert window.stack_view.index == 7
    yaw = window.stack_view.yaw
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    sv = window.stack_view
    for kind, x in [(QEvent.MouseButtonPress, 100), (QEvent.MouseMove, 160), (QEvent.MouseButtonRelease, 160)]:
        ev = QMouseEvent(kind, QPointF(x, 100), QPointF(x, 100), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        {QEvent.MouseButtonPress: sv.mousePressEvent, QEvent.MouseMove: sv.mouseMoveEvent,
         QEvent.MouseButtonRelease: sv.mouseReleaseEvent}[kind](ev)
    assert sv.yaw != yaw  # orbited
    assert not sv.grab().isNull()
    window.view_switch.set_index(2)
    assert window.slider.isHidden()  # layers don't apply to the layout view


def test_laser_playback(window, models):
    sliced(window, models)
    window._toggle_scan()
    assert window.view.playing() and window.scan_button.text() == "Stop laser"
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    assert 0 < window.view._reveal < 1
    assert not window.view.grab().isNull()  # draws the partial layer and the spot
    window._toggle_scan()
    assert not window.view.playing() and window.scan_button.text() == "Play laser"


def test_flipbook(window, models):
    sliced(window, models)
    window._toggle_flipbook()
    assert window.flipbook.isActive() and window.flip_button.text() == "Pause layers"
    loop = QEventLoop()
    QTimer.singleShot(250, loop.quit)
    loop.exec()
    assert window.slider.value() > 0
    window._toggle_flipbook()
    assert not window.flipbook.isActive()
    window._goto(10 ** 9)
    window._toggle_flipbook()  # from the top, it starts over
    assert window.slider.value() <= 1
    window._stop_playback()


def test_toast(window):
    from xeroform.gui.widgets import Toast
    window.toast("Hello")
    toasts = window.centralWidget().findChildren(Toast)
    assert toasts and not toasts[-1].isHidden()  # (test windows are never on screen)


def test_theme_images_live_in_a_private_folder(app):
    import stat
    from xeroform.gui import theme
    path = theme._icon_file("check-mark", "#ffffff")
    folder = os.path.dirname(path)
    assert os.path.isfile(path) and os.path.normpath(folder) == os.path.normpath(theme._private_dir())
    assert os.path.basename(folder).startswith("xeroform-theme-")
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700
        assert os.stat(folder).st_uid == os.getuid()


def test_garbage_is_collected_on_the_gui_thread_only(window):
    """The cycle collector must never free Qt objects on a worker thread (it crashes)."""
    import gc
    from xeroform.gui.tasks import _MainThreadGC
    app = QtWidgets.QApplication.instance()
    assert not gc.isenabled() and len(app.findChildren(_MainThreadGC)) == 1
    MainWindow().deleteLater()  # a second window doesn't install a second collector
    assert len(app.findChildren(_MainThreadGC)) == 1


def test_every_button_has_a_name_for_screen_readers(window):
    """Icon-only buttons (theme, fit) must still be announced by screen readers."""
    buttons = window.findChildren(QtWidgets.QAbstractButton)
    nameless = [b for b in buttons if b.isVisibleTo(window) and not (b.text() or b.accessibleName())]
    assert not nameless, [b.objectName() or b.toolTip() for b in nameless]


def test_about_mentions_the_license(window, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "about", lambda parent, title, text: shown.append(text))
    window.about()
    assert "MIT License" in shown[0] and "THIRD_PARTY_NOTICES" in shown[0]
