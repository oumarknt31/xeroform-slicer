"""The views: one layer from above, the whole build from above, and the layer stack in 3D.

LayerView and LayoutView share PlateView: model coordinates in mm with +y up,
scroll to zoom, drag to pan, double-click to fit, a mm grid that adapts to the
zoom, and the cursor position shown in mm. LayerView can also play back the
laser tracing the layer. StackView draws the sliced contours stacked in 3D; drag
to orbit. All colours come from the theme.
"""
from __future__ import annotations
import math

import numpy as np
from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient,
                           QTransform)
from PySide6.QtWidgets import QToolTip, QWidget

from ..layers import Layer
from . import theme

LEVELS = ("#2563eb", "#ea580c", "#059669", "#7c3aed", "#d97706", "#db2777")
MARGIN = 28                       # px around the fitted view
GRID_STEPS = (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000)
MIN_GRID_PX = 36                  # grid lines at least this far apart on screen
SCAN_SECONDS = 4.0                # length of one layer's laser playback
FPS = 30


def _pen(color, width: float = 0, style=Qt.SolidLine) -> QPen:
    pen = QPen(QColor(color), width, style)
    pen.setCosmetic(True)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _alpha(color: str, a: int) -> QColor:
    c = QColor(color)
    c.setAlpha(a)
    return c


def _mix(a: str, b: str, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t), round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t))


def paint_canvas(p: QPainter, widget: QWidget) -> None:
    """The viewer background: graphite with a soft light in the middle (a vignette)."""
    t = theme.current()
    r = widget.rect()
    glow = QRadialGradient(r.center(), max(r.width(), r.height()) * 0.75)
    glow.setColorAt(0, QColor(t["canvas_hi"]))
    glow.setColorAt(1, QColor(t["canvas"]))
    p.fillRect(r, glow)


def _overlay_text(p: QPainter, widget: QWidget, text: str, corner: str) -> None:
    """Small muted text in a corner of the widget (screen space)."""
    p.resetTransform()
    fm = QFontMetrics(widget.font())
    w = fm.horizontalAdvance(text)
    x = 12 if corner.endswith("left") else widget.width() - w - 12
    y = widget.height() - 10 if corner.startswith("bottom") else fm.ascent() + 10
    p.setPen(theme.color("muted"))
    p.drawText(QPointF(x, y), text)


