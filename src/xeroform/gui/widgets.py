"""Small building blocks for the window: cards, stat tiles, toasts, chips, segments."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import theme


def shadow(widget: QWidget, color: str | None = None, blur: int = 22, dy: int = 4, alpha: int = 110) -> None:
    """A soft drop shadow (or, with an accent colour, a glow). Only for small widgets:
    Qt re-renders a shadowed widget offscreen on every repaint."""
    effect = QGraphicsDropShadowEffect(widget)
    c = QColor(color or theme.current()["shadow"])
    c.setAlpha(alpha)
    effect.setColor(c)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    widget.setGraphicsEffect(effect)


def spaced(widget: QWidget, spacing: float = 1.2) -> None:
    """Letter-spaced text, for small uppercase labels."""
    font = widget.font()
    font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    widget.setFont(font)


class Card(QFrame):
    """A rounded panel with a title; click the title to fold it away."""

    def __init__(self, title: str, collapsible: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 12)
        outer.setSpacing(8)
        head = QHBoxLayout()
        self.header = QToolButton()
        self.header.setObjectName("cardHeader")
        self.header.setText(title.upper())
        spaced(self.header)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setIconSize(QSize(14, 14))
        self.header.setCheckable(collapsible)
        self.header.setChecked(True)
        self.header.toggled.connect(self._toggle)
        head.addWidget(self.header)
        head.addStretch()
        self.trailing = QHBoxLayout()
        self.trailing.setSpacing(4)
        head.addLayout(self.trailing)
        outer.addLayout(head)
        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(8)
        outer.addWidget(self.content)
        self.collapsible = collapsible
        self.restyle()

    def _toggle(self, open_: bool) -> None:
        self.content.setVisible(open_)
        self.restyle()

    def restyle(self) -> None:
        if self.collapsible:
            self.header.setIcon(
                theme.icon("chevron-down" if self.header.isChecked() else "chevron-right", theme.current()["muted"])
            )


class StatTile(QFrame):
    """One headline number with a caption, e.g. "LASER TIME  1h 12m", on an accent bar."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("tile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 10, 12, 10)
        row.setSpacing(10)
        bar = QFrame()
        bar.setObjectName("tileBar")
        row.addWidget(bar)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.caption = QLabel(label.upper())
        self.caption.setObjectName("tileLabel")
        spaced(self.caption)
        self.value = QLabel("–")
        self.value.setObjectName("tileValue")
        col.addWidget(self.caption)
        col.addWidget(self.value)
        row.addLayout(col, 1)
        shadow(self, blur=18, dy=3, alpha=90)

    def set(self, value: str, tip: str = "") -> None:
        self.value.setText(value)
        self.setToolTip(tip)


class Segmented(QFrame):
    """A row of mutually exclusive buttons (like a tab bar). Emits the chosen index."""

    changed = Signal(int)

    def __init__(self, items: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setObjectName("segmented")
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[QToolButton] = []
        self._icons = [icon for _, icon in items]
        for i, (text, _) in enumerate(items):
            b = QToolButton()
            b.setObjectName("segment")
            b.setText(text)
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setIconSize(QSize(16, 16))
            self.group.addButton(b, i)
            self.buttons.append(b)
            row.addWidget(b)
        self.buttons[0].setChecked(True)
        self.group.idToggled.connect(lambda i, on: on and self.changed.emit(i))
        self.group.idToggled.connect(lambda *_: self.restyle())
        self.restyle()

    def index(self) -> int:
        return self.group.checkedId()

    def set_index(self, i: int) -> None:
        self.buttons[i].setChecked(True)

    def restyle(self) -> None:
        for b, name in zip(self.buttons, self._icons):
            b.setIcon(theme.icon(name, theme.current()["accent"] if b.isChecked() else theme.current()["muted"]))


def chip(text: str, checked: bool, tip: str = "") -> QToolButton:
    """A rounded on/off toggle for view options."""
    b = QToolButton()
    b.setObjectName("chip")
    b.setText(text)
    b.setCheckable(True)
    b.setChecked(checked)
    b.setToolTip(tip)
    return b


def tool_button(icon_name: str, text: str = "", tip: str = "") -> QToolButton:
    b = QToolButton()
    b.setProperty("iconName", icon_name)
    b.setIcon(theme.icon(icon_name))
    b.setIconSize(QSize(18, 18))
    if text:
        b.setText(text)
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    b.setToolTip(tip or text)
    b.setAccessibleName(text or tip)  # icon-only buttons still need a name for screen readers
    return b


class EmptyState(QWidget):
    """Shown instead of a blank view: an icon, a line of guidance and an action."""

    def __init__(self, icon_name: str, title: str, text: str, button: str | None = None, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        col = QVBoxLayout(self)
        col.addStretch()
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignCenter)
        self.title = QLabel(title)
        self.title.setObjectName("emptyTitle")
        self.title.setAlignment(Qt.AlignCenter)
        self.text = QLabel(text)
        self.text.setObjectName("muted")
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setWordWrap(True)
        for w in (self.picture, self.title, self.text):
            col.addWidget(w)
        self.button = None
        if button:
            self.button = QPushButton(button)
            self.button.setObjectName("primary")
            row = QHBoxLayout()
            row.addStretch()
            row.addWidget(self.button)
            row.addStretch()
            col.addSpacing(8)
            col.addLayout(row)
        col.addStretch()
        self.restyle()

    def set_text(self, title: str, text: str) -> None:
        self.title.setText(title)
        self.text.setText(text)

    def restyle(self) -> None:
        self.picture.setPixmap(theme.icon(self._icon_name, theme.current()["muted"]).pixmap(56, 56))


class Toast(QFrame):
    """A short message that fades in at the bottom right of its parent, then away."""

    def __init__(self, parent: QWidget, text: str, icon_name: str = "ok", ms: int = 3200):
        super().__init__(parent)
        self.setObjectName("toast")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 16, 10)
        mark = QLabel()
        mark.setPixmap(theme.icon(icon_name, theme.current()["toast_text"]).pixmap(16, 16))
        label = QLabel(text)
        label.setMaximumWidth(460)
        label.setWordWrap(True)
        row.addWidget(mark)
        row.addWidget(label)
        self.adjustSize()
        self._place()
        self.effect = QGraphicsOpacityEffect(self)  # (a widget takes one effect: fade, no shadow)
        self.setGraphicsEffect(self.effect)
        self.show()
        self.raise_()
        self._fade(0.0, 1.0)
        # the toast is the timer's context: if it is destroyed first (its window closed),
        # Qt cancels the timer instead of calling into a deleted widget
        QTimer.singleShot(ms, self, lambda: self._fade(1.0, 0.0, self.deleteLater))

    def _place(self) -> None:
        p = self.parentWidget()
        others = [w for w in p.findChildren(Toast) if w is not self and w.isVisible()]
        y = p.height() - self.height() - 20 - sum(w.height() + 8 for w in others)
        self.move(p.width() - self.width() - 20, max(y, 10))

    def _fade(self, start: float, end: float, then=None) -> None:
        anim = QPropertyAnimation(self.effect, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        if then:
            anim.finished.connect(then)
        anim.start()
