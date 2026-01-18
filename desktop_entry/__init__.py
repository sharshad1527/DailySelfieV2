# __init__.py DESKTOP ENTRY 
import platform

def enable_desktop_entry(paths):
    system = platform.system().lower()
    if system == "linux":
        from .linux import enable_desktop_entry as _enable
    elif system == "windows":
        from .windows import enable_desktop_entry as _enable
    else:
        raise RuntimeError("Desktop entry not supported on this OS")
    _enable(paths)


def disable_desktop_entry(paths):
    system = platform.system().lower()
    if system == "linux":
        from .linux import disable_desktop_entry as _disable
    elif system == "windows":
        from .windows import disable_desktop_entry as _disable
    else:
        raise RuntimeError("Desktop entry not supported on this OS")
    _disable(paths.app_name)


def is_desktop_entry_enabled(paths):
    system = platform.system().lower()
    if system == "linux":
        from .linux import is_autostart_desktop_entry
    elif system == "windows":
        from .windows import is_autostart_desktop_entry
    else:
        return False
    return is_desktop_entry_enabled(paths.app_name)

