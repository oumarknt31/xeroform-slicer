"""The Exporter contract every output format must satisfy."""
from __future__ import annotations
from abc import ABC, abstractmethod


class Exporter(ABC):
    """Write a list of XeroForm Layers to a machine-readable file."""

    #: file extension this exporter produces, e.g. ".cli"
    extension: str = ""

    @abstractmethod
    def write(self, layers, path: str, bounding_box) -> None:
        """Serialize `layers` to `path`.

        layers        : list[xeroform.layers.Layer]
        path          : output file path
        bounding_box  : [min_x, min_y, min_z, max_x, max_y, max_z]
        """
        raise NotImplementedError
