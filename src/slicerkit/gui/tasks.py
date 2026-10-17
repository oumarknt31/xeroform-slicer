"""Background work for the GUI: run a function on a thread with progress and cancel.

Expected problems (a bad model, parts that don't fit) come back as a plain
message; anything else is logged with its traceback and reported as unexpected,
so the window never dies with the work.
"""
from __future__ import annotations
import logging
import traceback
from typing import Callable

from PySide6.QtCore import QThread, Signal

from ..nesting import NestingError
from ..part import MeshError
from ..project import ProjectError

log = logging.getLogger("slicerkit.gui")

EXPECTED = (MeshError, NestingError, ProjectError, ValueError)


class Cancelled(Exception):
    pass


class Task(QThread):
    """Runs fn(progress) on a worker thread. progress(stage, done=0, total=0)."""

    progressed = Signal(str, int, int)  # stage, done, total (total 0 = unknown)
    succeeded = Signal(object)
    failed = Signal(str, str)           # message, technical details ("" when expected)

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
