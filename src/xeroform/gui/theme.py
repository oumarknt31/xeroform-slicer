"""Look and feel: colour tokens, the app style sheet, line icons and the XeroForm logo.

Two themes: dark graphite (the default) and a light theme in soft greys, both
with a single orange accent. Widgets and views read their colours from
`current()`; `apply()` switches theme for the whole app.
"""

from __future__ import annotations
import atexit
import os
import shutil
import tempfile

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSETS = os.path.join(os.path.dirname(__file__), "assets")
ACCENT = "#ff6b1a"  # laser orange

DARK = {  # graphite
    "bg": "#0b0d10",
    "bg2": "#0e1115",
    "header": "#12151a",
    "header2": "#0d1014",
    "surface": "#13161b",
    "surface_hi": "#181c22",
    "surface2": "#1c2027",
    "raised": "#232831",
    "base": "#0e1115",
    "canvas": "#08090c",
    "canvas_hi": "#121720",
    "plate": "#11151b",
    "border": "#242931",
    "border_hi": "#2f3540",
    "text": "#e9ebef",
    "muted": "#8b93a1",
    "faint": "#4e5664",
    "accent": ACCENT,
    "accent2": "#ff8a3d",
    "accent_hover": "#ff8540",
    "accent_glow": "#ffb37a",
    "accent_text": "#170a02",
    "accent_soft": "#2a1a10",
    "accent_line": "#6a3314",
    "hole": "#5aa9ff",
    "hatch": "#8f98a8",
    "grid": "#151a21",
    "warn_bg": "#2a2010",
    "warn_border": "#5c4614",
    "warn_text": "#f5c56b",
    "ok": "#3ddc97",
    "toast_bg": "#1d2229",
    "toast_text": "#e9ebef",
    "shadow": "#000000",
}
LIGHT = {  # soft greys, never white
    "bg": "#e3e5e9",
    "bg2": "#dadde2",
    "header": "#eceef1",
    "header2": "#e3e6ea",
    "surface": "#eceef1",
    "surface_hi": "#f2f3f5",
    "surface2": "#e1e4e9",
    "raised": "#d8dce2",
    "base": "#e7e9ed",
    "canvas": "#d3d7de",
    "canvas_hi": "#e4e7eb",
    "plate": "#e8eaee",
    "border": "#c8cdd5",
    "border_hi": "#f5f6f8",
    "text": "#15181d",
    "muted": "#5b6370",
    "faint": "#9aa1ab",
    "accent": "#e85d0c",
    "accent2": "#f57a2b",
    "accent_hover": "#d14f05",
    "accent_glow": "#f7a066",
    "accent_text": "#fff8f2",
    "accent_soft": "#f3d8c5",
    "accent_line": "#eaa77c",
    "hole": "#1f6fd1",
    "hatch": "#464d58",
    "grid": "#cbd0d7",
    "warn_bg": "#f1e2c1",
    "warn_border": "#d6b066",
    "warn_text": "#6b4300",
    "ok": "#14904f",
    "toast_bg": "#1d2229",
    "toast_text": "#e9ebef",
    "shadow": "#59606b",
}
MODES = ("dark", "light", "system")
DEFAULT_MODE = "dark"

_current = dict(DARK)
_mode = DEFAULT_MODE


def current() -> dict:
    """The active colour tokens."""
    return _current


def color(name: str) -> QColor:
    return QColor(_current[name])


def mode() -> str:
    return _mode


def is_dark() -> bool:
    return _current is DARK or _current.get("bg") == DARK["bg"]


def _system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return False


def apply(app, mode: str = DEFAULT_MODE) -> None:
    """Switch to `mode` ("dark", "light" or "system") and restyle the whole app."""
    global _mode
    _mode = mode if mode in MODES else DEFAULT_MODE
    dark = _system_is_dark() if _mode == "system" else _mode == "dark"
    _current.clear()
    _current.update(DARK if dark else LIGHT)
    sheet = _stylesheet()
    if app.styleSheet() == sheet and app.style().name().lower() == "fusion":
        return  # unchanged: re-applying would re-style every widget for nothing
    app.setStyle("Fusion")  # the one style that honours the whole style sheet everywhere
    app.setPalette(_palette())
    app.setStyleSheet(sheet)
    _icon_cache.clear()


