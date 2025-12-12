"""
paths.py

OS-aware path resolution for DailySelfie project.
Provides a single AppPaths dataclass and helper functions to resolve and create
application directories (config, data, logs, photos, venv).

Behavior:
- Uses XDG spec on Unix-like systems (XDG_CONFIG_HOME, XDG_DATA_HOME)
- Uses APPDATA / LOCALAPPDATA on Windows falling back to sensible defaults
- Allows environment-variable overrides for each path via DS_ prefixed vars, e.g.
  DS_CONFIG_DIR, DS_DATA_DIR, DS_PHOTOS_DIR, DS_VENV_DIR
- Ensures directories exist when requested
- Returns stable pathlib.Path objects

Example:
    from paths import get_app_paths
    paths = get_app_paths("DailySelfie")
    print(paths.photos_root)

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


def _expand_env_override(var: str) -> Optional[Path]:
    v = os.environ.get(var)
    if not v:
        return None
    return Path(v).expanduser().resolve()


def _ensure_dir(p: Path) -> Path:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        # Let caller handle exceptions if they want; we raise for visibility
        raise
    return p


def get_app_paths(app_name: str = "DailySelfie", *, ensure: bool = True) -> AppPaths:
    """Resolve application paths and return AppPaths.

    Parameters
    ----------
    app_name: str
        Application name used as directory name under config/data on most
        platforms.
    ensure: bool
        If True, directories will be created on disk.

    Environment overrides
    ---------------------
    DS_CONFIG_DIR  - absolute/relative path to config dir
    DS_DATA_DIR    - absolute/relative path to data dir
    DS_PHOTOS_DIR  - absolute/relative path to photos root
    DS_VENV_DIR    - absolute/relative path to venv dir

    Returns
    -------
    AppPaths
    """
    home = Path.home()
    os_name = platform.system().lower()

    # Environment overrides
    cfg_override = _expand_env_override("DS_CONFIG_DIR")
    data_override = _expand_env_override("DS_DATA_DIR")
    photos_override = _expand_env_override("DS_PHOTOS_DIR")
    venv_override = _expand_env_override("DS_VENV_DIR")

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
    logs_dir = data_dir / "logs"

    # Normalize
    config_dir = config_dir.expanduser().resolve()
    data_dir = data_dir.expanduser().resolve()
    photos_root = photos_root.expanduser().resolve()
    venv_dir = venv_dir.expanduser().resolve()
    logs_dir = logs_dir.expanduser().resolve()

    if ensure:
        for p in (config_dir, data_dir, logs_dir, photos_root, venv_dir):
            _ensure_dir(p)

    return AppPaths(
        app_name=app_name,
        os_name=os_name,
        home=home,
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
    print("Resolved paths:")
    print(f"OS: {p.os_name}")
    print(f"config_dir: {p.config_dir}")
    print(f"data_dir:   {p.data_dir}")
    print(f"logs_dir:   {p.logs_dir}")
    print(f"photos_root:{p.photos_root}")
    print(f"venv_dir:   {p.venv_dir}")
