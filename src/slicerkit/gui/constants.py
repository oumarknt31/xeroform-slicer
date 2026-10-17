"""Names and file types shared across the XeroForm window modules."""
from ..project import EXTENSION, LEGACY_EXTENSIONS

APP_NAME = "XeroForm"
REPO_URL = "https://github.com/oumarknt31/xeroform-slicer"
MODEL_EXTENSIONS = (".stl", ".obj", ".ply", ".3mf", ".off", ".glb")
MODEL_FILTER = "3D models (*.stl *.STL *.obj *.ply *.3mf *.3MF);;All files (*)"
PROJECT_EXTENSIONS = (EXTENSION, *LEGACY_EXTENSIONS)
PROJECT_FILTER = f"XeroForm project ({' '.join('*' + e for e in PROJECT_EXTENSIONS)})"
MAX_RECENT = 8
FLIPBOOK_FPS = 24
THEME_ICONS = {"system": "auto", "light": "sun", "dark": "moon"}
THEME_NAMES = {"system": "follow the system", "light": "light", "dark": "dark"}
