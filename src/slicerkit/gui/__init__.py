"""Desktop GUI for slicerkit (PySide6). Install with:  pip install -e ".[gui]"

Run:  slicerkit-gui [model.stl | project.slicerkit ...]   or   python -m slicerkit.gui
"""
from __future__ import annotations
import logging
import os
import sys
import traceback

log = logging.getLogger("slicerkit.gui")


def _setup_logging() -> str:
    """Log to a file in the user's app-data folder; return its path."""
    from PySide6.QtCore import QStandardPaths

    folder = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "slicerkit.log")
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("slicerkit")
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return path


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .. import __version__
    from ..project import EXTENSION
    from .window import MainWindow

    argv = sys.argv if argv is None else argv
    app = QApplication.instance() or QApplication(argv)
    app.setOrganizationName("slicerkit")
    app.setApplicationName("slicerkit")
    app.setApplicationVersion(__version__)
    from .theme import app_icon
    app.setWindowIcon(app_icon())
    log_path = _setup_logging()
    log.info("slicerkit %s starting", __version__)

    window = MainWindow(log_path=log_path)

    def excepthook(kind, value, tb):  # last line of defence: log it, tell the user, keep running
        details = "".join(traceback.format_exception(kind, value, tb))
        log.error("unhandled exception\n%s", details)
        box = QMessageBox(QMessageBox.Critical, "Unexpected error", str(value) or kind.__name__, parent=window)
        box.setInformativeText(f"Details are in the log file:\n{log_path}")
        box.setDetailedText(details)
        box.exec()

    sys.excepthook = excepthook
    files = [os.path.abspath(a) for a in argv[1:]]
    projects = [f for f in files if f.endswith(EXTENSION)]
    if projects:
        window.open_project(projects[0])
    elif files:
        window.add_models(files)
    window.show()
    return app.exec()
