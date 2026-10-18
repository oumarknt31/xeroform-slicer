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
    window._goto(10**9)
    assert window.slider.value() == 18

    for name in ("show_travel", "scan_order"):
        window.view.set_option(name, True)
    assert not window.view.grab().isNull()

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
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a: (path[: -len(".xeroform")], ""))
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

    monkeypatch.setattr(win, "slice_project", lambda *a, **k: 1 / 0)
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
    assert window.pages.currentIndex() == 1 and window.views.currentWidget() is window.model_view
    assert window.parts.empty_hint.isHidden()
    window.settings.spins["layer_thickness"].setValue(1)
    wait(window.start_slicing())
    assert window.views.currentWidget() is window.view  # the layers, once sliced


def test_stat_tiles(window, models):
    sliced(window, models, copies=(2, 1))
    tiles = {k: t.value.text() for k, t in window.tiles.items()}
    assert tiles["layers"] == "19" and tiles["parts"] == "3" and tiles["height"] == "20.0 mm"
    assert tiles["density"].endswith("%") and tiles["energy"] == "0.050 J/mm²"
    window.new_project()
    assert window.tiles["layers"].value.text() == "–"


def test_3d_stack_view(window, models):
    sliced(window, models)
    window.view_switch.set_index(2)
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
        {
            QEvent.MouseButtonPress: sv.mousePressEvent,
            QEvent.MouseMove: sv.mouseMoveEvent,
            QEvent.MouseButtonRelease: sv.mouseReleaseEvent,
        }[kind](ev)
    assert sv.yaw != yaw  # orbited
    assert not sv.grab().isNull()
    window.view_switch.set_index(0)
    assert window.slider.isHidden()  # layers don't apply to the plate


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
    window._goto(10**9)
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


# --- orientation ------------------------------------------------------------


@pytest.fixture
def tall_model(tmp_path):
    path = tmp_path / "tall.stl"
    trimesh.creation.box(extents=[10, 20, 60]).export(str(path))
    return str(path)


def test_orientation_card_follows_selection(window, tall_model, models):
    assert window.orientation.part is None and not window.orientation.placeholder.isHidden()
    wait(window.add_models([tall_model, models[0]]))
    assert window.orientation.part.path == tall_model  # the first part is selected
    assert "60.0 mm tall" in window.orientation.info.text()
    window.parts.table.selectRow(1)
    assert window.orientation.part.path == models[0]
    assert not window.orientation.preview.grab().isNull()


def test_lowest_height_lays_the_part_down(window, tall_model):
    wait(window.add_models([tall_model]))
    window.settings.spins["layer_thickness"].setValue(1)
    window.orientation._lowest()
    assert window.parts.table.item(0, 3).text() == "60.0 × 20.0 × 10.0"
    assert "10 layers at 1 mm" in window.orientation.info.text()
    wait(window.start_slicing())
    assert len(window.result.layers) == 9  # sliced lying down
    window.orientation._turn("x")
    assert window.stale  # turning a part after slicing makes the slice out of date


def test_lay_flat_steps_and_reset(window, tall_model):
    wait(window.add_models([tall_model]))
    window.orientation._lay_flat()
    assert "resting on face 1 of 6" in window.orientation.info.text()
    window.orientation._lay_flat()
    window.orientation._lay_flat()
    assert "resting on face 3 of 6" in window.orientation.info.text()
    window.orientation.reset_button.click()
    assert window.parts.info(0).rotation == (0.0, 0.0, 0.0)


def test_angle_boxes_set_the_rotation(window, tall_model):
    wait(window.add_models([tall_model]))
    window.orientation.spins[0].setValue(90)
    assert window.parts.info(0).rotation == (90.0, 0.0, 0.0)
    assert window.parts.table.item(0, 3).text() == "10.0 × 60.0 × 20.0"


def test_project_keeps_orientation(window, tall_model, tmp_path, monkeypatch):
    wait(window.add_models([tall_model]))
    window.orientation._lowest()
    path = str(tmp_path / "o.xeroform")
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a: (path, ""))
    assert window.save_project()
    window.new_project()
    wait(window.open_project(path))
    assert window.parts.table.item(0, 3).text() == "60.0 × 20.0 × 10.0"


# --- the plate ----------------------------------------------------------------


def settle(window):
    """Wait until the parts are laid out (the debounce timer and any arranging)."""
    for _ in range(400):
        QtWidgets.QApplication.processEvents()
        if not window.layout_timer.isActive() and not window.busy():
            break
        loop = QEventLoop()
        QTimer.singleShot(15, loop.quit)
        loop.exec()
    for _ in range(3):
        QtWidgets.QApplication.processEvents()


def mouse(view, kind, pos, button=Qt.LeftButton):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else button
    ev = QMouseEvent(kind, QPointF(*pos), QPointF(*pos), button, buttons, Qt.NoModifier)
    {
        QEvent.MouseButtonPress: view.mousePressEvent,
        QEvent.MouseMove: view.mouseMoveEvent,
        QEvent.MouseButtonRelease: view.mouseReleaseEvent,
    }[kind](ev)


