from core.config import write_config
from autostart import enable_autostart, disable_autostart

def set_autostart(paths, cfg, enabled: bool):
    """
    Enable or disable autostart AND persist intent to config.
    """
    if enabled:
        enable_autostart(paths)
        cfg["installation"]["autostart"] = True
    else:
        disable_autostart(paths)
        cfg["installation"]["autostart"] = False

    write_config(paths.config_dir / "config.toml", cfg)