def _palette() -> QPalette:
    t, p = _current, QPalette()
    roles = {
        QPalette.Window: t["bg"],
        QPalette.WindowText: t["text"],
        QPalette.Base: t["base"],
        QPalette.AlternateBase: t["surface2"],
        QPalette.Text: t["text"],
        QPalette.Button: t["surface"],
        QPalette.ButtonText: t["text"],
        QPalette.Highlight: t["accent"],
        QPalette.HighlightedText: t["accent_text"],
        QPalette.ToolTipBase: t["surface"],
        QPalette.ToolTipText: t["text"],
        QPalette.PlaceholderText: t["muted"],
        QPalette.Mid: t["border"],
        QPalette.Midlight: t["grid"],
        QPalette.Link: t["accent"],
    }
    for role, value in roles.items():
        p.setColor(role, QColor(value))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(t["muted"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(t["muted"]))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(t["muted"]))
    return p


_image_dir: str | None = None


def _private_dir() -> str:
    """A folder only this process uses: mkdtemp makes it owner-only (0700) with a
    random name, so another user can't pre-create it or plant links in it (as they
    could with a fixed name in a shared /tmp). Removed when the app exits."""
    global _image_dir
    if _image_dir is None:
        _image_dir = tempfile.mkdtemp(prefix="xeroform-theme-")
        atexit.register(shutil.rmtree, _image_dir, True)
    return _image_dir


def _icon_file(name: str, color: str) -> str:
    """An icon saved as PNG, for style sheets (which need image files)."""
    path = os.path.join(_private_dir(), f"{name}-{color.strip('#')}.png")
    if not os.path.exists(path):
        icon(name, color).pixmap(32, 32).save(path)
    return path.replace("\\", "/")


