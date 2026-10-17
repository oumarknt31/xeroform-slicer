"""Main window: a header with the main actions, parts and settings on the left,
the viewer (layers, 3D stack, build layout) with headline numbers on the right.

Models load and slices run on worker threads, so the window never freezes. A
slice stays in memory until exported; changing a part or a setting afterwards
marks it out of date and blocks exporting it. Projects (.slicerkit) save the
parts and every setting; the window remembers its layout, theme and settings.
"""
from __future__ import annotations
import json
import logging
import os

from PySide6.QtCore import QRectF, QSettings, Qt, QTimer, QUrl, qVersion
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider, QSplitter, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .. import __version__
from ..laser import estimate_scan_time, layer_scan_time
from ..part import MeshError, prepare_mesh
from ..pipeline import SliceResult, export, slice_build, slice_job
from ..preview import write_preview
from ..project import EXTENSION, Project, ProjectError, config_from_dict, config_to_dict
from ..summary import hms, summary_lines
from . import theme
from .panels import PartsPanel, SettingsPanel, gui_defaults
from .tasks import Task
from .views import LayerView, LayoutView, StackView
from .widgets import Card, EmptyState, Segmented, StatTile, Toast, chip, tool_button

log = logging.getLogger("slicerkit.gui")

MODEL_EXTENSIONS = (".stl", ".obj", ".ply", ".3mf", ".off", ".glb")
MODEL_FILTER = "3D models (*.stl *.STL *.obj *.ply *.3mf *.3MF);;All files (*)"
PROJECT_FILTER = f"slicerkit project (*{EXTENSION})"
MAX_RECENT = 8
FLIPBOOK_FPS = 24
THEME_ICONS = {"system": "auto", "light": "sun", "dark": "moon"}


