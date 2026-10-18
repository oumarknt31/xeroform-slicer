"""The Orientation card: turn the selected part, lay it flat, or find its lowest height,
with a small 3D preview of the part on the plate."""

from __future__ import annotations

import math

import numpy as np
import trimesh
from PySide6.QtCore import QLineF, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..orient import NO_ROTATION, Angles, flat_faces, lay_flat, lowest, matrix, turn
from . import theme
from .views import _alpha, _pen, paint_canvas
from .widgets import Card, tool_button

EDGE_LIMIT = 12000  # edges drawn in the preview
SHARP_DEGREES = 25  # an edge between faces bent more than this is drawn


def outline_edges(mesh: trimesh.Trimesh) -> np.ndarray:
    """(E, 2, 3) edges that show a part's shape: its sharp edges, or for smooth
    organic shapes a thinned-out wireframe. Centred on the part."""
    sharp = mesh.face_adjacency_edges[mesh.face_adjacency_angles > np.radians(SHARP_DEGREES)]
    if len(sharp) < 300:
        sharp = mesh.edges_unique
    if len(sharp) > EDGE_LIMIT:
        sharp = sharp[np.linspace(0, len(sharp) - 1, EDGE_LIMIT).astype(int)]
    return (mesh.vertices[sharp] - mesh.bounds.mean(axis=0)).astype(np.float32)


