# core/config.py
"""
Configuration management for DailySelfie.

Responsibilities:
- Define default configuration
- Load config.toml if it exists
- Create config.toml with defaults if missing
- Normalize and validate paths
- Write config atomically

This module MUST NOT:
- Perform installation
- Create venvs
- Register autostart
- Ask user input
"""
from __future__ import annotations

import os
import platform
import tempfile
from pathlib import Path
from typing import Dict, Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # fallback

try:
    import tomli_w
except ModuleNotFoundError:
    tomli_w = None


# ---------------------------------------------------------
# Default configuration (OS-AWARE DEFAULTS)
# ---------------------------------------------------------
# Detect OS to determine the correct default root
if platform.system().lower() == "windows":
    # Windows: ~\AppData\Local\DailySelfie
    _DEF_ROOT = r"~\AppData\Local\DailySelfie"
    _SEP = "\\"
else:
    # Linux/Mac: ~/.local/share/DailySelfie
    _DEF_ROOT = "~/.local/share/DailySelfie"
    _SEP = "/"

DEFAULT_CONFIG: Dict[str, Any] = {
    "installation": {
        "install_dir": _DEF_ROOT,
        "venv_dir": f"{_DEF_ROOT}{_SEP}venv",
        "data_dir": f"{_DEF_ROOT}{_SEP}data",
        "logs_dir": f"{_DEF_ROOT}{_SEP}logs",
        "photos_root": f"{_DEF_ROOT}{_SEP}photos",
        "create_desktop_entry": True,
        "autostart": False,
    },
    "behavior": {
        "camera_index": 0,

        # Camera resolution (0 or None = camera default)
        "width": 1280,
        "height": 720,

        # Image encoding
        "image_format": "jpg",  # future: png, webp
        "quality": 90,

        # Capture rules
        "audit_enabled": True,
        "one_photo_per_day": True,
        "allow_retake": False,

        # Default timer is 0 (Off)
        "timer_duration": 0
    },
    "theme": {
    "name": "material-theme",

    # Dark Or Light
    "mode": "dark", 

    # Contrast standard, medium, high
    "contrast": "standard"
    },
}


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def _expand_path(p: str) -> str:
    """Expand ~ and environment variables and return absolute path."""
    return str(Path(os.path.expandvars(os.path.expanduser(p))).resolve())


def _normalize_paths(cfg: Dict[str, Any]) -> None:
    """Normalize all path values in-place."""
    inst = cfg.get("installation", {})
    for key in ("install_dir", "venv_dir", "data_dir", "logs_dir", "photos_root"):
        if key in inst and isinstance(inst[key], str):
            inst[key] = _expand_path(inst[key])


def _validate_behavior(cfg: Dict[str, Any]) -> None:
    """Validate behavior settings for correctness."""
    behavior = cfg.get("behavior", {})

    fmt = behavior.get("image_format", "jpg").lower()
    if fmt not in ("jpg",):
        raise ValueError(f"Unsupported image_format: {fmt}")
    behavior["image_format"] = fmt

    # Normalize width/height
    for k in ("width", "height"):
        v = behavior.get(k)
        if v in (0, None):
            behavior[k] = None
        elif not isinstance(v, int) or v <= 0:
            raise ValueError(f"{k} must be a positive integer or null")

    q = behavior.get("quality", 90)
    if not isinstance(q, int) or not (1 <= q <= 100):
        raise ValueError("quality must be an integer between 1 and 100")
    behavior["quality"] = q


def _deep_merge(default: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Merge override onto default recursively."""
    result = dict(default)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# ---------------------------------------------------------
# Public API
# ---------------------------------------------------------
def load_config(config_path: Path) -> Dict[str, Any]:
    """
    Load config.toml from disk.
    Returns merged config (defaults + user overrides).
    Does NOT write to disk.
    """
    if not config_path.exists():
        cfg = dict(DEFAULT_CONFIG)
        _normalize_paths(cfg)
        _validate_behavior(cfg)
        return cfg

    with config_path.open("rb") as f:
        user_cfg = tomllib.load(f)

    cfg = _deep_merge(DEFAULT_CONFIG, user_cfg)
    _normalize_paths(cfg)
    _validate_behavior(cfg)
    return cfg


def write_config(config_path: Path, cfg: Dict[str, Any]) -> None:
    """
    Write config.toml atomically.
    """
    if tomli_w is None:
        raise RuntimeError("tomli-w is required to write config.toml")

    config_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=str(config_path.parent), prefix=".config.", suffix=".toml"
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(tomli_w.dumps(cfg).encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        Path(tmp_name).replace(config_path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except Exception:
            pass


def write_config_bootstrap(config_path: Path, cfg: Dict[str, Any]) -> None:
    """
    Bootstrap-safe config writer.
    Uses manual TOML writing.
    No external dependencies.
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []

    for section, values in cfg.items():
        lines.append(f"[{section}]")
        for k, v in values.items():
            if isinstance(v, bool):
                v = "true" if v else "false"
            elif v is None:
                v = "null"
            elif isinstance(v, (int, float)):
                v = str(v)
            else:
                # Escape backslashes and quotes for Windows paths
                val_str = str(v)
                val_str = val_str.replace("\\", "\\\\").replace('"', '\\"')
                v = f'"{val_str}"'
            lines.append(f"{k} = {v}")
        lines.append("")

    config_path.write_text("\n".join(lines), encoding="utf-8")


def ensure_config(config_dir: Path) -> Dict[str, Any]:
    """
    Ensure config.toml exists in config_dir.
    If missing → create with defaults.
    Returns loaded config dict.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"

    if not config_path.exists():
        cfg = dict(DEFAULT_CONFIG)
        _normalize_paths(cfg)
        _validate_behavior(cfg)
        write_config(config_path, cfg)
        return cfg

    return load_config(config_path)

def apply_config_to_paths(paths, cfg: Dict[str, Any]):
    """
    Override install-related paths using config.
    config_dir is NOT overridden (bootstrap invariant).
    """
    inst = cfg.get("installation", {})

    # install_dir is informational (used by installer/uninstaller)
    install_dir = Path(
        inst.get("install_dir", "~/.local/share/DailySelfie")
    ).expanduser().resolve()

    paths.data_dir = Path(
        inst.get("data_dir", install_dir / "data")
    ).expanduser().resolve()

    paths.logs_dir = Path(
        inst.get("logs_dir", install_dir / "logs")
    ).expanduser().resolve()

    paths.photos_root = Path(
        inst.get("photos_root", install_dir / "photos")
    ).expanduser().resolve()

    paths.venv_dir = Path(
        inst.get("venv_dir", install_dir / "venv")
    ).expanduser().resolve()

    return paths




# ---------------------------------------------------------
# Debug / smoke test
# ---------------------------------------------------------
if __name__ == "__main__":
    test_dir = Path("./_config_test")
    cfg = ensure_config(test_dir)
    print("Config loaded:")
    for section, values in cfg.items():
        print(f"[{section}]")
        for k, v in values.items():
            print(f"  {k} = {v}")
