"""
core/paths.py

Refactored for proper install/config awareness.

Now:
- No longer creates directories on import (ensure=False default)
- DS_DEV still works, but can defer to config.toml if present
- Paths.py stays pure and does not import config.py
"""
from __future__ import annotations
from dataclasses import dataclass
import os
import platform
from pathlib import Path
from typing import Optional, Dict


@dataclass
class AppPaths:
    app_name: str
    os_name: str
    home: Path
    project_root: Path
    config_dir: Path
    data_dir: Path
    logs_dir: Path
    photos_root: Path
    venv_dir: Path

    def as_dict(self) -> Dict[str, str]:
        return {k: str(v) for k, v in self.__dict__.items() if isinstance(v, Path) or isinstance(v, str)}


# Defaults
_DEFAULT_PHOTOS_SUBDIR = "Pictures"
_DEFAULT_VENV_DIRNAME = ".venv"
_DEFAULT_DEV_FOLDER = ".ds_dev"


def _truthy_env(name: str) -> bool:
    v = os.environ.get(name)
    if not v:
        return False
    return v.strip().lower() in ("1", "true", "yes", "on")


def _expand_env_override(var: str) -> Optional[Path]:
    v = os.environ.get(var)
    if not v:
        return None
    return Path(v).expanduser().resolve()


def _ensure_dir(p: Path) -> Path:
    """Create a directory if missing."""
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        raise
    return p


def get_app_paths(app_name: str = "DailySelfie", *, ensure: bool = False) -> AppPaths:
    """
    Resolve default OS paths for the app.

    DS_DEV=1 → forces project-local .ds_dev directory.
    If config.toml exists under ~/.config/<app_name>/ or ./.ds_dev/config/,
    its install_dir may be used later by config.py.
    """
    home = Path.home()
    os_name = platform.system().lower()
    project_root = Path.cwd().expanduser().resolve()

    # Development mode
    dev_mode = _truthy_env("DS_DEV") or _truthy_env("DS_FORCE_LOCAL")
    dev_base = project_root / _DEFAULT_DEV_FOLDER

    # Environment overrides
    cfg_override = _expand_env_override("DS_CONFIG_DIR")
    data_override = _expand_env_override("DS_DATA_DIR")
    photos_override = _expand_env_override("DS_PHOTOS_DIR")
    venv_override = _expand_env_override("DS_VENV_DIR")

    if dev_mode:
        base = dev_base
        config_dir = cfg_override or (base / "config")
        data_dir = data_override or (base / "data")
        photos_root = photos_override or (base / "photos")
        venv_dir = venv_override or (base / "venv")
    else:
        if os_name == "windows":
            appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
            localappdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
            default_config = appdata / app_name
            default_data = localappdata / app_name
            default_photos = Path(os.environ.get("USERPROFILE", home)) / app_name / _DEFAULT_PHOTOS_SUBDIR
        else:
            xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
            xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
            default_config = xdg_config / app_name
            default_data = xdg_data / app_name
            default_photos = Path(os.environ.get("DS_PHOTOS_FALLBACK", home / _DEFAULT_PHOTOS_SUBDIR))

        config_dir = cfg_override or default_config
        data_dir = data_override or default_data
        photos_root = photos_override or default_photos
        venv_dir = venv_override or (data_dir / _DEFAULT_VENV_DIRNAME)

    logs_dir = Path(data_dir) / "logs"

    # Normalize
    config_dir = Path(config_dir).expanduser().resolve()
    data_dir = Path(data_dir).expanduser().resolve()
    photos_root = Path(photos_root).expanduser().resolve()
    venv_dir = Path(venv_dir).expanduser().resolve()
    logs_dir = Path(logs_dir).expanduser().resolve()

    if ensure:
        for p in (config_dir, data_dir, logs_dir, photos_root, venv_dir):
            _ensure_dir(p)

    return AppPaths(
        app_name=app_name,
        os_name=os_name,
        home=home,
        project_root=project_root,
        config_dir=config_dir,
        data_dir=data_dir,
        logs_dir=logs_dir,
        photos_root=photos_root,
        venv_dir=venv_dir,
    )


def photos_folder_for_ts(root: Path, year: int) -> Path:
    folder = root / str(year)
    _ensure_dir(folder)
    return folder


if __name__ == "__main__":
    p = get_app_paths("DailySelfie", ensure=False)
    print("OS:", p.os_name)
    print("Resolved paths:")
    for k, v in p.as_dict().items():
        print(f"{k}: {v}")
