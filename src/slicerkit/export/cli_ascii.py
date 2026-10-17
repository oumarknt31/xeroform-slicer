"""ASCII Common Layer Interface (.cli) exporter.

NOTE: the exact CLI dialect (units, ASCII vs binary, header keywords, the
POLYLINE direction flag) must be confirmed against the STM32 firmware. Those
knobs live here so matching the real machine is a change to this one file.

Standard CLI has no fields for laser power or speed, so the ScanParams on each
contour/hatch are not written here; the machine must get them another way.
"""
from __future__ import annotations
import numpy as np

from .base import Exporter


class AsciiCliExporter(Exporter):
    extension = ".cli"

    def __init__(self, units: float = 1.0):
        # units = mm per stored coordinate unit.
        self.units = units

    def _n(self, v: float) -> str:
        return f"{v / self.units:.4f}"

    def write(self, layers, path: str, bounding_box) -> None:
        n = self._n
        bb = bounding_box
        with open(path, "w") as f:
            f.write("$$HEADERSTART\n$$ASCII\n")
            f.write(f"$$UNITS/{self.units:.6f}\n$$VERSION/200\n$$LABEL/1,part\n")
            f.write(
                f"$$DIMENSION/{n(bb[0])},{n(bb[1])},{n(bb[2])},"
                f"{n(bb[3])},{n(bb[4])},{n(bb[5])}\n"
            )
            f.write(f"$$LAYERS/{len(layers)}\n$$HEADEREND\n$$GEOMETRYSTART\n")
            for layer in layers:
                f.write(f"$$LAYER/{n(layer.z)}\n")
                for c in layer.contours:
                    # direction flag per CLI spec: 0 = clockwise (hole), 1 = counter-clockwise (outer)
                    direction = 0 if c.is_hole else 1
                    pts = ",".join(f"{n(x)},{n(y)}" for x, y in c.points)
                    f.write(f"$$POLYLINE/1,{direction},{len(c.points)},{pts}\n")
                for h in layer.hatches:
                    flat = np.asarray(h.segments).reshape(-1, 2)
                    vals = ",".join(f"{n(x)},{n(y)}" for x, y in flat)
                    f.write(f"$$HATCHES/1,{len(h.segments)},{vals}\n")
            f.write("$$GEOMETRYEND\n")
