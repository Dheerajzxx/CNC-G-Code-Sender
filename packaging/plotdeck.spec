# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PlotDeck.app.

Build with:  pyinstaller --noconfirm --clean packaging/plotdeck.spec
Output:      dist/PlotDeck.app
"""

import os

from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas, binaries, hiddenimports = collect_all("pyqtgraph")

manual_path = os.path.join(SPECPATH, "..", "USER_MANUAL.md")
if os.path.exists(manual_path):
    datas.append((manual_path, "."))

try:  # 3D view is optional; bundle OpenGL support when it is installed.
    gl_datas, gl_binaries, gl_hidden = collect_all("OpenGL")
    datas += gl_datas
    binaries += gl_binaries
    hiddenimports += gl_hidden
except Exception:  # noqa: BLE001
    pass

icon_path = os.path.join(os.path.dirname(os.path.abspath(SPEC)), "icon.icns")
icon = icon_path if os.path.exists(icon_path) else None

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[os.path.join(SPECPATH, "..", "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pkg_resources", "setuptools", "jaraco"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PlotDeck",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=icon,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PlotDeck",
)
app = BUNDLE(
    coll,
    name="PlotDeck.app",
    icon=icon,
    bundle_identifier="com.plotdeck.app",
    info_plist={
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "LSMinimumSystemVersion": "11.0",
        "NSHumanReadableCopyright": "PlotDeck",
    },
)
