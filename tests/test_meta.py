"""Project metadata: one version number, license files present."""

import importlib.metadata
import pathlib

import xeroform

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_version_has_one_source():
    assert importlib.metadata.version("xeroform") == xeroform.__version__


def test_license_files():
    assert "MIT License" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "LGPL-3.0" in notices and "PySLM" in notices


def test_changelog_has_this_version():
    assert f"## {xeroform.__version__} " in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
