"""Background work for the GUI: run a function on a thread with progress and cancel.

Expected problems (a bad model, parts that don't fit) come back as a plain
message; anything else is logged with its traceback and reported as unexpected,
so the window never dies with the work.
"""

from __future__ import annotations
import gc
import logging
import traceback
from typing import Callable

from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer, Signal

from ..nesting import NestingError
from ..part import MeshError
from ..project import ProjectError

log = logging.getLogger("xeroform.gui")

EXPECTED = (MeshError, NestingError, ProjectError, ValueError)


class Cancelled(Exception):
    pass


class Task(QThread):
    """Runs fn(progress) on a worker thread. progress(stage, done=0, total=0)."""

    progressed = Signal(str, int, int)  # stage, done, total (total 0 = unknown)
    succeeded = Signal(object)
    failed = Signal(str, str)  # message, technical details ("" when expected)

    def __init__(self, fn: Callable, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def progress(self, stage: str, done: int = 0, total: int = 0) -> None:
        if self._cancel:
            raise Cancelled
        self.progressed.emit(stage, done, total)

    def run(self) -> None:
        try:
            self.succeeded.emit(self._fn(self.progress))
        except Cancelled:
            self.failed.emit("Cancelled.", "")
        except EXPECTED as e:
            self.failed.emit(str(e), "")
        except Exception as e:  # noqa: BLE001 - report, don't crash the app
            log.exception("background task failed")
            self.failed.emit(f"Unexpected error: {e}", traceback.format_exc())


class _MainThreadGC(QObject):
    """Run Python's cycle collector on the GUI thread only.

    The collector runs on whichever thread happens to trip its threshold - often a
    worker. If the garbage it frees holds Qt objects (widgets of a closed window,
    kept in cycles by lambdas), Qt destroys them off the GUI thread and crashes.
    So automatic collection is switched off and the GUI thread collects on a timer,
    with the same generation thresholds Python would use.
    """

    INTERVAL_MS = 400

    def __init__(self, app):
        super().__init__(app)
        self.thresholds = gc.get_threshold()
        gc.disable()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.collect)
        self.timer.start(self.INTERVAL_MS)

    def collect(self) -> None:
        t0, t1, t2 = self.thresholds
        c0, c1, c2 = gc.get_count()
        if c0 > t0:
            gc.collect(2 if c2 > t2 and c1 > t1 else 1 if c1 > t1 else 0)


def collect_garbage_on_gui_thread() -> None:
    """Install the GUI-thread collector once per application."""
    app = QCoreApplication.instance()
    if app is not None and app.findChild(_MainThreadGC) is None:
        _MainThreadGC(app)
