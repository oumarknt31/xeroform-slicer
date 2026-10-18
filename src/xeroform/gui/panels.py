"""Sidebar panels: the parts to print, and every slicing setting."""

from __future__ import annotations
import os
from dataclasses import dataclass, field, fields

import numpy as np
import trimesh

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import SliceConfig
from ..nesting import Spot
from ..orient import NO_ROTATION, Angles, extents
from ..part import HUGE_MM, TINY_MM, MeshReport
from ..project import ProjectPart
from ..scan_order import SCAN_ORDERS
from ..summary import describe_settings
from . import theme
from .widgets import Card, tool_button

PLACEHOLDER_VOLUME = (150.0, 150.0, 150.0)  # until the machine's build volume is known


def gui_defaults() -> SliceConfig:
    """SliceConfig defaults, with the placeholder build volume on so packing works."""
    return SliceConfig(build_volume=PLACEHOLDER_VOLUME)


# (SliceConfig field, label, min, max, step, decimals, suffix, tooltip)
NUMBER_FIELDS = {
    "Slicing": [
        (
            "layer_thickness",
            "Layer thickness",
            0.01,
            5,
            0.01,
            3,
            " mm",
            "Height of one powder layer. Thinner layers give finer detail but more layers to print.",
        ),
        (
            "hatch_distance",
            "Hatch spacing",
            0.01,
            5,
            0.01,
            3,
            " mm",
            "Distance between fill lines. Keep it below the laser spot size so lines overlap.",
        ),
        (
            "hatch_angle",
            "Hatch angle",
            -180,
            180,
            1,
            1,
            " °",
            "Fill direction on the first layer (PySLM convention: lines run at this angle + 90°).",
        ),
        (
            "hatch_angle_increment",
            "Rotation per layer",
            -180,
            180,
            1,
            1,
            " °",
            "Added to the fill direction on every layer, to spread heat and stress. 0 = fixed.",
        ),
    ],
    "Laser": [
        ("hatch_power", "Fill power", 0, 1000, 0.5, 2, " W", "Laser power while filling."),
        ("hatch_speed", "Fill speed", 1, 100000, 50, 0, " mm/s", "Scan speed while filling."),
        ("contour_power", "Outline power", 0, 1000, 0.5, 2, " W", "Laser power on part outlines."),
        ("contour_speed", "Outline speed", 1, 100000, 50, 0, " mm/s", "Scan speed on part outlines."),
        (
            "jump_speed",
            "Jump speed",
            1,
            100000,
            100,
            0,
            " mm/s",
            "Speed of laser-off moves between lines. Used for the time estimate.",
        ),
    ],
    "Placement": [
        (
            "scale",
            "Scale",
            0.001,
            10000,
            1,
            3,
            " ×",
            "Multiply every model by this. Use 25.4 for models drawn in inches.",
        ),
        (
            "part_spacing",
            "Part spacing",
            0,
            100,
            0.5,
            1,
            " mm",
            "Gap kept between packed parts and to the chamber walls.",
        ),
    ],
}


@dataclass(eq=False)
class PartInfo:
    """One model in the parts list, as loaded (unscaled, in the file's orientation),
    with what the user chose for it."""

    path: str
    report: MeshReport
    hull: np.ndarray | None = None  # convex hull vertices, for instant size and orientation
    edges: np.ndarray | None = None  # (E, 2, 3) outline edges for the preview
    rotation: Angles = NO_ROTATION
    mesh: trimesh.Trimesh | None = None  # repaired, on the plate: for laying the build out
    display: trimesh.Trimesh | None = None  # a lighter copy, for drawing
    settings: dict = field(default_factory=dict)  # its own values (config.PART_SETTINGS)
    spots: list[Spot] = field(default_factory=list)  # where each copy is on the plate

    def size(self, scale: float = 1.0) -> np.ndarray:
        """Size (x, y, z) in mm at this scale and orientation."""
        if self.hull is None:
            return np.asarray(self.report.size) * scale
        return extents(self.hull, self.rotation) * scale


