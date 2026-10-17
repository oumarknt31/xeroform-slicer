"""XeroForm desktop app (PySide6). Install with:  pip install -e ".[gui]"

Run:  xeroform-gui [model.stl | project.xeroform ...]   or   python -m xeroform.gui
      xeroform-gui --smoke-test   checks a build works (slice, export, open the window)
"""
from __future__ import annotations
import logging
import os
import sys
import traceback

log = logging.getLogger("xeroform.gui")


def _setup_logging() -> str:
    """Log to a file in the user's app-data folder; return its path."""
    from PySide6.QtCore import QStandardPaths

    folder = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "xeroform.log")
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("xeroform")
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return path


def smoke_test() -> int:
    """Check that this build works end to end: load, slice and export a model, open the window.

    Used on every packaged app before it is published. Settings go to a temporary
    folder so the check leaves nothing behind.
    """
    import tempfile

    import trimesh
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from ..config import SliceConfig
    from ..pipeline import slice_job
    from .window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    with tempfile.TemporaryDirectory() as folder:
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, folder)
        model, out = os.path.join(folder, "cube.stl"), os.path.join(folder, "cube.cli")
        trimesh.creation.box(extents=[10, 10, 10]).export(model)
        layers = slice_job(model, out, SliceConfig(layer_thickness=1)).layers
        window = MainWindow()
        window.show()
        app.processEvents()
        window.dirty = False
        window.close()
        ok = len(layers) == 9 and os.path.getsize(out) > 0
    print(f"XeroForm smoke test: {'ok' if ok else 'FAILED'} ({len(layers)} layers)")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .. import __version__
    from ..project import EXTENSION
    from .constants import APP_NAME
    from .window import MainWindow

    argv = sys.argv if argv is None else argv
    if "--smoke-test" in argv:
        return smoke_test()
    app = QApplication.instance() or QApplication(argv)
    app.setOrganizationName(APP_NAME)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    from .theme import app_icon
    app.setWindowIcon(app_icon())
    log_path = _setup_logging()
    log.info("XeroForm %s starting", __version__)

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
