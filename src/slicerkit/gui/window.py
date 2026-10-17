"""Main window: parts list + settings on the left, layer view in the middle.

Slicing runs on a worker thread so the window stays responsive; the result is
kept in memory, previewed, and only written to disk on Save.
"""
from __future__ import annotations
import os
from dataclasses import fields

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..config import SliceConfig
from ..nesting import NestingError
from ..part import MeshError, prepare_mesh
from ..pipeline import SliceResult, export, slice_build, slice_job
from ..preview import write_preview
from ..scan_order import SCAN_ORDERS
from ..summary import summary_lines
from .layer_view import LayerView

MODEL_FILTER = "3D models (*.stl *.STL *.obj *.ply *.3mf *.3MF);;All files (*)"

# (SliceConfig field, label, min, max, step, decimals, suffix)
NUMBER_FIELDS = {
    "Slicing": [
        ("layer_thickness", "Layer thickness", 0.01, 5, 0.01, 3, " mm"),
        ("hatch_distance", "Hatch spacing", 0.01, 5, 0.01, 3, " mm"),
        ("hatch_angle", "Hatch angle", -180, 180, 1, 1, " °"),
        ("hatch_angle_increment", "Rotation per layer", -180, 180, 1, 1, " °"),
    ],
    "Laser (placeholders - tune on hardware)": [
        ("hatch_power", "Fill power", 0, 1000, 0.5, 2, " W"),
        ("hatch_speed", "Fill speed", 1, 100000, 50, 0, " mm/s"),
        ("contour_power", "Outline power", 0, 1000, 0.5, 2, " W"),
        ("contour_speed", "Outline speed", 1, 100000, 50, 0, " mm/s"),
        ("jump_speed", "Jump speed", 1, 100000, 100, 0, " mm/s"),
    ],
    "Placement": [
        ("scale", "Scale", 0.001, 10000, 1, 3, "×"),
        ("part_spacing", "Part spacing", 0, 100, 0.5, 1, " mm"),
    ],
}


class _Cancelled(Exception):
    pass


