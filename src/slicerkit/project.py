"""Project files: which models to print (and how many copies) plus every setting.

Saved as JSON with the extension .xeroform (older .slicerkit files still open).
Model paths are stored relative to the project file, so a project folder can be
moved or shared as a whole.
"""
from __future__ import annotations
import json
import os
from dataclasses import asdict, dataclass, field, fields

from .config import SliceConfig

EXTENSION = ".xeroform"
LEGACY_EXTENSIONS = (".slicerkit",)        # projects saved before the XeroForm name
FORMAT = "xeroform-project"
LEGACY_FORMATS = ("slicerkit-project",)
VERSION = 1


class ProjectError(ValueError):
    """The project file can't be read. The message says why."""


@dataclass
class ProjectPart:
    path: str        # absolute in memory; relative to the project file on disk
    copies: int = 1


@dataclass
class Project:
    parts: list[ProjectPart] = field(default_factory=list)
    config: SliceConfig = field(default_factory=SliceConfig)

    def save(self, path: str) -> None:
        base = os.path.dirname(os.path.abspath(path))
        data = {
            "format": FORMAT,
            "version": VERSION,
            "parts": [{"path": _relative(p.path, base), "copies": p.copies} for p in self.parts],
            "settings": config_to_dict(self.config),
        }
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)  # never leave a half-written project behind

    @classmethod
    def load(cls, path: str) -> "Project":
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except OSError as e:
            raise ProjectError(f"Could not open {path}: {e.strerror or e}") from e
        except json.JSONDecodeError as e:
            raise ProjectError(f"{path} is not a valid project file (line {e.lineno}).") from e
        if not isinstance(data, dict) or data.get("format") not in (FORMAT, *LEGACY_FORMATS):
            raise ProjectError(f"{path} is not a XeroForm project file.")
        if data.get("version", 0) > VERSION:
            raise ProjectError(f"{path} was saved by a newer XeroForm; please update.")
        base = os.path.dirname(os.path.abspath(path))
        try:
            entries = [(str(p["path"]), int(p.get("copies", 1))) for p in data.get("parts", [])]
        except (KeyError, TypeError, ValueError) as e:
            raise ProjectError(f"{path} has a malformed parts list.") from e
        # A project file may come from someone else. A network path in it would make
        # Windows contact that host (and send the user's credentials) as soon as we
        # check the file exists - so refuse those before touching the filesystem.
        for raw, _ in entries:
            if _is_network_path(raw):
                raise ProjectError(f"{path} refers to a model on a network location ({raw}). "
                                   "Copy the model next to the project and add it again.")
        parts = [ProjectPart(os.path.normpath(os.path.join(base, raw)), copies) for raw, copies in entries]
        return cls(parts=parts, config=config_from_dict(data.get("settings", {})))


def config_to_dict(config: SliceConfig) -> dict:
    d = asdict(config)
    if d["build_volume"] is not None:
        d["build_volume"] = list(d["build_volume"])
    return d


def config_from_dict(d: dict) -> SliceConfig:
    """Build a SliceConfig; unknown keys are ignored, missing ones get defaults."""
    known = {f.name for f in fields(SliceConfig)}
    values = {k: v for k, v in d.items() if k in known}
    if values.get("build_volume") is not None:
        values["build_volume"] = tuple(values["build_volume"])
    try:
        return SliceConfig(**values)
    except (TypeError, ValueError) as e:
        raise ProjectError(f"Invalid settings in project: {e}") from e


def _is_network_path(path: str) -> bool:
    """UNC / network paths: \\\\host\\share, //host/share, \\\\?\\UNC\\..."""
    return path.replace("/", "\\").startswith("\\\\")


def _relative(path: str, base: str) -> str:
    try:
        return os.path.relpath(path, base)
    except ValueError:  # different drive on Windows
        return path
