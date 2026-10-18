"""The Part settings card: laser settings of its own for the selected part, e.g.
more power for a thick part in a build of thin ones."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QFormLayout, QLabel, QWidget

from ..config import PART_SETTINGS, SliceConfig
from .panels import NUMBER_FIELDS
from .widgets import Card

_SPECS = {spec[0]: spec for specs in NUMBER_FIELDS.values() for spec in specs if spec[0] in PART_SETTINGS}


class PartSettingsPanel(Card):
    """Edit the selected part's own settings. Emits `settings_changed` with them
    ({} = it follows the build's settings)."""

    settings_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__("Part settings", parent=parent)
        self.part = None  # PartInfo of the selected part
        self.build = SliceConfig()  # the build's settings, which a part follows by default
        self.placeholder = QLabel("Select a part to give it settings of its own.")
        self.placeholder.setObjectName("hint")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setMinimumHeight(48)
        self.body.addWidget(self.placeholder)

        self.editor = QWidget()
        form = QFormLayout(self.editor)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.own = QCheckBox("Own laser settings for this part")
        self.own.setToolTip("Use different power, speed or hatch spacing for this part than for the rest of the build")
        self.own.toggled.connect(self._own_toggled)
        form.addRow(self.own)
        self.spins: dict[str, QDoubleSpinBox] = {}
        for name in PART_SETTINGS:
            _, label, lo, hi, step, decimals, suffix, tip = _SPECS[name]
            spin = QDoubleSpinBox()
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            spin.setDecimals(decimals)
            spin.setSuffix(suffix)
            spin.setToolTip(tip)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self._edited)
            self.spins[name] = spin
            form.addRow(label, spin)
        self.energy = QLabel()
        self.energy.setObjectName("muted")
        form.addRow(self.energy)
        self.body.addWidget(self.editor)
        self.set_part(None)

    # --- inputs from the window ------------------------------------------------------

    def set_part(self, part) -> None:
        self.part = part
        self.placeholder.setVisible(part is None)
        self.editor.setVisible(part is not None)
        self._show()

    def set_build(self, config: SliceConfig) -> None:
        self.build = config
        self._show()

    # --- edits -----------------------------------------------------------------------

    def _own_toggled(self, on: bool) -> None:
        if self.part is None:
            return
        self.part.settings = {k: getattr(self.build, k) for k in PART_SETTINGS} if on else {}
        self._show()
        self.settings_changed.emit(dict(self.part.settings))

    def _edited(self) -> None:
        if self.part is None or not self.own.isChecked():
            return
        self.part.settings = {k: s.value() for k, s in self.spins.items()}
        self._show()
        self.settings_changed.emit(dict(self.part.settings))

    # --- display -----------------------------------------------------------------------

    def _show(self) -> None:
        part = self.part
        own = bool(part and part.settings)
        values = self.build.for_part(part.settings if part else None)
        self.own.blockSignals(True)
        self.own.setChecked(own)
        self.own.blockSignals(False)
        for name, spin in self.spins.items():
            spin.blockSignals(True)
            spin.setValue(getattr(values, name))
            spin.setEnabled(own)
            spin.blockSignals(False)
        energy = values.hatch_energy_density
        self.energy.setText(
            f"Energy density {energy:.3f} J/mm²" + ("" if own else " (the build's)") if part is not None else ""
        )
