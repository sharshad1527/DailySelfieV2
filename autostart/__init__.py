# __init__.py AUTOSTART
import platform

def enable_autostart(paths):
    system = platform.system().lower()
    if system == "linux":
        from .linux import enable_autostart as _enable
    elif system == "windows":
        from .windows import enable_autostart as _enable
    else:
        raise RuntimeError("Autostart not supported on this OS")
    _enable(paths)


def disable_autostart(paths):
    system = platform.system().lower()
    if system == "linux":
        from .linux import disable_autostart as _disable
    elif system == "windows":
        from .windows import disable_autostart as _disable
    else:
        raise RuntimeError("Autostart not supported on this OS")
    _disable(paths.app_name)


def is_autostart_enabled(paths):
    system = platform.system().lower()
    if system == "linux":
        from .linux import is_autostart_enabled
    elif system == "windows":
        from .windows import is_autostart_enabled
    else:
        return False
    return is_autostart_enabled(paths.app_name)