class SliceWorker(QThread):
    progressed = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, jobs: list[str], config: SliceConfig):
        super().__init__()
        self.jobs, self.config = jobs, config
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def _progress(self, done: int, total: int) -> None:
        if self._cancel:
            raise _Cancelled
        self.progressed.emit(done, total)

    def run(self) -> None:
        try:
            if len(self.jobs) == 1:
                result = slice_job(self.jobs[0], None, self.config, self._progress)
            else:
                result = slice_build(self.jobs, None, self.config, progress=self._progress)
            self.succeeded.emit(result)
        except _Cancelled:
            self.failed.emit("Slicing cancelled.")
        except (MeshError, NestingError, ValueError) as e:
            self.failed.emit(str(e))
        except Exception as e:  # keep the window alive; show what happened
            self.failed.emit(f"Unexpected error: {e!r}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("slicerkit")
        self.resize(1280, 820)
        self.result: SliceResult | None = None
        self.result_config: SliceConfig | None = None
        self.worker: SliceWorker | None = None
        self.spins: dict[str, QDoubleSpinBox] = {}

        split = QSplitter()
        split.addWidget(self._build_sidebar())
        split.addWidget(self._build_viewer())
        split.setStretchFactor(1, 1)
        split.setSizes([400, 880])
        self.setCentralWidget(split)
        self._build_menu()
        self._set_busy(False)

    # --- layout ----------------------------------------------------------------

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        for text, key, slot in [
            ("&Add models…", QKeySequence.Open, self.add_models),
            ("&Save .cli…", QKeySequence.Save, self.save_cli),
            ("Save &preview (.html)…", None, self.save_preview),
            ("&Quit", QKeySequence.Quit, self.close),
        ]:
            action = QAction(text, self)
            if key is not None:
                action.setShortcut(key)
            action.triggered.connect(slot)
            file_menu.addAction(action)
            setattr(self, f"action_{slot.__name__}", action)

    def _build_sidebar(self) -> QWidget:
        defaults = SliceConfig()
        box = QWidget()
        col = QVBoxLayout(box)

        parts = QGroupBox("Parts")
        pl = QVBoxLayout(parts)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Model", "Copies", "Size (mm)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(140)
        pl.addWidget(self.table)
        row = QHBoxLayout()
        add, remove = QPushButton("Add…"), QPushButton("Remove")
        add.clicked.connect(self.add_models)
        remove.clicked.connect(self.remove_selected)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        pl.addLayout(row)
        col.addWidget(parts)

        for title, specs in NUMBER_FIELDS.items():
            group = QGroupBox(title)
            form = QFormLayout(group)
            for name, label, lo, hi, step, decimals, suffix in specs:
                spin = QDoubleSpinBox()
                spin.setRange(lo, hi)
                spin.setSingleStep(step)
                spin.setDecimals(decimals)
                spin.setSuffix(suffix)
                spin.setValue(getattr(defaults, name))
                self.spins[name] = spin
                form.addRow(label, spin)
            if title == "Slicing":
                self.scan_order = QComboBox()
                self.scan_order.addItems(SCAN_ORDERS)
                self.scan_order.setCurrentText(defaults.scan_order)
                form.addRow("Scan order", self.scan_order)
            if title == "Placement":
                self.allow_rotation = QCheckBox("Turn parts 90° to fit more")
                self.allow_rotation.setChecked(defaults.allow_rotation)
                form.addRow(self.allow_rotation)
                self.use_volume = QCheckBox("Build volume (needed for several parts)")
                self.use_volume.setChecked(True)
                form.addRow(self.use_volume)
                vol = QHBoxLayout()
                self.volume = []
                for axis in "XYZ":
                    spin = QDoubleSpinBox()
                    spin.setRange(1, 5000)
                    spin.setDecimals(0)
                    spin.setPrefix(f"{axis} ")
                    spin.setValue(150)  # placeholder until the machine is specified
                    self.volume.append(spin)
                    vol.addWidget(spin)
                self.use_volume.toggled.connect(lambda on: [s.setEnabled(on) for s in self.volume])
                form.addRow(vol)
            col.addWidget(group)
        col.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(box)
        scroll.setWidgetResizable(True)

        # Slice, progress and report stay in view below the scrolling settings.
        side = QWidget()
        side.setMinimumWidth(380)
        outer = QVBoxLayout(side)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll, 3)
        row = QHBoxLayout()
        self.slice_button = QPushButton("Slice")
        self.slice_button.setDefault(True)
        self.slice_button.clicked.connect(self.start_slicing)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_slicing)
        row.addWidget(self.slice_button, 1)
        row.addWidget(self.cancel_button)
        outer.addLayout(row)
        self.progress = QProgressBar()
        outer.addWidget(self.progress)

        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("Add a model, then Slice.")
        self.report.setMinimumHeight(140)
        outer.addWidget(self.report, 2)
        return side

    def _build_viewer(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        self.view = LayerView()
        col.addWidget(self.view, 1)
        bar = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._layer_changed)
        self.z_label = QLabel("no layers")
        self.z_label.setMinimumWidth(170)
        bar.addWidget(self.slider, 1)
        bar.addWidget(self.z_label)
        col.addLayout(bar)
        toggles = QHBoxLayout()
        for text, name, on in [("Outlines", "show_contours", True), ("Hatches", "show_hatches", True),
                               ("Travel moves", "show_travel", False), ("Scan order", "scan_order", False)]:
            box = QCheckBox(text)
            box.setChecked(on)
            box.toggled.connect(lambda checked, n=name: self.view.set_option(n, checked))
            toggles.addWidget(box)
        toggles.addStretch()
        hint = QLabel("scroll to zoom · drag to pan · double-click to fit")
        hint.setEnabled(False)
        toggles.addWidget(hint)
        col.addLayout(toggles)
        return w

    # --- parts -----------------------------------------------------------------

    def add_models(self, paths: list[str] | None = None) -> None:
        if not paths:
            paths, _ = QFileDialog.getOpenFileNames(self, "Add models", "", MODEL_FILTER)
        for path in paths:
            try:
                mesh, report = prepare_mesh(path, self.spins["scale"].value())
            except MeshError as e:
                QMessageBox.warning(self, "Can't use this model", str(e))
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            item = QTableWidgetItem(os.path.basename(path))
            item.setData(Qt.UserRole, path)
            item.setToolTip("\n".join([path, *report.repairs, *report.warnings]))
            self.table.setItem(r, 0, item)
            copies = QSpinBox()
            copies.setRange(1, 999)
            self.table.setCellWidget(r, 1, copies)
            x, y, z = report.size
            self.table.setItem(r, 2, QTableWidgetItem(f"{x:.1f} × {y:.1f} × {z:.1f}"))

    def remove_selected(self) -> None:
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def jobs(self) -> list[str]:
        """Every part to print, a path repeated once per copy."""
        out = []
        for r in range(self.table.rowCount()):
            path = self.table.item(r, 0).data(Qt.UserRole)
            out += [path] * self.table.cellWidget(r, 1).value()
        return out

    def config(self) -> SliceConfig:
        values = {name: spin.value() for name, spin in self.spins.items()}
        volume = tuple(s.value() for s in self.volume) if self.use_volume.isChecked() else None
        known = {f.name for f in fields(SliceConfig)}
        return SliceConfig(**{k: v for k, v in values.items() if k in known},
                           scan_order=self.scan_order.currentText(),
                           allow_rotation=self.allow_rotation.isChecked(),
                           build_volume=volume)

    # --- slicing ---------------------------------------------------------------

    def start_slicing(self) -> None:
        jobs = self.jobs()
        if not jobs:
            self.report.setPlainText("Add a model first.")
            return
        try:
            config = self.config()
        except ValueError as e:
            self.report.setPlainText(f"Error: {e}")
            return
        self.worker = SliceWorker(jobs, config)
        self.worker.progressed.connect(self._progressed)
        self.worker.succeeded.connect(lambda result: self._sliced(result, config))
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(lambda: self._set_busy(False))
        self.report.setPlainText(f"Slicing {len(jobs)} part{'s' if len(jobs) > 1 else ''}…")
        self.progress.setRange(0, 0)  # busy until the first layer is done (loading, packing)
        self._set_busy(True)
        self.worker.start()

    def cancel_slicing(self) -> None:
        if self.worker:
            self.worker.cancel()

    def _progressed(self, done: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)

    def _sliced(self, result: SliceResult, config: SliceConfig) -> None:
        self.result, self.result_config = result, config
        self.report.setPlainText("\n".join(summary_lines(result, config)))
        plate = config.build_volume[:2] if config.build_volume else None
        self.view.set_layers(result.layers, plate)
        self.slider.setRange(0, len(result.layers) - 1)
        self.slider.setValue(0)
        self.slider.setEnabled(True)
        self._layer_changed(0)

    def _failed(self, message: str) -> None:
        self.report.setPlainText(f"Error: {message}")

    def _set_busy(self, busy: bool) -> None:
        self.slice_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        if not busy:
            self.progress.setRange(0, 1)
            self.progress.setValue(1 if self.result else 0)
        has_result = self.result is not None and not busy
        self.action_save_cli.setEnabled(has_result)
        self.action_save_preview.setEnabled(has_result)

    def _layer_changed(self, i: int) -> None:
        if not self.result:
            return
        self.view.set_index(i)
        layer = self.result.layers[i]
        self.z_label.setText(f"layer {i + 1} / {len(self.result.layers)} · z {layer.z:.3f} mm")

    # --- saving ----------------------------------------------------------------

    def save_cli(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save laser paths", "build.cli", "CLI (*.cli)")
        if path:
            export(self.result, path, self.result_config)
            self.statusBar().showMessage(f"Saved {path}", 5000)

    def save_preview(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save preview", "preview.html", "HTML (*.html)")
        if path:
            write_preview(self.result.layers, path, title="slicerkit build",
                          jump_speed=self.result_config.jump_speed)
            self.statusBar().showMessage(f"Saved {path}", 5000)

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)
        super().closeEvent(event)