class PlateView(QWidget):
    cursor_moved = Signal(float, float)  # mm
    cursor_left = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.plate: tuple[float, float] | None = None  # build plate (x, y) mm, centred on 0
        self.show_grid = True
        self._bounds = QRectF(-50, -50, 100, 100)
        self._scale, self._tx, self._ty = 1.0, 0.0, 0.0
        self._user_moved = False
        self._drag = None
        self._cursor: QPointF | None = None

    def content_bounds(self) -> QRectF | None:
        return None

    def refresh_bounds(self) -> None:
        if self.plate:
            w, h = self.plate
            self._bounds = QRectF(-w / 2, -h / 2, w, h)
        else:
            self._bounds = self.content_bounds() or QRectF(-50, -50, 100, 100)
        self._user_moved = False
        self.fit()

    def fit(self) -> None:
        b = self._bounds
        w, h = max(self.width() - 2 * MARGIN, 1), max(self.height() - 2 * MARGIN, 1)
        self._scale = min(w / max(b.width(), 1e-6), h / max(b.height(), 1e-6))
        self._tx = self.width() / 2 - self._scale * b.center().x()
        self._ty = self.height() / 2 + self._scale * b.center().y()  # model +y points up
        self.update()

    def transform(self) -> QTransform:
        return QTransform(self._scale, 0, 0, -self._scale, self._tx, self._ty)

    def to_world(self, p: QPointF) -> QPointF:
        return QPointF((p.x() - self._tx) / self._scale, (self._ty - p.y()) / self._scale)

    def grid_step(self) -> float:
        return next((s for s in GRID_STEPS if s * self._scale >= MIN_GRID_PX), GRID_STEPS[-1])

    # --- interaction -----------------------------------------------------------

    def resizeEvent(self, event):
        if not self._user_moved:
            self.fit()
        super().resizeEvent(event)

    def wheelEvent(self, event):
        k = 1.0015 ** event.angleDelta().y()
        p = event.position()
        self._tx = p.x() - (p.x() - self._tx) * k
        self._ty = p.y() - (p.y() - self._ty) * k
        self._scale *= k
        self._user_moved = True
        self.update()

    def mousePressEvent(self, event):
        self._drag = event.position()
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        self._cursor = self.to_world(event.position())
        self.cursor_moved.emit(self._cursor.x(), self._cursor.y())
        if self._drag is not None:
            d = event.position() - self._drag
            self._tx, self._ty = self._tx + d.x(), self._ty + d.y()
            self._drag = event.position()
            self._user_moved = True
        self.update()

    def mouseReleaseEvent(self, event):
        self._drag = None
        self.unsetCursor()

    def mouseDoubleClickEvent(self, event):
        self._user_moved = False
        self.fit()

    def leaveEvent(self, event):
        self._cursor = None
        self.cursor_left.emit()
        self.update()
        super().leaveEvent(event)

    # --- drawing -------------------------------------------------------------

    def paint_background(self, p: QPainter) -> None:
        t = theme.current()
        paint_canvas(p, self)
        p.setTransform(self.transform())
        if self.plate:
            p.setPen(_pen(t["border_hi"], 1))
            p.setBrush(QColor(t["plate"]))
            p.drawRect(self._bounds)
            p.setBrush(Qt.NoBrush)
        if self.show_grid:
            self._paint_grid(p)

    def _paint_grid(self, p: QPainter) -> None:
        step = self.grid_step()
        area = self.transform().inverted()[0].mapRect(QRectF(self.rect()))
        if self.plate:
            area = area.intersected(self._bounds)
        if area.isEmpty():
            return
        lines = []
        x = math.ceil(area.left() / step) * step
        while x <= area.right():
            lines.append(QLineF(x, area.top(), x, area.bottom()))
            x += step
        y = math.ceil(area.top() / step) * step
        while y <= area.bottom():
            lines.append(QLineF(area.left(), y, area.right(), y))
            y += step
        p.setPen(_pen(theme.current()["grid"]))
        p.drawLines(lines)

    def paint_overlays(self, p: QPainter) -> None:
        if self.show_grid:
            _overlay_text(p, self, f"grid {self.grid_step():g} mm", "bottom-left")
        if self._cursor is not None:
            _overlay_text(p, self, f"x {self._cursor.x():.2f}   y {self._cursor.y():.2f} mm", "bottom-right")


