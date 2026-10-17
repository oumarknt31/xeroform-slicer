"""Look and feel: colour tokens (light/dark), the app style sheet, and line icons.

Everything visual reads its colours from `current()`, so switching theme is one
call to `apply()`. Icons are small SVGs drawn for this app and tinted at runtime.
"""
from __future__ import annotations
import os
import tempfile

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

ACCENT = "#ea580c"  # laser orange

LIGHT = {
    "bg": "#f4f5f7", "surface": "#ffffff", "surface2": "#f0f1f4", "base": "#ffffff",
    "canvas": "#f7f8fa", "plate": "#ffffff", "border": "#e3e5ea", "text": "#14161a",
    "muted": "#6b7280", "accent": ACCENT, "accent_hover": "#c2410c", "accent_text": "#ffffff",
    "accent_soft": "#fdebdf", "hole": "#2563eb", "hatch": "#3f4451", "grid": "#e9ebef",
    "warn_bg": "#fff7e6", "warn_border": "#f5d08a", "warn_text": "#7a4b00",
    "ok": "#16a34a", "toast_bg": "#1f2329", "toast_text": "#f4f5f7",
}
DARK = {
    "bg": "#0e1014", "surface": "#171a20", "surface2": "#20242c", "base": "#1b1e25",
    "canvas": "#121419", "plate": "#1a1d24", "border": "#2b303a", "text": "#e8eaee",
    "muted": "#9aa1ad", "accent": "#fb923c", "accent_hover": "#fdba74", "accent_text": "#1a0d03",
    "accent_soft": "#3a2414", "hole": "#60a5fa", "hatch": "#c3c8d2", "grid": "#22262e",
    "warn_bg": "#2e2410", "warn_border": "#6b5216", "warn_text": "#f5d08a",
    "ok": "#4ade80", "toast_bg": "#e8eaee", "toast_text": "#14161a",
}
MODES = ("system", "light", "dark")

_current = dict(LIGHT)
_mode = "system"


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


def apply(app, mode: str = "system") -> None:
    """Switch to `mode` ("system", "light" or "dark") and restyle the whole app."""
    global _mode
    _mode = mode if mode in MODES else "system"
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
        QPalette.Window: t["bg"], QPalette.WindowText: t["text"], QPalette.Base: t["base"],
        QPalette.AlternateBase: t["surface2"], QPalette.Text: t["text"], QPalette.Button: t["surface"],
        QPalette.ButtonText: t["text"], QPalette.Highlight: t["accent"],
        QPalette.HighlightedText: t["accent_text"], QPalette.ToolTipBase: t["surface"],
        QPalette.ToolTipText: t["text"], QPalette.PlaceholderText: t["muted"], QPalette.Mid: t["border"],
        QPalette.Midlight: t["grid"], QPalette.Link: t["accent"],
    }
    for role, value in roles.items():
        p.setColor(role, QColor(value))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(t["muted"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(t["muted"]))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(t["muted"]))
    return p


def _icon_file(name: str, color: str) -> str:
    """An icon saved as PNG, for style sheets (which need image files)."""
    folder = os.path.join(tempfile.gettempdir(), "slicerkit-theme")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{name}-{color.strip('#')}.png")
    if not os.path.exists(path):
        icon(name, color).pixmap(32, 32).save(path)
    return path.replace("\\", "/")


