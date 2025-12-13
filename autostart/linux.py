"""
autostart/linux.py

Linux autostart integration using XDG Autostart specification.

Creates and removes ~/.config/autostart/DailySelfie.desktop
"""

from __future__ import annotations
import os
import platform
from pathlib import Path


DESKTOP_TEMPLATE = """[Desktop Entry]
Type=Application
Version=1.0
Name=DailySelfie
Comment=Daily Selfie Capture App
Exec= sh -c "sleep 30 && {exec_cmd}"
Icon=camera
Terminal=false
X-GNOME-Autostart-enabled=true
"""


def _autostart_dir() -> Path:
    return Path.home() / ".config" / "autostart"


def _desktop_file(app_name: str) -> Path:
    return _autostart_dir() / f"{app_name}.desktop"


def enable_autostart(paths) -> None:
    """
    Enable autostart on Linux using .desktop file.
    """
    if platform.system().lower() != "linux":
        raise RuntimeError("Linux autostart called on non-Linux system")

    autostart_dir = _autostart_dir()
    autostart_dir.mkdir(parents=True, exist_ok=True)

    python_exe = paths.venv_dir / "bin" / "python"
    app_entry = paths.project_root / "DailySelfie.py"

    exec_cmd = f'"{python_exe}" "{app_entry}" --start-up'

    desktop_content = DESKTOP_TEMPLATE.format(exec_cmd=exec_cmd)

    desktop_path = _desktop_file(paths.app_name)

    with desktop_path.open("w", encoding="utf-8") as f:
        f.write(desktop_content)

    # Ensure readable
    os.chmod(desktop_path, 0o644)

    print(f"Linux autostart enabled: {desktop_path}")


def disable_autostart(app_name: str = "DailySelfie") -> None:
    """
    Disable Linux autostart by removing .desktop file.
    """
    desktop_path = _desktop_file(app_name)

    if desktop_path.exists():
        desktop_path.unlink()
        print(f"Linux autostart removed: {desktop_path}")
    else:
        print("Linux autostart not enabled.")


def is_autostart_enabled(app_name: str = "DailySelfie") -> bool:
    """
    Check whether Linux autostart is enabled.
    """
    return _desktop_file(app_name).exists()
