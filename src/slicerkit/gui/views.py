"""Plate views: one sliced layer (LayerView) and the packed build from above (LayoutView).

Both share PlateView: model coordinates in mm with +y up, scroll to zoom, drag
to pan, double-click to fit, a mm grid that adapts to the zoom, and the cursor
position reported in mm.
"""
from __future__ import annotations
import math

import numpy as np
from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QToolTip, QWidget

from ..layers import Layer

OUTER = QColor("#c2410c")
HOLE = QColor("#2563eb")
LEVELS = [QColor(c) for c in ("#2563eb", "#c2410c", "#059669", "#7c3aed", "#d97706", "#db2777")]
MARGIN = 24                       # px around the fitted view
GRID_STEPS = (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000)
MIN_GRID_PX = 36                  # grid lines at least this far apart on screen


def _cosmetic(color: QColor, width: float = 0, style=Qt.SolidLine) -> QPen:
    pen = QPen(color, width, style)
    pen.setCosmetic(True)
    return pen


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

    # subclasses: the world rect worth fitting when there is no plate
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
        w = self.to_world(event.position())
        self.cursor_moved.emit(w.x(), w.y())
        if self._drag is None:
            return
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
        self.cursor_left.emit()
        super().leaveEvent(event)

    # --- drawing -------------------------------------------------------------

    def paint_background(self, p: QPainter) -> None:
        pal = self.palette()
        p.fillRect(self.rect(), pal.window())
        p.setTransform(self.transform())
        if self.plate:
            p.setPen(_cosmetic(pal.mid().color()))
            p.setBrush(pal.base())
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
        color = QColor(self.palette().mid().color())
        color.setAlpha(70)
        lines = []
        x = math.ceil(area.left() / step) * step
        while x <= area.right():
            lines.append(QLineF(x, area.top(), x, area.bottom()))
            x += step
        y = math.ceil(area.top() / step) * step
        while y <= area.bottom():
            lines.append(QLineF(area.left(), y, area.right(), y))
            y += step
        p.setPen(_cosmetic(color))
        p.drawLines(lines)

    def paint_grid_label(self, p: QPainter) -> None:
        if not self.show_grid:
            return
        p.resetTransform()
        step = self.grid_step()
        p.setPen(self.palette().placeholderText().color())
        p.drawText(10, self.height() - 10, f"grid {step:g} mm")


class LayerView(PlateView):
    """One sliced layer: outlines (holes in blue), hatches, travel moves, scan order."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layers: list[Layer] = []
        self.index = 0
        self.show_contours = True
        self.show_hatches = True
        self.show_travel = False
        self.scan_order = False
        self._cache: dict[int, tuple] = {}

    def set_layers(self, layers: list[Layer], plate: tuple[float, float] | None = None) -> None:
        self.layers, self.plate, self.index = layers, plate, 0
        self._cache.clear()
        self.refresh_bounds()

    def set_index(self, index: int) -> None:
        self.index = max(0, min(index, len(self.layers) - 1))
        self.update()

    def set_option(self, name: str, on: bool) -> None:
        setattr(self, name, on)
        self.update()

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
        self.paint_grid_label(p)

    def _paint_layer(self, p: QPainter) -> None:
        pal = self.palette()
        contours, hatches, travel = self._geometry(self.index)
        if self.show_travel and travel:
            p.setPen(_cosmetic(pal.mid().color(), 0, Qt.DashLine))
            p.drawLines(travel)
        if self.show_hatches and hatches:
            if self.scan_order:  # first vector yellow -> last vector purple
                n = max(len(hatches) - 1, 1)
                for i, line in enumerate(hatches):
                    p.setPen(_cosmetic(QColor.fromHslF((50 + 230 * i / n) / 360, 0.85, 0.52)))
                    p.drawLine(line)
            else:
                p.setPen(_cosmetic(pal.text().color()))
                p.drawLines(hatches)
        if self.show_contours:
            for poly, hole in contours:
                p.setPen(_cosmetic(HOLE if hole else OUTER, 1.5))
                p.drawPolygon(poly)


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
            item = self.item_at(e.position() if hasattr(e, "position") else QPointF(e.pos()))
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
            fill = QColor(color)
            fill.setAlpha(40)
            p.setPen(_cosmetic(color, 1.5))
            p.setBrush(fill)
            p.drawRect(rect)
        p.setBrush(Qt.NoBrush)
        # labels in screen space so they stay readable at any zoom
        t = self.transform()
        p.resetTransform()
        fm = QFontMetrics(self.font())
        for rect, name, detail, _ in self.items:
            box = t.mapRect(rect).adjusted(4, 4, -4, -4)
            if box.width() < 30 or box.height() < fm.height():
                continue
            p.setPen(self.palette().text().color())
            lines = [name, detail] if box.height() >= 2 * fm.height() else [name]
            for k, text in enumerate(lines):
                text = fm.elidedText(text, Qt.ElideRight, int(box.width()))
                p.drawText(QPointF(box.left(), box.top() + fm.ascent() + k * fm.height()), text)
        self.paint_grid_label(p)