class LayerView(PlateView):
    """One sliced layer: outlines (holes in blue), hatches, travel moves, scan order, playback."""

    playback_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layers: list[Layer] = []
        self.index = 0
        self.show_contours = True
        self.show_hatches = True
        self.show_travel = False
        self.scan_order = False
        self._cache: dict[int, tuple] = {}
        self._reveal: float | None = None  # share of the layer's scan shown while playing
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // FPS)
        self._timer.timeout.connect(self._tick)

    def set_layers(self, layers: list[Layer], plate: tuple[float, float] | None = None) -> None:
        self.stop_scan()
        self.layers, self.plate, self.index = layers, plate, 0
        self._cache.clear()
        self.refresh_bounds()

    def set_index(self, index: int) -> None:
        self.index = max(0, min(index, len(self.layers) - 1))
        if self._reveal is not None:
            self._reveal = 0.0  # replay the new layer
        self.update()

    def set_option(self, name: str, on: bool) -> None:
        setattr(self, name, on)
        self.update()

    # --- laser playback ------------------------------------------------------------

    def playing(self) -> bool:
        return self._timer.isActive()

    def play_scan(self) -> None:
        if not self.layers:
            return
        self._reveal = 0.0
        self._timer.start()
        self.playback_changed.emit(True)
        self.update()

    def stop_scan(self) -> None:
        was = self._timer.isActive()
        self._timer.stop()
        self._reveal = None
        if was:
            self.playback_changed.emit(False)
        self.update()

    def _tick(self) -> None:
        self._reveal += 1 / (SCAN_SECONDS * FPS)
        if self._reveal >= 1:
            self.stop_scan()
        self.update()

    # --- drawing -------------------------------------------------------------

    def content_bounds(self) -> QRectF | None:
        pts = [np.asarray(c.points).reshape(-1, 2) for l in self.layers for c in l.contours]
        if not pts:
            return None
        pts = np.concatenate(pts)
        (x0, y0), (x1, y1) = pts.min(axis=0), pts.max(axis=0)
        return QRectF(x0, y0, max(x1 - x0, 1e-3), max(y1 - y0, 1e-3))

    def _geometry(self, i: int):
        """World-space drawing data for layer i, cached."""
        if i not in self._cache:
            layer = self.layers[i]
            contours = [(QPolygonF([QPointF(x, y) for x, y in np.asarray(c.points)]), c.is_hole)
                        for c in layer.contours]
            segs = (np.concatenate([np.asarray(h.segments).reshape(-1, 2, 2) for h in layer.hatches])
                    if layer.hatches else np.empty((0, 2, 2)))
            hatches = [QLineF(a[0], a[1], b[0], b[1]) for a, b in segs]
            # laser-off jumps, in scan order: contours first, then hatches (as exported)
            starts = [np.asarray(c.points)[0] for c in layer.contours] + list(segs[:, 0])
            ends = [np.asarray(c.points)[-1] for c in layer.contours] + list(segs[:, 1])
            travel = [QLineF(e[0], e[1], s[0], s[1]) for e, s in zip(ends[:-1], starts[1:])]
            if len(self._cache) > 64:  # keep memory bounded on tall builds
                self._cache.clear()
            self._cache[i] = (contours, hatches, travel)
        return self._cache[i]

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p)
        if self.layers:
            self._paint_layer(p)
        self.paint_overlays(p)

    def _paint_layer(self, p: QPainter) -> None:
        t = theme.current()
        contours, hatches, travel = self._geometry(self.index)
        n_c = len(contours)
        if self._reveal is None:
            k = n_c + len(hatches)
        else:
            k = int(self._reveal * (n_c + len(hatches)))
        shown_c, shown_h = contours[:min(k, n_c)], hatches[:max(0, k - n_c)]

        if self.show_travel and travel and self._reveal is None:
            p.setPen(_pen(t["muted"], 0, Qt.DashLine))
            p.drawLines(travel)
        if self.show_hatches and shown_h:
            if self.scan_order:  # first vector yellow -> last vector purple
                n = max(len(hatches) - 1, 1)
                for i, line in enumerate(shown_h):
                    p.setPen(_pen(QColor.fromHslF((50 + 230 * i / n) / 360, 0.85, 0.52)))
                    p.drawLine(line)
            else:
                p.setPen(_pen(_alpha(t["hatch"], 200)))
                p.drawLines(shown_h)
        if self.show_contours:
            for width, a in ((7, 40), (3.5, 70)):  # soft glow under the line
                for poly, hole in shown_c:
                    p.setPen(_pen(_alpha(t["hole"] if hole else t["accent"], a), width))
                    p.drawPolygon(poly)
            for poly, hole in shown_c:
                p.setPen(_pen(t["hole"] if hole else t["accent_glow"], 1.4))
                p.drawPolygon(poly)

        if self._reveal is not None and k:  # the laser spot, glowing
            if k <= n_c:
                poly = contours[k - 1][0]
                spot = poly.at(poly.size() - 1)
            else:
                spot = hatches[k - n_c - 1].p2()
            s = self.transform().map(spot)
            p.resetTransform()
            glow = QRadialGradient(s, 18)
            glow.setColorAt(0, _alpha("#fde68a", 230))
            glow.setColorAt(0.25, _alpha("#fb923c", 160))
            glow.setColorAt(1, _alpha("#fb923c", 0))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(s, 18, 18)
            p.setBrush(QColor("#fffbeb"))
            p.drawEllipse(s, 2.5, 2.5)