def _keep_space(widget) -> None:
    """Keep a widget's space when it is hidden, so the layout doesn't jump."""
    policy = widget.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(policy)


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
        self._themed: list = []  # widgets with a restyle() to call on theme change

        self.setAcceptDrops(True)
        self.resize(1400, 900)
        self.setMinimumSize(1000, 640)
        root = QWidget()
        root.setObjectName("root")
        col = QVBoxLayout(root)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._build_header())
        self.split = QSplitter()
        self.split.setContentsMargins(12, 12, 12, 12)
        self.split.addWidget(self._build_sidebar())
        self.split.addWidget(self._build_main())
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([400, 1000])
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

        self.parts.changed.connect(self._changed)
        self.parts.add_requested.connect(self.add_models_dialog)
        self.settings.changed.connect(self._settings_changed)
        self._restore_state()
        self.dirty = False
        self._refresh()

    # ===================================================================== layout

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("header")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(6)
        logo = QLabel()
        logo.setPixmap(theme.app_icon().pixmap(30, 30))
        row.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title_label = QLabel("Untitled")
        self.title_label.setObjectName("appTitle")
        self.subtitle_label = QLabel("slicerkit")
        self.subtitle_label.setObjectName("hint")
        titles.addWidget(self.title_label)
        titles.addWidget(self.subtitle_label)
        row.addLayout(titles)
        row.addSpacing(18)

        self.open_button = tool_button("open", "Open", "Open a project (⌘O)")
        self.open_button.clicked.connect(lambda: self.open_project())
        self.save_button = tool_button("save", "Save", "Save the project (⌘S)")
        self.save_button.clicked.connect(self.save_project)
        self.header_add = tool_button("add", "Add models", "Add models (⌘I)")
        self.header_add.clicked.connect(self.add_models_dialog)
        for b in (self.open_button, self.save_button, self.header_add):
            row.addWidget(b)
        row.addStretch()

        self.theme_button = tool_button("auto", "", "Theme: follow the system")
        self.theme_button.clicked.connect(self._cycle_theme)
        row.addWidget(self.theme_button)
        self.export_button = QPushButton("Export")
        self.export_button.setToolTip("Write the laser paths for the machine (⌘E)")
        self.export_button.clicked.connect(self.export_cli)
        row.addWidget(self.export_button)
        self.slice_button = QPushButton("Slice")
        self.slice_button.setObjectName("primary")
        self.slice_button.setToolTip("Slice all parts (⌘R)")
        self.slice_button.setMinimumWidth(110)
        self.slice_button.clicked.connect(self.start_slicing)
        row.addWidget(self.slice_button)
        return bar

    def _build_sidebar(self) -> QWidget:
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(10)
        self.parts = PartsPanel()
        self.settings = SettingsPanel()
        self._themed += [self.parts, self.settings]
        col.addWidget(self.parts)
        col.addWidget(self.settings)
        col.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        side = QWidget()
        side.setMinimumWidth(380)
        side.setMaximumWidth(560)
        outer = QVBoxLayout(side)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        outer.addWidget(scroll, 1)

        self.progress_card = QFrame()
        self.progress_card.setObjectName("card")
        pc = QVBoxLayout(self.progress_card)
        pc.setContentsMargins(14, 10, 14, 10)
        top = QHBoxLayout()
        self.stage = QLabel("Working…")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        top.addWidget(self.stage, 1)
        top.addWidget(self.cancel_button)
        pc.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        pc.addWidget(self.progress)
        self.progress_card.hide()
        outer.addWidget(self.progress_card)
        return side

    def _build_main(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(6, 0, 0, 0)
        col.setSpacing(10)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 8, 8, 8)
        self.banner_icon = QLabel()
        text = QLabel("Parts or settings changed since this slice. The view is out of date "
                      "and can't be exported.")
        text.setWordWrap(True)
        again = QPushButton("Slice again")
        again.setObjectName("primary")
        again.clicked.connect(self.start_slicing)
        bl.addWidget(self.banner_icon)
        bl.addWidget(text, 1)
        bl.addWidget(again)
        self.banner.hide()
        col.addWidget(self.banner)

        viewer = QFrame()
        viewer.setObjectName("card")
        vc = QVBoxLayout(viewer)
        vc.setContentsMargins(12, 10, 12, 10)
        vc.setSpacing(8)

        top = QHBoxLayout()
        self.view_switch = Segmented([("Layers", "slice"), ("3D", "cube"), ("Build layout", "layout")])
        self.view_switch.changed.connect(self._view_changed)
        self._themed.append(self.view_switch)
        top.addWidget(self.view_switch)
        top.addStretch()
        self.chips = {}
        for text, name, on, tip in [("Outlines", "show_contours", True, "Part outlines (holes in blue)"),
                                    ("Hatches", "show_hatches", True, "Fill lines"),
                                    ("Travel", "show_travel", False, "Laser-off moves between lines"),
                                    ("Scan order", "scan_order", False, "Colour the fill from first (yellow) "
                                                                         "to last (purple)"),
                                    ("Grid", "show_grid", True, "mm grid")]:
            c = chip(text, on, tip)
            c.toggled.connect(lambda checked, n=name: self._set_view_option(n, checked))
            _keep_space(c)
            self.chips[name] = c
            top.addWidget(c)
        self.fit_button = tool_button("fit", "", "Fit the view (⌘0)")
        self.fit_button.clicked.connect(self._fit_views)
        top.addWidget(self.fit_button)
        vc.addLayout(top)

        # views + the vertical layer slider, or an empty state before the first slice
        self.pages = QStackedWidget()
        self.empty = EmptyState("drop", "Drop models here",
                                "STL, OBJ, PLY or 3MF. Or open a project.", "Add models")
        self.empty.button.clicked.connect(self.add_models_dialog)
        self._themed.append(self.empty)
        self.pages.addWidget(self.empty)

        stage = QWidget()
        sl = QHBoxLayout(stage)
        sl.setContentsMargins(0, 0, 0, 0)
        self.views = QStackedWidget()
        self.view = LayerView()
        self.stack_view = StackView()
        self.layout_view = LayoutView()
        for v in (self.view, self.stack_view, self.layout_view):
            self.views.addWidget(v)
        sl.addWidget(self.views, 1)
        rail = QVBoxLayout()
        rail.setSpacing(4)
        self.top_z = QLabel()
        self.top_z.setObjectName("hint")
        self.top_z.setAlignment(Qt.AlignHCenter)
        self.slider = QSlider(Qt.Vertical)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._layer_changed)
        self.bottom_z = QLabel()
        self.bottom_z.setObjectName("hint")
        self.bottom_z.setAlignment(Qt.AlignHCenter)
        rail.addWidget(self.top_z)
        rail.addWidget(self.slider, 1, Qt.AlignHCenter)
        rail.addWidget(self.bottom_z)
        for part in (self.top_z, self.slider, self.bottom_z):
            _keep_space(part)
        sl.addLayout(rail)
        self.pages.addWidget(stage)
        vc.addWidget(self.pages, 1)

        bottom = QHBoxLayout()
        self.scan_button = tool_button("laser", "Play laser", "Animate the laser tracing this layer")
        self.scan_button.clicked.connect(self._toggle_scan)
        self.flip_button = tool_button("film", "Play layers", "Play through the layers like a flip-book")
        self.flip_button.clicked.connect(self._toggle_flipbook)
        self.view.playback_changed.connect(self._scan_state)
        _keep_space(self.scan_button)
        bottom.addWidget(self.scan_button)
        bottom.addWidget(self.flip_button)
        bottom.addSpacing(8)
        self.layer_info = QLabel("No slice yet.")
        self.layer_info.setObjectName("muted")
        self.layer_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bottom.addWidget(self.layer_info, 1)
        hint = QLabel("← → layer · PgUp/PgDn ±10")
        hint.setObjectName("hint")
        bottom.addWidget(hint)
        vc.addLayout(bottom)
        col.addWidget(viewer, 1)

        tiles = QGridLayout()
        tiles.setSpacing(10)
        self.tiles = {}
        for i, (key, label) in enumerate([("layers", "Layers"), ("height", "Build height"),
                                          ("time", "Laser time"), ("parts", "Parts"),
                                          ("density", "Packing"), ("energy", "Energy density")]):
            tile = StatTile(label)
            self.tiles[key] = tile
            tiles.addWidget(tile, 0, i)
        col.addLayout(tiles)

        self.details = Card("Details")
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("The slicing report appears here.")
        self.report.setMinimumHeight(110)
        self.report.setMaximumHeight(170)
        self.details.body.addWidget(self.report)
        self.details.header.setChecked(False)
        self._themed.append(self.details)
        col.addWidget(self.details)

        # keyboard: step through layers while the viewer has focus
        for keys, step in [((Qt.Key_Right, Qt.Key_Up), 1), ((Qt.Key_Left, Qt.Key_Down), -1),
                           ((Qt.Key_PageUp,), 10), ((Qt.Key_PageDown,), -10)]:
            for key in keys:
                QShortcut(QKeySequence(key), viewer, lambda s=step: self._step(s),
                          context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence(Qt.Key_Home), viewer, lambda: self._goto(0), context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence(Qt.Key_End), viewer, lambda: self._goto(10 ** 9),
                  context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence(Qt.Key_Space), viewer, self._toggle_scan, context=Qt.WidgetWithChildrenShortcut)
        return w

    def _build_menus(self) -> None:
        def action(text, slot, shortcut=None):
            a = QAction(text, self)
            if shortcut is not None:
                a.setShortcut(shortcut)
            a.triggered.connect(slot)
            self.addAction(a)  # shortcuts work with the menu bar hidden too
            return a

        self.act_new = action("&New Project", self.new_project, QKeySequence.New)
        self.act_open = action("&Open Project…", lambda: self.open_project(), QKeySequence.Open)
        self.act_save = action("&Save Project", self.save_project, QKeySequence.Save)
        self.act_save_as = action("Save Project &As…", self.save_project_as, QKeySequence.SaveAs)
        self.act_add = action("&Add Models…", self.add_models_dialog, QKeySequence("Ctrl+I"))
        self.act_slice = action("S&lice", self.start_slicing, QKeySequence("Ctrl+R"))
        self.act_export = action("&Export Laser Paths (.cli)…", self.export_cli, QKeySequence("Ctrl+E"))
        self.act_preview = action("Export &Preview (.html)…", self.export_preview)
        self.act_quit = action("&Quit", self.close, QKeySequence.Quit)
        self.act_fit = action("&Fit View", self._fit_views, QKeySequence("Ctrl+0"))
        self.act_about = action("&About slicerkit", self.about)
        self.act_log = action("Show &Log File", self.show_log)

        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
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
        bar.addMenu("&Build").addAction(self.act_slice)
        view_menu = bar.addMenu("&View")
        view_menu.addAction(self.act_fit)
        theme_menu = view_menu.addMenu("&Theme")
        for mode in theme.MODES:
            theme_menu.addAction(mode.capitalize(), lambda m=mode: self.set_theme(m))
        help_menu = bar.addMenu("&Help")
        help_menu.addActions([self.act_about, self.act_log])

    # ================================================================ theme

    def set_theme(self, mode: str) -> None:
        theme.apply(QApplication.instance(), mode)
        self.store.setValue("theme", theme.mode())
        self._restyle()

    def _cycle_theme(self) -> None:
        modes = theme.MODES
        self.set_theme(modes[(modes.index(theme.mode()) + 1) % len(modes)])
        self.toast(f"Theme: {theme.mode()}", THEME_ICONS[theme.mode()])

    def _restyle(self) -> None:
        """Re-tint icons and redraw views after a theme change."""
        for w in self._themed:
            w.restyle()
        for b in (self.open_button, self.save_button, self.header_add, self.fit_button,
                  self.scan_button, self.flip_button):
            b.setIcon(theme.icon(b.property("iconName")))
        self.theme_button.setIcon(theme.icon(THEME_ICONS[theme.mode()]))
        self.theme_button.setToolTip(f"Theme: {theme.mode()} (click to change)")
        self.banner_icon.setPixmap(theme.icon("warning", theme.current()["warn_text"]).pixmap(18, 18))
        self._scan_state(self.view.playing())
        for v in (self.view, self.stack_view, self.layout_view):
            v.update()

    def toast(self, text: str, icon_name: str = "ok") -> None:
        Toast(self.centralWidget(), text, icon_name)

    # ================================================================ state + UI

    def busy(self) -> bool:
        return any(t.isRunning() for t in self.tasks)

    def _refresh(self) -> None:
        """Bring title, banner, empty state and enabled actions in line with the state."""
        name = os.path.splitext(os.path.basename(self.project_path))[0] if self.project_path else "Untitled"
        self.setWindowTitle(f"{name}[*] — slicerkit")
        self.setWindowModified(self.dirty)
        self.title_label.setText(name + (" •" if self.dirty else ""))
        self.subtitle_label.setText(self.project_path or "Not saved yet")
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
        self.banner.setVisible(self.result is not None and self.stale and not slicing)
        self.progress_card.setVisible(busy)
        has_result = self.result is not None
        for w in (self.scan_button, self.flip_button):
            w.setEnabled(has_result)
        if has_result:
            self.pages.setCurrentIndex(1)
        else:
            self.pages.setCurrentIndex(0)
            if self.parts.parts():
                self.empty.set_text("Ready to slice", "Check the settings on the left, then press Slice (⌘R).")
                self.empty.button.hide()
            else:
                self.empty.set_text("Drop models here", "STL, OBJ, PLY or 3MF. Or open a project.")
                self.empty.button.show()

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

    def _view_changed(self, i: int) -> None:
        self.views.setCurrentIndex(i)
        layer_only = i == 0
        for name, c in self.chips.items():
            c.setVisible(layer_only or (name == "show_grid" and i == 2))
        self.scan_button.setVisible(layer_only)
        for part in (self.top_z, self.slider, self.bottom_z):  # layers don't apply to the layout
            part.setVisible(i != 2)
        if not layer_only:
            self.view.stop_scan()

    def _fit_views(self) -> None:
        for v in (self.view, self.layout_view):
            v.refresh_bounds()
        self.stack_view.reset_view()

    # ================================================================== tasks

    def _run(self, task: Task, on_success, what: str) -> Task:
        task.progressed.connect(self._progress)
        task.succeeded.connect(on_success)
        task.failed.connect(lambda message, details: self._failed(what, message, details))
        task.finished.connect(lambda: (self.tasks.discard(task), self._refresh()))
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
            box.setInformativeText("This looks like a bug. The details are also in the log file "
                                   "(Help ▸ Show Log File).")
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
            added = len(results) - len(problems)
            if added:
                self.toast(f"Added {added} model{'s' if added != 1 else ''}.")
            if then:
                then()

        return self._run(Task(load), loaded, "Loading models")

    # ================================================================== slicing

    def start_slicing(self) -> Task | None:
        if self.busy():
            return None
        jobs = self.parts.jobs()
        if not jobs:
            self.toast("Add a model first.", "warning")
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

        self._stop_playback()
        self.report.setPlainText(f"Slicing {len(jobs)} part{'s' if len(jobs) > 1 else ''}…")
        self.slicing = self._run(Task(run), lambda r: self._sliced(r, jobs, config), "Slicing")
        return self.slicing

    def _sliced(self, result: SliceResult, jobs: list[str], config) -> None:
        self.result, self.result_jobs, self.result_config, self.stale = result, jobs, config, False
        self.report.setPlainText("\n".join(summary_lines(result, config)))
        plate = config.build_volume[:2] if config.build_volume else None
        self.view.set_layers(result.layers, plate)
        self.stack_view.set_layers(result.layers)
        self.layout_view.set_items(self._layout_items(result, jobs), plate)
        self.slider.setRange(0, len(result.layers) - 1)
        self.slider.setValue(0)
        self.slider.setEnabled(True)
        self.top_z.setText(f"{result.layers[-1].z:.1f}")
        self.bottom_z.setText(f"{result.layers[0].z:.1f}")
        self._layer_changed(0)
        self._fill_tiles(result, jobs, config)
        self._refresh()
        self.toast(f"Sliced {len(result.layers)} layers.")

    def _fill_tiles(self, result: SliceResult, jobs: list[str], config) -> None:
        seconds = estimate_scan_time(result.layers, config.jump_speed)
        height = result.bounding_box[5] if result.bounding_box else 0
        self.tiles["layers"].set(f"{len(result.layers):,}", f"{config.layer_thickness:g} mm each")
        self.tiles["height"].set(f"{height:.1f} mm")
        self.tiles["time"].set(hms(seconds), "Laser scanning only - recoating and heating not included")
        self.tiles["parts"].set(str(len(jobs)))
        self.tiles["density"].set(f"{result.build.density:.1%}" if result.build else "–",
                                  "Part volume / (plate area × build height)")
        self.tiles["energy"].set(f"{config.hatch_energy_density:.3f} J/mm²",
                                 "Fill power / (speed × hatch spacing) - the main number to tune per powder")

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
        self.stack_view.set_index(i)
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

    # ================================================================== playback

    def _toggle_scan(self) -> None:
        if not self.result:
            return
        if self.view.playing():
            self.view.stop_scan()
        else:
            self.flipbook.stop()
            self._flip_state()
            self.view_switch.set_index(0)
            self.view.play_scan()

    def _scan_state(self, playing: bool) -> None:
        self.scan_button.setText("Stop laser" if playing else "Play laser")
        self.scan_button.setIcon(theme.icon("stop" if playing else "laser"))
        self.scan_button.setProperty("iconName", "stop" if playing else "laser")

    def _toggle_flipbook(self) -> None:
        if not self.result:
            return
        if self.flipbook.isActive():
            self.flipbook.stop()
        else:
            self.view.stop_scan()
            if self.slider.value() >= self.slider.maximum():
                self.slider.setValue(0)
            self.flipbook.start()
        self._flip_state()

    def _flip(self) -> None:
        if self.slider.value() >= self.slider.maximum():
            self.flipbook.stop()
            self._flip_state()
        else:
            self._step(1)

    def _flip_state(self) -> None:
        on = self.flipbook.isActive()
        self.flip_button.setText("Pause layers" if on else "Play layers")
        self.flip_button.setIcon(theme.icon("pause" if on else "film"))
        self.flip_button.setProperty("iconName", "pause" if on else "film")

    def _stop_playback(self) -> None:
        self.view.stop_scan()
        self.flipbook.stop()
        self._flip_state()

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
        self.toast(f"Exported {os.path.basename(path)}", "export")

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
        self.toast(f"Exported {os.path.basename(path)}", "export")

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
        self._stop_playback()
        self.parts.clear()
        self.result, self.result_jobs, self.stale = None, [], False
        self.view.set_layers([], None)
        self.stack_view.set_layers([])
        self.layout_view.set_items([], None)
        self.slider.setEnabled(False)
        self.top_z.setText("")
        self.bottom_z.setText("")
        self.layer_info.setText("No slice yet.")
        self.report.clear()
        for tile in self.tiles.values():
            tile.set("–")

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
        self.toast(f"Saved {os.path.basename(path)}", "save")
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
            a.setToolTip(path)
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
        theme.apply(QApplication.instance(), self.store.value("theme", "system"))
        self._restyle()
        try:
            saved = self.store.value("last_settings")
            if saved:
                self.settings.set_config(config_from_dict(json.loads(saved)))
        except (ValueError, TypeError):
            log.warning("ignoring unreadable saved settings")

    def _save_state(self) -> None:
        self.store.setValue("geometry", self.saveGeometry())
        self.store.setValue("splitter", self.split.saveState())
        self.store.setValue("theme", theme.mode())
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
        self._stop_playback()
        self.cancel()
        for t in list(self.tasks):
            t.wait(10000)
        self._save_state()
        super().closeEvent(event)
