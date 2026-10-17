"""Main window: parts and settings on the left; layer and build-layout views on the right.

Models load and slices run on worker threads, so the window never freezes. A
slice stays in memory until exported; changing a part or a setting afterwards
marks it out of date and blocks exporting it. Projects (.slicerkit) save the
parts and every setting; the window remembers its layout and last settings.
"""
from __future__ import annotations
import json
import logging
import os

from PySide6.QtCore import QRectF, QSettings, Qt, QUrl, qVersion
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider, QSplitter, QStyle,
    QTabWidget, QToolBar, QVBoxLayout, QWidget,
)

from .. import __version__
from ..laser import layer_scan_time
from ..part import MeshError, prepare_mesh
from ..pipeline import SliceResult, export, slice_build, slice_job
from ..preview import write_preview
from ..project import EXTENSION, Project, ProjectError, ProjectPart, config_from_dict, config_to_dict
from ..summary import hms, summary_lines
from .panels import PartsPanel, SettingsPanel, gui_defaults
from .tasks import Task
from .views import HOLE, OUTER, LayerView, LayoutView

log = logging.getLogger("slicerkit.gui")

MODEL_EXTENSIONS = (".stl", ".obj", ".ply", ".3mf", ".off", ".glb")
MODEL_FILTER = "3D models (*.stl *.STL *.obj *.ply *.3mf *.3MF);;All files (*)"
PROJECT_FILTER = f"slicerkit project (*{EXTENSION})"
MAX_RECENT = 8


def _swatch(color: QColor) -> QIcon:
    pix = QPixmap(12, 12)
    pix.fill(color)
    return QIcon(pix)


