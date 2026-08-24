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
from typing import Any, Dict, List

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # fallback

try:
    import tomli_w
except ModuleNotFoundError:
    tomli_w = None

try:
    # paths.py is dependency-free; used here so explicit DS_* env overrides
    # can win over config-derived defaults inside apply_config_to_paths().
    from core.paths import get_env_overrides
except ModuleNotFoundError:
    # Direct-script execution fallback (python core/config.py): degrade to
    # pre-fix behavior instead of breaking standalone use.
    get_env_overrides = None


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
        "timer_duration": 0,

        # Motion system gate (docs/design/motion-system.md)
        "motion_enabled": True,

        # Photo quality advisory gate (core/quality.py): before saving, score
        # the capture and show a Retake/Save Anyway dialog when blurry/dark/
        # bright. Advisory-only; user can always save. Passthrough bool like
        # allow_retake: no _validate_behavior coercion needed — TOML emits
        # native bools and _deep_merge fills absent keys from defaults.
        "quality_gate_enabled": True
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

    # Motion gate: bool coercion (accepts "true"/"1"/"on" style strings)
    me = behavior.get("motion_enabled", True)
    if isinstance(me, str):
        behavior["motion_enabled"] = me.strip().lower() not in ("0", "false", "off", "no")
    else:
        behavior["motion_enabled"] = bool(me)


def _deep_merge(default: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Merge override onto default recursively."""
    result = dict(default)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _strip_none(value: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a copy of a nested mapping with None-valued keys removed.
    TOML has no null; absent keys fall back to defaults on load.
    Does not mutate the input.
    """
    out: Dict[str, Any] = {}
    for k, v in value.items():
        if v is None:
            continue
        out[k] = _strip_none(v) if isinstance(v, dict) else v
    return out


def _format_toml_value(v: Any) -> str:
    """Format a scalar or flat array as an inline TOML value."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_format_toml_value(x) for x in v) + "]"
    if isinstance(v, (int, float)):
        return str(v)
    s = (
        str(v)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{s}"'


def _collect_toml_lines(mapping: Dict[str, Any], prefix: str, lines: List[str]) -> None:
    """
    Append TOML lines for one table level. None-valued keys are omitted;
    nested dicts become [dotted] sub-tables after their scalars (TOML order).
    """
    for k, v in mapping.items():
        if v is None or isinstance(v, dict):
            continue
        lines.append(f"{k} = {_format_toml_value(v)}")
    for k, v in mapping.items():
        if not isinstance(v, dict):
            continue
        header = f"{prefix}.{k}" if prefix else str(k)
        lines.append("")
        lines.append(f"[{header}]")
        _collect_toml_lines(v, header, lines)


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
            f.write(tomli_w.dumps(_strip_none(cfg)).encode("utf-8"))
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
    Uses manual TOML writing (no external dependencies), atomic replace+fsync.
    None-valued keys are omitted entirely: TOML has no null and a bare
    `null` token would make the file unparseable on the next load; absent
    keys fall back to defaults in load_config/_validate_behavior.
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)

    lines: List[str] = []
    _collect_toml_lines(cfg, "", lines)

    fd, tmp_name = tempfile.mkstemp(
        dir=str(config_path.parent), prefix=".config.", suffix=".toml"
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(("\n".join(lines) + "\n").encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        Path(tmp_name).replace(config_path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except Exception:
            pass


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

    Precedence per dir:
        explicit DS_* env var (set before this call)
        > config.toml [installation] value
        > install_dir-derived fallback / OS default already in `paths`

    When DS_DATA_DIR is set, logs_dir is pinned under it even if config.toml
    carries an explicit logs_dir, so harness probes can never be redirected
    back onto real user dirs. Use DS_LOGS_DIR for an explicit sandbox logs dir.
    """
    inst = cfg.get("installation", {})

    env = get_env_overrides() if get_env_overrides is not None else {}

    # install_dir is informational (used by installer/uninstaller)
    install_dir = Path(
        inst.get("install_dir", "~/.local/share/DailySelfie")
    ).expanduser().resolve()

    if "data_dir" in env:
        paths.data_dir = env["data_dir"]
    else:
        paths.data_dir = Path(
            inst.get("data_dir", install_dir / "data")
        ).expanduser().resolve()

    if "logs_dir" in env:
        paths.logs_dir = env["logs_dir"]
    elif "data_dir" in env:
        paths.logs_dir = env["data_dir"] / "logs"
    else:
        paths.logs_dir = Path(
            inst.get("logs_dir", install_dir / "logs")
        ).expanduser().resolve()

    if "photos_root" in env:
        paths.photos_root = env["photos_root"]
    else:
        paths.photos_root = Path(
            inst.get("photos_root", install_dir / "photos")
        ).expanduser().resolve()

    if "venv_dir" in env:
        paths.venv_dir = env["venv_dir"]
    else:
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
