# PyInstaller spec for SlideVision
# Build: pixi run pyinstaller packaging/slide_stitcher.spec --noconfirm

import glob
import os
import sys
from pathlib import Path

# PyInstaller provides SPECPATH (abs path to spec file's directory)
SPEC_DIR = Path(SPECPATH).resolve()  # packaging/
PROJECT_ROOT = SPEC_DIR.parent  # backend/

ICON_PATH = SPEC_DIR / "icons" / "icon.icns"
ICON_PATH_WIN = SPEC_DIR / "icons" / "icon.ico"

PIXI_ENV = PROJECT_ROOT / ".pixi" / "envs" / "default"

if sys.platform == "darwin":
    LIB_DIR = PIXI_ENV / "lib"
    LIB_GLOB = "*.dylib"
elif sys.platform == "win32":
    LIB_DIR = PIXI_ENV / "Library" / "bin"
    LIB_GLOB = "*.dll"
else:
    LIB_DIR = PIXI_ENV / "lib"
    LIB_GLOB = "*.so*"

binaries = []
if LIB_DIR.exists():
    for f in sorted(LIB_DIR.glob(LIB_GLOB)):
        name = f.name.lower()
        if any(skip in name for skip in (
            "_sysconfigdata",
            "libpython",
        )):
            continue
        binaries.append((str(f), "lib"))
    print(f"[spec] Bundling {len(binaries)} native libs from {LIB_DIR}")
else:
    print(f"[spec] WARNING: pixi lib dir not found at {LIB_DIR}")

hidden = [
    "slide_stitcher",
    "slide_stitcher.config",
    "slide_stitcher.models",
    "slide_stitcher.main",
    "slide_stitcher.services",
    "slide_stitcher.services.wsi",
    "slide_stitcher.services.thumbnail",
    "slide_stitcher.services.compose",
    "slide_stitcher.services.mapping",
    "slide_stitcher.services.storage",
    "slide_stitcher.services.types",
    "slide_stitcher.ui",
    "slide_stitcher.ui.main_window",
    "slide_stitcher.ui.controllers.case_controller",
    "slide_stitcher.ui.dialogs.new_case_dialog",
    "slide_stitcher.ui.widgets.case_sidebar",
    "slide_stitcher.ui.widgets.slide_canvas",
    "slide_stitcher.ui.widgets.slide_item",
]

datas = []
# Include QSS theme + icon next to executable
qss_src = PROJECT_ROOT / "src" / "slide_stitcher" / "assets" / "theme.qss"
if qss_src.exists():
    datas.append((str(qss_src), "assets"))
icon_for_bundle = ICON_PATH if sys.platform == "darwin" else ICON_PATH_WIN
if not icon_for_bundle.exists():
    icon_for_bundle = None

a = Analysis(
    [str(PROJECT_ROOT / "src" / "slide_stitcher" / "main.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "IPython",
        "jupyter",
        "jupyterlab",
        "notebook",
        "pytest",
        "pyvips",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SlideVision",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_for_bundle) if icon_for_bundle else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SlideVision",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="SlideVision.app",
        icon=str(ICON_PATH) if ICON_PATH.exists() else None,
        bundle_identifier="com.slidevision.app",
        info_plist={
            "CFBundleShortVersionString": "0.2.0",
            "CFBundleVersion": "1",
            "CFBundleName": "SlideVision",
            "CFBundleDisplayName": "SlideVision",
            "NSHighResolutionCapable": True,
            "NSPrincipalClass": "NSApplication",
            "NSSupportsAutomaticGraphicsSwitching": True,
            "LSMinimumSystemVersion": "11.0",
            "LSApplicationCategoryType": "public.app-category.medical",
        },
    )
