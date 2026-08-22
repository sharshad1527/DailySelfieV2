# core/installer.py
"""
Interactive installer for DailySelfie.

Responsibilities:
- Ask user for installation preferences
- Write config.toml using core.config
- Create required directories
- Create virtual environment and install dependencies

This module:
- IS interactive
- MUST NOT launch GUI
- MUST NOT register autostart directly (only records preference)
"""
from __future__ import annotations

import sys
import os
import stat
import platform
import copy
from pathlib import Path
import platform

from core.venv_helper import ensure_venv
from core.config import DEFAULT_CONFIG, write_config_bootstrap
from core.autostart_manager import set_autostart
from core.desktop_entry_manager import set_desktop_entry
from core.spinner import Spinner

#----------------------------------------------------------
# CLI Wrappers (bin/dailyselfie)
#----------------------------------------------------------
def create_cli_wrapper(install_dir: Path, venv_dir: Path, project_root: Path) -> None:
    """
    Creates Wrapper Script ('dailyselfie' or 'dailyselfie.bat')
    so user can run the app from terminal.
    """

    os_name = platform.system().lower()

    # Defining OS Based On Paths
    if os_name == "windows":
        # Create Bin Folder Inside The Install Directory
        bin_dir = install_dir / "bin"
        wrapper_name = "dailyselfie.bat"
        python_exe = venv_dir / "Scripts" / "Python.exe"
    else:
        # Linux: Use Standard User Bin Directory
        bin_dir = Path.home() / ".local" / "bin"
        wrapper_name = "dailyselfie"
        python_exe = venv_dir / "bin" / "python"

    bin_dir.mkdir(parents=True, exist_ok=True)
    wrapper_path = bin_dir / wrapper_name
    main_script = project_root / "DailySelfie.py"
    print(f"\nCreating command-line tool at {wrapper_path}")
    print(main_script)

    # Writing Command Line Content
    try: 
        if os_name == "windows":
            #-------WINDOWS.BAT FILE ---------
            content = f"""@echo off
            REM DailySelfie CLI Wrapper
            "{python_exe}" "{main_script}" %*
            """
            with open(wrapper_path, "w", encoding="utf-8") as f:
                f.write(content)

            print(f"[NOTE] To Use 'dailyselfie' from anywhare, add this to your PATH:\n --> {bin_dir}")
        
        else:
            #--------LINUX SHELL SCRIPT--------
            # We use The Venv Python Directly in the shebang
            content = f"""#!{python_exe}
# -*- coding: utf-8 -*-
import os
import sys
PROJECT_ROOT = "{project_root}"

if __name__ == '__main__':
# 1. Adding Project Root To Path
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    # 2. Verify Source Exists
    if not os.path.exists(PROJECT_ROOT):
        print(f"Error Source Code Found at:{{PROJECT_ROOT}}")
        print("Reinstall App Correctly")
        sys.exit(1)

    try:
        import DailySelfie
        sys.exit(DailySelfie.main())
    except ImportError as e:
        print(f"Error Importing DailySelfie {{e}}")
        sys.exit(1)
            """

            with open(wrapper_path, "w", encoding="utf-8") as f:
                f.write(content)

                # To Make It Executable (chmod +x)
                st = os.stat(wrapper_path)
                os.chmod(wrapper_path, st.st_mode | stat.S_IEXEC)
                print("Wrapper Created and marked executable")
    except Exception as e:
        print(f"Could not create CLI Wrapper {e}")

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def _prompt_bool(question: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        ans = input(f"{question} [{suffix}]: ").strip().lower()
        if not ans:
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("Please answer yes or no.")


def _prompt_int(question: str, default: int, allow_empty: bool = False):
    while True:
        ans = input(f"{question} [{default}]: ").strip()
        if not ans:
            return default
        if allow_empty and ans.lower() in ("none", "null"):
            return None
        try:
            val = int(ans)
            if val < 0:
                 print("Please enter a positive number.")
                 continue
            return val
        except ValueError:
            print("Please enter a valid number.")

def _prompt_choice(question: str, choices: list[str], default: str) -> str:
    choices_str = "/".join(choices)
    while True:
        ans = input(f"{question} [{choices_str}] (default: {default}): ").strip().lower()
        if not ans:
            return default
        if ans in choices:
            return ans
        print(f"Please choose one of: {choices_str}")


def _prompt_path(question: str, default: str) -> str:
    ans = input(f"{question} [{default}]: ").strip()
    return ans if ans else default


def _expand(p: str) -> Path:
    """Expand ~ and return absolute Path."""
    return Path(p).expanduser().resolve()


# ---------------------------------------------------------
# Installer
# ---------------------------------------------------------
def run_install(config_dir: Path, requirements_path: Path | None = None) -> None:
    print("\n=== DailySelfie Interactive Installer ===\n")

    # If requirements_path isn't provided, try to find it relative to this file's package
    if requirements_path is None:
        # Assuming core/installer.py -> ../requirements.txt
        # If installer.py is in core/, parent is root.
        candidate = Path(__file__).resolve().parent.parent / "requirements.txt"
        if candidate.exists():
            requirements_path = candidate

    # IMPORTANT: deep copy
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    inst = cfg["installation"]
    beh = cfg["behavior"]
    theme = cfg["theme"]

    print("Default installation plan:\n")
    print(f" Install directory      : {inst['install_dir']}")
    print(f" Venv directory         : {inst['venv_dir']}")
    print(f" Data directory         : {inst['data_dir']}")
    print(f" Photos directory       : {inst['photos_root']}")
    print(f" Logs directory         : {inst['logs_dir']}")
    print()
    print(f" Camera index           : {beh['camera_index']}")
    print(f" Resolution             : {beh['width']} x {beh['height']}")
    print(f" Image format           : {beh['image_format']}")
    print(f" JPEG quality           : {beh['quality']}")
    print(f" Timer duration         : {beh.get('timer_duration', 0)}s")
    print()
    print(f" Create Desktop Entry   : {inst['create_desktop_entry']}")
    print(f" Autostart              : {inst['autostart']}")
    print()
    print(" Theme settings:")
    print(f"  Theme name            : {theme['name']}")
    print(f"  Color mode            : {theme['mode']}")
    print(f"  Contrast level        : {theme['contrast']}")
    print()

    if _prompt_bool("Do you want to change any of these settings?", False):
        inst["install_dir"] = _prompt_path("Install directory", inst["install_dir"])
        inst["venv_dir"] = str(Path(inst["install_dir"]) / "venv")
        inst["data_dir"] = str(Path(inst["install_dir"]) / "data")
        inst["photos_root"] = str(Path(inst["install_dir"]) / "photos")
        inst["logs_dir"] = str(Path(inst["install_dir"]) / "logs")

        beh["camera_index"] = _prompt_int("Camera index", beh["camera_index"])
        beh["width"] = _prompt_int("Camera width (0 = default)", beh["width"], allow_empty=True)
        beh["height"] = _prompt_int("Camera height (0 = default)", beh["height"], allow_empty=True)
        beh["quality"] = _prompt_int("JPEG quality (1-100)", beh["quality"])

        inst["create_desktop_entry"] = _prompt_bool("Create DailySelfie Desktop Entry?", True)
        inst["autostart"] = _prompt_bool("Start DailySelfie automatically on login?", False)

        print("\nTheme preferences:\n")

        theme["mode"] = _prompt_choice(
            "Preferred color mode",
            ["dark", "light"],
            theme.get("mode", "dark"),
        )

        theme["contrast"] = _prompt_choice(
            "Preferred contrast level",
            ["standard", "medium", "high"],
            theme.get("contrast", "standard"),
        )

    print("\nFinal installation plan:\n")
    print(f" Install directory      : {inst['install_dir']}")
    print(f" Venv directory         : {inst['venv_dir']}")
    print(f" Data directory         : {inst['data_dir']}")
    print(f" Photos directory       : {inst['photos_root']}")
    print(f" Logs directory         : {inst['logs_dir']}")
    print()
    print(f" Create Desktop Entry   : {inst['create_desktop_entry']}")
    print(f" Autostart              : {inst['autostart']}")
    print()
    print(" Theme settings:")
    print(f"  Theme name            : {theme['name']}")
    print(f"  Color mode            : {theme['mode']}")
    print(f"  Contrast level        : {theme['contrast']}")
    print()

    if not _prompt_bool("Proceed with installation?", True):
        print("Installation cancelled.")
        sys.exit(0)

    # -------------------------------------------------
    # Expand paths ONCE (fixes ~ bug permanently)
    # -------------------------------------------------
    install_dir = _expand(inst["install_dir"])
    inst["install_dir"] = str(install_dir)
    inst["venv_dir"] = str(install_dir / "venv")
    inst["data_dir"] = str(install_dir / "data")
    inst["photos_root"] = str(install_dir / "photos")
    inst["logs_dir"] = str(install_dir / "logs")

    config_dir = _expand(str(config_dir))

    # -------------------------------------------------
    # Create directories
    # -------------------------------------------------
    print("\nCreating directories...\n")

    for p in (
        install_dir,
        Path(inst["venv_dir"]),
        Path(inst["data_dir"]),
        Path(inst["photos_root"]),
        Path(inst["logs_dir"]),
        config_dir,
    ):
        p.mkdir(parents=True, exist_ok=True)
        print(f"  ✓ {p}")

    # -------------------------------------------------
    # Write config
    # -------------------------------------------------
    config_path = config_dir / "config.toml"
    write_config_bootstrap(config_path, cfg)
    print(f"\nConfig written to: {config_path}")

    # -------------------------------------------------
    # Venv + pip (spinner)
    # -------------------------------------------------
    print()
    with Spinner("Setting up virtual environment"):
        ok, msg, py = ensure_venv(
            Path(inst["venv_dir"]),
            requirements=requirements_path,
            quiet=True,  # this removes pip spam
        )

    if not ok:
        print(f"\nInstallation failed: {msg}")
        sys.exit(1)

    print(f"Virtual environment ready: {py}")

    # -------------------------------------------------
    # Create CLI WRAPPER
    # -------------------------------------------------
    project_root = Path(__file__).absolute().parent.parent
    print(project_root)
    create_cli_wrapper(install_dir, Path(inst["venv_dir"]), project_root)

    # -------------------------------------------------
    # Desktop entry (single call)
    # -------------------------------------------------
    if inst.get("create_desktop_entry"):
        print("\nCreating Desktop Entry...")
        try:
            set_desktop_entry(True)
        except Exception as e:
            print(f"Failed To Create Entry: {e}")
    else:
        print("\nDesktop Entry disabled by user choice.")

    # -------------------------------------------------
    # Autostart (single call)
    # -------------------------------------------------
    if inst.get("autostart"):
        print("\nEnabling autostart...")
        try:
            set_autostart(True)
        except Exception as e:
            print(f"Autostart failed: {e}")
    else:
        print("\nAutostart disabled by user choice.")

    # -------------------------------------------------
    # Done
    # -------------------------------------------------
    print("\nInstallation complete.")
    print("You can now run:")
    print(f"dailyselfie\n")


# ---------------------------------------------------------
# Manual test
# ---------------------------------------------------------
if __name__ == "__main__":
    from core.paths import get_app_paths

    paths = get_app_paths("DailySelfie", ensure=True)
    req = Path("requirements.txt") if Path("requirements.txt").exists() else None
    run_install(paths.config_dir, requirements_path=req)


    