def _stylesheet() -> str:
    t = dict(
        _current,
        check=_icon_file("check-mark", _current["accent_text"]),
        chevron=_icon_file("chevron-down", _current["muted"]),
        up=_icon_file("chevron-up", _current["muted"]),
    )
    return """
* {{ outline: 0; }}
QWidget {{ color: {text}; font-size: 13px; }}
QMainWindow {{ background: {bg}; }}
QWidget#root {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {bg}, stop:1 {bg2}); }}

QFrame#header {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {header}, stop:1 {header2});
                 border: none; }}
QFrame#accentLine {{ min-height: 1px; max-height: 1px; border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 transparent, stop:0.35 {accent_line},
                                stop:0.5 {accent}, stop:0.65 {accent_line}, stop:1 transparent); }}
QLabel#wordmark {{ font-size: 18px; font-weight: 800; }}
QLabel#wordmarkSub {{ color: {accent}; font-size: 11px; font-weight: 700; }}
QFrame#pill {{ background: {base}; border: 1px solid {border}; border-radius: 15px; }}
QLabel#pillTitle {{ font-weight: 600; }}
QLabel#muted, QLabel#hint {{ color: {muted}; }}
QLabel#hint {{ font-size: 12px; }}
QLabel#dirtyDot {{ color: {accent}; font-size: 16px; }}

QFrame#card {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {surface_hi}, stop:1 {surface});
               border: 1px solid {border}; border-top: 1px solid {border_hi}; border-radius: 14px; }}
QFrame#card QLabel, QFrame#card QCheckBox {{ background: transparent; }}
QToolButton#cardHeader {{ color: {muted}; font-weight: 700; font-size: 11px; padding: 2px 0; }}
QToolButton#cardHeader:hover {{ background: transparent; color: {accent}; }}

QPushButton {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {raised}, stop:1 {surface2});
               border: 1px solid {border}; border-top-color: {border_hi}; border-radius: 9px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {accent_line}; }}
QPushButton:pressed {{ background: {surface2}; }}
QPushButton:disabled {{ color: {faint}; background: {surface2}; border-color: {border}; }}
QPushButton#primary {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {accent2}, stop:1 {accent});
                       color: {accent_text}; border: 1px solid {accent}; font-weight: 700; padding: 8px 22px; }}
QPushButton#primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {accent_glow}, stop:1 {accent2}); }}
QPushButton#primary:disabled {{ background: {surface2}; border-color: {border}; color: {faint}; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 5px 9px; }}
QToolButton:hover {{ background: {surface2}; border-color: {border}; }}
QToolButton:pressed {{ background: {raised}; }}
QToolButton:disabled {{ color: {faint}; }}
QToolButton#chip {{ border: 1px solid {border}; border-radius: 13px; padding: 3px 11px; color: {muted}; }}
QToolButton#chip:hover {{ color: {text}; }}
QToolButton#chip:checked {{ background: {accent_soft}; border-color: {accent_line}; color: {text}; }}
QFrame#segmented {{ background: {base}; border: 1px solid {border}; border-radius: 11px; }}
QToolButton#segment {{ border-radius: 8px; padding: 5px 13px; color: {muted}; }}
QToolButton#segment:checked {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {raised}, stop:1 {surface2});
                              border: 1px solid {border_hi}; color: {text}; font-weight: 600; }}

QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit {{ background: {base}; border: 1px solid {border};
    border-radius: 7px; padding: 4px 8px; min-height: 20px; selection-background-color: {accent};
    selection-color: {accent_text}; }}
QDoubleSpinBox:hover, QSpinBox:hover, QComboBox:hover {{ border-color: {border_hi}; }}
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus, QLineEdit:focus {{ border-color: {accent}; }}
QDoubleSpinBox:disabled, QSpinBox:disabled {{ color: {faint}; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ border: none; background: transparent; width: 16px; }}
QAbstractSpinBox::up-arrow {{ image: url({up}); width: 9px; height: 9px; }}
QAbstractSpinBox::down-arrow {{ image: url({chevron}); width: 9px; height: 9px; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({chevron}); width: 11px; height: 11px; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border}; border-radius: 8px;
    padding: 4px; selection-background-color: {accent_soft}; selection-color: {text}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {border_hi};
    background: {base}; }}
QCheckBox::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; image: url({check}); }}

QTableWidget {{ background: transparent; border: none; gridline-color: transparent;
    selection-background-color: {accent_soft}; selection-color: {text}; }}
QTableWidget::item {{ padding: 4px; border-bottom: 1px solid {border}; }}
QHeaderView::section {{ background: transparent; border: none; border-bottom: 1px solid {border};
    color: {muted}; padding: 4px; font-weight: 700; font-size: 11px; }}

QProgressBar {{ background: {base}; border: 1px solid {border}; border-radius: 4px; max-height: 8px; min-height: 8px; }}
QProgressBar::chunk {{ border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {accent}, stop:1 {accent_glow}); }}

QSlider::groove:vertical {{ background: {base}; border: 1px solid {border}; width: 6px; border-radius: 3px; }}
QSlider::add-page:vertical {{ border-radius: 3px; width: 6px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {accent_glow}, stop:1 {accent}); }}
QSlider::sub-page:vertical {{ background: {base}; border-radius: 3px; width: 6px; }}
QSlider::handle:vertical {{ background: {surface_hi}; border: 2px solid {accent}; height: 14px; width: 14px;
    margin: 0 -6px; border-radius: 9px; }}
QSlider::handle:vertical:hover {{ background: {accent_soft}; }}

QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {raised}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {raised}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QPlainTextEdit {{ background: {base}; border: 1px solid {border}; border-radius: 9px; padding: 8px;
    font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 12px; color: {muted}; }}
QSplitter::handle {{ background: transparent; width: 8px; }}

QFrame#banner {{ background: {warn_bg}; border: 1px solid {warn_border}; border-radius: 12px; }}
QFrame#banner QLabel {{ color: {warn_text}; background: transparent; }}
QFrame#tile {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {surface_hi}, stop:1 {surface});
               border: 1px solid {border}; border-top-color: {border_hi}; border-radius: 12px; }}
QFrame#tile QLabel {{ background: transparent; }}
QFrame#tileBar {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {accent_glow}, stop:1 {accent});
                  border-radius: 2px; min-width: 3px; max-width: 3px; }}
QLabel#tileValue {{ font-size: 19px; font-weight: 700; }}
QLabel#tileLabel {{ color: {muted}; font-size: 11px; font-weight: 700; }}
QFrame#toast {{ background: {toast_bg}; border: 1px solid {border_hi}; border-radius: 12px; }}
QFrame#toast QLabel {{ color: {toast_text}; background: transparent; }}
QLabel#emptyTitle {{ font-size: 18px; font-weight: 700; }}

QMenuBar {{ background: {header}; }}
QMenuBar::item:selected {{ background: {surface2}; }}
QMenu {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {accent_soft}; color: {text}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}
QToolTip {{ background: {surface_hi}; color: {text}; border: 1px solid {border_hi}; border-radius: 7px; padding: 5px 7px; }}
QMessageBox {{ background: {surface}; }}
""".format(**t)


