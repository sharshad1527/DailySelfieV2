"""
core/autostart_manager.py

One-call autostart toggle for DailySelfie.

Public API:
    set_autostart(True)   -> enable
    set_autostart(False)  -> disable

Internally:
- Bootstraps config safely
- Loads config.toml
- Applies install paths
- Calls autostart.enable/disable (OS-specific)
- Persists autostart flag to config
"""

from __future__ import annotations
from pathlib import Path

from core.paths import get_app_paths
from core.config import load_config, write_config, apply_config_to_paths
from autostart import enable_autostart, disable_autostart


def set_autostart(enabled: bool) -> None:
    """
    Enable or disable DailySelfie autostart globally.

    Automatically:
      - Loads config
      - Resolves install paths
      - Enables/disables autostart for OS
      - Updates config.toml
    """
    # Bootstrap basic paths
    bootstrap_paths = get_app_paths("DailySelfie", ensure=False)
    config_path = bootstrap_paths.config_dir / "config.toml"

    if not config_path.exists():
        raise RuntimeError("DailySelfie is not installed (config.toml missing).")

    # Load config + resolve install paths
    cfg = load_config(config_path)
    paths = apply_config_to_paths(bootstrap_paths, cfg)

    # Apply OS-specific change
    if enabled:
        enable_autostart(paths)
        cfg["installation"]["autostart"] = True
    else:
        disable_autostart(paths)
        cfg["installation"]["autostart"] = False

    # Persist config
    write_config(config_path, cfg)

    state = "enabled" if enabled else "disabled"
    print(f"Autostart {state} and configuration updated.")