class PartsPanel(Card):
    """The models to print, with a copy count and orientation each.

    Emits `changed` on any edit and `selection_changed` with the selected part.
    """

    changed = Signal()
    add_requested = Signal()
    selection_changed = Signal(object)  # PartInfo or None

    def __init__(self, parent=None):
        super().__init__("Parts", collapsible=False, parent=parent)
        self.scale = 1.0
        col = self.body
        self.count = QLabel()
        self.count.setObjectName("hint")
        self.trailing.addWidget(self.count)
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
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.ClickFocus)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setToolTip("Drop model files on the window or use Add")
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(lambda: self.selection_changed.emit(self.selected()))
        col.addWidget(self.table)
        self.empty_hint = QLabel("No models yet.\nDrop STL, OBJ, PLY or 3MF files on the window,\nor click Add models.")
        self.empty_hint.setObjectName("hint")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setMinimumHeight(110)
        col.addWidget(self.empty_hint)
        QShortcut(QKeySequence.Delete, self.table, self.remove_selected)
        QShortcut(QKeySequence(Qt.Key_Backspace), self.table, self.remove_selected)

        row = QHBoxLayout()
        self.add_button = tool_button("add", "Add models", "Add STL, OBJ, PLY or 3MF models (⌘I)")
        self.remove_button = tool_button("trash", "Remove", "Remove the selected models (Delete)")
        self.clear_button = tool_button("clear", "Clear", "Remove all models")
        self.add_button.clicked.connect(self.add_requested)
        self.remove_button.clicked.connect(self.remove_selected)
        self.clear_button.clicked.connect(self.clear)
        row.addWidget(self.add_button)
        row.addStretch()
        row.addWidget(self.remove_button)
        row.addWidget(self.clear_button)
        col.addLayout(row)
        self._update_count()

    # --- rows ------------------------------------------------------------------

    def add_part(
        self,
        path: str,
        report: MeshReport,
        copies: int = 1,
        hull: np.ndarray | None = None,
        edges: np.ndarray | None = None,
        rotation: Angles = NO_ROTATION,
        **more,
    ) -> PartInfo:
        """Add a row; `more` are further PartInfo fields (mesh, display, settings, spots)."""
        info = PartInfo(path, report, hull, edges, tuple(rotation), **more)
        self._add_row(info, copies)
        self._update_count()
        if self.table.currentRow() < 0:
            self.table.selectRow(self.table.rowCount() - 1)
        self.changed.emit()
        return info

    def _add_row(self, info: PartInfo, copies: int) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        name = QTableWidgetItem(os.path.basename(info.path))
        name.setData(Qt.UserRole, info)
        self.table.setItem(r, 0, QTableWidgetItem())
        self.table.setItem(r, 1, name)
        spin = QSpinBox()
        spin.setRange(1, 999)
        spin.setValue(copies)
        spin.setToolTip("How many copies of this model to pack into the build")
        spin.setAccessibleName(f"Copies of {os.path.basename(info.path)}")
        spin.valueChanged.connect(self._update_count)
        spin.valueChanged.connect(self.changed)
        self.table.setCellWidget(r, 2, spin)
        self.table.setItem(r, 3, QTableWidgetItem())
        self._refresh_row(r)

    def rows(self) -> list[tuple[PartInfo, int]]:
        """Every row as (part, copies)."""
        return [(self.info(r), self.table.cellWidget(r, 2).value()) for r in range(self.table.rowCount())]

    def set_rows(self, rows: list[tuple[PartInfo, int]], selected: int = -1) -> None:
        """Replace every row (e.g. going back to an earlier state), without emitting `changed`."""
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for info, copies in rows:
            self._add_row(info, copies)
        self.table.blockSignals(False)
        self._update_count()
        if 0 <= selected < len(rows):
            self.table.selectRow(selected)
        self.selection_changed.emit(self.selected())

    def selected_row(self) -> int:
        rows = {i.row() for i in self.table.selectedIndexes()}
        return min(rows) if rows else -1

    def select_row(self, r: int) -> None:
        if 0 <= r < self.table.rowCount() and r != self.selected_row():
            self.table.selectRow(r)

    def info(self, r: int) -> PartInfo:
        return self.table.item(r, 1).data(Qt.UserRole)

    def selected(self) -> PartInfo | None:
        r = self.selected_row()
        return self.info(r) if r >= 0 else None

    def set_selected_rotation(self, rotation: Angles) -> None:
        r = self.selected_row()
        if r < 0:
            return
        self.info(r).rotation = tuple(rotation)
        self._refresh_row(r)
        self.changed.emit()

    def selected_settings_changed(self) -> None:
        """The selected part's own settings were edited (in its PartInfo)."""
        r = self.selected_row()
        if r >= 0:
            self._refresh_row(r)
            self.changed.emit()

    def set_scale(self, scale: float) -> None:
        self.scale = scale
        for r in range(self.table.rowCount()):
            self._refresh_row(r)

    def _refresh_row(self, r: int) -> None:
        info = self.info(r)
        path, report = info.path, info.report
        x, y, z = info.size(self.scale)
        self.table.item(r, 3).setText(f"{x:.1f} × {y:.1f} × {z:.1f}")
        notes = list(report.repairs) + list(report.warnings)
        largest = max(x, y, z)
        if largest < TINY_MM:
            notes.append(f"Only {largest:.3g} mm across at this scale - check the units (inches: scale 25.4).")
        elif largest > HUGE_MM:
            notes.append(f"{largest:.0f} mm across at this scale - check the units.")
        warn = bool(report.warnings) or largest < TINY_MM or largest > HUGE_MM
        t = theme.current()
        icon = theme.icon("warning", "#d97706") if warn else theme.icon("ok", t["ok"])
        status = self.table.item(r, 0)
        status.setIcon(icon)
        tip = "\n".join([path, *notes]) if notes else f"{path}\nNo problems found."
        status.setToolTip(tip)
        name = self.table.item(r, 1)
        if info.settings:
            tip += f"\nOwn settings: {describe_settings(info.settings)}"
        name.setIcon(theme.icon("laser", t["accent"]) if info.settings else QIcon())
        name.setToolTip(tip)

    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        if rows:
            self._update_count()
            self.changed.emit()

    def clear(self) -> None:
        if self.table.rowCount():
            self.table.setRowCount(0)
            self._update_count()
            self.changed.emit()

    def _update_count(self) -> None:
        n = sum(p.copies for p in self.parts())
        self.count.setText(f"{n} part{'s' if n != 1 else ''}" if n else "")
        self.table.setVisible(bool(n))
        self.empty_hint.setVisible(not n)

    def restyle(self) -> None:
        super().restyle()
        if hasattr(self, "table"):
            for b in (self.add_button, self.remove_button, self.clear_button):
                b.setIcon(theme.icon(b.property("iconName")))
            for r in range(self.table.rowCount()):
                self._refresh_row(r)

    # --- what to print -----------------------------------------------------------

    def parts(self) -> list[ProjectPart]:
        return [
            ProjectPart(info.path, copies, info.rotation, dict(info.settings), list(info.spots[:copies]))
            for info, copies in self.rows()
        ]

    def jobs(self) -> list[str]:
        """Every part to print, a path repeated once per copy."""
        return [p.path for p in self.parts() for _ in range(p.copies)]


