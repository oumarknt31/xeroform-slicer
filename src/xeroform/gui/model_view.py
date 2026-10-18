"""The plate in 3D: every copy of every part where it will be printed, shaded.

Drag a part to move it on the plate, drag empty space to orbit, scroll to zoom,
right-drag to pan, double-click to reset. In face-picking mode a click on a
part lays it flat on the face clicked. Drawn with QPainter (back to front), so
it needs no OpenGL.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QLineF, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QWidget

from ..nesting import Spot
from . import theme
from .scene import at_spot, turned_normals
from .views import _alpha, _mix, _overlay_text, _pen, paint_canvas

PROBLEM = "#ef4444"
_LIGHT = np.array([-0.35, -0.55, 0.76])  # from the upper left, behind the viewer


@dataclass
class SceneItem:
    """One copy of a part: its posed display mesh (centred, resting on z = 0) and where it is."""

    row: int
    copy: int
    triangles: np.ndarray  # (n, 3, 3) posed, before the spot
    normals: np.ndarray  # (n, 3) posed
    file_normals: np.ndarray  # (n, 3) in the model file's own frame, for laying flat on a face
    spot: Spot
    placed: tuple | None = field(default=None, repr=False, compare=False)  # (spot, triangles, normals) at the spot


class ModelView(QWidget):
    selected = Signal(int)  # row of the part clicked
    moved = Signal(int, int, tuple)  # row, copy, new spot - while a part is dragged
    move_done = Signal()  # the drag ended
    face_picked = Signal(int, object)  # row, normal of the face clicked (model file frame)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.items: list[SceneItem] = []
        self.volume: tuple[float, float, float] | None = None
        self.selected_row = -1
        self.problems: set[tuple[int, int]] = set()  # (row, copy) of parts too close or outside
        self.picking = False
        self._frame = None  # what the last paint drew, for picking
        self._press = None
        self._drag_item: SceneItem | None = None
        self._hover = None
        self.reset_view()

    # --- input from the window ----------------------------------------------------

    def set_scene(self, items: list[SceneItem], volume, selected_row: int = -1, problems=()) -> None:
        self.items, self.volume = items, volume
        self.selected_row, self.problems = selected_row, set(problems)
        self._frame, self._hover, self._drag_item = None, None, None  # they referred to the old items
        self.update()

    def set_selected(self, row: int) -> None:
        self.selected_row = row
        self.update()

    def set_problems(self, problems) -> None:
        self.problems = set(problems)
        self.update()

    def set_picking(self, on: bool) -> None:
        self.picking = on
        self._hover = None
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        self.update()

    # --- camera -------------------------------------------------------------------

    def reset_view(self) -> None:
        self.yaw, self.elev, self.zoom = math.radians(-35), math.radians(35), 1.0
        self.pan = np.zeros(2)
        self.update()

    def top_view(self) -> None:
        self.yaw, self.elev = 0.0, math.radians(90)
        self.pan = np.zeros(2)
        self.update()

    def _extent(self) -> tuple[np.ndarray, float]:
        """Centre and radius of what to fit: the plate and the parts on it, or the parts."""
        if self.volume:
            X, Y, Z = self.volume
            tops = [self._triangles(it)[0][..., 2].max() for it in self.items]
            height = min(Z, max([*tops, 0.2 * max(X, Y)]))
            lo, hi = np.array([-X / 2, -Y / 2, 0.0]), np.array([X / 2, Y / 2, height])
        elif self.items:
            pts = np.concatenate([self._triangles(it)[0].reshape(-1, 3) for it in self.items])
            lo, hi = pts.min(axis=0), pts.max(axis=0)
        else:
            lo, hi = np.array([-50.0, -50, 0]), np.array([50.0, 50, 50])
        return (lo + hi) / 2, max(float(np.linalg.norm(hi - lo)) / 2, 1.0)

    def _camera(self):
        centre, radius = self._extent()
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        ce, se = math.cos(self.elev), math.sin(self.elev)
        scale = self.zoom * min(self.width(), self.height()) * 0.46 / radius
        right = np.array([cy, -sy, 0.0])
        ahead = np.array([sy, cy, 0.0])  # away from the viewer, level
        up = ce * np.array([0, 0, 1.0]) + se * ahead
        into = ce * ahead - se * np.array([0, 0, 1.0])  # the viewing direction
        origin = np.array([self.width() / 2, self.height() / 2]) + self.pan
        return centre, scale, right, up, into, origin

    def _project(self, pts: np.ndarray, cam) -> np.ndarray:
        centre, scale, right, up, _, origin = cam
        rel = pts - centre
        return np.stack([origin[0] + (rel @ right) * scale, origin[1] - (rel @ up) * scale], axis=-1)

    # --- interaction ------------------------------------------------------------------

    def mousePressEvent(self, event):
        pos = event.position()
        self._press = (pos, event.button())
        self._drag_item = None
        if event.button() != Qt.LeftButton:
            return
        hit = self._hit(pos)
        if hit is None:
            return
        item, face = hit
        if self.picking:
            self.face_picked.emit(item.row, item.file_normals[face])
            return
        self.selected.emit(item.row)
        self._drag_item = item
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._press is None:
            if self.picking:
                self._hover = self._hit(pos)
                self.update()
            return
        last, button = self._press
        d = pos - last
        self._press = (pos, button)
        if self._drag_item is not None:
            self._move_item(self._drag_item, d.x(), d.y())
        elif button == Qt.LeftButton and not self.picking:
            self.yaw += math.radians(d.x() * 0.5)
            self.elev = min(max(self.elev + math.radians(d.y() * 0.4), 0.0), math.radians(90))
        elif button in (Qt.RightButton, Qt.MiddleButton):
            self.pan = self.pan + (d.x(), d.y())
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_item is not None:
            self.move_done.emit()
        self._press, self._drag_item = None, None
        self.setCursor(Qt.CrossCursor if self.picking else Qt.ArrowCursor)
        self.update()

    def mouseDoubleClickEvent(self, event):
        if self._hit(event.position()) is None:
            self.reset_view()

    def wheelEvent(self, event):
        self.zoom = min(max(self.zoom * 1.0015 ** event.angleDelta().y(), 0.2), 30)
        self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()
        super().leaveEvent(event)

    def _move_item(self, item: SceneItem, dx: float, dy: float) -> None:
        """Slide a part across the plate by a mouse move of (dx, dy) pixels."""
        _, scale, right, up, _, _ = self._camera()
        se = math.sin(self.elev)
        if se < 0.15:  # looking along the plate: only sideways moves make sense
            across, ahead = dx / scale, 0.0
        else:
            across, ahead = dx / scale, -dy / (scale * se)
        level = np.array([math.sin(self.yaw), math.cos(self.yaw), 0.0])
        delta = across * right + ahead * level
        x, y, z, turn = item.spot
        x, y = x + delta[0], y + delta[1]
        if self.volume:
            X, Y, _ = self.volume
            x, y = min(max(x, -X / 2), X / 2), min(max(y, -Y / 2), Y / 2)
        item.spot = (float(x), float(y), z, turn)
        self.moved.emit(item.row, item.copy, item.spot)

    def _hit(self, pos: QPointF):
        """The part (SceneItem, face index) under a widget position, nearest first."""
        if self._frame is None:
            return None
        screen, owners, faces, dist = self._frame
        if not len(screen):
            return None
        p = np.array([pos.x(), pos.y()])
        a, b, c = screen[:, 0], screen[:, 1], screen[:, 2]

        def side(u, v):
            return (v[:, 0] - u[:, 0]) * (p[1] - u[:, 1]) - (v[:, 1] - u[:, 1]) * (p[0] - u[:, 0])

        s1, s2, s3 = side(a, b), side(b, c), side(c, a)
        inside = ((s1 >= 0) & (s2 >= 0) & (s3 >= 0)) | ((s1 <= 0) & (s2 <= 0) & (s3 <= 0))
        hits = np.flatnonzero(inside)
        if not len(hits):
            return None
        k = hits[np.argmin(dist[hits])]
        return self.items[owners[k]], int(faces[k])

    # --- drawing ------------------------------------------------------------------------

    @staticmethod
    def _triangles(item: SceneItem):
        """The item's triangles and normals where it is now."""
        if item.placed is None or item.placed[0] != item.spot:
            item.placed = (
                item.spot,
                at_spot(item.triangles, item.spot),
                turned_normals(item.normals, int(item.spot[3])),
            )
        return item.placed[1:]

    def paintEvent(self, event):
        t = theme.current()
        p = QPainter(self)
        paint_canvas(p, self)
        cam = self._camera()
        p.setRenderHint(QPainter.Antialiasing)
        self._paint_plate(p, cam)
        p.setRenderHint(QPainter.Antialiasing, False)  # thousands of small faces: crisp and fast
        self._paint_parts(p, cam, t)
        p.setRenderHint(QPainter.Antialiasing)
        if self.volume:
            self._paint_volume_top(p, cam)
        hint = (
            "click a face to lay the part flat on it"
            if self.picking
            else "drag a part to move it · drag to orbit · right-drag to pan · scroll to zoom"
        )
        _overlay_text(p, self, hint, "bottom-left")

    def _paint_plate(self, p: QPainter, cam) -> None:
        t = theme.current()
        if self.volume:
            X, Y, _ = self.volume
        else:
            _, radius = self._extent()
            X = Y = radius * 1.6
        corners = np.array([[-X / 2, -Y / 2, 0], [X / 2, -Y / 2, 0], [X / 2, Y / 2, 0], [-X / 2, Y / 2, 0]])
        plate = QPolygonF([QPointF(*q) for q in self._project(corners, cam).tolist()])
        p.setPen(_pen(t["border_hi"], 1))
        p.setBrush(QColor(t["plate"]))
        p.drawPolygon(plate)
        p.setBrush(Qt.NoBrush)
        step = 10.0 if max(X, Y) <= 400 else 50.0
        lines = []
        for x in np.arange(-X / 2 + (X / 2) % step, X / 2, step):
            lines.append([[x, -Y / 2, 0], [x, Y / 2, 0]])
        for y in np.arange(-Y / 2 + (Y / 2) % step, Y / 2, step):
            lines.append([[-X / 2, y, 0], [X / 2, y, 0]])
        if lines:
            ends = self._project(np.array(lines, dtype=float), cam)
            p.setPen(_pen(t["grid"], 1))
            p.drawLines([QLineF(a[0], a[1], b[0], b[1]) for a, b in ends.tolist()])
        if self.volume:  # the chamber walls, faintly
            Z = self.volume[2]
            uprights = np.array([[c, c + (0, 0, Z)] for c in corners])
            ends = self._project(uprights, cam)
            p.setPen(_pen(_alpha(t["muted"], 70), 1, Qt.DashLine))
            p.drawLines([QLineF(a[0], a[1], b[0], b[1]) for a, b in ends.tolist()])

    def _paint_volume_top(self, p: QPainter, cam) -> None:
        X, Y, Z = self.volume
        corners = np.array([[-X / 2, -Y / 2, Z], [X / 2, -Y / 2, Z], [X / 2, Y / 2, Z], [-X / 2, Y / 2, Z]])
        top = QPolygonF([QPointF(*q) for q in self._project(corners, cam).tolist()])
        p.setPen(_pen(_alpha(theme.current()["muted"], 70), 1, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(top)

    def _paint_parts(self, p: QPainter, cam, t) -> None:
        if not self.items:
            self._frame = None
            return
        _, _, _, _, into, _ = cam
        tris, norms, owners, faces = [], [], [], []
        for i, item in enumerate(self.items):
            world, normals = self._triangles(item)
            front = normals @ into < 1e-9  # facing the viewer (closed meshes: skip the back)
            tris.append(world[front])
            norms.append(normals[front])
            owners.append(np.full(int(front.sum()), i))
            faces.append(np.flatnonzero(front))
        tris, norms = np.concatenate(tris), np.concatenate(norms)
        owners, faces = np.concatenate(owners), np.concatenate(faces)
        dist = tris.mean(axis=1) @ into
        order = np.argsort(-dist)  # far ones first
        tris, norms, owners, faces, dist = tris[order], norms[order], owners[order], faces[order], dist[order]
        screen = self._project(tris, cam)
        self._frame = (screen, owners, faces, dist)

        light = _LIGHT @ np.stack([cam[2], cam[3], -into])  # fixed to the camera
        light /= np.linalg.norm(light)
        shade = np.clip(0.38 + 0.62 * np.clip(norms @ light, 0, 1), 0, 1)
        levels = np.round(shade * 31).astype(int)
        base = {}
        for i, item in enumerate(self.items):
            if (item.row, item.copy) in self.problems:
                base[i] = PROBLEM
            elif item.row == self.selected_row:
                base[i] = t["accent"]
            else:
                base[i] = _mix(t["muted"], t["text"], 0.35).name()
        dark = t["canvas"]
        palette: dict[tuple[int, int], QColor] = {}
        hover = None
        if self.picking and self._hover is not None:
            hover = (self.items.index(self._hover[0]), self._hover[1])
        p.setPen(Qt.NoPen)
        for tri, owner, face, level in zip(screen.tolist(), owners.tolist(), faces.tolist(), levels.tolist()):
            if hover == (owner, face):
                color = QColor(t["accent_glow"])
            else:
                key = (owner, level)
                if key not in palette:
                    palette[key] = _mix(dark, base[owner], 0.15 + 0.85 * level / 31)
                color = palette[key]
            p.setBrush(color)
            p.drawPolygon(QPolygonF([QPointF(*tri[0]), QPointF(*tri[1]), QPointF(*tri[2])]))

    def restyle(self) -> None:
        self.update()
