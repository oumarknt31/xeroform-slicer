"""Sidebar panels: the parts to print, and every slicing setting."""
from __future__ import annotations
import os
from dataclasses import fields

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QPushButton, QSpinBox, QStyle, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..config import SliceConfig
from ..part import HUGE_MM, TINY_MM, MeshReport
from ..project import ProjectPart
from ..scan_order import SCAN_ORDERS

PLACEHOLDER_VOLUME = (150.0, 150.0, 150.0)  # until the machine's build volume is known


def gui_defaults() -> SliceConfig:
    """SliceConfig defaults, with the placeholder build volume on so packing works."""
    return SliceConfig(build_volume=PLACEHOLDER_VOLUME)

# (SliceConfig field, label, min, max, step, decimals, suffix, tooltip)
NUMBER_FIELDS = {
    "Slicing": [
        ("layer_thickness", "Layer thickness", 0.01, 5, 0.01, 3, " mm",
         "Height of one powder layer. Thinner layers give finer detail but more layers to print."),
        ("hatch_distance", "Hatch spacing", 0.01, 5, 0.01, 3, " mm",
         "Distance between fill lines. Keep it below the laser spot size so lines overlap."),
        ("hatch_angle", "Hatch angle", -180, 180, 1, 1, " °",
         "Fill direction on the first layer (PySLM convention: lines run at this angle + 90°)."),
        ("hatch_angle_increment", "Rotation per layer", -180, 180, 1, 1, " °",
         "Added to the fill direction on every layer, to spread heat and stress. 0 = fixed."),
    ],
    "Laser": [
        ("hatch_power", "Fill power", 0, 1000, 0.5, 2, " W", "Laser power while filling."),
        ("hatch_speed", "Fill speed", 1, 100000, 50, 0, " mm/s", "Scan speed while filling."),
        ("contour_power", "Outline power", 0, 1000, 0.5, 2, " W", "Laser power on part outlines."),
        ("contour_speed", "Outline speed", 1, 100000, 50, 0, " mm/s", "Scan speed on part outlines."),
        ("jump_speed", "Jump speed", 1, 100000, 100, 0, " mm/s",
         "Speed of laser-off moves between lines. Used for the time estimate."),
    ],
    "Placement": [
        ("scale", "Scale", 0.001, 10000, 1, 3, " ×",
         "Multiply every model by this. Use 25.4 for models drawn in inches."),
        ("part_spacing", "Part spacing", 0, 100, 0.5, 1, " mm",
         "Gap kept between packed parts and to the chamber walls."),
    ],
}


class PartsPanel(QGroupBox):
    """The models to print, with a copy count each. Emits `changed` on any edit."""

    changed = Signal()
    add_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("Parts", parent)
        self.scale = 1.0
        col = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "Model", "Copies", "Size (mm)"])
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        head.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(150)
        self.table.setToolTip("Drop model files here or use Add…")
        col.addWidget(self.table)
        QShortcut(QKeySequence.Delete, self.table, self.remove_selected)
        QShortcut(QKeySequence(Qt.Key_Backspace), self.table, self.remove_selected)

        row = QHBoxLayout()
        add, remove, clear = QPushButton("Add…"), QPushButton("Remove"), QPushButton("Clear")
        add.clicked.connect(self.add_requested)
        remove.clicked.connect(self.remove_selected)
        clear.clicked.connect(self.clear)
        for b in (add, remove, clear):
            row.addWidget(b)
        row.addStretch()
        col.addLayout(row)

    # --- rows ------------------------------------------------------------------

    def add_part(self, path: str, report: MeshReport, copies: int = 1) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        name = QTableWidgetItem(os.path.basename(path))
        name.setData(Qt.UserRole, (path, report))
        self.table.setItem(r, 0, QTableWidgetItem())
        self.table.setItem(r, 1, name)
        spin = QSpinBox()
        spin.setRange(1, 999)
        spin.setValue(copies)
        spin.setToolTip("How many copies of this model to pack into the build")
        spin.valueChanged.connect(self.changed)
        self.table.setCellWidget(r, 2, spin)
        self.table.setItem(r, 3, QTableWidgetItem())
        self._refresh_row(r)
        self.changed.emit()

    def set_scale(self, scale: float) -> None:
        self.scale = scale
        for r in range(self.table.rowCount()):
            self._refresh_row(r)

    def _refresh_row(self, r: int) -> None:
        path, report = self.table.item(r, 1).data(Qt.UserRole)
        x, y, z = (v * self.scale for v in report.size)
        self.table.item(r, 3).setText(f"{x:.1f} × {y:.1f} × {z:.1f}")
        notes = list(report.repairs) + list(report.warnings)
        largest = max(x, y, z)
        if largest < TINY_MM:
            notes.append(f"Only {largest:.3g} mm across at this scale - check the units "
                         "(inches: scale 25.4).")
        elif largest > HUGE_MM:
            notes.append(f"{largest:.0f} mm across at this scale - check the units.")
        warn = bool(report.warnings) or largest < TINY_MM or largest > HUGE_MM
        icon = self.style().standardIcon(QStyle.SP_MessageBoxWarning if warn else QStyle.SP_DialogApplyButton)
        status = self.table.item(r, 0)
        status.setIcon(icon)
        tip = "\n".join([path, *notes]) if notes else f"{path}\nNo problems found."
        status.setToolTip(tip)
        self.table.item(r, 1).setToolTip(tip)

    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        if rows:
            self.changed.emit()

    def clear(self) -> None:
        if self.table.rowCount():
            self.table.setRowCount(0)
            self.changed.emit()

    # --- what to print -----------------------------------------------------------

    def parts(self) -> list[ProjectPart]:
        return [ProjectPart(self.table.item(r, 1).data(Qt.UserRole)[0], self.table.cellWidget(r, 2).value())
                for r in range(self.table.rowCount())]

    def jobs(self) -> list[str]:
        """Every part to print, a path repeated once per copy."""
        return [p.path for p in self.parts() for _ in range(p.copies)]


