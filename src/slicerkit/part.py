"""Mesh loading, wrapped around PySLM's Part."""
from __future__ import annotations
import pyslm


class Part:
    """A 3D model loaded and rested on the build platform.

    Thin wrapper over pyslm.Part so the rest of the engine never touches PySLM
    directly. Exposes just what the slicer needs: the bounding box and a raw
    slice at a given height.
    """

    def __init__(self, mesh_path: str, name: str = "part"):
        self._part = pyslm.Part(name)
        self._part.setGeometry(mesh_path)
        self._part.dropToPlatform()

    @property
    def bounding_box(self):
        """[min_x, min_y, min_z, max_x, max_y, max_z] in mm."""
        return self._part.boundingBox

    @property
    def z_max(self) -> float:
        return float(self._part.boundingBox[5])

    def raw_slice(self, z: float):
        """Return the layer's outline polygons at height z (PySLM objects)."""
        return self._part.getVectorSlice(z)
