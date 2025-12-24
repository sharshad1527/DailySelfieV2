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
import copy
from pathlib import Path

from core.venv_helper import ensure_venv
from core.config import DEFAULT_CONFIG, write_config_bootstrap
from core.autostart_manager import set_autostart
from core.spinner import Spinner


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
    print(f" Install directory : {inst['install_dir']}")
    print(f" Venv directory    : {inst['venv_dir']}")
    print(f" Data directory    : {inst['data_dir']}")
    print(f" Photos directory  : {inst['photos_root']}")
    print(f" Logs directory    : {inst['logs_dir']}")
    print()
    print(f" Camera index      : {beh['camera_index']}")
    print(f" Resolution        : {beh['width']} x {beh['height']}")
    print(f" Image format      : {beh['image_format']}")
    print(f" JPEG quality      : {beh['quality']}")
    print(f" Timer duration    : {beh.get('timer_duration', 0)}s")
    print()
    print(f" Autostart         : {inst['autostart']}")
    print()
    print(" Theme settings:")
    print(f"  Theme name       : {theme['name']}")
    print(f"  Color mode       : {theme['mode']}")
    print(f"  Contrast level   : {theme['contrast']}")
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
    print(f" Install directory : {inst['install_dir']}")
    print(f" Venv directory    : {inst['venv_dir']}")
    print(f" Data directory    : {inst['data_dir']}")
    print(f" Photos directory  : {inst['photos_root']}")
    print(f" Logs directory    : {inst['logs_dir']}")
    print()
    print(f" Autostart         : {inst['autostart']}")
    print()
    print(" Theme settings:")
    print(f"  Theme name       : {theme['name']}")
    print(f"  Color mode       : {theme['mode']}")
    print(f"  Contrast level   : {theme['contrast']}")
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
    print(f"{py} DailySelfie.py --start-up\n")


# ---------------------------------------------------------
# Manual test
# ---------------------------------------------------------
if __name__ == "__main__":
    from core.paths import get_app_paths

    paths = get_app_paths("DailySelfie", ensure=True)
    req = Path("requirements.txt") if Path("requirements.txt").exists() else None
    run_install(paths.config_dir, requirements_path=req)
