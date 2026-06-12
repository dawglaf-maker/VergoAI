# -*- mode: python ; coding: utf-8 -*-
# ================================================================
#  VergoAI -- PyInstaller build spec
#  Mode:  ONE FILE  (everything packed into VergoAI.exe)
#  Build: pyinstaller VergoAI.spec
#  Out:   dist\VergoAI.exe
#
#  On first launch the exe self-extracts to a hidden temp folder.
#  User configs are copied to %APPDATA%\VergoAI\ automatically.
#  Startup takes ~15-40s on the first run (extraction), then faster.
# ================================================================

from PyInstaller.utils.hooks import collect_all, collect_submodules
import os as _os

def _adb_binaries():
    """Bundle adb.exe (and optional DLLs) from the local platform-tools folder."""
    bins = []
    for name in ["adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"]:
        path = _os.path.join("platform-tools", name)
        if _os.path.exists(path):
            bins.append((path, "."))
    return bins

block_cipher = None

ctk_b,   ctk_d,   ctk_h   = collect_all("customtkinter")
ocr_b,   ocr_d,   ocr_h   = collect_all("easyocr")
ultra_b, ultra_d, ultra_h  = collect_all("ultralytics")
pil_b,   pil_d,   pil_h   = collect_all("PIL")
cv_b,    cv_d,    cv_h    = collect_all("cv2")
# scrcpy ships scrcpy-server.jar as a package data file; collect_all
# grabs it so the bundled exe can push it to the Android device at runtime.
scrcpy_b, scrcpy_d, scrcpy_h = collect_all("scrcpy")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=(ctk_b + ocr_b + ultra_b + pil_b + cv_b + scrcpy_b + _adb_binaries()),
    datas=(
        ("cfg/",                  "cfg"),
        ("images/",               "images"),
        ("models/",               "models"),
        ("api/",                  "api"),
        ("typization/",           "typization"),
        ("bluestacks_controls/",  "bluestacks_controls"),
        *ctk_d, *ocr_d, *ultra_d, *pil_d, *cv_d, *scrcpy_d,
    ),
    hiddenimports=(
        ctk_h + ocr_h + ultra_h + pil_h + cv_h + scrcpy_h
        + collect_submodules("torch")
        + collect_submodules("torchvision")
        + collect_submodules("onnxruntime")
        + [
            "scrcpy", "adbutils", "adbutils._utils",
            "toml", "packaging", "packaging.version",
            "shapely",
            "pyautogui", "pygetwindow",
        ]
    ),
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "notebook", "IPython", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── Single-file exe (everything bundled in) ───────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,      # <-- include in the exe itself
    a.zipfiles,
    a.datas,
    name="VergoAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=["vcruntime140.dll", "ucrtbase.dll"],
    console=False,                  # no black window
    icon="images\\vergo_logo.ico",
    uac_admin=False,                # don't demand admin -- ADB works without it
)

# NOTE: No COLLECT step -- that's what makes it one file.
