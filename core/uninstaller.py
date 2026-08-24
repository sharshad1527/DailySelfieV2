"""
core/uninstaller.py

Safe uninstallation logic for DailySelfie.

Responsibilities:
- Confirm and remove installation directory
- Ask whether to delete photos
- If photos are kept, MOVE them to ~/Pictures/DailySelfie-rescue-<ts>/photos
- ALWAYS rescue app data (index.db, captures.jsonl, metadata sidecars, thumbs)
  by moving it to ~/Pictures/DailySelfie-rescue-<ts>/data so a reinstall can
  restore memories (logs are disposable and are NOT rescued)
- Leave a README.txt in the rescue folder explaining how to point a fresh
  install at the rescued data ([installation] data_dir override in config.toml)
- Remove autostart entry, desktop entry and CLI wrapper BEFORE rescue/deletion
- Never delete a subtree whose rescue failed or failed verification
"""

from __future__ import annotations
import logging
import shutil
import sys
import os
import platform
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
from core.autostart_manager import set_autostart
from core.desktop_entry_manager import set_desktop_entry
from core.logging import get_logger

logger = get_logger("uninstaller")

RESCUE_PREFIX = "DailySelfie-rescue"
RESCUE_README_NAME = "README.txt"


def _ensure_console_logging() -> None:
    """Make sure INFO logs reach the console even without init_logger()."""
    root = logging.getLogger("dailyselfie")
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        handler.setLevel(logging.INFO)
        root.addHandler(handler)
        root.setLevel(logging.INFO)


def _remove_cli_wrapper(install_dir: Path):
    """
    Removes The "dailyselfie" command line wrapper.
    """
    os_name = platform.system().lower()
    wrapper_path = None

    if os_name == "windows":
        wrapper_path = install_dir / "bin" / "dailyselfie.bat"
    else:
        wrapper_path = Path.home() / ".local" / "bin" / "dailyselfie"

    if wrapper_path and wrapper_path.exists():
        try:
            wrapper_path.unlink()
            logger.info(f"Removed CLI Command: {wrapper_path}")
        except Exception as e:
            logger.warning(f"Failed To Remove CLI Command: {e}")


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
            logger.warning(f"Safety Check: Cannot delete project root ({resolved})")
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


def _is_within(child: Path, ancestor: Path) -> bool:
    """True if child equals ancestor or lives underneath it."""
    try:
        child.resolve().relative_to(ancestor.resolve())
        return True
    except Exception:
        return False


def _count_files(path: Path) -> int:
    """Count files (and symlinks) recursively under path."""
    count = 0
    try:
        if path.is_symlink() or path.is_file():
            return 1
        if not path.is_dir():
            return 0
        for entry in path.rglob("*"):
            try:
                if entry.is_symlink() or entry.is_file():
                    count += 1
            except OSError:
                continue
    except Exception:
        pass
    return count


def _make_rescue_root(base: Optional[Path] = None) -> Optional[Path]:
    """Create ~/Pictures/DailySelfie-rescue-<ts> (unique) and return it."""
    if base is None:
        base = _get_pictures_dir()
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Cannot create rescue base directory {base}: {e}")
        return None

    ts = time.strftime("%Y%m%d-%H%M%S")
    candidate = base / f"{RESCUE_PREFIX}-{ts}"
    i = 1
    while candidate.exists():
        candidate = base / f"{RESCUE_PREFIX}-{ts}-{i}"
        i += 1
    try:
        candidate.mkdir(parents=True)
    except Exception as e:
        logger.error(f"Cannot create rescue folder {candidate}: {e}")
        return None
    return candidate


def _move_subtree(src: Path, dst_dir: Path, rescued_out: List[Dict[str, Any]]) -> bool:
    """
    Move src (file/dir) into dst_dir, preserving its name.

    Verifies file counts before/after. On any failure logs loudly and returns
    False; caller must then preserve src from deletion.
    """
    name = src.name
    dst = dst_dir / name
    i = 1
    while dst.exists():
        dst = dst_dir / f"{name}-{i}"
        i += 1

    before = _count_files(src)
    try:
        shutil.move(str(src), str(dst))
    except Exception as e:
        logger.error(
            f"RESCUE FAILED: could not move {src}: {e}. "
            f"This subtree will be PRESERVED (not deleted)."
        )
        return False

    after = _count_files(dst)
    if before != after:
        logger.error(
            f"RESCUE INCOMPLETE for {src}: expected {before} file(s) at "
            f"{dst}, found {after}. Source will be PRESERVED (not deleted)."
        )
        return False

    logger.info(f"Rescued {before} file(s): {src} -> {dst}")
    rescued_out.append({"src": str(src), "dst": str(dst), "files": before})
    return True