def _stylesheet() -> str:
    t = dict(_current, check=_icon_file("check-mark", _current["accent_text"]),
             chevron=_icon_file("chevron-down", _current["muted"]))
    return """
* {{ outline: 0; }}
QWidget {{ color: {text}; font-size: 13px; }}
QMainWindow, QWidget#root {{ background: {bg}; }}
QFrame#header {{ background: {surface}; border-bottom: 1px solid {border}; }}
QLabel#appTitle {{ font-size: 15px; font-weight: 600; }}
QLabel#muted, QLabel#hint {{ color: {muted}; }}
QLabel#hint {{ font-size: 12px; }}

QFrame#card {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
QFrame#card QLabel {{ background: transparent; }}
QToolButton#cardHeader {{ font-weight: 600; font-size: 13px; padding: 2px 0; text-align: left; }}
QToolButton#cardHeader:hover {{ background: transparent; color: {accent}; }}

QPushButton {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 6px 12px; }}
QPushButton:hover {{ background: {surface2}; }}
QPushButton:pressed {{ background: {border}; }}
QPushButton:disabled {{ color: {muted}; background: {surface}; }}
QPushButton#primary {{ background: {accent}; color: {accent_text}; border: 1px solid {accent};
                       font-weight: 600; padding: 7px 18px; }}
QPushButton#primary:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
QPushButton#primary:disabled {{ background: {surface2}; border-color: {border}; color: {muted}; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 5px 8px; }}
QToolButton:hover {{ background: {surface2}; }}
QToolButton:pressed {{ background: {border}; }}
QToolButton:disabled {{ color: {muted}; }}
QToolButton#chip {{ border: 1px solid {border}; border-radius: 13px; padding: 3px 10px; }}
QToolButton#chip:checked {{ background: {accent_soft}; border-color: {accent}; }}
QFrame#segmented {{ background: {surface2}; border-radius: 9px; }}
QToolButton#segment {{ border-radius: 7px; padding: 5px 12px; }}
QToolButton#segment:checked {{ background: {surface}; border: 1px solid {border}; font-weight: 600; }}

QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit {{ background: {base}; border: 1px solid {border};
    border-radius: 6px; padding: 3px 6px; min-height: 20px; selection-background-color: {accent};
    selection-color: {accent_text}; }}
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus, QLineEdit:focus {{ border-color: {accent}; }}
QDoubleSpinBox:disabled, QSpinBox:disabled {{ color: {muted}; background: {surface2}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({chevron}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border}; border-radius: 6px;
    selection-background-color: {accent_soft}; selection-color: {text}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {border};
    background: {base}; }}
QCheckBox::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; image: url({check}); }}

QTableWidget {{ background: {surface}; border: none; gridline-color: transparent;
    selection-background-color: {accent_soft}; selection-color: {text}; }}
QTableWidget::item {{ padding: 4px; border-bottom: 1px solid {surface2}; }}
QHeaderView::section {{ background: transparent; border: none; border-bottom: 1px solid {border};
    color: {muted}; padding: 4px; font-weight: 600; font-size: 12px; }}

QProgressBar {{ background: {surface2}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}

QSlider::groove:vertical {{ background: {surface2}; width: 6px; border-radius: 3px; }}
QSlider::add-page:vertical {{ background: {accent}; border-radius: 3px; width: 6px; }}
QSlider::sub-page:vertical {{ background: {surface2}; border-radius: 3px; width: 6px; }}
QSlider::handle:vertical {{ background: {surface}; border: 3px solid {accent}; height: 12px; width: 12px;
    margin: 0 -6px; border-radius: 9px; }}
QSlider::groove:horizontal {{ background: {surface2}; height: 6px; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 3px; height: 6px; }}
QSlider::handle:horizontal {{ background: {surface}; border: 3px solid {accent}; height: 12px; width: 12px;
    margin: -6px 0; border-radius: 9px; }}

QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 3px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {border}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QPlainTextEdit {{ background: {base}; border: 1px solid {border}; border-radius: 8px; padding: 6px;
    font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 12px; }}
QSplitter::handle {{ background: transparent; width: 6px; }}

QFrame#banner {{ background: {warn_bg}; border: 1px solid {warn_border}; border-radius: 10px; }}
QFrame#banner QLabel {{ color: {warn_text}; background: transparent; }}
QFrame#tile {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; }}
QFrame#tile QLabel {{ background: transparent; }}
QLabel#tileValue {{ font-size: 17px; font-weight: 600; }}
QLabel#tileLabel {{ color: {muted}; font-size: 11px; }}
QFrame#toast {{ background: {toast_bg}; border-radius: 10px; }}
QFrame#toast QLabel {{ color: {toast_text}; background: transparent; }}
QLabel#emptyTitle {{ font-size: 17px; font-weight: 600; }}

QMenuBar {{ background: {surface}; }}
QMenu {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {accent_soft}; color: {text}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}
QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 4px 6px; }}
""".format(**t)


# --- icons ---------------------------------------------------------------------
# 24 x 24 line icons, stroke 2 (fills marked fill=). Drawn for slicerkit.

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
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
               f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
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


def app_icon() -> QIcon:
    """The app icon: powder layers and a laser beam on a dark tile."""
    pix = QPixmap(256, 256)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#15181e"))
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 56, 56)
    for i, y in enumerate((146, 172, 198)):
        p.setBrush(QColor(ACCENT) if i == 0 else QColor("#e5e7eb" if i == 1 else "#9ca3af"))
        p.drawRoundedRect(QRectF(52, y, 152, 16), 8, 8)
    p.setBrush(QColor(251, 146, 60, 90))
    p.drawEllipse(QRectF(104, 116, 48, 48))
    p.setBrush(QColor("#fdba74"))
    p.drawRoundedRect(QRectF(122, 44, 12, 100), 6, 6)
    p.end()
    return QIcon(pix)