class LayoutView(PlateView):
    """The build seen from above: every part's footprint, coloured by stacking level."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[tuple[QRectF, str, str, int]] = []  # rect mm, name, detail, level

    def set_items(self, items: list[tuple[QRectF, str, str, int]],
                  plate: tuple[float, float] | None = None) -> None:
        # draw lower levels first so stacked parts sit on top
        self.items, self.plate = sorted(items, key=lambda it: it[3]), plate
        self.refresh_bounds()

    def item_at(self, pos: QPointF):
        """The topmost part under a widget position, or None."""
        w = self.to_world(pos)
        hits = [it for it in self.items if it[0].contains(w)]
        return hits[-1] if hits else None

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            item = self.item_at(QPointF(e.pos()))
            if item:
                rect, name, detail, _ = item
                QToolTip.showText(e.globalPos(), f"{name}\n{detail}\n{rect.width():.1f} × {rect.height():.1f} mm "
                                                 f"at x {rect.left():.1f}, y {rect.top():.1f}", self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def content_bounds(self) -> QRectF | None:
        if not self.items:
            return None
        r = QRectF(self.items[0][0])
        for rect, *_ in self.items[1:]:
            r = r.united(rect)
        return r.adjusted(-5, -5, 5, 5)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p)
        for rect, _, _, level in self.items:
            color = LEVELS[level % len(LEVELS)]
            p.setPen(_pen(color, 1.6))
            p.setBrush(_alpha(color, 46))
            p.drawRoundedRect(rect, 1.2, 1.2)
        p.setBrush(Qt.NoBrush)
        # labels in screen space so they stay readable at any zoom
        tr = self.transform()
        p.resetTransform()
        fm = QFontMetrics(self.font())
        for rect, name, detail, _ in self.items:
            box = tr.mapRect(rect).adjusted(6, 5, -6, -5)
            if box.width() < 30 or box.height() < fm.height():
                continue
            lines = [name, detail] if box.height() >= 2 * fm.height() else [name]
            for k, text in enumerate(lines):
                p.setPen(theme.color("text" if k == 0 else "muted"))
                text = fm.elidedText(text, Qt.ElideRight, int(box.width()))
                p.drawText(QPointF(box.left(), box.top() + fm.ascent() + k * fm.height()), text)
        self.paint_overlays(p)


class StackView(QWidget):
    """The sliced contours stacked in 3D. Drag to orbit, scroll to zoom, double-click to reset.

    Layers above the selected one are drawn faintly, so the selected layer reads
    as a cut through the part.
    """

    MAX_POINTS = 60000          # points drawn per frame at rest
    MAX_POINTS_DRAGGING = 18000  # ... and while orbiting, to stay smooth
    MAX_CONTOUR_POINTS = 160

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setFocusPolicy(Qt.StrongFocus)
        self.layers: list[tuple[float, list[np.ndarray]]] = []
        self.index = 0
        self._center = np.zeros(3)
        self._radius = 50.0
        self._points = 0
        self.reset_view()
        self._drag = None

    def reset_view(self) -> None:
        self.yaw, self.elev, self.zoom = math.radians(-35), math.radians(32), 1.0
        self.update()

    def set_layers(self, layers: list[Layer]) -> None:
        data, lo, hi = [], np.full(3, np.inf), np.full(3, -np.inf)
        self._points = 0
        for layer in layers:
            contours = []
            for c in layer.contours:
                pts = np.asarray(c.points, dtype=float).reshape(-1, 2)
                if len(pts) > self.MAX_CONTOUR_POINTS:
                    pts = pts[np.linspace(0, len(pts) - 1, self.MAX_CONTOUR_POINTS).astype(int)]
                contours.append(pts)
                self._points += len(pts)
                lo[:2], hi[:2] = np.minimum(lo[:2], pts.min(axis=0)), np.maximum(hi[:2], pts.max(axis=0))
            lo[2], hi[2] = min(lo[2], layer.z), max(hi[2], layer.z)
            data.append((float(layer.z), contours))
        self.layers, self.index = data, 0
        if np.isfinite(lo).all():
            lo[2] = 0.0
            self._center = (lo + hi) / 2
            self._radius = max(float(np.linalg.norm(hi - lo)) / 2, 1.0)
        self.update()

    def set_index(self, index: int) -> None:
        self.index = max(0, min(index, len(self.layers) - 1))
        self.update()

    # --- interaction -----------------------------------------------------------

    def mousePressEvent(self, event):
        self._drag = event.position()
        self.setCursor(Qt.ClosedHandCursor)

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
        self.unsetCursor()
        self.update()  # full detail again

    def wheelEvent(self, event):
        self.zoom = min(max(self.zoom * 1.0015 ** event.angleDelta().y(), 0.2), 20)
        self.update()

    def mouseDoubleClickEvent(self, event):
        self.reset_view()

    # --- drawing -------------------------------------------------------------

    def _projector(self):
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        ce, se = math.cos(self.elev), math.sin(self.elev)
        scale = self.zoom * min(self.width(), self.height()) * 0.42 / self._radius
        ox, oy = self.width() / 2, self.height() / 2
        cx, cyy, cz = self._center

        def project(pts: np.ndarray, z: float) -> QPolygonF:
            x, y = pts[:, 0] - cx, pts[:, 1] - cyy
            across = x * cy - y * sy
            depth = x * sy + y * cy
            up = (z - cz) * ce + depth * se
            sx, sy_ = ox + across * scale, oy - up * scale
            return QPolygonF([QPointF(a, b) for a, b in zip(sx.tolist(), sy_.tolist())])

        return project

    def paintEvent(self, event):
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        paint_canvas(p, self)
        if not self.layers:
            return
        project = self._projector()

        # the build plate under the part
        lo = self._center[:2] - self._radius * 0.75
        hi = self._center[:2] + self._radius * 0.75
        plate = np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]])
        p.setPen(_pen(t["border_hi"], 1))
        p.setBrush(_alpha(t["plate"], 255))
        p.drawPolygon(project(plate, 0.0))
        p.setBrush(Qt.NoBrush)

        n = len(self.layers)
        budget = self.MAX_POINTS_DRAGGING if self._drag is not None else self.MAX_POINTS
        step = max(1, math.ceil(self._points / budget))
        low, high = t["faint"], t["accent"]
        for i in range(0, n, step):
            if i == self.index:
                continue
            z, contours = self.layers[i]
            if i < self.index:
                color = _mix(low, high, 0.15 + 0.6 * i / max(n - 1, 1))
                color.setAlpha(150)
            else:
                color = _alpha(t["muted"], 34)  # above the cut: a ghost
            p.setPen(_pen(color, 1))
            for pts in contours:
                p.drawPolygon(project(pts, z))

        # the selected layer: a filled, outlined cut. Outlines run counter-clockwise and
        # holes clockwise, so non-zero winding leaves the holes open from any angle.
        z, contours = self.layers[self.index]
        cut = QPainterPath()
        cut.setFillRule(Qt.WindingFill)
        for pts in contours:
            cut.addPolygon(project(pts, z))
            cut.closeSubpath()
        p.setBrush(Qt.NoBrush)
        for width, a in ((8, 35), (4, 70)):  # glow
            p.setPen(_pen(_alpha(t["accent"], a), width))
            p.drawPath(cut)
        p.setPen(_pen(t["accent_glow"], 1.6))
        p.setBrush(_alpha(t["accent"], 70))
        p.drawPath(cut)
        _overlay_text(p, self, f"z {z:.2f} mm", "bottom-right")
        _overlay_text(p, self, "drag to orbit · scroll to zoom · double-click to reset", "bottom-left")
