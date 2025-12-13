"""
core/uninstaller.py

Safe uninstallation logic for DailySelfie.

Responsibilities:
- Confirm and remove installation directory (config + data + venv + logs)
- Ask whether to delete photos directory
- Remove autostart entry (Linux)
- Provide clear feedback for every action

Safety:
- Aborts if install_dir is suspicious (/, $HOME, /usr, etc.)
- Confirms with user before any deletion
"""

from __future__ import annotations
import shutil
import sys
import os
from pathlib import Path
from typing import Dict, Any
from autostart import disable_autostart


def _is_safe_to_delete(path: Path) -> bool:
    """Return True if this path looks safe to remove."""
    forbidden = {Path("/"), Path.home(), Path("/usr"), Path("/usr/local")}
    try:
        resolved = path.resolve()
        for bad in forbidden:
            if resolved == bad:
                return False
    except Exception:
        return False
    return True


def _confirm(prompt: str) -> bool:
    """Simple yes/no prompt."""
    ans = input(f"{prompt} [y/N]: ").strip().lower()
    return ans in ("y", "yes")




def run_uninstall(paths, cfg: Dict[str, Any]):
    """Main uninstall entrypoint."""
    app_name = paths.app_name
    inst = cfg.get("installation", {})
    install_dir = Path(inst.get("install_dir", "~/.local/share/DailySelfie")).expanduser().resolve()
    photos_root = Path(inst.get("photos_root", install_dir / "photos")).expanduser().resolve()

    print(f"\n=== Uninstall {app_name} ===")
    print(f"Installation directory: {install_dir}")

    # Sanity checks
    if not install_dir.exists():
        print("Install directory not found. Nothing to uninstall.")
        return

    if not _is_safe_to_delete(install_dir):
        print(f"Unsafe uninstall target: {install_dir}")
        print("Aborting to prevent accidental data loss.")
        return

    # Confirm uninstall
    if not _confirm("Proceed with uninstallation?"):
        print("Uninstall cancelled.")
        return

    # Optional photos removal
    delete_photos = False
    if photos_root.exists():
        delete_photos = _confirm(f"Do you also want to delete your photos in {photos_root}?")

    # Remove main install directory
    try:
        shutil.rmtree(install_dir)
        print(f"Removed installation directory: {install_dir}")
    except Exception as e:
        print(f"Failed to remove install dir: {e}")

    # Remove photos if user agreed
    if delete_photos:
        try:
            shutil.rmtree(photos_root)
            print(f"Removed photos directory: {photos_root}")
        except Exception as e:
            print(f"Failed to remove photos: {e}")
    else:
        print("Photos preserved.")

    # Remove autostart entry (cross-platform)
    try:
        set_autostart(paths, cfg, False)
    except Exception as e:
        print(f"Failed to remove autostart: {e}")

    print("\n Uninstallation complete.\n")


if __name__ == "__main__":
    from core.paths import get_app_paths
    from core.config import ensure_config, apply_config_to_paths

    paths = get_app_paths("DailySelfie", ensure=False)
    cfg = ensure_config(paths.config_dir)
    paths = apply_config_to_paths(paths, cfg)

    run_uninstall(paths, cfg)
