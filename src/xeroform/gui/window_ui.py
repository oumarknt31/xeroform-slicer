"""How the XeroForm window is laid out: header, sidebar, viewer and menus."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .constants import APP_NAME
from .orientation import OrientationPanel
from .panels import PartsPanel, SettingsPanel
from .views import LayerView, LayoutView, StackView
from .widgets import Card, EmptyState, Segmented, StatTile, chip, spaced, tool_button


def _keep_space(widget) -> None:
    """Keep a widget's space when it is hidden, so the layout doesn't jump."""
    policy = widget.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(policy)


class WindowLayoutMixin:
    """Builds the window's widgets; MainWindow supplies the behaviour they connect to."""

    # ===================================================================== layout

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("header")
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 10, 18, 10)
        row.setSpacing(6)
        self.logo = QLabel()
        self.logo.setPixmap(theme.app_icon().pixmap(36, 36))
        self.logo.setToolTip(APP_NAME)
        self.logo.setAccessibleName(f"{APP_NAME} logo")
        row.addWidget(self.logo)
        row.addSpacing(6)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        wordmark = QLabel(APP_NAME)
        wordmark.setObjectName("wordmark")
        sub_mark = QLabel("SLICER")
        sub_mark.setObjectName("wordmarkSub")
        spaced(sub_mark, 2.5)
        brand.addWidget(wordmark)
        brand.addWidget(sub_mark)
        row.addLayout(brand)
        row.addSpacing(22)

        self.open_button = tool_button("open", "Open", "Open a project (⌘O)")
        self.open_button.clicked.connect(lambda: self.open_project())
        self.save_button = tool_button("save", "Save", "Save the project (⌘S)")
        self.save_button.clicked.connect(self.save_project)
        self.header_add = tool_button("add", "Add models", "Add models (⌘I)")
        self.header_add.clicked.connect(self.add_models_dialog)
        for b in (self.open_button, self.save_button, self.header_add):
            row.addWidget(b)
        row.addStretch()

        # the project, as a pill in the middle
        pill = QFrame()
        pill.setObjectName("pill")
        pl = QHBoxLayout(pill)
        pl.setContentsMargins(14, 5, 14, 5)
        pl.setSpacing(8)
        self.dirty_dot = QLabel("●")
        self.dirty_dot.setObjectName("dirtyDot")
        self.dirty_dot.setToolTip("Unsaved changes")
        self.title_label = QLabel("Untitled")
        self.title_label.setObjectName("pillTitle")
        self.subtitle_label = QLabel("not saved yet")
        self.subtitle_label.setObjectName("hint")
        pl.addWidget(self.dirty_dot)
        pl.addWidget(self.title_label)
        pl.addWidget(self.subtitle_label)
        row.addWidget(pill)
        row.addStretch()

        self.theme_button = tool_button("moon", "", "Theme: switch between dark, light and system")
        self.theme_button.clicked.connect(self._cycle_theme)
        row.addWidget(self.theme_button)
        row.addSpacing(4)
        self.export_button = QPushButton("Export")
        self.export_button.setToolTip("Write the laser paths for the machine (⌘E)")
        self.export_button.clicked.connect(self.export_cli)
        row.addWidget(self.export_button)
        row.addSpacing(4)
        self.slice_button = QPushButton("Slice")
        self.slice_button.setObjectName("primary")
        self.slice_button.setToolTip("Slice all parts (⌘R)")
        self.slice_button.setMinimumWidth(120)
        self.slice_button.clicked.connect(self.start_slicing)
        row.addWidget(self.slice_button)
        return bar

    def _build_sidebar(self) -> QWidget:
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(10)
        self.parts = PartsPanel()
        self.orientation = OrientationPanel()
        self.settings = SettingsPanel()
        self._themed += [self.parts, self.orientation, self.settings]
        col.addWidget(self.parts)
        col.addWidget(self.orientation)
        col.addWidget(self.settings)
        col.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        side = QWidget()
        side.setMinimumWidth(400)
        side.setMaximumWidth(560)
        outer = QVBoxLayout(side)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        outer.addWidget(scroll, 1)

        self.progress_card = QFrame()
        self.progress_card.setObjectName("card")
        pc = QVBoxLayout(self.progress_card)
        pc.setContentsMargins(14, 10, 14, 10)
        top = QHBoxLayout()
        self.stage = QLabel("Working…")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        top.addWidget(self.stage, 1)
        top.addWidget(self.cancel_button)
        pc.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        pc.addWidget(self.progress)
        self.progress_card.hide()
        outer.addWidget(self.progress_card)
        return side

    def _build_main(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(6, 0, 0, 0)
        col.setSpacing(10)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 8, 8, 8)
        self.banner_icon = QLabel()
        text = QLabel("Parts or settings changed since this slice. The view is out of date and can't be exported.")
        text.setWordWrap(True)
        again = QPushButton("Slice again")
        again.setObjectName("primary")
        again.clicked.connect(self.start_slicing)
        bl.addWidget(self.banner_icon)
        bl.addWidget(text, 1)
        bl.addWidget(again)
        self.banner.hide()
        col.addWidget(self.banner)

        viewer = QFrame()
        viewer.setObjectName("card")
        vc = QVBoxLayout(viewer)
        vc.setContentsMargins(12, 10, 12, 10)
        vc.setSpacing(8)

        top = QHBoxLayout()
        self.view_switch = Segmented([("Layers", "slice"), ("3D", "cube"), ("Build layout", "layout")])
        self.view_switch.changed.connect(self._view_changed)
        self._themed.append(self.view_switch)
        top.addWidget(self.view_switch)
        top.addStretch()
        self.chips = {}
        for text, name, on, tip in [
            ("Outlines", "show_contours", True, "Part outlines (holes in blue)"),
            ("Hatches", "show_hatches", True, "Fill lines"),
            ("Travel", "show_travel", False, "Laser-off moves between lines"),
            ("Scan order", "scan_order", False, "Colour the fill from first (yellow) to last (purple)"),
            ("Grid", "show_grid", True, "mm grid"),
        ]:
            c = chip(text, on, tip)
            c.toggled.connect(lambda checked, n=name: self._set_view_option(n, checked))
            _keep_space(c)
            self.chips[name] = c
            top.addWidget(c)
        self.fit_button = tool_button("fit", "", "Fit the view (⌘0)")
        self.fit_button.setAccessibleName("Fit the view")
        self.fit_button.clicked.connect(self._fit_views)
        top.addWidget(self.fit_button)
        vc.addLayout(top)

        # views + the vertical layer slider, or an empty state before the first slice
        self.pages = QStackedWidget()
        self.empty = EmptyState("drop", "Drop models here", "STL, OBJ, PLY or 3MF. Or open a project.", "Add models")
        self.empty.button.clicked.connect(self.add_models_dialog)
        self._themed.append(self.empty)
        self.pages.addWidget(self.empty)

        stage = QWidget()
        sl = QHBoxLayout(stage)
        sl.setContentsMargins(0, 0, 0, 0)
        self.views = QStackedWidget()
        self.view = LayerView()
        self.stack_view = StackView()
        self.layout_view = LayoutView()
        for v, name in (
            (self.view, "Layer view"),
            (self.stack_view, "3D layer stack"),
            (self.layout_view, "Build layout"),
        ):
            v.setAccessibleName(name)
            self.views.addWidget(v)
        sl.addWidget(self.views, 1)
        rail = QVBoxLayout()
        rail.setSpacing(4)
        self.top_z = QLabel()
        self.top_z.setObjectName("hint")
        self.top_z.setAlignment(Qt.AlignHCenter)
        self.slider = QSlider(Qt.Vertical)
        self.slider.setAccessibleName("Layer")
        self.slider.setToolTip("Layer · ← → step · PgUp/PgDn ±10 · Home/End · Space plays the laser")
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._layer_changed)
        self.bottom_z = QLabel()
        self.bottom_z.setObjectName("hint")
        self.bottom_z.setAlignment(Qt.AlignHCenter)
        rail.addWidget(self.top_z)
        rail.addWidget(self.slider, 1, Qt.AlignHCenter)
        rail.addWidget(self.bottom_z)
        for part in (self.top_z, self.slider, self.bottom_z):
            _keep_space(part)
        sl.addLayout(rail)
        self.pages.addWidget(stage)
        vc.addWidget(self.pages, 1)

        bottom = QHBoxLayout()
        self.scan_button = tool_button("laser", "Play laser", "Animate the laser tracing this layer")
        self.scan_button.clicked.connect(self._toggle_scan)
        self.flip_button = tool_button("film", "Play layers", "Play through the layers like a flip-book")
        self.flip_button.clicked.connect(self._toggle_flipbook)
        self.view.playback_changed.connect(self._scan_state)
        _keep_space(self.scan_button)
        bottom.addWidget(self.scan_button)
        bottom.addWidget(self.flip_button)
        bottom.addSpacing(8)
        self.layer_info = QLabel("No slice yet.")
        self.layer_info.setObjectName("muted")
        self.layer_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bottom.addWidget(self.layer_info, 1)
        vc.addLayout(bottom)
        col.addWidget(viewer, 1)

        tiles = QGridLayout()
        tiles.setSpacing(10)
        self.tiles = {}
        for i, (key, label) in enumerate(
            [
                ("layers", "Layers"),
                ("height", "Build height"),
                ("time", "Laser time"),
                ("parts", "Parts"),
                ("density", "Packing"),
                ("energy", "Energy density"),
            ]
        ):
            tile = StatTile(label)
            self.tiles[key] = tile
            tiles.addWidget(tile, 0, i)
        col.addLayout(tiles)

        self.details = Card("Details")
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("The slicing report appears here.")
        self.report.setMinimumHeight(110)
        self.report.setMaximumHeight(170)
        self.details.body.addWidget(self.report)
        self.details.header.setChecked(False)
        self._themed.append(self.details)
        col.addWidget(self.details)

        # keyboard: step through layers while the viewer has focus
        for keys, step in [
            ((Qt.Key_Right, Qt.Key_Up), 1),
            ((Qt.Key_Left, Qt.Key_Down), -1),
            ((Qt.Key_PageUp,), 10),
            ((Qt.Key_PageDown,), -10),
        ]:
            for key in keys:
                QShortcut(
                    QKeySequence(key), viewer, lambda s=step: self._step(s), context=Qt.WidgetWithChildrenShortcut
                )
        QShortcut(QKeySequence(Qt.Key_Home), viewer, lambda: self._goto(0), context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence(Qt.Key_End), viewer, lambda: self._goto(10**9), context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence(Qt.Key_Space), viewer, self._toggle_scan, context=Qt.WidgetWithChildrenShortcut)
        return w

    def _build_menus(self) -> None:
        def action(text, slot, shortcut=None):
            a = QAction(text, self)
            if shortcut is not None:
                a.setShortcut(shortcut)
            a.triggered.connect(slot)
            self.addAction(a)  # shortcuts work with the menu bar hidden too
            return a

        self.act_new = action("&New Project", self.new_project, QKeySequence.New)
        self.act_open = action("&Open Project…", lambda: self.open_project(), QKeySequence.Open)
        self.act_save = action("&Save Project", self.save_project, QKeySequence.Save)
        self.act_save_as = action("Save Project &As…", self.save_project_as, QKeySequence.SaveAs)
        self.act_add = action("&Add Models…", self.add_models_dialog, QKeySequence("Ctrl+I"))
        self.act_slice = action("S&lice", self.start_slicing, QKeySequence("Ctrl+R"))
        self.act_export = action("&Export Laser Paths (.cli)…", self.export_cli, QKeySequence("Ctrl+E"))
        self.act_preview = action("Export &Preview (.html)…", self.export_preview)
        self.act_quit = action("&Quit", self.close, QKeySequence.Quit)
        self.act_fit = action("&Fit View", self._fit_views, QKeySequence("Ctrl+0"))
        self.act_about = action(f"&About {APP_NAME}", self.about)
        self.act_log = action("Show &Log File", self.show_log)

        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        file_menu.addActions([self.act_new, self.act_open])
        self.recent_menu = file_menu.addMenu("Open &Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        file_menu.addActions([self.act_save, self.act_save_as])
        file_menu.addSeparator()
        file_menu.addAction(self.act_add)
        file_menu.addSeparator()
        file_menu.addActions([self.act_export, self.act_preview])
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)
        bar.addMenu("&Build").addAction(self.act_slice)
        view_menu = bar.addMenu("&View")
        view_menu.addAction(self.act_fit)
        theme_menu = view_menu.addMenu("&Theme")
        for mode in theme.MODES:
            theme_menu.addAction(mode.capitalize(), lambda m=mode: self.set_theme(m))
        help_menu = bar.addMenu("&Help")
        help_menu.addActions([self.act_about, self.act_log])