def screen_point(view, row, copy=0, normal=None):
    """Where on screen a part (or one of its faces facing `normal`) is drawn."""
    import numpy as np

    view.resize(900, 600)
    view.grab()  # paint, so the view knows what is where
    screen, owners, faces, _ = view._frame
    for k in range(len(owners) - 1, -1, -1):  # nearest first
        item = view.items[owners[k]]
        if (item.row, item.copy) != (row, copy):
            continue
        if normal is not None and np.dot(item.file_normals[faces[k]], normal) < 0.99:
            continue
        a, b, c = screen[k]
        centre = (a + b + c) / 3
        if view._hit(QPointF(*centre)) is not None and view._hit(QPointF(*centre))[0] is item:
            return tuple(centre)
    raise AssertionError("part not on screen")


def test_parts_are_packed_onto_the_plate(window, models):
    wait(window.add_models(list(models), [1, 2]))
    settle(window)
    rows = window.parts.rows()
    assert [len(info.spots) for info, _ in rows] == [1, 2]
    assert len(window.model_view.items) == 3 and window.plate_problems == []
    assert window.layer_info.text().startswith("3 parts on the plate")
    assert not window.model_view.grab().isNull()
    window.model_view.top_view()
    assert not window.model_view.grab().isNull()
    window.parts.table.cellWidget(1, 2).setValue(1)  # fewer copies: the plate follows
    settle(window)
    assert len(window.model_view.items) == 2


def test_drag_a_part_then_undo(window, models):
    from PySide6.QtCore import QEvent

    wait(window.add_models(list(models)))
    settle(window)
    view = window.model_view
    before = window.parts.info(0).spots[0]
    start = screen_point(view, 0)
    mouse(view, QEvent.MouseButtonPress, start)
    assert window.parts.selected_row() == 0
    mouse(view, QEvent.MouseMove, (start[0] + 60, start[1]))
    mouse(view, QEvent.MouseButtonRelease, (start[0] + 60, start[1]))
    settle(window)
    after = window.parts.info(0).spots[0]
    assert after != before and window.hand_placed and window.isWindowModified()
    assert window.act_undo.text() == "&Undo Move Part"
    window.undo()
    settle(window)
    assert window.parts.info(0).spots[0] == before and not window.hand_placed
    window.redo()
    settle(window)
    assert window.parts.info(0).spots[0] == after and window.hand_placed


def test_hand_placed_parts_stay_put_until_arranged(window, models):
    wait(window.add_models(list(models)))
    settle(window)
    window._part_moved(0, 0, (40.0, 40.0, 0.0, 0))
    window._move_done()
    settle(window)
    window.parts.table.cellWidget(1, 2).setValue(2)  # a new copy goes around the parts in place
    settle(window)
    assert window.parts.info(0).spots == [(40.0, 40.0, 0.0, 0)] and len(window.parts.info(1).spots) == 2
    assert window.plate_problems == []
    wait(window.arrange())
    settle(window)
    assert not window.hand_placed and window.parts.info(0).spots != [(40.0, 40.0, 0.0, 0)]


def test_parts_too_close_are_flagged(window, models):
    wait(window.add_models(list(models)))
    settle(window)
    window._part_moved(1, 0, window.parts.info(0).spots[0])  # right on top of the cube
    window._move_done()
    settle(window)
    assert window.plate_problems and window.model_view.problems == {(0, 0), (1, 0)}
    assert "⚠" in window.layer_info.text()
    window.settings.spins["layer_thickness"].setValue(1)
    wait(window.start_slicing())
    assert "warning: cube.stl and ring.stl are" in window.report.toPlainText()


def test_slice_uses_the_plate(window, models):
    wait(window.add_models(list(models)))
    settle(window)
    window._part_moved(0, 0, (30.0, -20.0, 0.0, 0))
    window._move_done()
    settle(window)
    window.settings.spins["layer_thickness"].setValue(1)
    wait(window.start_slicing())
    assert window.result.build.placements[0].spot == pytest.approx((30, -20, 0, 0))


def test_lay_flat_on_a_clicked_face(window, tall_model):
    from PySide6.QtCore import QEvent

    wait(window.add_models([tall_model]))
    settle(window)
    window.orientation.pick_button.setChecked(True)
    view = window.model_view
    assert view.picking and window.views.currentWidget() is view
    point = screen_point(view, 0, normal=(1, 0, 0))  # the 20 x 60 side
    mouse(view, QEvent.MouseButtonPress, point)
    mouse(view, QEvent.MouseButtonRelease, point)
    assert window.parts.table.item(0, 3).text() == "60.0 × 20.0 × 10.0"  # lying on that side
    assert not window.orientation.pick_button.isChecked() and not view.picking
    assert window.act_undo.text() == "&Undo Orientation"


