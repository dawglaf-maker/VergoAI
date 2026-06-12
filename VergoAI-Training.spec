# -*- mode: python ; coding: utf-8 -*-
# ================================================================
#  VergoAI-Training -- PyInstaller build spec
#  Same bundle as VergoAI.spec but boots training_entry.py, which
#  presets --training: brawler picker -> N games each -> learn.
#  Build: pyinstaller VergoAI-Training.spec
#  Out:   dist\VergoAI-Training.exe
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
scrcpy_b, scrcpy_d, scrcpy_h = collect_all("scrcpy")

a = Analysis(
    ["training_entry.py"],
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="VergoAI-Training",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=["vcruntime140.dll", "ucrtbase.dll"],
    console=False,
    icon="images\\vergo_logo.ico",
    uac_admin=False,
)
