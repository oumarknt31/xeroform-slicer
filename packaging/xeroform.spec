# PyInstaller recipe for the XeroForm desktop app.
#
#   python tools/make_icons.py
#   pyinstaller packaging/xeroform.spec --noconfirm
#
# -> dist/XeroForm.app (macOS) or dist/XeroForm/ (Windows, Linux).
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
sys.path.insert(0, os.path.join(ROOT, "src"))
from xeroform import __version__  # noqa: E402

hidden = (
    [m for m in collect_submodules("pyslm") if "visualise" not in m]  # plotting needs matplotlib
    + collect_submodules("trimesh.exchange")  # file formats are imported lazily
    + collect_submodules("pyclipr")
)
datas = (
    [(os.path.join(ROOT, "src", "xeroform", "gui", "assets", "*.svg"), os.path.join("xeroform", "gui", "assets")),
     (os.path.join(ROOT, "LICENSE"), "."),
     (os.path.join(ROOT, "THIRD_PARTY_NOTICES.md"), ".")]
    + collect_data_files("trimesh")
)
excludes = ["matplotlib", "tkinter", "IPython", "pandas", "pytest", "vtk", "PySide6.QtQml", "PySide6.QtQuick",
            "PySide6.QtNetwork", "PySide6.QtPdf"]

a = Analysis(
    [os.path.join(SPECPATH, "xeroform_gui.py")],
    pathex=[os.path.join(ROOT, "src")],
    datas=datas,
    hiddenimports=hidden,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="XeroForm",
    console=False,
    icon=os.path.join(SPECPATH, "xeroform.ico" if sys.platform == "win32" else "xeroform.icns"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="XeroForm", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="XeroForm.app",
        icon=os.path.join(SPECPATH, "xeroform.icns"),
        bundle_identifier="io.github.oumarknt31.xeroform",
        version=__version__,
        info_plist={
            "CFBundleName": "XeroForm",
            "CFBundleDisplayName": "XeroForm",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "XeroForm project",
                "CFBundleTypeExtensions": ["xeroform"],
                "CFBundleTypeRole": "Editor",
            }],
        },
    )