class SettingsPanel(QWidget):
    """Every SliceConfig setting, with tooltips. Emits `changed` on any edit."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.spins: dict[str, QDoubleSpinBox] = {}
        self.cards: list[Card] = []
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        for title, specs in NUMBER_FIELDS.items():
            group = Card(title)
            self.cards.append(group)
            if title == "Laser":
                note = QLabel("placeholders")
                note.setObjectName("hint")
                note.setToolTip("Real values come once the laser is chosen")
                group.trailing.addWidget(note)
            holder = QWidget()
            form = QFormLayout(holder)
            form.setContentsMargins(0, 0, 0, 0)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(8)
            form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            group.body.addWidget(holder)
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
                    "meander: zig-zag across the layer. raster: all one direction."
                )
                self.scan_order.currentTextChanged.connect(self.changed)
                form.addRow("Scan order", self.scan_order)
            if title == "Placement":
                self.allow_rotation = QCheckBox("Turn parts to fit more")
                self.allow_rotation.setToolTip("Let the packer turn parts about Z. Parts are never tipped over.")
                self.allow_rotation.toggled.connect(self.changed)
                form.addRow(self.allow_rotation)
                self.use_volume = QCheckBox("Build volume (mm)")
                self.use_volume.setToolTip(
                    "Printable size of the machine. Needed to pack several parts; "
                    "150 mm is a placeholder until the machine is specified."
                )
                self.use_volume.toggled.connect(self._volume_toggled)
                vol = QHBoxLayout()
                self.volume = []
                for axis in "XYZ":
                    spin = QDoubleSpinBox()
                    spin.setRange(1, 5000)
                    spin.setDecimals(0)
                    spin.setPrefix(f"{axis}  ")
                    spin.setKeyboardTracking(False)
                    spin.valueChanged.connect(self.changed)
                    self.volume.append(spin)
                    vol.addWidget(spin)
                form.addRow(self.use_volume)
                form.addRow(vol)
            col.addWidget(group)
        reset = tool_button("clear", "Reset to defaults", "Put every setting back to its default")
        reset.setIcon(theme.icon("auto"))
        reset.setProperty("iconName", "auto")
        self.reset_button = reset
        reset.clicked.connect(lambda: self.set_config(gui_defaults()))
        col.addWidget(reset, 0, Qt.AlignLeft)
        self.set_config(gui_defaults())

    def restyle(self) -> None:
        for card in self.cards:
            card.restyle()
        self.reset_button.setIcon(theme.icon("auto"))

    def _volume_toggled(self, on: bool) -> None:
        for s in self.volume:
            s.setEnabled(on)
        self.changed.emit()

    def state(self) -> dict:
        """Every value as shown, for going back to it later (see set_state)."""
        return {
            **{k: s.value() for k, s in self.spins.items()},
            "scan_order": self.scan_order.currentText(),
            "allow_rotation": self.allow_rotation.isChecked(),
            "use_volume": self.use_volume.isChecked(),
            "volume": tuple(s.value() for s in self.volume),
        }

    def set_state(self, state: dict) -> None:
        self.blockSignals(True)
        try:
            for k, spin in self.spins.items():
                spin.setValue(state[k])
            self.scan_order.setCurrentText(state["scan_order"])
            self.allow_rotation.setChecked(state["allow_rotation"])
            self.use_volume.setChecked(state["use_volume"])
            for spin, v in zip(self.volume, state["volume"]):
                spin.setValue(v)
                spin.setEnabled(state["use_volume"])
        finally:
            self.blockSignals(False)
        self.changed.emit()

    def config(self) -> SliceConfig:
        """The settings as a SliceConfig. Raises ValueError if they don't make sense."""
        known = {f.name for f in fields(SliceConfig)}
        values = {k: s.value() for k, s in self.spins.items() if k in known}
        volume = tuple(s.value() for s in self.volume) if self.use_volume.isChecked() else None
        return SliceConfig(
            **values,
            scan_order=self.scan_order.currentText(),
            allow_rotation=self.allow_rotation.isChecked(),
            build_volume=volume,
        )

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
