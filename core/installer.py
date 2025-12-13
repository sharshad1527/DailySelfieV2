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
- MUST NOT register autostart (only record preference)
"""
from __future__ import annotations

import sys
from pathlib import Path

from core.venv_helper import ensure_venv
from core.config import DEFAULT_CONFIG, write_config
from core.autostart_manager import set_autostart


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
            return int(ans)
        except ValueError:
            print("Please enter a valid number.")


def _prompt_path(question: str, default: str) -> str:
    ans = input(f"{question} [{default}]: ").strip()
    return ans if ans else default


# ---------------------------------------------------------
# Installer
# ---------------------------------------------------------
def run_install(config_dir: Path, requirements_path: Path | None = None) -> None:
    print("\n=== DailySelfie Interactive Installer ===\n")

    cfg = DEFAULT_CONFIG.copy()
    inst = cfg["installation"]
    beh = cfg["behavior"]

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
    print()
    print(f" One photo/day     : {beh['one_photo_per_day']}")
    print(f" Allow retake      : {beh['allow_retake']}")
    print(f" Audit enabled     : {beh['audit_enabled']}")
    print()

    if _prompt_bool("Do you want to change any of these settings?", False):
        # Installation paths
        inst["install_dir"] = _prompt_path("Install directory", inst["install_dir"])
        inst["venv_dir"] = str(Path(inst["install_dir"]) / "venv")
        inst["data_dir"] = str(Path(inst["install_dir"]) / "data")
        inst["photos_root"] = str(Path(inst["install_dir"]) / "photos")
        inst["logs_dir"] = str(Path(inst["install_dir"]) / "logs")

        # Behavior
        beh["camera_index"] = _prompt_int("Camera index", beh["camera_index"])
        beh["width"] = _prompt_int("Camera width (0 = default)", beh["width"], allow_empty=True)
        beh["height"] = _prompt_int("Camera height (0 = default)", beh["height"], allow_empty=True)
        beh["quality"] = _prompt_int("JPEG quality (1-100)", beh["quality"])

        inst["autostart"] = _prompt_bool("Start DailySelfie automatically on login?", False)

    print("\nFinal installation plan:\n")
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
    print()
    print(f" Autostart         : {inst['autostart']}")
    print()

    if not _prompt_bool("Proceed with installation?", True):
        print("Installation cancelled.")
        sys.exit(0)

    # -------------------------------------------------
    # Perform installation
    # -------------------------------------------------
    print("\nInstalling...\n")

    created_dirs = []
    for p in (
        inst["install_dir"],
        inst["venv_dir"],
        inst["data_dir"],
        inst["photos_root"],
        inst["logs_dir"],
        config_dir,
    ):
        path_obj = Path(p)
        path_obj.mkdir(parents=True, exist_ok=True)
        created_dirs.append(str(path_obj))

    print("Created directories:")
    for d in created_dirs:
        print(f"  - {d}")

    # Write config
    config_path = config_dir / "config.toml"
    write_config(config_path, cfg)
    print(f"\nConfig written to: {config_path}")

    # Create venv
    print("\nCreating virtual environment and installing packages...\n")
    ok, msg, py = ensure_venv(Path(inst["venv_dir"]), requirements=requirements_path)

    if not ok:
        print(" Venv creation failed:", msg)
        sys.exit(1)
    else:
        print(f"Virtual environment ready: {py}")
    # -------------------------------------------------
    # Autostart setup (OS-specific, optional)
    # -------------------------------------------------
    if inst.get("autostart"):
        print("\nConfig requests autostart. Enabling...")
        try:
            set_autostart(paths, cfg, True)

            enable_autostart(paths)
        except Exception as e:
            print(f"Failed to enable autostart: {e}")
    else:
        print("\nAutostart disabled by user choice.")

    # Show installed packages if pip was called
    try:
        import subprocess
        print("\nInstalled packages:")
        subprocess.run(
            [str(py), "-m", "pip", "list"],
            check=False
        )
    except Exception:
        print("(could not display installed packages)")

    print("\nInstallation complete.")
    print("You can now run:")
    print(f"{py} DailySelfie.py --start-up\n")



# ---------------------------------------------------------
# Manual test entry
# ---------------------------------------------------------
if __name__ == "__main__":
    from core.paths import get_app_paths

    paths = get_app_paths("DailySelfie", ensure=True)
    req = Path("requirements.txt") if Path("requirements.txt").exists() else None
    run_install(paths.config_dir, requirements_path=req)
