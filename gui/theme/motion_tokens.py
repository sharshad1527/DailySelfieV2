# gui/theme/motion_tokens.py
"""
House motion language per docs/design/motion-system.md.

Durations/curves are developer constants — NOT user config. Users get
`behavior.motion_enabled` only (checked at trigger time via is_motion_enabled).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QEasingCurve

# Tokens
duration_fast = 150          # ms — hover/leave lifts, close anims
duration_base = 200          # ms — enters, toggles, transitions
curve_enter = QEasingCurve.OutCubic   # all entrances
curve_exit = QEasingCurve.InCubic     # exits
stagger_interval = 20        # ms — month-load tile cascade (cap 160 ms)
slide_distance = 16          # px — page transition offset
press_alpha = 0.12           # state-layer press fills


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "off", "no")
    return bool(value)


# Cached gate reads: hover-time callers hit this every enter/leave, so cache
# the resolved config path and the value per mtime (None = missing file).
_config_path: Optional[Path] = None
_gate_cache: Dict[str, Any] = {}


def _default_config_path() -> Path:
    global _config_path
    if _config_path is None:
        from core.paths import get_app_paths
        _config_path = get_app_paths("DailySelfie", ensure=False).config_dir / "config.toml"
    return _config_path


def is_motion_enabled(cfg: Optional[Dict[str, Any]] = None) -> bool:
    """Gate on behavior.motion_enabled; default True when absent/unreadable.

    The no-argument form reads the on-disk config with an mtime-based cache;
    passing an explicit cfg dict bypasses the cache.
    """
    try:
        if cfg is None:
            path = _default_config_path()
            try:
                mtime: Any = path.stat().st_mtime_ns
            except OSError:
                mtime = None
            cached = _gate_cache.get(str(path))
            if cached is not None and cached[0] == mtime:
                return cached[1]
            from core.config import load_config
            value = _coerce_bool(
                load_config(path).get("behavior", {}).get("motion_enabled", True))
            # mtime None = file absent: skip caching so a config.toml created
            # later in this session is picked up on the next call.
            if mtime is not None:
                _gate_cache[str(path)] = (mtime, value)
            return value
        beh = cfg.get("behavior", {}) if isinstance(cfg, dict) else {}
        return _coerce_bool(beh.get("motion_enabled", True))
    except Exception:
        return True