def test_projects_keep_hand_placed_parts_only(window, models, tmp_path, monkeypatch):
    import json

    wait(window.add_models(list(models)))
    settle(window)
    path = str(tmp_path / "plate.xeroform")
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a: (path, ""))
    assert window.save_project()
    assert all("spots" not in p for p in json.loads(open(path, encoding="utf-8").read())["parts"])
    window._part_moved(0, 0, (40.0, 40.0, 0.0, 0))
    window._move_done()
    assert window.save_project()
    window.new_project()
    wait(window.open_project(path))
    settle(window)
    assert window.hand_placed and window.parts.info(0).spots == [(40.0, 40.0, 0.0, 0)]
    assert not window.isWindowModified() and window.act_undo.text() == "&Undo"


# --- part settings, undo, updates -------------------------------------------------


def test_part_settings(window, models, tmp_path, monkeypatch):
    wait(window.add_models(list(models)))
    window.parts.select_row(1)
    card = window.part_settings
    assert card.part is window.parts.info(1) and not card.spins["hatch_power"].isEnabled()
    card.own.setChecked(True)
    card.spins["hatch_power"].setValue(9)
    assert window.parts.info(1).settings["hatch_power"] == 9
    assert not window.parts.table.item(1, 1).icon().isNull()  # marked in the list
    assert "Own settings: fill 9 W" in window.parts.table.item(1, 1).toolTip()
    assert window.act_undo.text() == "&Undo Part Settings"
    window.settings.spins["layer_thickness"].setValue(1)
    wait(window.start_slicing())
    assert "own settings: fill 9 W" in window.report.toPlainText()
    powers = {h.params.power for layer in window.result.layers for h in layer.hatches}
    assert powers == {5.0, 9.0}

    path = str(tmp_path / "own.xeroform")
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a: (path, ""))
    assert window.save_project()
    window.new_project()
    wait(window.open_project(path))
    assert window.parts.info(1).settings["hatch_power"] == 9 and not window.parts.info(0).settings
    window.parts.select_row(1)
    card.own.setChecked(False)
    assert window.parts.info(1).settings == {} and window.parts.table.item(1, 1).icon().isNull()


def test_undo_and_redo(window, models):
    assert not window.act_undo.isEnabled() and not window.undo_button.isEnabled()
    window.settings.spins["hatch_power"].setValue(8)
    assert window.act_undo.text() == "&Undo Fill power"
    wait(window.add_models([models[0]]))
    settle(window)
    window.parts.table.cellWidget(0, 2).setValue(3)
    settle(window)
    assert window.act_undo.text() == "&Undo Copies"
    window.undo()
    settle(window)
    assert window.parts.table.cellWidget(0, 2).value() == 1 and len(window.model_view.items) == 1
    window.undo()
    assert window.parts.table.rowCount() == 0
    window.undo()
    assert window.settings.spins["hatch_power"].value() == 5 and not window.act_undo.isEnabled()
    window.redo()
    window.redo()
    window.redo()
    settle(window)
    assert window.settings.spins["hatch_power"].value() == 8 and window.parts.table.cellWidget(0, 2).value() == 3
    assert not window.act_redo.isEnabled()


def test_quick_edits_are_one_undo_step(window):
    for v in (6, 7, 8, 9):
        window.settings.spins["hatch_power"].setValue(v)
    window.undo()
    assert window.settings.spins["hatch_power"].value() == 5


def test_update_notice(window, monkeypatch):
    from xeroform.gui.updates import install_command, is_newer, version_in

    assert version_in("https://github.com/o/r/releases/tag/v0.4.0") == "0.4.0"
    assert version_in("https://github.com/o/r/releases") is None
    assert is_newer("0.10.0", "0.9.9") and not is_newer("0.3.0", "0.3.0")
    assert install_command("win32").startswith("irm ") and "install-mac.sh" in install_command("darwin")

    assert window.update_button.isHidden()
    window.updates.handle("https://github.com/oumarknt31/xeroform-slicer/releases/tag/v99.0.0")
    assert not window.update_button.isHidden() and window.update_button.text() == "Update to 99.0.0"
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.informativeText()))
    window.show_update()
    assert install_command() in shown[0]

    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: told.append(a[2]))
    window._update_by_hand = True
    window.updates.handle("https://github.com/oumarknt31/xeroform-slicer/releases/tag/v0.0.1")
    assert told and "latest" in told[0]


def test_automatic_update_checks_respect_the_setting(window, monkeypatch):
    asked = []
    monkeypatch.setattr(window.updates, "check", lambda: asked.append(True))
    window.act_auto_updates.setChecked(False)
    window.check_for_updates()
    assert not asked
    window.act_auto_updates.setChecked(True)
    window.store.remove("update_checked")
    window.check_for_updates()
    window.check_for_updates()  # once a day at most
    assert len(asked) == 1
    window.check_for_updates(by_hand=True)
    assert len(asked) == 2


def test_parts_that_dont_fit_are_named_and_the_rest_shown(window, tmp_path):
    big = tmp_path / "big.stl"
    trimesh.creation.box(extents=[60, 60, 60]).export(str(big))
    wait(window.add_models([str(big)], [12]))  # 4 fit on the 150 mm plate (2 x 2), with room for 4 above
    settle(window)
    shown = len(window.model_view.items)
    assert 0 < shown < 12
    assert f"{12 - shown} don't fit" in window.layer_info.text()
    assert "Left over: big.stl" in window.report.toPlainText()
