"""
autostart/windows.py

Windows autostart integration using Startup folder.

Creates and removes:
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\DailySelfie.cmd
"""

from __future__ import annotations
import os
import platform
from pathlib import Path


def _startup_dir() -> Path:
    return (
        Path(os.environ["APPDATA"])
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )


def _startup_file(app_name: str) -> Path:
    return _startup_dir() / f"{app_name}.cmd"


def enable_autostart(paths) -> None:
    """
    Enable Windows autostart by creating a .cmd file in Startup folder.
    """
    if platform.system().lower() != "windows":
        raise RuntimeError("Windows autostart called on non-Windows system")

    startup_dir = _startup_dir()
    startup_dir.mkdir(parents=True, exist_ok=True)

    python_exe = paths.venv_dir / "Scripts" / "python.exe"
    app_entry = paths.project_root / "DailySelfie.py"

    cmd_content = f"""@echo off
"{python_exe}" "{app_entry}" --start-up
"""

    startup_file = _startup_file(paths.app_name)

    with startup_file.open("w", encoding="utf-8") as f:
        f.write(cmd_content)

    print(f"Windows autostart enabled: {startup_file}")


def disable_autostart(app_name: str = "DailySelfie") -> None:
    """
    Disable Windows autostart by removing the .cmd file.
    """
    startup_file = _startup_file(app_name)

    if startup_file.exists():
        startup_file.unlink()
        print(f"Windows autostart removed: {startup_file}")
    else:
        print("Windows autostart not enabled.")


def is_autostart_enabled(app_name: str = "DailySelfie") -> bool:
    """
    Check if Windows autostart is enabled.
    """
    return _startup_file(app_name).exists()