class PartPreview(QWidget):
    """The selected part in its current orientation, resting on the plate. Drag to orbit."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.setAccessibleName("Part orientation preview")
        self.edges: np.ndarray | None = None
        self.rotation: Angles = NO_ROTATION
        self.yaw, self.elev = math.radians(-35), math.radians(28)
        self._drag = None

    def set_part(self, edges: np.ndarray | None, rotation: Angles) -> None:
        self.edges, self.rotation = edges, rotation
        self.update()

    def mousePressEvent(self, event):
        self._drag = event.position()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        d = event.position() - self._drag
        self._drag = event.position()
        self.yaw += math.radians(d.x() * 0.5)
        self.elev = min(max(self.elev + math.radians(d.y() * 0.4), 0.0), math.radians(90))
        self.update()

    def mouseReleaseEvent(self, event):
        self._drag = None

    def paintEvent(self, event):
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        paint_canvas(p, self)
        if self.edges is None or not len(self.edges):
            return
        pts = self.edges.reshape(-1, 3) @ matrix(self.rotation).T
        pts[:, 2] -= pts[:, 2].min()  # resting on the plate
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        centre = (lo + hi) / 2
        radius = max(float(np.linalg.norm(hi - lo)) / 2, 1e-6)
        scale = min(self.width(), self.height()) * 0.40 / radius
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        ce, se = math.cos(self.elev), math.sin(self.elev)

        def project(xyz: np.ndarray) -> np.ndarray:
            x, y, z = (xyz - centre).T
            across, depth = x * cy - y * sy, x * sy + y * cy
            up = z * ce + depth * se
            return np.column_stack([self.width() / 2 + across * scale, self.height() / 2 - up * scale])

        size = max(hi[0] - lo[0], hi[1] - lo[1]) * 0.75
        plate = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]]) * size + centre[:2]
        plate = project(np.column_stack([plate, np.full(4, lo[2])]))
        p.setPen(_pen(t["border_hi"], 1))
        p.setBrush(_alpha(t["plate"], 255))
        p.drawPolygon(QPolygonF([QPointF(*q) for q in plate]))
        p.setBrush(Qt.NoBrush)

        flat = project(pts).reshape(-1, 2, 2)
        lines = [QLineF(a[0], a[1], b[0], b[1]) for a, b in flat.tolist()]
        p.setPen(_pen(_alpha(t["accent"], 45), 3.5))
        p.drawLines(lines)
        p.setPen(_pen(QColor(t["accent_glow"]), 1))
        p.drawLines(lines)


class OrientationPanel(Card):
    """Orient the part selected in the parts list. Emits `rotation_changed` on edits."""

    rotation_changed = Signal(tuple)

    def __init__(self, parent=None):
        super().__init__("Orientation", parent=parent)
        self.part = None  # PartInfo of the selected part
        self.scale = 1.0
        self.layer = 0.1
        self._next_face = 0  # the face the next "Lay flat" click rests the part on
        self._resting_face: int | None = None
        self.name = QLabel()
        self.name.setObjectName("hint")
        self.trailing.addWidget(self.name)

        self.placeholder = QLabel("Select a part to orient it.")
        self.placeholder.setObjectName("hint")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setMinimumHeight(60)
        self.body.addWidget(self.placeholder)

        self.editor = QWidget()
        ed = QVBoxLayout(self.editor)
        ed.setContentsMargins(0, 0, 0, 0)
        ed.setSpacing(8)
        self.preview = PartPreview()
        ed.addWidget(self.preview)

        caption = QLabel("Rotation (degrees)")
        caption.setObjectName("hint")
        ed.addWidget(caption)
        angles = QHBoxLayout()
        self.spins: list[QDoubleSpinBox] = []
        for axis in "XYZ":
            spin = QDoubleSpinBox()
            spin.setRange(-180, 180)
            spin.setDecimals(1)
            spin.setSingleStep(15)
            spin.setWrapping(True)
            spin.setKeyboardTracking(False)
            spin.setPrefix(f"{axis} ")
            spin.setMinimumWidth(0)
            spin.setToolTip(f"Rotation about the {axis} axis, in degrees")
            spin.setAccessibleName(f"Rotation about {axis}")
            spin.valueChanged.connect(self._angles_edited)
            self.spins.append(spin)
            angles.addWidget(spin)
        ed.addLayout(angles)

        turns = QHBoxLayout()
        self.turn_buttons = []
        for axis in "xyz":
            b = tool_button("rotate", f"{axis.upper()} +90°", f"Turn the part 90° about the {axis.upper()} axis")
            b.clicked.connect(lambda _=False, a=axis: self._turn(a))
            self.turn_buttons.append(b)
            turns.addWidget(b)
        turns.addStretch()
        ed.addLayout(turns)

        actions = QHBoxLayout()
        self.flat_button = tool_button("lay-flat", "Lay flat", "Rest the part on its next flat face, largest first")
        self.flat_button.clicked.connect(self._lay_flat)
        self.lowest_button = tool_button(
            "height", "Lowest height", "Turn the part for the fewest layers (fastest and cheapest)"
        )
        self.lowest_button.clicked.connect(self._lowest)
        self.reset_button = tool_button("clear", "Reset", "Back to the orientation saved in the file")
        self.reset_button.clicked.connect(lambda: self._apply(NO_ROTATION))
        for b in (self.flat_button, self.lowest_button, self.reset_button):
            actions.addWidget(b)
        actions.addStretch()
        ed.addLayout(actions)

        self.info = QLabel()
        self.info.setObjectName("muted")
        self.info.setWordWrap(True)
        ed.addWidget(self.info)
        self.body.addWidget(self.editor)
        self.set_part(None)

    # --- inputs from the window ------------------------------------------------

    def set_part(self, part) -> None:
        self.part = part
        self._next_face, self._resting_face = 0, None
        self.placeholder.setVisible(part is None)
        self.editor.setVisible(part is not None)
        self.name.setText("" if part is None else part.path.replace("\\", "/").rsplit("/", 1)[-1])
        self._show()

    def set_scale(self, scale: float) -> None:
        self.scale = scale
        self._show()

    def set_layer_thickness(self, layer: float) -> None:
        self.layer = layer
        self._show()

    # --- edits -------------------------------------------------------------------

    def _apply(self, rotation: Angles, face: int | None = None) -> None:
        if self.part is None:
            return
        self.part.rotation = tuple(rotation)
        self._resting_face = face
        self._show()
        self.rotation_changed.emit(self.part.rotation)

    def _angles_edited(self) -> None:
        if self.part is not None:
            self._apply(tuple(s.value() for s in self.spins))

    def _turn(self, axis: str) -> None:
        if self.part is not None:
            self._apply(turn(self.part.rotation, axis, 90))

    def _lay_flat(self) -> None:
        if self.part is None or self.part.hull is None:
            return
        faces = len(flat_faces(self.part.hull))
        face = self._next_face % faces
        self._next_face = face + 1
        self._apply(lay_flat(self.part.hull, face), face=face)

    def _lowest(self) -> None:
        if self.part is not None and self.part.hull is not None:
            self._apply(lowest(self.part.hull))

    # --- display -----------------------------------------------------------------

    def _show(self) -> None:
        part = self.part
        if part is None:
            self.preview.set_part(None, NO_ROTATION)
            return
        for spin, angle in zip(self.spins, part.rotation):
            spin.blockSignals(True)
            spin.setValue(angle)
            spin.blockSignals(False)
        self.preview.set_part(part.edges, part.rotation)
        x, y, z = part.size(self.scale)
        layers = max(1, math.ceil(z / self.layer - 1e-9))
        text = f"{x:.1f} × {y:.1f} × {z:.1f} mm · {z:.1f} mm tall · {layers} layers at {self.layer:g} mm"
        if part.hull is not None and self._resting_face is not None:
            text += f" · resting on face {self._resting_face + 1} of {len(flat_faces(part.hull))}"
        self.info.setText(text)

    def restyle(self) -> None:
        super().restyle()
        for b in [
            *getattr(self, "turn_buttons", []),
            *(getattr(self, n, None) for n in ("flat_button", "lowest_button", "reset_button")),
        ]:
            if b is not None:
                b.setIcon(theme.icon(b.property("iconName")))
        if hasattr(self, "preview"):
            self.preview.update()
