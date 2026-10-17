"""Desktop GUI for slicerkit (PySide6). Install with:  pip install -e ".[gui]"

Run:  slicerkit-gui [model.stl ...]   or   python -m slicerkit.gui
"""
from __future__ import annotations
import sys


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication
    from .window import MainWindow

    argv = sys.argv if argv is None else argv
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("slicerkit")
    window = MainWindow()
    if argv[1:]:
        window.add_models(argv[1:])
    window.show()
    return app.exec()