def _rescue_contents(
    src_dir: Path,
    dst_dir: Path,
    exclude: List[Path],
    rescued_out: List[Dict[str, Any]],
) -> Set[Path]:
    """
    Move each child of src_dir into dst_dir (skipping excluded subtrees).

    Returns the set of source paths that must be preserved because their
    rescue failed or was incomplete.
    """
    protected: Set[Path] = set()
    if not src_dir.is_dir():
        return protected

    try:
        children = sorted(src_dir.iterdir())
    except Exception as e:
        logger.error(
            f"RESCUE FAILED: cannot enumerate {src_dir}: {e}. "
            f"This subtree will be PRESERVED (not deleted)."
        )
        return {src_dir.resolve()}

    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(
            f"RESCUE FAILED: cannot create destination {dst_dir}: {e}. "
            f"{src_dir} will be PRESERVED (not deleted)."
        )
        return {src_dir.resolve()}

    for child in children:
        if any(_is_within(child, ex) for ex in exclude):
            logger.info(f"Not rescuing disposable path: {child}")
            continue
        if not _move_subtree(child, dst_dir, rescued_out):
            protected.add(child.resolve())
    return protected


def _has_rescuable_content(src_dir: Path, exclude: List[Path]) -> bool:
    """True if src_dir holds anything worth rescuing (excluding `exclude`)."""
    try:
        for child in src_dir.iterdir():
            if not any(_is_within(child, ex) for ex in exclude):
                return True
    except Exception:
        pass
    return False


def _write_rescue_readme(rescue_root: Path, rescued: List[Dict[str, Any]]) -> None:
    """Explain the rescue folder and how to reconnect a fresh install to it."""
    entries = "\n".join(
        f"  - {item['src']} -> {item['dst']} ({item['files']} file(s))"
        for item in rescued
    ) or "  (nothing was rescued in this run)"
    content = (
        "DailySelfie Rescue Folder\n"
        "=========================\n"
        f"Created by the uninstaller on {time.strftime('%Y-%m-%d %H:%M:%S')}.\n"
        "\n"
        "Your photos and application data were MOVED here (not copied) before\n"
        "the old installation directory was removed:\n"
        "\n"
        "  photos/  - your selfie library, original layout preserved\n"
        "             (<year>/<image files>)\n"
        "  data/    - application metadata linking photos to memories:\n"
        "             index.db, captures.jsonl, metadata/ sidecars, thumbs/\n"
        "             Logs were intentionally NOT rescued (disposable).\n"
        "\n"
        "How to reuse this data with a fresh install:\n"
        "  1. Install DailySelfie again.\n"
        "  2. Edit its config.toml and point [installation] at these folders:\n"
        "\n"
        "       [installation]\n"
        f"       data_dir = \"{rescue_root / 'data'}\"\n"
        f"       photos_root = \"{rescue_root / 'photos'}\"\n"
        "\n"
        "     By default config.toml lives at ~/.config/DailySelfie/config.toml.\n"
        "  3. Start the app - your existing memories will show up again.\n"
        "\n"
        "You can also move these folders back into a new installation\n"
        "directory (data -> <install>/data, photos -> <install>/photos).\n"
        "Anything listed as preserved below failed to move and stayed in the\n"
        "original location; copy it manually if you still need it.\n"
        "\n"
        "Rescued items:\n"
        f"{entries}\n"
    )
    try:
        (rescue_root / RESCUE_README_NAME).write_text(content, encoding="utf-8")
        logger.info(f"Wrote rescue notes: {rescue_root / RESCUE_README_NAME}")
    except Exception as e:
        logger.warning(f"Could not write rescue README in {rescue_root}: {e}")


def _prune_delete(target: Path, protected: Set[Path]) -> bool:
    """
    Delete target recursively EXCEPT any subtree equal to / containing a
    protected path. Returns True if target was fully removed.
    """
    try:
        resolved = target.resolve()
    except Exception:
        resolved = target
    if resolved in protected:
        logger.warning(f"PRESERVED (rescue incomplete): {target}")
        return False

    try:
        if target.is_symlink() or target.is_file():
            target.unlink()
            return True
        if not target.is_dir():
            return True
    except Exception as e:
        logger.warning(f"Could not remove {target}: {e}")
        return False

    fully_removed = True
    try:
        children = list(target.iterdir())
    except Exception as e:
        logger.warning(f"Could not enumerate {target}: {e}")
        return False

    for child in children:
        try:
            child_resolved = child.resolve()
        except Exception:
            child_resolved = child
        if any(_is_within(p, child_resolved) for p in protected):
            fully_removed &= _prune_delete(child, protected)
            continue
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        except Exception as e:
            logger.warning(f"Could not remove {child}: {e}")
            fully_removed = False

    if fully_removed:
        try:
            target.rmdir()
        except Exception as e:
            logger.warning(f"Could not remove {target}: {e}")
            fully_removed = False
    return fully_removed


