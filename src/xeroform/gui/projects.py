"""Projects and files: open/save projects, export, recent files, saved window state,
and dropping files on the window."""

from __future__ import annotations
import json
import logging
import os

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from ..pipeline import export
from ..preview import write_preview
from ..project import EXTENSION, Project, ProjectError, config_from_dict, config_to_dict
from . import theme
from .constants import MAX_RECENT, MODEL_EXTENSIONS, PROJECT_EXTENSIONS, PROJECT_FILTER
from .panels import gui_defaults
from .tasks import Task

log = logging.getLogger("xeroform.gui")


class ProjectsMixin:
    def _default_name(self, ext: str) -> str:
        base = (
            os.path.splitext(os.path.basename(self.project_path))[0]
            if self.project_path
            else os.path.splitext(os.path.basename(self.result_jobs[0]))[0]
            if self.result_jobs
            else "build"
        )
        return os.path.join(self._last_dir(), base + ext)

    def export_cli(self) -> None:
        if self.result is None or self.stale:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export laser paths", self._default_name(".cli"), "Common Layer Interface (*.cli)"
        )
        if not path:
            return
        try:
            export(self.result, path, self.result_config)
        except OSError as e:
            QMessageBox.warning(self, "Export failed", f"Could not write {path}:\n{e.strerror or e}")
            return
        self._remember_dir(path)
        self.toast(f"Exported {os.path.basename(path)}", "export")

    def export_preview(self) -> None:
        if self.result is None or self.stale:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export preview", self._default_name(".html"), "HTML (*.html)")
        if not path:
            return
        try:
            write_preview(
                self.result.layers,
                path,
                title=os.path.basename(self._default_name("")),
                jump_speed=self.result_config.jump_speed,
            )
        except OSError as e:
            QMessageBox.warning(self, "Export failed", f"Could not write {path}:\n{e.strerror or e}")
            return
        self._remember_dir(path)
        self.toast(f"Exported {os.path.basename(path)}", "export")

    # ================================================================== projects

    def maybe_save(self) -> bool:
        """Ask about unsaved changes. False = the user cancelled."""
        if not self.dirty or (self.project_path is None and not self.parts.parts()):
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            "Save the changes to this project first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Save:
            return self.save_project()
        return answer == QMessageBox.Discard

    def new_project(self) -> None:
        if self.busy() or not self.maybe_save():
            return
        self._clear()
        self.settings.set_config(gui_defaults())
        self.project_path, self.dirty = None, False
        self._refresh()

    def open_project(self, path: str | None = None) -> Task | None:
        if self.busy() or not self.maybe_save():
            return None
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Open project", self._last_dir(), PROJECT_FILTER)
            if not path:
                return None
        try:
            project = Project.load(path)
        except ProjectError as e:
            QMessageBox.warning(self, "Can't open project", str(e))
            self._forget_recent(path)
            return None
        self._clear()
        self.settings.set_config(project.config)
        self.project_path = path
        self._remember_dir(path)
        self._add_recent(path)
        missing = [p for p in project.parts if not os.path.isfile(p.path)]
        found = [p for p in project.parts if os.path.isfile(p.path)]
        if missing:
            QMessageBox.warning(
                self,
                "Missing models",
                "These models were not found and are left out:\n\n" + "\n".join(p.path for p in missing),
            )

        def done():
            self.dirty = bool(missing)
            self._refresh()

        if not found:
            done()
            return None
        return self.add_models(
            [p.path for p in found], [p.copies for p in found], [p.rotation for p in found], then=done
        )

    def save_project(self) -> bool:
        if self.project_path is None:
            return self.save_project_as()
        return self._write_project(self.project_path)

    def save_project_as(self) -> bool:
        start = self.project_path or os.path.join(self._last_dir(), "build" + EXTENSION)
        path, _ = QFileDialog.getSaveFileName(self, "Save project", start, PROJECT_FILTER)
        if not path:
            return False
        if not path.endswith(PROJECT_EXTENSIONS):
            path += EXTENSION
        return self._write_project(path)

    def _write_project(self, path: str) -> bool:
        try:
            Project(parts=self.parts.parts(), config=self.settings.config()).save(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Can't save project", f"Could not write {path}:\n{e}")
            return False
        self.project_path, self.dirty = path, False
        self._remember_dir(path)
        self._add_recent(path)
        self.toast(f"Saved {os.path.basename(path)}", "save")
        self._refresh()
        return True

    # ================================================================== recent, dirs, state

    def _recent(self) -> list[str]:
        return [p for p in (self.store.value("recent", []) or []) if isinstance(p, str)]

    def _add_recent(self, path: str) -> None:
        path = os.path.abspath(path)
        self.store.setValue("recent", ([path] + [p for p in self._recent() if p != path])[:MAX_RECENT])

    def _forget_recent(self, path: str) -> None:
        self.store.setValue("recent", [p for p in self._recent() if p != os.path.abspath(path)])

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        recent = self._recent()
        for path in recent:
            a = self.recent_menu.addAction(os.path.basename(path))
            a.setToolTip(path)
            a.triggered.connect(lambda checked=False, p=path: self.open_project(p))
        if not recent:
            self.recent_menu.addAction("No recent projects").setEnabled(False)

    def _last_dir(self) -> str:
        return self.store.value("last_dir", os.path.expanduser("~"))

    def _remember_dir(self, path: str) -> None:
        self.store.setValue("last_dir", os.path.dirname(os.path.abspath(path)))

    def _restore_state(self) -> None:
        if (geometry := self.store.value("geometry")) is not None:
            self.restoreGeometry(geometry)
        if (split := self.store.value("splitter")) is not None:
            self.split.restoreState(split)
        theme.apply(QApplication.instance(), self.store.value("theme", theme.DEFAULT_MODE))
        self._restyle()
        try:
            saved = self.store.value("last_settings")
            if saved:
                self.settings.set_config(config_from_dict(json.loads(saved)))
        except (ValueError, TypeError):
            log.warning("ignoring unreadable saved settings")

    def _save_state(self) -> None:
        self.store.setValue("geometry", self.saveGeometry())
        self.store.setValue("splitter", self.split.saveState())
        self.store.setValue("theme", theme.mode())
        try:
            self.store.setValue("last_settings", json.dumps(config_to_dict(self.settings.config())))
        except ValueError:
            pass
        self.store.sync()

    # ================================================================== drag & drop

    @staticmethod
    def _dropped_files(event) -> list[str]:
        md = event.mimeData()
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md.hasUrls() else []

    def dragEnterEvent(self, event):
        files = self._dropped_files(event)
        if any(f.lower().endswith(MODEL_EXTENSIONS + PROJECT_EXTENSIONS) for f in files) and not self.busy():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = self._dropped_files(event)
        projects = [f for f in files if f.lower().endswith(PROJECT_EXTENSIONS)]
        models = [f for f in files if f.lower().endswith(MODEL_EXTENSIONS)]
        event.acceptProposedAction()
        if projects:
            self.open_project(projects[0])
        elif models:
            self._remember_dir(models[0])
            self.add_models(models)
