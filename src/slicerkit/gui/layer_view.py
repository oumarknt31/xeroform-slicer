"""A Qt widget that draws one sliced layer: outlines, hatches, travel moves.

Scroll to zoom, drag to pan, double-click to fit. Like the HTML preview, it only
reads slicerkit's Layer model.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QWidget

from ..layers import Layer

OUTER = QColor("#c2410c")
HOLE = QColor("#2563eb")
MARGIN = 24  # px around the fitted view


class LayerView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setMouseTracking(False)
        self.layers: list[Layer] = []
        self.index = 0
        self.plate: tuple[float, float] | None = None  # build plate size (x, y) mm, centred on 0
        self.show_contours = True
        self.show_hatches = True
        self.show_travel = False
        self.scan_order = False
        self._bounds = QRectF(-50, -50, 100, 100)  # world rect to fit
        self._scale, self._tx, self._ty = 1.0, 0.0, 0.0
        self._user_moved = False
        self._drag = None
        self._cache: dict[int, tuple] = {}

    # --- data ---------------------------------------------------------------

    def set_layers(self, layers: list[Layer], plate: tuple[float, float] | None = None) -> None:
        self.layers, self.plate, self.index = layers, plate, 0
        self._cache.clear()
        self._bounds = self._world_bounds()
        self._user_moved = False
        self._fit()
        self.update()

    def set_index(self, index: int) -> None:
        self.index = max(0, min(index, len(self.layers) - 1))
        self.update()

    def set_option(self, name: str, on: bool) -> None:
        setattr(self, name, on)
        self.update()

    def _world_bounds(self) -> QRectF:
        if self.plate:
            w, h = self.plate
            return QRectF(-w / 2, -h / 2, w, h)
        pts = [np.asarray(c.points).reshape(-1, 2) for l in self.layers for c in l.contours]
        if not pts:
            return QRectF(-50, -50, 100, 100)
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
            self._cache[i] = (contours, hatches, travel)
        return self._cache[i]

    # --- view transform -------------------------------------------------------

    def _fit(self) -> None:
        b = self._bounds
        w, h = max(self.width() - 2 * MARGIN, 1), max(self.height() - 2 * MARGIN, 1)
        self._scale = min(w / b.width(), h / b.height())
        self._tx = self.width() / 2 - self._scale * b.center().x()
        self._ty = self.height() / 2 + self._scale * b.center().y()  # model +y points up

    def _transform(self) -> QTransform:
        return QTransform(self._scale, 0, 0, -self._scale, self._tx, self._ty)

    def resizeEvent(self, event):
        if not self._user_moved:
            self._fit()
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
        self._fit()
        self.update()

    # --- drawing -------------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        p.fillRect(self.rect(), pal.window())
        p.setTransform(self._transform())

        if self.plate:
            p.setPen(Qt.NoPen)
            p.setBrush(pal.base())
            p.drawRect(self._bounds)
            p.setBrush(Qt.NoBrush)
        if not self.layers:
            return
        contours, hatches, travel = self._geometry(self.index)

        if self.show_travel and travel:
            pen = QPen(pal.mid().color(), 0, Qt.DashLine)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.drawLines(travel)
        if self.show_hatches and hatches:
            if self.scan_order:  # first vector yellow -> last vector purple
                n = max(len(hatches) - 1, 1)
                for i, line in enumerate(hatches):
                    pen = QPen(QColor.fromHslF((50 + 230 * i / n) / 360, 0.85, 0.52), 0)
                    pen.setCosmetic(True)
                    p.setPen(pen)
                    p.drawLine(line)
            else:
                pen = QPen(pal.text().color(), 0)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.drawLines(hatches)
        if self.show_contours:
            for poly, hole in contours:
                pen = QPen(HOLE if hole else OUTER, 1.5)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.drawPolygon(poly)