def run_uninstall(paths, cfg: Dict[str, Any]):
    """Main uninstall entrypoint."""
    _ensure_console_logging()
    app_name = paths.app_name
    inst = cfg.get("installation", {})

    install_dir = Path(inst.get("install_dir", "~/.local/share/DailySelfie")).expanduser().resolve()
    photos_root = Path(inst.get("photos_root", install_dir / "photos")).expanduser().resolve()
    data_dir = Path(inst.get("data_dir", install_dir / "data")).expanduser().resolve()
    logs_dir = Path(inst.get("logs_dir", data_dir / "logs")).expanduser().resolve()

    logger.info(f"\n=== Uninstall {app_name} ===")
    logger.info(f"Installation directory: {install_dir}")

    # Sanity checks
    if not install_dir.exists():
        logger.info("Install directory not found. Nothing to uninstall.")
        return

    if not _is_safe_to_delete(install_dir):
        logger.error(f"Unsafe uninstall target: {install_dir}")
        logger.error("Aborting to prevent accidental data loss.")
        return

    # Confirm uninstall
    if not _confirm("Proceed with uninstallation?", default=False):
        logger.info("Uninstall cancelled.")
        return

    # ---------------------------------------------------------
    # 1. Determine Fate of Photos
    # ---------------------------------------------------------
    photos_exist = False
    try:
        photos_exist = photos_root.is_dir() and any(photos_root.iterdir())
    except Exception as e:
        logger.warning(f"Could not inspect photos directory {photos_root}: {e}")

    delete_photos = False
    if photos_exist:
        logger.info(f"\nFound photo library at: {photos_root}")
        # Default is NO (Keep photos)
        if _confirm("Do you want to PERMANENTLY DELETE these photos?", default=False):
            delete_photos = True
        else:
            logger.info("Photos will be preserved.")
            delete_photos = False

    # ---------------------------------------------------------
    # 2. Tear Down App Hooks FIRST (autostart/desktop entry/CLI)
    #    Nothing should recreate state while we rescue/delete.
    # ---------------------------------------------------------
    try:
        set_autostart(False)
    except Exception as e:
        logger.warning(f"Note: Failed to clean up autostart: {e}")

    try:
        set_desktop_entry(False)
    except Exception as e:
        logger.warning(f"Note: Failed to clean up desktop entry: {e}")

    _remove_cli_wrapper(install_dir)

    # ---------------------------------------------------------
    # 3. Rescue Phase (MOVE, never copy): photos + data minus logs
    # ---------------------------------------------------------
    protected: Set[Path] = set()
    rescued: List[Dict[str, Any]] = []
    rescue_root: Optional[Path] = None

    def _need_rescue_root() -> Optional[Path]:
        nonlocal rescue_root
        if rescue_root is None:
            rescue_root = _make_rescue_root()
        return rescue_root

    if photos_exist and not delete_photos:
        rr = _need_rescue_root()
        if rr is None:
            logger.error(
                f"No rescue location available; {photos_root} will be "
                f"PRESERVED in place (not deleted)."
            )
            protected.add(photos_root.resolve())
        else:
            protected |= _rescue_contents(photos_root, rr / "photos", [], rescued)

    if data_dir.is_dir() and _has_rescuable_content(data_dir, [logs_dir]):
        rr = _need_rescue_root()
        if rr is None:
            logger.error(
                f"No rescue location available; {data_dir} will be "
                f"PRESERVED in place (not deleted)."
            )
            protected.add(data_dir.resolve())
        else:
            protected |= _rescue_contents(data_dir, rr / "data", [logs_dir], rescued)

    if rescue_root is not None:
        _write_rescue_readme(rescue_root, rescued)

    # ---------------------------------------------------------
    # 4. Remove Installation Directory (minus any preserved subtree)
    # ---------------------------------------------------------
    if install_dir.exists():
        fully_removed = _prune_delete(install_dir, protected)
        if fully_removed:
            logger.info(f"Removed installation directory: {install_dir}")
        else:
            logger.warning(
                f"Some contents of {install_dir} were PRESERVED because their "
                f"rescue did not complete safely:"
            )
            for p in sorted(protected):
                if _is_within(p, install_dir):
                    logger.warning(f"  kept: {p}")

    # ---------------------------------------------------------
    # 5. Cleanup External Photos (Edge Case)
    # ---------------------------------------------------------
    # If photos_root was OUTSIDE install_dir and user wanted to delete them:
    if delete_photos and photos_root.exists():
        try:
            shutil.rmtree(photos_root)
            logger.info(f"Removed photos directory: {photos_root}")
        except Exception as e:
            logger.warning(f"Failed to remove photos: {e}")

    # ---------------------------------------------------------
    # 6. Final Summary
    # ---------------------------------------------------------
    logger.info("\n--- Uninstall summary ---")
    if rescued:
        for item in rescued:
            logger.info(
                f"Rescued: {item['src']} -> {item['dst']} ({item['files']} file(s))"
            )
        if rescue_root is not None:
            logger.info(
                f"Rescue folder: {rescue_root} (see README.txt inside to "
                f"reconnect a fresh install)"
            )
    else:
        logger.info("Nothing needed rescuing.")
    for p in sorted(protected):
        logger.warning(f"PRESERVED (not deleted): {p}")
    logger.info("Uninstallation complete.")


if __name__ == "__main__":
    from core.paths import get_app_paths
    from core.config import ensure_config, apply_config_to_paths

    paths = get_app_paths("DailySelfie", ensure=False)
    if paths.config_dir.exists():
        cfg = ensure_config(paths.config_dir)
        paths = apply_config_to_paths(paths, cfg)
        run_uninstall(paths, cfg)
    else:
        logger.error("Configuration not found.")