# --- icons ---------------------------------------------------------------------
# 24 x 24 line icons, stroke 2 (fills marked fill=). Drawn for XeroForm.

_ICONS = {
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "save": '<path d="M5 3h11l3 3v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/>'
    '<path d="M7 3v5h8V3M7 21v-7h10v7"/>',
    "add": '<rect x="3" y="3" width="18" height="18" rx="4"/><path d="M12 8v8M8 12h8"/>',
    "slice": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 12.5l9 5 9-5"/><path d="M3 16.5l9 5 9-5"/>',
    "export": '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
    "drop": '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
    "play": '<path fill="C" stroke="none" d="M7 4.5v15a1 1 0 0 0 1.5.9l12-7.5a1 1 0 0 0 0-1.8l-12-7.5A1 1 0 0 0 7 4.5z"/>',
    "pause": '<rect fill="C" stroke="none" x="6" y="4" width="4" height="16" rx="1"/>'
    '<rect fill="C" stroke="none" x="14" y="4" width="4" height="16" rx="1"/>',
    "laser": '<circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4M5 5l2.5 2.5M16.5 16.5L19 19"/>',
    "film": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
    "fit": '<path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2'
    'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "auto": '<circle cx="12" cy="12" r="9"/><path fill="C" d="M12 3a9 9 0 0 1 0 18z"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    "clear": '<path d="M6 6l12 12M18 6L6 18"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "chevron-up": '<path d="M6 15l6-6 6 6"/>',
    "cube": '<path d="M12 2l9 5v10l-9 5-9-5V7z"/><path d="M3 7l9 5 9-5M12 12v10"/>',
    "layout": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/>'
    '<rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "warning": '<path d="M12 3.5l9.5 17h-19z"/><path d="M12 10v4.5M12 17.5v.01"/>',
    "ok": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.8 2.8L16 9.8"/>',
    "check-mark": '<path stroke-width="3" d="M5 12.5l4.5 4.5L19 7.5"/>',
    "stop": '<rect fill="C" stroke="none" x="6" y="6" width="12" height="12" rx="2"/>',
    "logo": '<rect fill="C" stroke="none" x="2" y="2" width="20" height="20" rx="5"/>',
}

_icon_cache: dict[tuple[str, str], QIcon] = {}


def icon(name: str, color: str | None = None) -> QIcon:
    """A line icon tinted with `color` (default: the text colour)."""
    color = color or _current["text"]
    key = (name, color)
    if key not in _icon_cache:
        body = _ICONS[name].replace('fill="C"', f'fill="{color}"')
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
        )
        renderer = QSvgRenderer(QByteArray(svg.encode()))
        ic = QIcon()
        for size in (16, 20, 24, 32, 48, 64):
            pix = QPixmap(size, size)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            renderer.render(p, QRectF(0, 0, size, size))
            p.end()
            ic.addPixmap(pix)
        _icon_cache[key] = ic
    return _icon_cache[key]


def _logo_svg(name: str, color: str | None = None) -> QByteArray:
    with open(os.path.join(ASSETS, name), encoding="utf-8") as f:
        svg = f.read()
    if color:
        svg = svg.replace('fill="#fff"', f'fill="{color}"')
    return QByteArray(svg.encode())


def app_icon() -> QIcon:
    """The XeroForm logo: the white mark on its black rounded tile."""
    renderer = QSvgRenderer(_logo_svg("xeroform-icon.svg"))
    ic = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        renderer.render(p, QRectF(0, 0, size, size * 110 / 112))
        p.end()
        ic.addPixmap(pix)
    return ic


def mark_pixmap(height: int, color: str | None = None, dpr: float = 2.0) -> QPixmap:
    """The XeroForm mark alone (no tile), tinted `color` (default: the text colour)."""
    renderer = QSvgRenderer(_logo_svg("xeroform-mark.svg", color or _current["text"]))
    size = renderer.defaultSize()
    w = round(height * size.width() / size.height())
    pix = QPixmap(round(w * dpr), round(height * dpr))
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, pix.width(), pix.height()))
    p.end()
    pix.setDevicePixelRatio(dpr)
    return pix
