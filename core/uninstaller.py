"""
core/uninstaller.py

Safe uninstallation logic for DailySelfie.

Responsibilities:
- Confirm and remove installation directory
- Ask whether to delete photos
- If photos are kept, MOVE them to ~/Pictures/DailySelfie so they survive and are accessible
- Remove autostart entry
"""

from __future__ import annotations
import shutil
import sys
import os
import time
from pathlib import Path
from typing import Dict, Any
from core.autostart_manager import set_autostart


def _is_safe_to_delete(path: Path) -> bool:
    """Return True if this path looks safe to remove."""
    forbidden = {Path("/"), Path.home(), Path("/usr"), Path("/usr/local")}
    try:
        resolved = path.resolve()

        # 1. Check against hardcoded forbidden paths
        for bad in forbidden:
            if resolved == bad:
                return False

        # 2. Prevent deleting the project root itself if running from source.
        #    This happens if the user installs into the current directory.
        #    We define "project root" as the parent of this file's folder (core/).
        project_root = Path(__file__).resolve().parent.parent
        if resolved == project_root:
            print(f"Safety Check: Cannot delete project root ({resolved})")
            return False

    except Exception:
        return False
    return True


def _confirm(prompt: str, default: bool = False) -> bool:
    """Simple yes/no prompt. Returns True for Yes."""
    suffix = "Y/n" if default else "y/N"
    while True:
        ans = input(f"{prompt} [{suffix}]: ").strip().lower()
        if not ans:
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False


def _get_pictures_dir() -> Path:
    """Return a cross-platform 'Pictures' directory."""
    # Works on most Linux/Windows setups
    return Path.home() / "Pictures"


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
    if not _confirm("Proceed with uninstallation?", default=False):
        print("Uninstall cancelled.")
        return

    # ---------------------------------------------------------
    # 1. Determine Fate of Photos
    # ---------------------------------------------------------
    photos_exist = photos_root.exists() and any(photos_root.iterdir())
    delete_photos = False
    
    if photos_exist:
        print(f"\nFound photo library at: {photos_root}")
        # Default is NO (Keep photos)
        if _confirm("Do you want to PERMANENTLY DELETE these photos?", default=False):
            delete_photos = True
        else:
            print("Photos will be preserved.")
            delete_photos = False

    # ---------------------------------------------------------
    # 2. Rescue Photos (Move to Pictures) if Keeping
    # ---------------------------------------------------------
    # We must do this BEFORE deleting install_dir, because photos_root might be inside it.
    if photos_exist and not delete_photos:
        try:
            backup_root = _get_pictures_dir()
            target_dir = backup_root / "DailySelfie"
            
            # If target exists, rename to avoid collision
            if target_dir.exists():
                timestamp = int(time.time())
                target_dir = backup_root / f"DailySelfie_Backup_{timestamp}"

            print(f"\nMoving photos to accessible location: {target_dir} ...")
            
            # Ensure parent exists
            backup_root.mkdir(parents=True, exist_ok=True)
            
            # Move the folder
            shutil.move(str(photos_root), str(target_dir))
            print("Photos successfully moved.")
            
        except Exception as e:
            print(f"Error moving photos: {e}")
            print("Aborting uninstallation to prevent data loss.")
            return

    # ---------------------------------------------------------
    # 3. Remove Autostart
    # ---------------------------------------------------------
    try:
        set_autostart(False)
    except Exception as e:
        print(f"Note: Failed to clean up autostart: {e}")

    # ---------------------------------------------------------
    # 4. Remove Installation Directory
    # ---------------------------------------------------------
    # Now it is safe to delete install_dir because we moved the photos out (or deleted them)
    try:
        if install_dir.exists():
            shutil.rmtree(install_dir)
            print(f"Removed installation directory: {install_dir}")
    except Exception as e:
        print(f"Failed to remove install dir: {e}")

    # ---------------------------------------------------------
    # 5. Cleanup External Photos (Edge Case)
    # ---------------------------------------------------------
    # If photos_root was OUTSIDE install_dir and user wanted to delete them:
    if delete_photos and photos_root.exists():
        try:
            shutil.rmtree(photos_root)
            print(f"Removed photos directory: {photos_root}")
        except Exception as e:
            print(f"Failed to remove photos: {e}")

    print("\nUninstallation complete.")


if __name__ == "__main__":
    from core.paths import get_app_paths
    from core.config import ensure_config, apply_config_to_paths

    paths = get_app_paths("DailySelfie", ensure=False)
    if paths.config_dir.exists():
        cfg = ensure_config(paths.config_dir)
        paths = apply_config_to_paths(paths, cfg)
        run_uninstall(paths, cfg)
    else:
        print("Configuration not found.")