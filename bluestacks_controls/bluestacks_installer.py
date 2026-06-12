"""BlueStacks control installer.

Locates the user's BlueStacks 5 install, finds the Brawl Stars control
profile folder, and drops the VergoAI control schema in there.  Handles
the common BlueStacks 5 install paths and reports clearly when something
needs manual intervention.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


BLUESTACKS_PACKAGE = "com.supercell.brawlstars"

# Common BlueStacks 5 install paths -- we check them in order.
CANDIDATE_USER_DIRS = [
    Path(os.environ.get("USERPROFILE", "")) / "BlueStacks_nxt" / "bgp",
    Path(os.environ.get("LOCALAPPDATA", "")) / "BlueStacks_nxt" / "bgp",
    Path(os.environ.get("APPDATA",      "")) / "BlueStacks_nxt" / "bgp",
    Path("C:/ProgramData/BlueStacks_nxt/bgp"),
]


def find_bluestacks_profile_dir() -> Optional[Path]:
    """Return the deepest existing BlueStacks bgp folder, or None."""
    for base in CANDIDATE_USER_DIRS:
        if base.exists() and base.is_dir():
            return base
    return None


def find_brawl_stars_profile_dir() -> Optional[Path]:
    """Path of the Brawl Stars control profile folder inside BlueStacks."""
    base = find_bluestacks_profile_dir()
    if base is None:
        return None
    target = base / BLUESTACKS_PACKAGE
    if target.exists():
        return target
    # Search one level deep -- some installs nest by instance name.
    for child in base.iterdir():
        if child.is_dir():
            nested = child / BLUESTACKS_PACKAGE
            if nested.exists():
                return nested
    return None


def install_controls(source_json: Path | str | None = None) -> tuple[bool, str]:
    """Copy the VergoAI keymap into BlueStacks' Brawl Stars profile.

    Returns (success, message). On failure the message explains what to
    do manually.
    """
    if source_json is None:
        source_json = Path(__file__).resolve().parent / "brawl_stars_vergo.json"
    source_json = Path(source_json)
    if not source_json.exists():
        return False, f"Source profile missing at {source_json}"

    profile_dir = find_brawl_stars_profile_dir()
    if profile_dir is None:
        base = find_bluestacks_profile_dir()
        if base is None:
            return False, (
                "BlueStacks 5 install not found.\n"
                "Open BlueStacks and launch Brawl Stars once, then try again."
            )
        # BlueStacks creates the package folder only after BS is launched once.
        return False, (
            f"BlueStacks installed at {base} but Brawl Stars profile not "
            "found.\nLaunch Brawl Stars in BlueStacks once, then try again."
        )

    # Backup existing keymap if present.
    target = profile_dir / "vergo_controls.json"
    backup_dir = profile_dir / "vergo_backups"
    backup_dir.mkdir(exist_ok=True)
    if target.exists():
        import time as _t
        ts = _t.strftime("%Y%m%d_%H%M%S")
        shutil.copy2(target, backup_dir / f"vergo_controls.{ts}.json")

    try:
        shutil.copy2(source_json, target)
    except PermissionError as e:
        return False, (
            "BlueStacks is currently running and locking the file.\n"
            "Close BlueStacks completely (right-click tray icon -> Quit) "
            f"and try again.\nError: {e}"
        )
    except Exception as e:
        return False, f"Copy failed: {e}"

    return True, (
        f"Controls installed to:\n  {target}\n\n"
        "Reopen BlueStacks and start Brawl Stars. If the keymap doesn't "
        "appear, open BlueStacks' control editor and import the file "
        "manually."
    )


def open_profile_folder() -> bool:
    """Open the BlueStacks Brawl Stars profile folder in Explorer."""
    profile_dir = find_brawl_stars_profile_dir()
    target = profile_dir or find_bluestacks_profile_dir()
    if target is None:
        return False
    try:
        subprocess.Popen(["explorer", str(target)])
        return True
    except Exception:
        return False


if __name__ == "__main__":
    # CLI usage: python bluestacks_installer.py
    ok, msg = install_controls()
    print("OK" if ok else "FAIL")
    print(msg)