class SettingsPanel(QWidget):
    """Every SliceConfig setting, with tooltips. Emits `changed` on any edit."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.spins: dict[str, QDoubleSpinBox] = {}
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        for title, specs in NUMBER_FIELDS.items():
            group = QGroupBox(title + (" - placeholders until the laser is chosen" if title == "Laser" else ""))
            form = QFormLayout(group)
            for name, label, lo, hi, step, decimals, suffix, tip in specs:
                spin = QDoubleSpinBox()
                spin.setRange(lo, hi)
                spin.setSingleStep(step)
                spin.setDecimals(decimals)
                spin.setSuffix(suffix)
                spin.setToolTip(tip)
                spin.setKeyboardTracking(False)  # one change per edit, not per keystroke
                spin.valueChanged.connect(self.changed)
                self.spins[name] = spin
                form.addRow(label, spin)
                form.labelForField(spin).setToolTip(tip)
            if title == "Slicing":
                self.scan_order = QComboBox()
                self.scan_order.addItems(SCAN_ORDERS)
                self.scan_order.setToolTip(
                    "Order of the fill lines. nearest: least laser-off travel (default). "
                    "meander: zig-zag across the layer. raster: all one direction.")
                self.scan_order.currentTextChanged.connect(self.changed)
                form.addRow("Scan order", self.scan_order)
            if title == "Placement":
                self.allow_rotation = QCheckBox("Turn parts 90° to fit more")
                self.allow_rotation.setToolTip("Let the packer turn parts about Z. Parts are never tipped over.")
                self.allow_rotation.toggled.connect(self.changed)
                form.addRow(self.allow_rotation)
                self.use_volume = QCheckBox("Build volume")
                self.use_volume.setToolTip("Printable size of the machine. Needed to pack several parts; "
                                           "150 mm is a placeholder until the machine is specified.")
                self.use_volume.toggled.connect(self._volume_toggled)
                vol = QHBoxLayout()
                self.volume = []
                for axis in "XYZ":
                    spin = QDoubleSpinBox()
                    spin.setRange(1, 5000)
                    spin.setDecimals(0)
                    spin.setPrefix(f"{axis} ")
                    spin.setSuffix(" mm")
                    spin.setKeyboardTracking(False)
                    spin.valueChanged.connect(self.changed)
                    self.volume.append(spin)
                    vol.addWidget(spin)
                form.addRow(self.use_volume)
                form.addRow(vol)
            col.addWidget(group)
        reset = QPushButton("Reset to defaults")
        reset.setToolTip("Put every setting back to its default")
        reset.clicked.connect(lambda: self.set_config(gui_defaults()))
        col.addWidget(reset, 0, Qt.AlignLeft)
        self.set_config(gui_defaults())

    def _volume_toggled(self, on: bool) -> None:
        for s in self.volume:
            s.setEnabled(on)
        self.changed.emit()

    def config(self) -> SliceConfig:
        """The settings as a SliceConfig. Raises ValueError if they don't make sense."""
        known = {f.name for f in fields(SliceConfig)}
        values = {k: s.value() for k, s in self.spins.items() if k in known}
        volume = tuple(s.value() for s in self.volume) if self.use_volume.isChecked() else None
        return SliceConfig(**values, scan_order=self.scan_order.currentText(),
                           allow_rotation=self.allow_rotation.isChecked(), build_volume=volume)

    def set_config(self, config: SliceConfig) -> None:
        self.blockSignals(True)
        try:
            for name, spin in self.spins.items():
                spin.setValue(getattr(config, name))
            self.scan_order.setCurrentText(config.scan_order)
            self.allow_rotation.setChecked(config.allow_rotation)
            self.use_volume.setChecked(config.build_volume is not None)
            for spin, v in zip(self.volume, config.build_volume or PLACEHOLDER_VOLUME):
                spin.setValue(v)
            for s in self.volume:
                s.setEnabled(config.build_volume is not None)
        finally:
            self.blockSignals(False)
        self.changed.emit()
