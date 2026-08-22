"""
desktop_entry/windows.py

Creates and removes Windows desktop shortcuts (.lnk) for DailySelfie.

Shortcut locations:
  - Desktop:    %USERPROFILE%\\Desktop\\DailySelfie.lnk
  - Start Menu: %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\DailySelfie.lnk

Uses pylnk3 (pure Python, no COM dependency).
"""

from __future__ import annotations
import os
import platform
from pathlib import Path


# ─────────────────────────────────────────────
# Path helpers
# ─────────────────────────────────────────────

def _desktop_dir() -> Path:
    """User's Desktop folder."""
    return Path.home() / "Desktop"


def _start_menu_dir() -> Path:
    """User's Start Menu Programs folder."""
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def _shortcut_paths(app_name: str) -> list[Path]:
    """Return both target .lnk paths (Desktop + Start Menu)."""
    return [
        _desktop_dir() / f"{app_name}.lnk",
        _start_menu_dir() / f"{app_name}.lnk",
    ]


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def enable_desktop_entry(paths) -> None:
    """
    Create .lnk shortcut(s) on Windows.

    Target:   pythonw.exe from the project venv (avoids console window)
    Args:     path to DailySelfie.py
    WorkDir:  project root
    Icon:     app.ico
    """
    if platform.system().lower() != "windows":
        raise RuntimeError("Windows desktop entry called on non-Windows system")

    try:
        import pylnk3
    except ImportError:
        raise RuntimeError(
            "pylnk3 is required to create Windows shortcuts (pip install pylnk3)"
        )

    # Resolve key paths
    python_exe = paths.venv_dir / "Scripts" / "pythonw.exe"
    if not python_exe.exists():
        # Fallback to python.exe if pythonw is unavailable
        python_exe = paths.venv_dir / "Scripts" / "python.exe"

    app_entry = paths.project_root / "DailySelfie.py"
    icon_path = paths.project_root / "gui" / "assets" / "icons" / "app.ico"

    for lnk_path in _shortcut_paths(paths.app_name):
        # Ensure parent directory exists (Start Menu may not have Programs yet)
        lnk_path.parent.mkdir(parents=True, exist_ok=True)

        lnk = pylnk3.Lnk()
        lnk.target_file = str(python_exe)
        lnk.arguments = f'"{app_entry}"'
        lnk.working_dir = str(paths.project_root)
        lnk.description = "Daily Selfie — Your daily photo journal"
        lnk.icon_location = str(icon_path)
        lnk.icon_index = 0

        lnk.save(str(lnk_path))
        print(f"Windows shortcut created: {lnk_path}")


def disable_desktop_entry(app_name: str = "DailySelfie") -> None:
    """Remove .lnk shortcut(s) from Desktop and Start Menu."""
    for lnk_path in _shortcut_paths(app_name):
        if lnk_path.exists():
            lnk_path.unlink()
            print(f"Windows shortcut removed: {lnk_path}")
        else:
            print(f"Windows shortcut not found: {lnk_path}")


def is_desktop_entry_enabled(app_name: str = "DailySelfie") -> bool:
    """Check whether the Desktop shortcut exists."""
    desktop_lnk = _desktop_dir() / f"{app_name}.lnk"
    return desktop_lnk.exists()