"""slicerkit - an open-source SLS slicing engine.

Turns a 3D model (STL) into laser tool-paths for the XeroForm SLS printer:
load -> slice -> hatch -> export (.cli).

The engine is built on the open-source PySLM library, but PySLM's objects are
wrapped behind slicerkit's own data model (see `layers.py`) so the rest of the
engine stays decoupled and portable.
"""
from .config import SliceConfig
from .pipeline import slice_file
from .layers import Layer, Contour, Hatch, ScanParams
from .laser import LaserSettings, estimate_scan_time
from .preview import write_preview

__version__ = "0.1.1"
__all__ = ["SliceConfig", "slice_file", "Layer", "Contour", "Hatch", "ScanParams",
           "LaserSettings", "estimate_scan_time", "write_preview"]