class MainWindow(QMainWindow):
    def __init__(self, log_path: str | None = None):
        super().__init__()
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

        self.setAcceptDrops(True)
        self.resize(1320, 860)
        self.split = QSplitter()
        self.split.addWidget(self._build_sidebar())
        self.split.addWidget(self._build_viewer())
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([420, 900])
        self.setCentralWidget(self.split)
        self._build_actions()
        self.cursor_label = QLabel()
        self.statusBar().addPermanentWidget(self.cursor_label)

        self.parts.changed.connect(self._changed)
        self.parts.add_requested.connect(self.add_models_dialog)
        self.settings.changed.connect(self._settings_changed)
        self._restore_state()
        self.dirty = False
        self._refresh()

    # ===================================================================== layout

    def _build_sidebar(self) -> QWidget:
        inner = QWidget()
        col = QVBoxLayout(inner)
        self.parts = PartsPanel()
        self.settings = SettingsPanel()
        col.addWidget(self.parts)
        col.addWidget(self.settings)
        col.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)

        side = QWidget()
        side.setMinimumWidth(400)
        outer = QVBoxLayout(side)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll, 3)
        row = QHBoxLayout()
        self.slice_button = QPushButton("Slice")
        self.slice_button.setDefault(True)
        self.slice_button.setToolTip("Slice all parts (⌘R)")
        self.slice_button.clicked.connect(self.start_slicing)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.slice_button, 1)
        row.addWidget(self.cancel_button)
        outer.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.stage = QLabel(" ")
        self.stage.setEnabled(False)
        outer.addWidget(self.progress)
        outer.addWidget(self.stage)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("Add models (or drop them on the window), then Slice.")
        self.report.setMinimumHeight(140)
        outer.addWidget(self.report, 2)
        return side

    def _build_viewer(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)

        self.banner = QFrame()
        self.banner.setFrameShape(QFrame.StyledPanel)
        self.banner.setAutoFillBackground(True)
        self.banner.setBackgroundRole(self.banner.palette().ColorRole.ToolTipBase)
        bl = QHBoxLayout(self.banner)
        text = QLabel("Parts or settings changed since this slice. The view is out of date "
                      "and can't be exported.")
        text.setForegroundRole(text.palette().ColorRole.ToolTipText)
        text.setWordWrap(True)
        again = QPushButton("Slice again")
        again.clicked.connect(self.start_slicing)
        bl.addWidget(text, 1)
        bl.addWidget(again)
        self.banner.hide()
        col.addWidget(self.banner)

        self.tabs = QTabWidget()
        col.addWidget(self.tabs, 1)

        layers = QWidget()
        lc = QVBoxLayout(layers)
        lc.setContentsMargins(0, 0, 0, 0)
        self.view = LayerView()
        lc.addWidget(self.view, 1)
        nav = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._layer_changed)
        nav.addWidget(self.slider, 1)
        lc.addLayout(nav)
        self.layer_info = QLabel("No slice yet.")
        self.layer_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lc.addWidget(self.layer_info)
        toggles = QHBoxLayout()
        for text, name, on, color in [("Outlines", "show_contours", True, OUTER),
                                      ("Holes in blue", None, True, HOLE),
                                      ("Hatches", "show_hatches", True, None),
                                      ("Travel moves", "show_travel", False, None),
                                      ("Scan order", "scan_order", False, None),
                                      ("Grid", "show_grid", True, None)]:
            if name is None:  # a legend entry, not a toggle
                key = QLabel(text)
                key.setPixmap(_swatch(color).pixmap(12, 12))
                toggles.addWidget(key)
                toggles.addWidget(QLabel(text))
                continue
            box = QCheckBox(text)
            box.setChecked(on)
            if color is not None:
                box.setIcon(_swatch(color))
            box.toggled.connect(lambda checked, n=name: self._set_view_option(n, checked))
            toggles.addWidget(box)
        toggles.addStretch()
        hint = QLabel("← → layer · PgUp/PgDn ±10 · scroll zoom · drag pan · double-click fit")
        hint.setEnabled(False)
        toggles.addWidget(hint)
        lc.addLayout(toggles)
        self.tabs.addTab(layers, "Layers")

        layout = QWidget()
        yc = QVBoxLayout(layout)
        yc.setContentsMargins(0, 0, 0, 0)
        self.layout_view = LayoutView()
        yc.addWidget(self.layout_view, 1)
        self.layout_info = QLabel("Where each part sits on the plate, seen from above. "
                                  "Colours show stacking levels.")
        self.layout_info.setWordWrap(True)
        yc.addWidget(self.layout_info)
        self.tabs.addTab(layout, "Build layout")

        for v in (self.view, self.layout_view):
            v.cursor_moved.connect(lambda x, y: self.cursor_label.setText(f"x {x:8.2f}   y {y:8.2f} mm"))
            v.cursor_left.connect(lambda: self.cursor_label.setText(""))
        for keys, step in [((Qt.Key_Right, Qt.Key_Up), 1), ((Qt.Key_Left, Qt.Key_Down), -1),
                           ((Qt.Key_PageUp,), 10), ((Qt.Key_PageDown,), -10)]:
            for key in keys:
                QShortcut(QKeySequence(key), layers, lambda s=step: self._step(s),
                          context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence(Qt.Key_Home), layers, lambda: self._goto(0), context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence(Qt.Key_End), layers, lambda: self._goto(10 ** 9),
                  context=Qt.WidgetWithChildrenShortcut)
        return w

    def _build_actions(self) -> None:
        style = self.style()

        def action(text, slot, shortcut=None, icon=None, tip=None):
            a = QAction(text, self)
            if shortcut is not None:
                a.setShortcut(shortcut)
            if icon is not None:
                a.setIcon(style.standardIcon(icon))
            if tip:
                a.setStatusTip(tip)
            a.triggered.connect(slot)
            return a

        self.act_new = action("&New Project", self.new_project, QKeySequence.New)
        self.act_open = action("&Open Project…", lambda: self.open_project(), QKeySequence.Open,
                               QStyle.SP_DialogOpenButton)
        self.act_save = action("&Save Project", self.save_project, QKeySequence.Save, QStyle.SP_DialogSaveButton)
        self.act_save_as = action("Save Project &As…", self.save_project_as, QKeySequence.SaveAs)
        self.act_add = action("&Add Models…", self.add_models_dialog, QKeySequence("Ctrl+I"),
                              QStyle.SP_FileDialogNewFolder, "Add STL, OBJ, PLY or 3MF models")
        self.act_slice = action("S&lice", self.start_slicing, QKeySequence("Ctrl+R"), QStyle.SP_MediaPlay,
                                "Slice all parts")
        self.act_export = action("&Export Laser Paths (.cli)…", self.export_cli, QKeySequence("Ctrl+E"),
                                 QStyle.SP_ArrowDown, "Write the sliced result for the machine")
        self.act_preview = action("Export &Preview (.html)…", self.export_preview)
        self.act_quit = action("&Quit", self.close, QKeySequence.Quit)
        self.act_fit = action("&Fit View", self._fit_views, QKeySequence("Ctrl+0"))
        self.act_about = action("&About slicerkit", self.about)
        self.act_log = action("Show &Log File", self.show_log)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions([self.act_new, self.act_open])
        self.recent_menu = file_menu.addMenu("Open &Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        file_menu.addActions([self.act_save, self.act_save_as])
        file_menu.addSeparator()
        file_menu.addAction(self.act_add)
        file_menu.addSeparator()
        file_menu.addActions([self.act_export, self.act_preview])
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)
        build_menu = self.menuBar().addMenu("&Build")
        build_menu.addAction(self.act_slice)
        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.act_fit)
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addActions([self.act_about, self.act_log])

        bar = QToolBar("Main")
        bar.setObjectName("main-toolbar")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        bar.addActions([self.act_open, self.act_save])
        bar.addSeparator()
        bar.addActions([self.act_add, self.act_slice, self.act_export])
        self.addToolBar(bar)

    # ================================================================ state + UI

    def busy(self) -> bool:
        return any(t.isRunning() for t in self.tasks)

    def _refresh(self) -> None:
        """Bring title, banner and enabled actions in line with the current state."""
        name = os.path.splitext(os.path.basename(self.project_path))[0] if self.project_path else "Untitled"
        self.setWindowTitle(f"{name}[*] — slicerkit")
        self.setWindowModified(self.dirty)
        busy, slicing = self.busy(), self.slicing is not None and self.slicing.isRunning()
        exportable = self.result is not None and not self.stale and not busy
        self.slice_button.setEnabled(not busy)
        self.act_slice.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.act_export.setEnabled(exportable)
        self.act_preview.setEnabled(exportable)
        for a in (self.act_new, self.act_open, self.act_add):
            a.setEnabled(not busy)
        self.banner.setVisible(self.result is not None and self.stale and not slicing)
        if not busy:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.stage.setText(" ")

    def _changed(self) -> None:
        self.dirty = True
        if self.result is not None:
            self.stale = True
        self._refresh()

    def _settings_changed(self) -> None:
        self.parts.set_scale(self.settings.spins["scale"].value())
        self._changed()

    def _set_view_option(self, name: str, on: bool) -> None:
        self.view.set_option(name, on)
        if name == "show_grid":
            self.layout_view.show_grid = on
            self.layout_view.update()

    def _fit_views(self) -> None:
        for v in (self.view, self.layout_view):
            v.refresh_bounds()

    # ================================================================== tasks

    def _run(self, task: Task, on_success, what: str) -> Task:
        task.progressed.connect(self._progress)
        task.succeeded.connect(on_success)
        task.failed.connect(lambda message, details: self._failed(what, message, details))
        task.finished.connect(lambda: (self.tasks.discard(task), self._refresh()))
        self.tasks.add(task)
        self.progress.setRange(0, 0)
        task.start()
        self._refresh()
        return task

    def _progress(self, stage: str, done: int, total: int) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.stage.setText(f"{stage}: {done} of {total}")
        else:
            self.progress.setRange(0, 0)
            self.stage.setText(stage)

    def _failed(self, what: str, message: str, details: str) -> None:
        if message == "Cancelled.":
            self.statusBar().showMessage(f"{what} cancelled.", 5000)
            if what == "Slicing":
                self.report.setPlainText("Slicing cancelled.")
            return
        self.report.setPlainText(f"{what} failed: {message}")
        if details:  # unexpected: show the details and where the log is
            box = QMessageBox(QMessageBox.Critical, f"{what} failed", message, parent=self)
            box.setInformativeText("This looks like a bug. The details are also in the log file "
                                   "(Help ▸ Show Log File).")
            box.setDetailedText(details)
            box.exec()

    def cancel(self) -> None:
        for t in list(self.tasks):
            t.cancel()

    # ================================================================== parts

    def add_models_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add models", self._last_dir(), MODEL_FILTER)
        if paths:
            self._remember_dir(paths[0])
            self.add_models(paths)

    def add_models(self, paths: list[str], copies: list[int] | None = None, then=None) -> Task:
        """Load models in the background and add them to the parts list."""
        copies = copies or [1] * len(paths)

        def load(progress):
            out = []
            for i, path in enumerate(paths):
                progress(f"Loading {os.path.basename(path)}", i, len(paths))
                try:
                    _, report = prepare_mesh(path, 1.0)  # sizes are shown at the current scale
                    out.append((path, report, None))
                except MeshError as e:
                    out.append((path, None, str(e)))
            return out

        def loaded(results):
            problems = []
            for (path, report, error), n in zip(results, copies):
                if error:
                    problems.append(f"{os.path.basename(path)}: {error}")
                else:
                    self.parts.add_part(path, report, n)
            if problems:
                QMessageBox.warning(self, "Some models can't be used", "\n\n".join(problems))
            self.statusBar().showMessage(f"Added {len(results) - len(problems)} model(s).", 4000)
            if then:
                then()

        return self._run(Task(load), loaded, "Loading models")

    # ================================================================== slicing

    def start_slicing(self) -> Task | None:
        if self.busy():
            return None
        jobs = self.parts.jobs()
        if not jobs:
            self.report.setPlainText("Add a model first (File ▸ Add Models, or drop files on the window).")
            return None
        try:
            config = self.settings.config()
        except ValueError as e:
            self.report.setPlainText(f"Settings problem: {e}")
            return None

        def run(progress):
            progress("Loading and packing models")
            step = lambda done, total: progress("Slicing layer", done, total)  # noqa: E731
            if len(jobs) == 1:
                return slice_job(jobs[0], None, config, step)
            return slice_build(jobs, None, config, progress=step)

        self.report.setPlainText(f"Slicing {len(jobs)} part{'s' if len(jobs) > 1 else ''}…")
        self.slicing = self._run(Task(run), lambda r: self._sliced(r, jobs, config), "Slicing")
        return self.slicing

    def _sliced(self, result: SliceResult, jobs: list[str], config) -> None:
        self.result, self.result_jobs, self.result_config, self.stale = result, jobs, config, False
        self.report.setPlainText("\n".join(summary_lines(result, config)))
        plate = config.build_volume[:2] if config.build_volume else None
        self.view.set_layers(result.layers, plate)
        self.layout_view.set_items(self._layout_items(result, jobs), plate)
        self.slider.setRange(0, len(result.layers) - 1)
        self.slider.setValue(0)
        self.slider.setEnabled(True)
        self._layer_changed(0)
        self.statusBar().showMessage(f"Sliced {len(result.layers)} layers.", 5000)
        self._refresh()

    @staticmethod
    def _layout_items(result: SliceResult, jobs: list[str]):
        if result.build is None:
            x0, y0, z0, x1, y1, z1 = result.bounding_box
            return [(QRectF(x0, y0, x1 - x0, y1 - y0), os.path.basename(jobs[0]),
                     f"z {z0:.0f}–{z1:.0f} mm", 0)]
        levels = sorted({round(p.position[2], 3) for p in result.build.placements})
        items = []
        for p in result.build.placements:
            (x, y, z), (sx, sy, sz) = p.position, p.size
            detail = f"z {z:.0f}–{z + sz:.0f} mm" + (" · turned" if p.rotated else "")
            items.append((QRectF(x, y, sx, sy), os.path.basename(jobs[p.item]), detail,
                          levels.index(round(z, 3))))
        return items

    def _layer_changed(self, i: int) -> None:
        if not self.result:
            return
        self.view.set_index(i)
        layer = self.result.layers[i]
        holes = sum(c.is_hole for c in layer.contours)
        if layer.contours or layer.hatches:
            seconds = layer_scan_time(layer, self.result_config.jump_speed)
            what = (f"{len(layer.contours)} contours ({holes} around holes) · "
                    f"{layer.num_hatch_vectors} hatch vectors · {seconds:.1f} s")
        else:
            what = "powder only (gap between stacked parts)"
        self.layer_info.setText(f"Layer {i + 1} of {len(self.result.layers)} · z {layer.z:.3f} mm · {what}")

    def _step(self, delta: int) -> None:
        if self.slider.isEnabled():
            self.slider.setValue(self.slider.value() + delta)

    def _goto(self, i: int) -> None:
        if self.slider.isEnabled():
            self.slider.setValue(min(i, self.slider.maximum()))

    # ================================================================== export

    def _default_name(self, ext: str) -> str:
        base = (os.path.splitext(os.path.basename(self.project_path))[0] if self.project_path
                else os.path.splitext(os.path.basename(self.result_jobs[0]))[0] if self.result_jobs else "build")
        return os.path.join(self._last_dir(), base + ext)

    def export_cli(self) -> None:
        if self.result is None or self.stale:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export laser paths", self._default_name(".cli"),
                                              "Common Layer Interface (*.cli)")
        if not path:
            return
        try:
            export(self.result, path, self.result_config)
        except OSError as e:
            QMessageBox.warning(self, "Export failed", f"Could not write {path}:\n{e.strerror or e}")
            return
        self._remember_dir(path)
        self.statusBar().showMessage(f"Exported {path}", 6000)

    def export_preview(self) -> None:
        if self.result is None or self.stale:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export preview", self._default_name(".html"), "HTML (*.html)")
        if not path:
            return
        try:
            write_preview(self.result.layers, path, title=os.path.basename(self._default_name("")),
                          jump_speed=self.result_config.jump_speed)
        except OSError as e:
            QMessageBox.warning(self, "Export failed", f"Could not write {path}:\n{e.strerror or e}")
            return
        self._remember_dir(path)
        self.statusBar().showMessage(f"Exported {path}", 6000)

    # ================================================================== projects

    def maybe_save(self) -> bool:
        """Ask about unsaved changes. False = the user cancelled."""
        if not self.dirty or (self.project_path is None and not self.parts.parts()):
            return True
        answer = QMessageBox.question(
            self, "Unsaved changes", "Save the changes to this project first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if answer == QMessageBox.Save:
            return self.save_project()
        return answer == QMessageBox.Discard

    def _clear(self) -> None:
        self.parts.clear()
        self.result, self.result_jobs, self.stale = None, [], False
        self.view.set_layers([], None)
        self.layout_view.set_items([], None)
        self.slider.setEnabled(False)
        self.layer_info.setText("No slice yet.")
        self.report.clear()

    def new_project(self) -> None:
        if self.busy() or not self.maybe_save():
            return
        self._clear()
        self.settings.set_config(gui_defaults())
        self.project_path, self.dirty = None, False
        self._refresh()

    def open_project(self, path: str | None = None) -> Task | None:
        if self.busy() or not self.maybe_save():
            return None
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Open project", self._last_dir(), PROJECT_FILTER)
            if not path:
                return None
        try:
            project = Project.load(path)
        except ProjectError as e:
            QMessageBox.warning(self, "Can't open project", str(e))
            self._forget_recent(path)
            return None
        self._clear()
        self.settings.set_config(project.config)
        self.project_path = path
        self._remember_dir(path)
        self._add_recent(path)
        missing = [p for p in project.parts if not os.path.isfile(p.path)]
        found = [p for p in project.parts if os.path.isfile(p.path)]
        if missing:
            QMessageBox.warning(self, "Missing models", "These models were not found and are left out:\n\n"
                                + "\n".join(p.path for p in missing))

        def done():
            self.dirty = bool(missing)
            self._refresh()

        if not found:
            done()
            return None
        return self.add_models([p.path for p in found], [p.copies for p in found], then=done)

    def save_project(self) -> bool:
        if self.project_path is None:
            return self.save_project_as()
        return self._write_project(self.project_path)

    def save_project_as(self) -> bool:
        start = self.project_path or os.path.join(self._last_dir(), "build" + EXTENSION)
        path, _ = QFileDialog.getSaveFileName(self, "Save project", start, PROJECT_FILTER)
        if not path:
            return False
        if not path.endswith(EXTENSION):
            path += EXTENSION
        return self._write_project(path)

    def _write_project(self, path: str) -> bool:
        try:
            Project(parts=self.parts.parts(), config=self.settings.config()).save(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Can't save project", f"Could not write {path}:\n{e}")
            return False
        self.project_path, self.dirty = path, False
        self._remember_dir(path)
        self._add_recent(path)
        self.statusBar().showMessage(f"Saved {path}", 4000)
        self._refresh()
        return True

    # ================================================================== recent, dirs, state

    def _recent(self) -> list[str]:
        return [p for p in (self.store.value("recent", []) or []) if isinstance(p, str)]

    def _add_recent(self, path: str) -> None:
        path = os.path.abspath(path)
        self.store.setValue("recent", ([path] + [p for p in self._recent() if p != path])[:MAX_RECENT])

    def _forget_recent(self, path: str) -> None:
        self.store.setValue("recent", [p for p in self._recent() if p != os.path.abspath(path)])

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        recent = self._recent()
        for path in recent:
            a = self.recent_menu.addAction(os.path.basename(path))
            a.setStatusTip(path)
            a.triggered.connect(lambda checked=False, p=path: self.open_project(p))
        if not recent:
            self.recent_menu.addAction("No recent projects").setEnabled(False)

    def _last_dir(self) -> str:
        return self.store.value("last_dir", os.path.expanduser("~"))

    def _remember_dir(self, path: str) -> None:
        self.store.setValue("last_dir", os.path.dirname(os.path.abspath(path)))

    def _restore_state(self) -> None:
        if (geometry := self.store.value("geometry")) is not None:
            self.restoreGeometry(geometry)
        if (split := self.store.value("splitter")) is not None:
            self.split.restoreState(split)
        try:
            saved = self.store.value("last_settings")
            if saved:
                self.settings.set_config(config_from_dict(json.loads(saved)))
        except (ValueError, TypeError):
            log.warning("ignoring unreadable saved settings")

    def _save_state(self) -> None:
        self.store.setValue("geometry", self.saveGeometry())
        self.store.setValue("splitter", self.split.saveState())
        try:
            self.store.setValue("last_settings", json.dumps(config_to_dict(self.settings.config())))
        except ValueError:
            pass
        self.store.sync()

    # ================================================================== drag & drop

    @staticmethod
    def _dropped_files(event) -> list[str]:
        md = event.mimeData()
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md.hasUrls() else []

    def dragEnterEvent(self, event):
        files = self._dropped_files(event)
        if any(f.lower().endswith(MODEL_EXTENSIONS + (EXTENSION,)) for f in files) and not self.busy():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = self._dropped_files(event)
        projects = [f for f in files if f.lower().endswith(EXTENSION)]
        models = [f for f in files if f.lower().endswith(MODEL_EXTENSIONS)]
        event.acceptProposedAction()
        if projects:
            self.open_project(projects[0])
        elif models:
            self._remember_dir(models[0])
            self.add_models(models)

    # ================================================================== help, close

    def about(self) -> None:
        QMessageBox.about(
            self, "About slicerkit",
            f"<h3>slicerkit {__version__}</h3>"
            "<p>Open-source SLS slicer for the XeroForm printer: 3D models in, "
            "laser tool-paths out.</p>"
            f"<p>Built on PySLM, trimesh and Qt {qVersion()}.</p>")

    def show_log(self) -> None:
        if self.log_path and os.path.exists(self.log_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.log_path))
        else:
            QMessageBox.information(self, "Log file", "Nothing has been logged yet.")

    def closeEvent(self, event) -> None:
        if not self.maybe_save():
            event.ignore()
            return
        self.cancel()
        for t in list(self.tasks):
            t.wait(10000)
        self._save_state()
        super().closeEvent(event)
