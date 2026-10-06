# gui/theme/motion_tokens.py
"""
House motion language per docs/design/motion-system.md.

Durations/curves are developer constants — NOT user config. Users get
`behavior.motion_enabled` only (checked at trigger time via is_motion_enabled).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

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


# ---------------------------------------------------------------------------
# Cached gate reads.
#
# is_motion_enabled() is called from animation hot paths (hover enter/leave on
# every liftable card, calendar tile painting, carousel retargets), so both the
# resolved config path and the boolean are cached.
#
#   * value cache — keyed by (path, mtime_ns, size, inode). One stat() per call;
#     the TOML read + parse happens only when the file actually changed. The
#     extra size/inode fields matter because write_config() writes to a temp
#     file and atomically replaces, so a fast rewrite inside the same mtime
#     tick must still invalidate the cache.
#
#   * path cache — keyed on the environment variables that are the ONLY inputs
#     to get_app_paths().config_dir. It must NOT be pinned for the process
#     lifetime: Settings supports moving/reconnecting the data location, and a
#     pinned path would keep gating on the abandoned config.toml forever
#     (regression: motion setting silently ignored after a config move).
#     os.environ reads are pure memory lookups — no filesystem hit on the hot
#     path — and the real path always comes from the canonical accessor
#     core.paths.get_app_paths().
# ---------------------------------------------------------------------------
_CONFIG_PATH_ENV_KEYS = (
    "DS_CONFIG_DIR",       # explicit harness/probe override (tests, DS_* mode)
    "DS_DEV",              # forces the project-local .ds_dev/config
    "DS_FORCE_LOCAL",      # alias of DS_DEV
    "XDG_CONFIG_HOME",     # Linux/macOS default config root
    "APPDATA",             # Windows default config root
)
_config_path: Optional[Path] = None
_config_path_env: Optional[Tuple[Optional[str], ...]] = None
_gate_cache: Dict[str, Any] = {}


def _config_env_signature() -> Tuple[Optional[str], ...]:
    """Cheap signature of everything that can move the config location."""
    return tuple(os.environ.get(k) for k in _CONFIG_PATH_ENV_KEYS)


def _default_config_path() -> Path:
    """Canonical config.toml path, re-resolved whenever its location changes."""
    global _config_path, _config_path_env
    signature = _config_env_signature()
    if _config_path is None or _config_path_env != signature:
        from core.paths import get_app_paths
        _config_path = get_app_paths("DailySelfie", ensure=False).config_dir / "config.toml"
        _config_path_env = signature
        # Entries keyed by the previous location can never be read again.
        _gate_cache.clear()
    return _config_path


def _file_token(path: Path) -> Any:
    """(mtime_ns, size, inode) or None when the file is absent/unreadable."""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def invalidate_gate_cache() -> None:
    """Drop the cached config path and every cached gate value.

    Not required for correctness (both caches are keyed on live state) but it
    is the explicit escape hatch for the "config moved" flow and for tests.
    """
    global _config_path, _config_path_env
    _config_path = None
    _config_path_env = None
    _gate_cache.clear()


def is_motion_enabled(cfg: Optional[Dict[str, Any]] = None) -> bool:
    """Gate on behavior.motion_enabled; default True when absent/unreadable.

    The no-argument form reads the on-disk config with a stat-keyed cache;
    passing an explicit cfg dict bypasses the cache entirely.
    """
    try:
        if cfg is None:
            path = _default_config_path()
            token = _file_token(path)
            cached = _gate_cache.get(str(path))
            if cached is not None and cached[0] == token:
                return cached[1]
            from core.config import load_config
            value = _coerce_bool(
                load_config(path).get("behavior", {}).get("motion_enabled", True))
            # token None = file absent: skip caching so a config.toml created
            # later in this session is picked up on the next call.
            if token is not None:
                _gate_cache[str(path)] = (token, value)
            return value
        beh = cfg.get("behavior", {}) if isinstance(cfg, dict) else {}
        return _coerce_bool(beh.get("motion_enabled", True))
    except Exception:
        return True
