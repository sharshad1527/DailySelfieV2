"""
desktop_entry/linux.py

Creates and removes ~/Desktop/DailySelfie.desktop
"""

from __future__ import annotations
import os
import platform
from pathlib import Path


DESKTOP_TEMPLATE = """[Desktop Entry]
Version=1.0
Type=Application
Name=Daily Selfie
Comment=Your DailySelfie App
Terminal=false
StartupWMClass=DailySelfie
StartupNotify=false
Exec= sh -c "{exec_cmd_desktop}"
Icon= {icon_entry}
Actions=startup;
StartupNotify=true



[Desktop Action startup]
Name=Retake Startup Window
Exec= sh -c "{exec_cmd_startup}"
Icon= {icon_entry}
StartupNotify=true

"""


def _desktop_entry_dir() -> Path:
    return Path.home() / "Desktop"

def _desktop_file_path(app_name: str) -> Path:
    return _desktop_entry_dir() / f"{app_name}.desktop"

def _application_dir() -> Path:
    return Path.home() / ".local" / "share" / "applications"

def _application_file_path(app_name: str) -> Path:
    return _application_dir() / f"{app_name}.desktop"


def enable_desktop_entry(paths) -> None:
    """
    Enable Desktop Entry on Linux using .desktop file.
    """
    if platform.system().lower() != "linux":
        raise RuntimeError("Linux desktop entry called on non-Linux system")

    # desktop_entry_dir = desktop_entry_dir()
    # desktop_entry_dir.mkdir(parents=True, exist_ok=True)

    python_exe = paths.venv_dir / "bin" / "python"
    app_entry = paths.project_root / "DailySelfie.py"
    icon_entry = paths.project_root / "gui" / "assets" / "icons" / "app.svg"

    exec_cmd_desktop = f'"{python_exe}" "{app_entry}"'
    exec_cmd_startup = f'"{python_exe}" "{app_entry}" --start-up --allow-retake'

    desktop_content = DESKTOP_TEMPLATE.format(exec_cmd_desktop=exec_cmd_desktop, exec_cmd_startup=exec_cmd_startup, icon_entry = icon_entry)

    desktop_path = _desktop_file_path(paths.app_name)
    app_path = _application_file_path(paths.app_name)

    with desktop_path.open("w", encoding="utf-8") as f:
        f.write(desktop_content)

    with app_path.open('w', encoding="utf-8") as f:
        f.write(desktop_content)

    # Ensure readable
    os.chmod(desktop_path, 0o644)
    os.chmod(app_path, 0o644)

    print(f"Linux Desktop Entry Created: {desktop_path}")
    print(f"Linux Desktop Entry Created On Application: {app_path}")


def disable_desktop_entry(app_name: str = "DailySelfie") -> None:
    """
    Disable Linux autostart by removing .desktop file.
    """
    desktop_path = _desktop_file_path(app_name)
    app_path = _application_file_path(app_name)

    if desktop_path.exists():
        desktop_path.unlink()
        print(f"Linux Desktop Entry removed: {desktop_path}")
    else:
        print("Linux Desktop not Avaliable")
    
    if app_path.exists():
        app_path.unlink()
        print(f"Linux Application Entry removed: {app_path}")
    else:
        print("Linux Application not found")
    




def is_desktop_entry_enabled(app_name: str = "DailySelfie") -> bool:
    """
    Check whether Linux autostart is enabled.
    """
    return _desktop_file(app_name).exists()

