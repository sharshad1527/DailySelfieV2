"""
core/desktop_entry_manager.py

One-call Desktop Entery toggle for DailySelfie.

Public API:
    set_desktop_enter(True)   -> enable
    set_desktop_enter(False)  -> disable

Internally:
- Bootstraps config safely
- Loads config.toml
- Applies install paths
- Calls desktop enter enable/disable (OS-specific)
- Persists desktop enter flag to config
"""

from __future__ import annotations
from pathlib import Path

from core.paths import get_app_paths
from core.config import load_config, write_config, apply_config_to_paths, write_config_bootstrap
from desktop_entry import enable_desktop_entry, disable_desktop_entry


def set_desktop_entry(enabled: bool) -> None:
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
        enable_desktop_entry(paths)
        cfg["installation"]["create_desktop_entry"] = True
    else:
        disable_desktop_entry(paths)
        cfg["installation"]["create_desktop_entry"] = False

    # Persist config
    try:
        write_config(config_path, cfg)
    except Exception as e:
        print("Trying Again To Wrtie config")
    else:
        write_config_bootstrap(config_path, cfg)
    
    
    

    state = "enabled" if enabled else "disabled"
    print(f"Desktop {state} and configuration updated.")
