# Third-party software

XeroForm Slicer's own code is under the [MIT License](LICENSE). The packaged
desktop apps also include the open-source libraries below, each under its own
license. They ship as separate files inside the app, unmodified, so they can be
replaced with other compatible versions.

| Library | Used for | License |
|---|---|---|
| [PySide6 / Qt](https://www.qt.io/qt-for-python) | desktop interface | LGPL-3.0 |
| [PythonSLM (PySLM)](https://github.com/drlukeparry/pyslm) | slicing and hatching | LGPL-2.1 |
| [trimesh](https://github.com/mikedh/trimesh) | loading and repairing meshes | MIT |
| [NumPy](https://numpy.org) | numerics | BSD-3-Clause |
| [SciPy](https://scipy.org) | geometry search (scan order) | BSD-3-Clause |
| [Shapely](https://github.com/shapely/shapely) | 2D geometry | BSD-3-Clause |
| [pyclipr](https://github.com/drlukeparry/pyclipr) | polygon clipping (Clipper2) | BSL-1.0 |
| [lxml](https://lxml.de) | reading 3MF files | BSD-3-Clause |
| [NetworkX](https://networkx.org) | mesh graph operations | BSD-3-Clause |
| [Rtree](https://github.com/Toblerity/rtree) | spatial index | MIT |
| [Pillow](https://python-pillow.org) | images | MIT-CMU |
| [Python](https://www.python.org) | runtime | PSF-2.0 |

The source code of every library above is available from its project page and
from [PyPI](https://pypi.org). The LGPL-licensed libraries are used unmodified;
their license texts are at
[gnu.org/licenses/lgpl-3.0](https://www.gnu.org/licenses/lgpl-3.0.html) and
[gnu.org/licenses/lgpl-2.1](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html).
