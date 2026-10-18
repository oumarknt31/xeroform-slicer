"""XeroForm main window: a header with the main actions, parts and settings on the left,
the viewer (the parts on the plate, then the layers and the 3D stack) with headline
numbers on the right.

Models load, parts are arranged and slices run on worker threads, so the window
never freezes. Parts are packed onto the plate as they are added; dragging one
there pins it, and Arrange packs everything again. A slice stays in memory until
exported; changing a part or a setting afterwards marks it out of date and blocks
exporting it. Every edit can be undone. Projects (.xeroform) save the parts and
every setting; the window remembers its layout, theme and settings.
"""

from __future__ import annotations
import logging
import os
import time

from PySide6.QtCore import QSettings, QTimer, QUrl, qVersion
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..laser import estimate_scan_time, layer_scan_time
from ..nesting import NestingError, placement_at, plan, problems
from ..orient import NO_ROTATION
from ..part import MeshError, prepare_mesh
from ..pipeline import SliceResult, slice_project
from ..project import Project
from ..summary import hms, summary_lines
from . import theme
from .constants import APP_NAME, FLIPBOOK_FPS, MODEL_FILTER, REPO_URL, THEME_ICONS, THEME_NAMES
from .history import History
from .model_view import SceneItem
from .orientation import outline_edges
from .panels import NUMBER_FIELDS
from .playback import PlaybackMixin
from .projects import ProjectsMixin
from .scene import DISPLAY_FACES, for_drawing, posed, simplified
from .tasks import Task, collect_garbage_on_gui_thread
from .updates import LATEST_URL, UpdateChecker, install_command
from .widgets import Toast, shadow
from .window_ui import WindowLayoutMixin

log = logging.getLogger("xeroform.gui")

__all__ = ["APP_NAME", "MainWindow"]

PLATE, LAYERS, STACK = range(3)  # the viewer's tabs
SCENE_FACES = 20000  # triangles drawn for the whole plate, shared between the copies
_SETTING_NAMES = {
    **{spec[0]: spec[1] for specs in NUMBER_FIELDS.values() for spec in specs},
    "scan_order": "Scan order",
    "allow_rotation": "Turn parts",
    "use_volume": "Build volume",
    "volume": "Build volume",
}


