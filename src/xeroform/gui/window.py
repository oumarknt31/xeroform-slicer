"""XeroForm main window: a header with the main actions, parts and settings on the left,
the viewer (layers, 3D stack, build layout) with headline numbers on the right.

Models load and slices run on worker threads, so the window never freezes. A
slice stays in memory until exported; changing a part or a setting afterwards
marks it out of date and blocks exporting it. Projects (.xeroform) save the
parts and every setting; the window remembers its layout, theme and settings.
"""

from __future__ import annotations
import logging
import os

from PySide6.QtCore import QRectF, QSettings, QTimer, QUrl, qVersion
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
from ..orient import NO_ROTATION
from ..part import MeshError, prepare_mesh
from ..pipeline import SliceResult, slice_build, slice_job
from ..summary import hms, summary_lines
from . import theme
from .orientation import outline_edges
from .constants import APP_NAME, FLIPBOOK_FPS, MODEL_FILTER, REPO_URL, THEME_ICONS, THEME_NAMES
from .playback import PlaybackMixin
from .projects import ProjectsMixin
from .tasks import Task, collect_garbage_on_gui_thread
from .widgets import Toast, shadow
from .window_ui import WindowLayoutMixin

log = logging.getLogger("xeroform.gui")

__all__ = ["APP_NAME", "MainWindow"]


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

        self.parts.changed.connect(self._changed)
        self.parts.add_requested.connect(self.add_models_dialog)
        self.parts.selection_changed.connect(self.orientation.set_part)
        self.orientation.rotation_changed.connect(self.parts.set_selected_rotation)
        self.settings.changed.connect(self._settings_changed)
        self._restore_state()
        self.dirty = False
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
            self.fit_button,
            self.scan_button,
            self.flip_button,
        ):
            b.setIcon(theme.icon(b.property("iconName")))
        self.theme_button.setIcon(theme.icon(THEME_ICONS[theme.mode()]))
        self.theme_button.setToolTip(f"Theme: {THEME_NAMES[theme.mode()]} (click to change)")
        self.theme_button.setAccessibleName(f"Theme: {THEME_NAMES[theme.mode()]}")
        shadow(self.slice_button, theme.current()["accent"], blur=26, dy=2, alpha=150)
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
        self.orientation.set_scale(self.settings.spins["scale"].value())
        self.orientation.set_layer_thickness(self.settings.spins["layer_thickness"].value())
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
    ) -> Task:
        """Load models in the background and add them to the parts list."""
        copies = copies or [1] * len(paths)
        rotations = rotations or [NO_ROTATION] * len(paths)

        def load(progress):
            out = []
            for i, path in enumerate(paths):
                progress(f"Loading {os.path.basename(path)}", i, len(paths))
                try:
                    mesh, report = prepare_mesh(path, 1.0)  # sizes are shown at the current scale
                    shape = (mesh.convex_hull.vertices, outline_edges(mesh))
                    out.append((path, report, shape, None))
                except MeshError as e:
                    out.append((path, None, None, str(e)))
            return out

        def loaded(results):
            problems = []
            for (path, report, shape, error), n, rotation in zip(results, copies, rotations):
                if error:
                    problems.append(f"{os.path.basename(path)}: {error}")
                else:
                    hull, edges = shape
                    self.parts.add_part(path, report, n, hull=hull, edges=edges, rotation=rotation)
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
        specs = self.parts.job_specs()
        jobs = [path for path, _ in specs]
        rotations = [rotation for _, rotation in specs]
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
                return slice_job(jobs[0], None, config, step, rotation=rotations[0])
            return slice_build(jobs, None, config, progress=step, rotations=rotations)

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
        self.tiles["density"].set(
            f"{result.build.density:.1%}" if result.build else "–", "Part volume / (plate area × build height)"
        )
        self.tiles["energy"].set(
            f"{config.hatch_energy_density:.3f} J/mm²",
            "Fill power / (speed × hatch spacing) - the main number to tune per powder",
        )

    @staticmethod
    def _layout_items(result: SliceResult, jobs: list[str]):
        if result.build is None:
            x0, y0, z0, x1, y1, z1 = result.bounding_box
            return [(QRectF(x0, y0, x1 - x0, y1 - y0), os.path.basename(jobs[0]), f"z {z0:.0f}–{z1:.0f} mm", 0)]
        levels = sorted({round(p.position[2], 3) for p in result.build.placements})
        items = []
        for p in result.build.placements:
            (x, y, z), (sx, sy, sz) = p.position, p.size
            detail = f"z {z:.0f}–{z + sz:.0f} mm" + (" · turned" if p.rotated else "")
            items.append((QRectF(x, y, sx, sy), os.path.basename(jobs[p.item]), detail, levels.index(round(z, 3))))
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
            what = (
                f"{len(layer.contours)} contours ({holes} around holes) · "
                f"{layer.num_hatch_vectors} hatch vectors · {seconds:.1f} s"
            )
        else:
            what = "powder only (gap between stacked parts)"
        self.layer_info.setText(f"Layer {i + 1} of {len(self.result.layers)} · z {layer.z:.3f} mm · {what}")

    def _step(self, delta: int) -> None:
        if self.slider.isEnabled():
            self.slider.setValue(self.slider.value() + delta)

    def _goto(self, i: int) -> None:
        if self.slider.isEnabled():
            self.slider.setValue(min(i, self.slider.maximum()))

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
