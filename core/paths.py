"""
paths.py

OS-aware path resolution for DailySelfie project.
Provides a single AppPaths dataclass and helper functions to resolve and create
application directories (config, data, logs, photos, venv).

This version adds a development mode switch controlled by environment variables
so you can keep all files inside the project folder during development.

Behavior summary:
- If DS_DEV is set to a truthy value ("1", "true", "yes") OR DS_FORCE_LOCAL is set,
  the resolver will place all folders under a single project-local directory
  (./.ds_dev by default) for easy testing.
- You can still override individual paths with DS_CONFIG_DIR, DS_DATA_DIR,
  DS_PHOTOS_DIR, DS_VENV_DIR environment variables.
- Uses XDG spec on Unix-like systems (XDG_CONFIG_HOME, XDG_DATA_HOME) by default,
  and APPDATA / LOCALAPPDATA on Windows unless dev mode or overrides are used.

Example dev usage (no env exports required):
    export DS_DEV=1
    python DailySelfie.py --show-paths

Alternatively set explicit overrides:
    export DS_DATA_DIR=./.ds_dev/data

"""
from __future__ import annotations
from dataclasses import dataclass
import os
import platform
from pathlib import Path
from typing import Optional, Dict


@dataclass(frozen=True)
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
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Let caller handle exceptions if they want; we raise for visibility
        raise
    return p


def get_app_paths(app_name: str = "DailySelfie", *, ensure: bool = True) -> AppPaths:
    """Resolve application paths and return AppPaths.

    Development mode:
      If DS_DEV is set (or DS_FORCE_LOCAL) the resolver will use a project-local
      folder (cwd / .ds_dev) to contain config, data, photos and venv. This makes
      testing and cleanup trivial.

    Environment overrides
    ---------------------
    DS_CONFIG_DIR  - absolute/relative path to config dir
    DS_DATA_DIR    - absolute/relative path to data dir
    DS_PHOTOS_DIR  - absolute/relative path to photos root
    DS_VENV_DIR    - absolute/relative path to venv dir

    """
    home = Path.home()
    os_name = platform.system().lower()
    project_root = Path.cwd().expanduser().resolve()

    # If dev mode requested, make everything local under .ds_dev unless explicitly overridden.
    dev_mode = _truthy_env("DS_DEV") or _truthy_env("DS_FORCE_LOCAL")
    dev_base = project_root / _DEFAULT_DEV_FOLDER

    # Environment overrides
    cfg_override = _expand_env_override("DS_CONFIG_DIR")
    data_override = _expand_env_override("DS_DATA_DIR")
    photos_override = _expand_env_override("DS_PHOTOS_DIR")
    venv_override = _expand_env_override("DS_VENV_DIR")

    if dev_mode:
        # prefer explicit overrides even in dev mode
        config_dir = cfg_override or (dev_base / "config")
        data_dir = data_override or (dev_base / "data")
        photos_root = photos_override or (dev_base / "photos")
        venv_dir = venv_override or (dev_base / "venv")
    else:
        # Normal OS-specific resolution
        if os_name == "windows":
            appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
            localappdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
            default_config = appdata / app_name
            default_data = localappdata / app_name
            default_photos = Path(os.environ.get("USERPROFILE", home)) / app_name / _DEFAULT_PHOTOS_SUBDIR
        else:
            # macOS and Linux: follow XDG where possible
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

    # Normalize to absolute resolved paths
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


# Convenience helpers
def photos_folder_for_ts(root: Path, year: int) -> Path:
    """Return the photos subfolder for a given year (creates it)."""
    folder = root / str(year)
    _ensure_dir(folder)
    return folder


if __name__ == "__main__":
    # Quick smoke test when run directly
    p = get_app_paths("DailySelfie", ensure=True)
    print(f"OS: {p.os_name}")
    print("Resolved paths:")
    print(f"project_root: {p.project_root}")
    print(f"config_dir: {p.config_dir}")
    print(f"data_dir:   {p.data_dir}")
    print(f"logs_dir:   {p.logs_dir}")
    print(f"photos_root:{p.photos_root}")
    print(f"venv_dir:   {p.venv_dir}")