class MainWindow(WindowLayoutMixin, ProjectsMixin, PlaybackMixin, QMainWindow):
    """The XeroForm window. Layout, projects and playback live in the mixins."""

    def __init__(self, log_path: str | None = None):
        super().__init__()
        collect_garbage_on_gui_thread()  # Qt objects must only ever be freed on this thread
        self.log_path = log_path
        self.store = QSettings()
        self.project_path: str | None = None
        self.dirty = False
        self.result: SliceResult | None = None
        self.result_jobs: list[str] = []
        self.result_config = None
        self.stale = False
        self.tasks: set[Task] = set()
        self.slicing: Task | None = None
        self._themed: list = []  # widgets with a restyle() to call on theme change

        # the plate: parts are packed automatically until one is moved by hand
        self.hand_placed = False
        self._arranged_key = None  # what the parts' places were worked out for
        self._arranging: Task | None = None
        self._arrange_again = False
        self._restoring = False  # going back to an earlier state: not an edit
        self._posed: dict[tuple, tuple] = {}  # drawing meshes of posed parts
        self.plate_problems: list[str] = []
        self.plate_error = ""  # why the last packing left parts out
        self.latest_version: str | None = None
        self._update_by_hand = False

        self.setAcceptDrops(True)
        self.resize(1400, 900)
        self.setMinimumSize(1000, 640)
        root = QWidget()
        root.setObjectName("root")
        col = QVBoxLayout(root)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._build_header())
        line = QFrame()
        line.setObjectName("accentLine")
        col.addWidget(line)
        self.split = QSplitter()
        self.split.setContentsMargins(12, 12, 12, 12)
        self.split.addWidget(self._build_sidebar())
        self.split.addWidget(self._build_main())
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([410, 990])
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(12, 12, 12, 12)
        bl.addWidget(self.split)
        col.addWidget(body, 1)
        self.setCentralWidget(root)
        self._build_menus()
        self.statusBar().hide()  # messages are toasts

        self.flipbook = QTimer(self)
        self.flipbook.setInterval(1000 // FLIPBOOK_FPS)
        self.flipbook.timeout.connect(self._flip)
        self.layout_timer = QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.setInterval(200)
        self.layout_timer.timeout.connect(self._update_layout)
        self.history = History(self._snapshot, self._restore)
        self.updates = UpdateChecker(self)
        self.updates.found.connect(self._update_found)
        self.updates.up_to_date.connect(self._up_to_date)
        self.updates.failed.connect(self._update_failed)
        self.act_auto_updates.setChecked(self.store.value("check_updates", True, type=bool))

        self.parts.changed.connect(self._changed)
        self.parts.add_requested.connect(self.add_models_dialog)
        self.parts.selection_changed.connect(self._selection_changed)
        self.orientation.rotation_changed.connect(self.parts.set_selected_rotation)
        self.orientation.picking_changed.connect(self._picking_changed)
        self.part_settings.settings_changed.connect(lambda _: self.parts.selected_settings_changed())
        self.settings.changed.connect(self._settings_changed)
        self.model_view.selected.connect(self.parts.select_row)
        self.model_view.moved.connect(self._part_moved)
        self.model_view.move_done.connect(self._move_done)
        self.model_view.face_picked.connect(self._face_picked)
        self._restore_state()
        self.dirty = False
        self.history.reset()
        self._view_changed(PLATE)
        self._refresh()

    # ================================================================ theme

    def set_theme(self, mode: str) -> None:
        theme.apply(QApplication.instance(), mode)
        self.store.setValue("theme", theme.mode())
        self._restyle()

    def _cycle_theme(self) -> None:
        modes = theme.MODES
        self.set_theme(modes[(modes.index(theme.mode()) + 1) % len(modes)])
        self.toast(f"Theme: {THEME_NAMES[theme.mode()]}", THEME_ICONS[theme.mode()])

    def _restyle(self) -> None:
        """Re-tint icons and redraw views after a theme change."""
        for w in self._themed:
            w.restyle()
        for b in (
            self.open_button,
            self.save_button,
            self.header_add,
            self.undo_button,
            self.redo_button,
            self.update_button,
            self.fit_button,
            self.scan_button,
            self.flip_button,
            *self.plate_controls,
        ):
            b.setIcon(theme.icon(b.property("iconName")))
        self.theme_button.setIcon(theme.icon(THEME_ICONS[theme.mode()]))
        self.theme_button.setToolTip(f"Theme: {THEME_NAMES[theme.mode()]} (click to change)")
        self.theme_button.setAccessibleName(f"Theme: {THEME_NAMES[theme.mode()]}")
        shadow(self.slice_button, theme.current()["accent"], blur=26, dy=2, alpha=150)
        self.banner_icon.setPixmap(theme.icon("warning", theme.current()["warn_text"]).pixmap(18, 18))
        self._scan_state(self.view.playing())
        for v in (self.model_view, self.view, self.stack_view):
            v.update()

    def toast(self, text: str, icon_name: str = "ok") -> None:
        Toast(self.centralWidget(), text, icon_name)

    # ================================================================ state + UI

    def busy(self) -> bool:
        return any(t.isRunning() for t in self.tasks)

    def _refresh(self) -> None:
        """Bring title, banner, empty state and enabled actions in line with the state."""
        name = os.path.splitext(os.path.basename(self.project_path))[0] if self.project_path else "Untitled"
        self.setWindowTitle(f"{name}[*] — {APP_NAME}")
        self.setWindowModified(self.dirty)
        self.title_label.setText(name)
        folder = os.path.basename(os.path.dirname(self.project_path)) if self.project_path else ""
        self.subtitle_label.setText(f"in {folder}" if folder else "not saved yet")
        self.subtitle_label.setToolTip(self.project_path or "")
        self.dirty_dot.setVisible(self.dirty)
        busy, slicing = self.busy(), self.slicing is not None and self.slicing.isRunning()
        exportable = self.result is not None and not self.stale and not busy
        self.slice_button.setEnabled(not busy)
        self.act_slice.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.export_button.setEnabled(exportable)
        self.act_export.setEnabled(exportable)
        self.act_preview.setEnabled(exportable)
        for a in (self.act_new, self.act_open, self.act_add):
            a.setEnabled(not busy)
        for b in (self.open_button, self.header_add):
            b.setEnabled(not busy)
        has_parts = bool(self.parts.rows())
        self.arrange_button.setEnabled(not busy and has_parts)
        self.act_arrange.setEnabled(not busy and has_parts)
        for action, button, label, verb in (
            (self.act_undo, self.undo_button, self.history.undo_label(), "Undo"),
            (self.act_redo, self.redo_button, self.history.redo_label(), "Redo"),
        ):
            action.setEnabled(label is not None and not busy)
            button.setEnabled(label is not None and not busy)
            action.setText(f"&{verb} {label}" if label else f"&{verb}")
            button.setToolTip(f"{verb} {label}" if label else verb)
        self.banner.setVisible(self.result is not None and self.stale and not slicing)
        self.progress_card.setVisible(busy)
        has_result = self.result is not None
        for w in (self.scan_button, self.flip_button):
            w.setEnabled(has_result)
        self.pages.setCurrentIndex(1 if has_parts or has_result else 0)
        self._show_info()

    def _show_info(self) -> None:
        """The line under the viewer: the plate's state, or the layer shown."""
        if self.view_switch.index() != PLATE:
            if self.result:
                self._layer_changed(self.slider.value())
            else:
                self.layer_info.setText("No slice yet - press Slice.")
            return
        n = len(self.model_view.items)
        text = f"{n} part{'s' if n != 1 else ''} on the plate" + (" · placed by hand" if self.hand_placed else "")
        missing = sum(copies for _, copies in self.parts.rows()) - n
        if missing > 0 and self.plate_error:
            text += f" · ⚠ {missing} don't fit - see Details"
        elif self.plate_problems:
            first = self.plate_problems[0]
            more = f" (+{len(self.plate_problems) - 1} more)" if len(self.plate_problems) > 1 else ""
            text += f" · ⚠ {first}{more}"
        self.layer_info.setText(text)
        self.layer_info.setToolTip(
            "\n".join(([self.plate_error] if missing > 0 and self.plate_error else []) + self.plate_problems)
        )

    def _changed(self) -> None:
        self.dirty = True
        if self.result is not None:
            self.stale = True
        if not self._restoring:
            self.history.record(self._describe())
            self.layout_timer.start()
        self._refresh()

    def _settings_changed(self) -> None:
        scale = self.settings.spins["scale"].value()
        self.parts.set_scale(scale)
        self.orientation.set_scale(scale)
        self.orientation.set_layer_thickness(self.settings.spins["layer_thickness"].value())
        try:
            self.part_settings.set_build(self.settings.config())
        except ValueError:
            pass
        self._changed()

    def _selection_changed(self, info) -> None:
        self.orientation.set_part(info)
        self.part_settings.set_part(info)
        self.model_view.set_selected(self.parts.selected_row())

    def _set_view_option(self, name: str, on: bool) -> None:
        self.view.set_option(name, on)

    def _view_changed(self, i: int) -> None:
        self.views.setCurrentIndex(i)
        self.toolbar.setCurrentIndex(i)
        self.scan_button.setVisible(i == LAYERS)
        self.flip_button.setVisible(i != PLATE)
        for part in (self.top_z, self.slider, self.bottom_z):  # layers don't apply to the plate
            part.setVisible(i != PLATE)
        if i != LAYERS:
            self.view.stop_scan()
        if i != PLATE:
            self.orientation.pick_button.setChecked(False)
        self._show_info()

    def _fit_views(self) -> None:
        self.view.refresh_bounds()
        self.stack_view.reset_view()
        self.model_view.reset_view()

    # ================================================================== undo / redo

    def _snapshot(self):
        rows = tuple(
            (info, info.rotation, copies, tuple(sorted(info.settings.items())), tuple(info.spots))
            for info, copies in self.parts.rows()
        )
        return rows, tuple(sorted(self.settings.state().items())), self.hand_placed

    def _restore(self, state) -> None:
        rows, settings, hand_placed = state
        self._restoring = True
        try:
            for info, rotation, _, own, spots in rows:
                info.rotation, info.settings, info.spots = rotation, dict(own), list(spots)
            self.parts.set_rows([(info, copies) for info, _, copies, _, _ in rows], self.parts.selected_row())
            self.settings.set_state(dict(settings))
            self.hand_placed = hand_placed
        finally:
            self._restoring = False
        self._arranged_key = self._layout_key()  # the places restored belong to this state
        self.dirty = True
        if self.result is not None:
            self.stale = True
        self._refresh_plate()
        self._refresh()

    def _describe(self) -> str:
        """A name for the edit just made, as in "Undo Fill power"."""
        before, after = self.history.last, self._snapshot()
        if before is None:
            return "Change"
        (rows0, settings0, _), (rows1, settings1, hand1) = before, after
        if len(rows1) != len(rows0) or any(a[0] is not b[0] for a, b in zip(rows0, rows1)):
            return "Add Models" if len(rows1) > len(rows0) else "Remove Parts"
        for a, b in zip(rows0, rows1):
            if a[2] != b[2]:
                return "Copies"
            if a[1] != b[1]:
                return "Orientation"
            if a[3] != b[3]:
                return "Part Settings"
        settings0, settings1 = dict(settings0), dict(settings1)
        changed = [k for k in settings1 if settings0.get(k) != settings1[k]]
        if changed:
            return _SETTING_NAMES.get(changed[0], "Setting")
        return "Move Part" if hand1 else "Arrange"

    def undo(self) -> None:
        if not self.busy():
            self.history.undo()
            self._refresh()

    def redo(self) -> None:
        if not self.busy():
            self.history.redo()
            self._refresh()

    # ================================================================== tasks

    def _run(self, task: Task, on_success, what: str) -> Task:
        task.progressed.connect(self._progress)
        task.succeeded.connect(on_success)
        task.failed.connect(lambda message, details: self._failed(what, message, details))
        task.finished.connect(lambda: (self.tasks.discard(task), self._refresh(), self.layout_timer.start()))
        self.tasks.add(task)
        self.progress.setRange(0, 0)
        self.stage.setText(f"{what}…")
        task.start()
        self._refresh()
        return task

    def _progress(self, stage: str, done: int, total: int) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.stage.setText(f"{stage} {done} of {total}")
        else:
            self.progress.setRange(0, 0)
            self.stage.setText(stage)

    def _failed(self, what: str, message: str, details: str) -> None:
        if message == "Cancelled.":
            self.toast(f"{what} cancelled.", "stop")
            if what == "Slicing":
                self.report.setPlainText("Slicing cancelled.")
            return
        self.report.setPlainText(f"{what} failed: {message}")
        self.details.header.setChecked(True)
        if details:  # unexpected: show the details and where the log is
            box = QMessageBox(QMessageBox.Critical, f"{what} failed", message, parent=self)
            box.setInformativeText(
                "This looks like a bug. The details are also in the log file (Help ▸ Show Log File)."
            )
            box.setDetailedText(details)
            box.exec()
        else:
            self.toast(f"{what} failed - see Details.", "warning")

    def cancel(self) -> None:
        for t in list(self.tasks):
            t.cancel()

    # ================================================================== parts

    def add_models_dialog(self) -> None:
        if self.busy():
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Add models", self._last_dir(), MODEL_FILTER)
        if paths:
            self._remember_dir(paths[0])
            self.add_models(paths)

    def add_models(
        self,
        paths: list[str],
        copies: list[int] | None = None,
        rotations: list | None = None,
        then=None,
        settings: list[dict] | None = None,
        spots: list[list] | None = None,
    ) -> Task:
        """Load models in the background and add them to the parts list."""
        copies = copies or [1] * len(paths)
        rotations = rotations or [NO_ROTATION] * len(paths)
        settings = settings or [{} for _ in paths]
        spots = spots or [[] for _ in paths]

        def load(progress):
            out = []
            for i, path in enumerate(paths):
                progress(f"Loading {os.path.basename(path)}", i, len(paths))
                try:
                    mesh, report = prepare_mesh(path, 1.0)  # sizes are shown at the current scale
                    shape = (mesh.convex_hull.vertices, outline_edges(mesh), mesh, simplified(mesh))
                    out.append((path, report, shape, None))
                except MeshError as e:
                    out.append((path, None, None, str(e)))
            return out

        def loaded(results):
            problems_ = []
            for (path, report, shape, error), n, rotation, own, places in zip(
                results, copies, rotations, settings, spots
            ):
                if error:
                    problems_.append(f"{os.path.basename(path)}: {error}")
                else:
                    hull, edges, mesh, display = shape
                    self.parts.add_part(
                        path,
                        report,
                        n,
                        hull=hull,
                        edges=edges,
                        rotation=rotation,
                        mesh=mesh,
                        display=display,
                        settings=dict(own),
                        spots=list(places),
                    )
            if problems_:
                QMessageBox.warning(self, "Some models can't be used", "\n\n".join(problems_))
            added = len(results) - len(problems_)
            if added:
                self.toast(f"Added {added} model{'s' if added != 1 else ''}.")
            if then:
                then()

        return self._run(Task(load), loaded, "Loading models")

    # ================================================================== the plate

    def _layout_key(self):
        """Everything the parts' places depend on."""
        state = self.settings.state()
        rows = tuple((id(info), info.rotation, copies) for info, copies in self.parts.rows())
        volume = state["volume"] if state["use_volume"] else None
        return rows, state["scale"], state["part_spacing"], volume, state["allow_rotation"]

    def _volume(self):
        state = self.settings.state()
        return tuple(state["volume"]) if state["use_volume"] else None

    def _update_layout(self) -> None:
        """After an edit: pack the parts again (or only new copies, once parts were
        placed by hand), or just redraw them."""
        if self._restoring:
            return
        if self._arranging is not None and self._arranging.isRunning():
            self._arrange_again = True
            return
        rows = self.parts.rows()
        for info, copies in rows:
            del info.spots[copies:]
        if self._volume() is None or not rows or self.busy():
            self._refresh_plate()
            return
        missing = any(len(info.spots) < copies for info, copies in rows)
        if not self.hand_placed and self._layout_key() != self._arranged_key:
            self.arrange(automatic=True)
        elif missing:
            self.arrange(automatic=True, keep=True)
        else:
            self._refresh_plate()

    def arrange(self, automatic: bool = False, keep: bool = False) -> Task | None:
        """Pack the parts onto the plate in the background. keep: leave the parts
        that have a place there and pack only the others around them."""
        rows = self.parts.rows()
        if not rows or self.busy():
            return None
        try:
            config = self.settings.config()
        except ValueError as e:
            self.report.setPlainText(f"Settings problem: {e}")
            return None
        if config.build_volume is None:
            if not automatic:
                self.toast("Turn on the build volume to lay out the plate.", "warning")
            return None
        key = self._layout_key()
        work = [
            (info.mesh, info.rotation, copies, list(info.spots), os.path.basename(info.path)) for info, copies in rows
        ]

        def run(progress):
            progress("Arranging parts")
            meshes, owners, names, pinned = [], [], [], {}
            for row, (mesh, rotation, copies, spots, name) in enumerate(work):
                m = posed(mesh, rotation, config.scale)
                for c in range(copies):
                    if keep and c < len(spots):
                        pinned[len(meshes)] = spots[c]
                    meshes.append(m)
                    owners.append((row, c))
                    names.append(name)
            try:
                placements, error = (
                    plan(meshes, config.build_volume, config.part_spacing, config.allow_rotation, names, pinned),
                    "",
                )
            except NestingError as e:  # show the parts that fit, and say what's left over
                placements, error = e.placements, str(e)
            return [(owners[p.item], p.spot) for p in placements], error

        def done(result):
            if self._layout_key() != key:  # edited meanwhile: work it out again
                self._arrange_again = True
                return
            placed, error = result
            self._apply_spots(rows, placed)
            self._arranged_key = key
            self.plate_error = error
            if error:
                self.report.setPlainText(error)
                self.toast("Not every part fits - see Details.", "warning")
            if automatic:
                self.history.amend()  # part of the edit that asked for it
                self._refresh_plate()
            else:
                self.hand_placed = False
                self._changed()

        def finished():
            if self._arrange_again:
                self._arrange_again = False
                self.layout_timer.start()

        self._arranged_key = key  # also when packing fails: don't retry until something changes
        self._arranging = self._run(Task(run), done, "Arranging parts")
        self._arranging.finished.connect(finished)
        return self._arranging

    @staticmethod
    def _apply_spots(rows, placed) -> None:
        spots: dict[int, dict[int, tuple]] = {}
        for (row, copy), spot in placed:
            spots.setdefault(row, {})[copy] = tuple(float(v) for v in spot[:3]) + (int(spot[3]),)
        for row, (info, copies) in enumerate(rows):
            info.spots = [spots[row][c] for c in range(copies) if c in spots.get(row, {})]

    def _display(self, info, scale: float, faces: int):
        """A part posed for drawing: triangles, normals, and normals in the file's frame."""
        key = (id(info), info.rotation, scale, faces)
        if key not in self._posed:
            if len(self._posed) > 64:
                self._posed.clear()
            lighter = for_drawing(info.display, faces)
            m = posed(lighter, info.rotation, scale)
            self._posed[key] = (m, m.triangles, m.face_normals, lighter.face_normals)
        return self._posed[key]

    def _refresh_plate(self) -> None:
        rows = self.parts.rows()
        volume = self._volume()
        scale = self.settings.state()["scale"]
        total = sum(copies for _, copies in rows)
        faces = int(min(max(SCENE_FACES // max(total, 1), 400), DISPLAY_FACES))
        items, meshes, placements, names = [], [], [], []
        for row, (info, copies) in enumerate(rows):
            if info.display is None:
                continue
            mesh, triangles, normals, file_normals = self._display(info, scale, faces)
            for c in range(copies):
                if c < len(info.spots):
                    spot = info.spots[c]
                elif volume is None:
                    spot = (0.0, 0.0, 0.0, 0)  # no plate to lay out: in the middle
                else:
                    continue  # not placed yet
                items.append(SceneItem(row, c, triangles, normals, file_normals, spot))
                placements.append(placement_at(mesh, len(meshes), spot))
                meshes.append(mesh)
                names.append(os.path.basename(info.path) + (f" #{c + 1}" if copies > 1 else ""))
        found = []
        if volume is not None and items:
            found = problems(meshes, placements, volume, self.settings.state()["part_spacing"], names, samples=6000)
        self.plate_problems = [p.message for p in found]
        bad = {(items[i].row, items[i].copy) for p in found for i in p.parts}
        self.model_view.set_scene(items, volume, self.parts.selected_row(), bad)
        self._show_info()

    def _part_moved(self, row: int, copy: int, spot) -> None:
        info = self.parts.info(row)
        if copy < len(info.spots):
            info.spots[copy] = spot

    def _move_done(self) -> None:
        self.hand_placed = True
        self._changed()

    def _picking_changed(self, on: bool) -> None:
        self.model_view.set_picking(on)
        if on:
            self.view_switch.set_index(PLATE)

    def _face_picked(self, row: int, normal) -> None:
        self.parts.select_row(row)
        self.orientation.lay_on_face(normal)
        self.orientation.pick_button.setChecked(False)

    # ================================================================== slicing

    def start_slicing(self) -> Task | None:
        if self.busy():
            return None
        if not self.parts.rows():
            self.toast("Add a model first.", "warning")
            return None
        try:
            config = self.settings.config()
        except ValueError as e:
            self.report.setPlainText(f"Settings problem: {e}")
            return None
        project = Project(parts=self.parts.parts(), config=config)
        jobs, key = self.parts.jobs(), self._layout_key()

        def run(progress):
            progress("Loading and packing models")
            step = lambda done, total: progress("Slicing layer", done, total)  # noqa: E731
            return slice_project(project, None, step)

        self._stop_playback()
        self.report.setPlainText(f"Slicing {len(jobs)} part{'s' if len(jobs) > 1 else ''}…")
        self.slicing = self._run(Task(run), lambda r: self._sliced(r, jobs, config, key), "Slicing")
        return self.slicing

    def _sliced(self, result: SliceResult, jobs: list[str], config, key) -> None:
        self.result, self.result_jobs, self.result_config, self.stale = result, jobs, config, False
        self.report.setPlainText("\n".join(summary_lines(result, config)))
        plate = config.build_volume[:2] if config.build_volume else None
        self.view.set_layers(result.layers, plate)
        self.stack_view.set_layers(result.layers)
        self.slider.setRange(0, len(result.layers) - 1)
        self.slider.setValue(0)
        self.slider.setEnabled(True)
        self.top_z.setText(f"{result.layers[-1].z:.1f}")
        self.bottom_z.setText(f"{result.layers[0].z:.1f}")
        if result.build is not None and key == self._layout_key():  # show the plate as sliced
            rows = self.parts.rows()
            owners = [(row, c) for row, (_, copies) in enumerate(rows) for c in range(copies)]
            self._apply_spots(rows, [(owners[p.item], p.spot) for p in result.build.placements])
            self._arranged_key = key
            self.history.amend()
            self._refresh_plate()
        self._fill_tiles(result, jobs, config)
        self.view_switch.set_index(LAYERS)
        self._layer_changed(0)
        self._refresh()
        self.toast(f"Sliced {len(result.layers)} layers.")

    def _fill_tiles(self, result: SliceResult, jobs: list[str], config) -> None:
        seconds = estimate_scan_time(result.layers, config.jump_speed)
        height = result.bounding_box[5] if result.bounding_box else 0
        self.tiles["layers"].set(f"{len(result.layers):,}", f"{config.layer_thickness:g} mm each")
        self.tiles["height"].set(f"{height:.1f} mm")
        self.tiles["time"].set(hms(seconds), "Laser scanning only - recoating and heating not included")
        self.tiles["parts"].set(str(len(jobs)))
        self.tiles["density"].set(
            f"{result.build.density:.1%}" if result.build else "–", "Part volume / (plate area × build height)"
        )
        self.tiles["energy"].set(
            f"{config.hatch_energy_density:.3f} J/mm²",
            "Fill power / (speed × hatch spacing) - the main number to tune per powder"
            + (" (parts with their own settings differ)" if result.own_settings else ""),
        )

    def _layer_changed(self, i: int) -> None:
        if not self.result:
            return
        self.view.set_index(i)
        self.stack_view.set_index(i)
        if self.view_switch.index() == PLATE:
            return
        layer = self.result.layers[i]
        holes = sum(c.is_hole for c in layer.contours)
        if layer.contours or layer.hatches:
            seconds = layer_scan_time(layer, self.result_config.jump_speed)
            what = (
                f"{len(layer.contours)} contours ({holes} around holes) · "
                f"{layer.num_hatch_vectors} hatch vectors · {seconds:.1f} s"
            )
        else:
            what = "powder only (gap between stacked parts)"
        self.layer_info.setText(f"Layer {i + 1} of {len(self.result.layers)} · z {layer.z:.3f} mm · {what}")
        self.layer_info.setToolTip("")

    def _step(self, delta: int) -> None:
        if self.slider.isEnabled():
            self.slider.setValue(self.slider.value() + delta)

    def _goto(self, i: int) -> None:
        if self.slider.isEnabled():
            self.slider.setValue(min(i, self.slider.maximum()))

    def _clear(self) -> None:
        self._stop_playback()
        self.orientation.pick_button.setChecked(False)
        self.parts.clear()
        self.result, self.result_jobs, self.stale = None, [], False
        self.hand_placed, self._arranged_key, self.plate_problems, self.plate_error = False, None, [], ""
        self.view.set_layers([], None)
        self.stack_view.set_layers([])
        self.model_view.set_scene([], self._volume())
        self.slider.setEnabled(False)
        self.top_z.setText("")
        self.bottom_z.setText("")
        self.report.clear()
        for tile in self.tiles.values():
            tile.set("–")
        self.view_switch.set_index(PLATE)

    # ================================================================== updates

    def check_for_updates(self, by_hand: bool = False) -> None:
        """Ask GitHub whether a newer XeroForm is out: by hand, or (if allowed) once a day."""
        if not by_hand:
            if not self.act_auto_updates.isChecked() or not self.updates.due(self.store.value("update_checked")):
                return
        self.store.setValue("update_checked", time.time())
        self._update_by_hand = by_hand
        self.updates.check()

    def _auto_updates_toggled(self, on: bool) -> None:
        self.store.setValue("check_updates", on)

    def _update_found(self, version: str) -> None:
        self.latest_version = version
        self.update_button.setText(f"Update to {version}")
        self.update_button.show()
        if self._update_by_hand:
            self.show_update()
        else:
            self.toast(f"{APP_NAME} {version} is available.", "update")

    def _up_to_date(self) -> None:
        if self._update_by_hand:
            QMessageBox.information(self, "No update", f"You have the latest {APP_NAME} ({__version__}).")

    def _update_failed(self, message: str) -> None:
        log.info("update check failed: %s", message)
        if self._update_by_hand:
            QMessageBox.warning(self, "Couldn't check for updates", message)

    def show_update(self) -> None:
        command = install_command()
        shell = "PowerShell" if command.startswith("irm") else "Terminal"
        box = QMessageBox(self)
        box.setWindowTitle("Update available")
        box.setText(f"{APP_NAME} {self.latest_version} is available. You have {__version__}.")
        box.setInformativeText(
            f"To update, save your work, quit {APP_NAME} and run this in {shell}:\n\n{command}\n\n"
            "It is the same command you installed with; your projects and settings stay."
        )
        copy = box.addButton("Copy Command", QMessageBox.AcceptRole)
        notes = box.addButton("What's New", QMessageBox.HelpRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is copy:
            QApplication.clipboard().setText(command)
            self.toast("Command copied.")
        elif box.clickedButton() is notes:
            QDesktopServices.openUrl(QUrl(LATEST_URL))

    # ================================================================== help, close

    def about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h3>{APP_NAME} Slicer {__version__}</h3>"
            "<p>The open-source SLS slicer for the XeroForm printer: 3D models in, "
            "laser tool-paths out.</p>"
            f"<p>Built on PySLM, trimesh and Qt {qVersion()}.</p>"
            "<p>Released under the MIT License. Includes third-party libraries under their own "
            "licenses, among them Qt / PySide6 (LGPL-3.0) and PySLM (LGPL-2.1): see "
            f'<a href="{REPO_URL}/blob/main/THIRD_PARTY_NOTICES.md">third-party notices</a> '
            "(also in the app folder).</p>"
            f'<p><a href="{REPO_URL}">{REPO_URL.removeprefix("https://")}</a></p>',
        )

    def show_log(self) -> None:
        if self.log_path and os.path.exists(self.log_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.log_path))
        else:
            QMessageBox.information(self, "Log file", "Nothing has been logged yet.")

    def closeEvent(self, event) -> None:
        if not self.maybe_save():
            event.ignore()
            return
        self._stop_playback()
        self.cancel()
        for t in list(self.tasks):
            t.wait(10000)
        self._save_state()
        super().closeEvent(event)
