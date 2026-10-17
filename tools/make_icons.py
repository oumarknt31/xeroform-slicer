"""Render the XeroForm app icons from the logo SVG: .icns (macOS) and .ico (Windows).

python tools/make_icons.py      # writes packaging/xeroform.icns and packaging/xeroform.ico
"""

import io
import os
import sys

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = os.path.join(os.path.dirname(__file__), os.pardir)
SVG = os.path.join(ROOT, "src", "xeroform", "gui", "assets", "xeroform-icon.svg")
OUT = os.path.join(ROOT, "packaging")


def render(size: int, inset: float = 0.0) -> Image.Image:
    """The icon at `size` px; `inset` leaves a margin (macOS icons sit on an 824/1024 grid)."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    m = size * inset
    side = size - 2 * m
    QSvgRenderer(SVG).render(p, QRectF(m, m + side * (1 - 110 / 112) / 2, side, side * 110 / 112))
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data())))


def main() -> None:
    QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    os.makedirs(OUT, exist_ok=True)
    render(1024, inset=100 / 1024).save(os.path.join(OUT, "xeroform.icns"))
    big = render(256)
    big.save(os.path.join(OUT, "xeroform.ico"), sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print("wrote packaging/xeroform.icns, packaging/xeroform.ico")


if __name__ == "__main__":
    main()
