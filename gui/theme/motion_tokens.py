# gui/theme/motion_tokens.py
"""
House motion language per docs/design/motion-system.md.

Durations/curves are developer constants — NOT user config. Users get
`behavior.motion_enabled` only (checked at trigger time via is_motion_enabled).
"""
from __future__ import annotations

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


def is_motion_enabled(cfg: Optional[Dict[str, Any]] = None) -> bool:
    """Gate on behavior.motion_enabled; default True when absent/unreadable."""
    try:
        if cfg is None:
            from core.config import load_config
            from core.paths import get_app_paths
            cfg = load_config(get_app_paths("DailySelfie", ensure=False).config_dir / "config.toml")
        beh = cfg.get("behavior", {}) if isinstance(cfg, dict) else {}
        return _coerce_bool(beh.get("motion_enabled", True))
    except Exception:
        return True
