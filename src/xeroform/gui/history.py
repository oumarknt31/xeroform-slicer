"""Undo and redo, by snapshots of the window's state.

After every edit the window calls `record`; if the state differs from the last
one recorded, the previous state goes on the undo stack. Quick edits of the same
thing (spinning through values, dragging a part) merge into one step.
"""

from __future__ import annotations
import time
from typing import Any, Callable

MERGE_SECONDS = 1.0


class History:
    def __init__(self, take: Callable[[], Any], restore: Callable[[Any], None], limit: int = 200):
        self._take, self._restore, self.limit = take, restore, limit
        self._undo: list[tuple[str, Any]] = []
        self._redo: list[tuple[str, Any]] = []
        self._last = None
        self._merge: tuple[str, float] | None = None  # (label, time) of the last step, while it can grow

    @property
    def last(self):
        """The state as last recorded."""
        return self._last

    def reset(self) -> None:
        """Forget everything (a new or opened project)."""
        self._undo.clear()
        self._redo.clear()
        self._last, self._merge = self._take(), None

    def record(self, label: str) -> None:
        """Note an edit called `label` (as in "Undo Fill power") if the state changed."""
        now = self._take()
        if now == self._last:
            return
        stamp = time.monotonic()
        merging = self._merge and self._merge[0] == label and stamp - self._merge[1] < MERGE_SECONDS and self._undo
        if not merging:
            self._undo.append((label, self._last))
            del self._undo[: -self.limit]
        self._redo.clear()
        self._last, self._merge = now, (label, stamp)

    def amend(self) -> None:
        """Fold a change into the last step instead of making a new one (e.g. the
        layout worked out after parts were added)."""
        self._last = self._take()

    def undo(self) -> None:
        self._step(self._undo, self._redo)

    def redo(self) -> None:
        self._step(self._redo, self._undo)

    def _step(self, source: list, target: list) -> None:
        if not source:
            return
        label, state = source.pop()
        target.append((label, self._take()))
        self._last, self._merge = state, None
        self._restore(state)

    def undo_label(self) -> str | None:
        return self._undo[-1][0] if self._undo else None

    def redo_label(self) -> str | None:
        return self._redo[-1][0] if self._redo else None
