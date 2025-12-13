#!/usr/bin/env python3
"""
DailySelfie.py

Top-level CLI and entrypoint for DailySelfie.
Corrected to respect config-based install paths.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.paths import get_app_paths
from core.config import ensure_config, apply_config_to_paths, write_config
from core.logging import init_logger, read_jsonl_tail
from core.venv_helper import ensure_venv
from core.index_api import get_api as get_index_api
from core.autostart_manager import set_autostart


# ---------------------------------------------------------
# Command helpers
# ---------------------------------------------------------
def cmd_show_paths(paths):
    print("Resolved paths:")
    print(f"os:       {paths.os_name}")
    print(f"home:     {paths.home}")
    print(f"config:   {paths.config_dir}")
    print(f"data:     {paths.data_dir}")
    print(f"logs:     {paths.logs_dir}")
    print(f"photos:   {paths.photos_root}")
    print(f"venv:     {paths.venv_dir}")


def cmd_list_cameras(logger, max_test=8):
    try:
        from core.camera import list_cameras
    except Exception as e:
        logger.error("camera_list_failed", extra={"meta": {"error": str(e)}})
        print("Camera listing unavailable.")
        return 3

    cams = list_cameras(max_test=max_test, only_available=True)
    if not cams:
        print("No usable cameras detected.")
        return 4

    for i, res in cams.items():
        print(f"{i}: available={res.available} read_ok={res.read_ok}")
    return 0


def cmd_capture(paths, cfg, logger, args):
    from core.capture import capture_once

    beh = cfg["behavior"]

    camera_index = args.camera_index if args.camera_index is not None else beh["camera_index"]
    width = args.width if args.width is not None else beh["width"]
    height = args.height if args.height is not None else beh["height"]
    quality = args.quality if args.quality is not None else beh["quality"]
    allow_retake = args.allow_retake or beh["allow_retake"]

    out = capture_once(
        paths,
        camera_index=camera_index,
        width=width,
        height=height,
        quality=quality,
        logger=logger,
        allow_retake=allow_retake,
    )

    if out.get("success"):
        print("Captured:", out["path"])
        return 0
    else:
        print("Capture failed:", out.get("error"))
        return 6


def cmd_tail_logs(paths, n=20):
    try:
        logs = read_jsonl_tail(paths.logs_dir / "dailyselfie.jsonl", max_lines=n)
    except Exception as e:
        print("Failed to read logs:", e)
        return 10

    for item in logs:
        print(item)
    return 0


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------
def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]

    # 1. Resolve OS bootstrap paths ONLY
    bootstrap_paths = get_app_paths("DailySelfie", ensure=False)

    # -------------------------------------------------
    # CLI
    # -------------------------------------------------
    parser = argparse.ArgumentParser(prog="DailySelfie")

    parser.add_argument("--install", action="store_true", help="Install DailySelfie")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall DailySelfie")
    parser.add_argument("--enable-autostart", action="store_true", help="Enable autostart on login")
    parser.add_argument("--disable-autostart", action="store_true", help="Disable autostart on login")
    parser.add_argument("--start-up", action="store_true", help="Start Manager UI")

    parser.add_argument("--show-paths", action="store_true")
    parser.add_argument("--list-cameras", action="store_true")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--allow-retake", action="store_true")
    parser.add_argument("--tail-logs", type=int, nargs="?", const=20)

    parser.add_argument("--camera-index", type=int)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--quality", type=int)

    args = parser.parse_args(argv)

    # -------------------------------------------------
    # INSTALL
    # -------------------------------------------------
    if args.install:
        from core.installer import run_install
        req = Path("requirements.txt") if Path("requirements.txt").exists() else None
        run_install(bootstrap_paths.config_dir, requirements_path=req)
        return 0

    

    # 2. Load config ONLY from OS config dir
    config_path = bootstrap_paths.config_dir / "config.toml"

    if not config_path.exists():
        print("DailySelfie is not installed.")
        print("Run: python DailySelfie.py --install")
        return 1

    from core.config import load_config
    cfg = load_config(config_path)

    # 3. Apply install paths
    paths = apply_config_to_paths(bootstrap_paths, cfg)


    # -------------------------------------------------
    # 3. Apply config install_dir → override paths
    # -------------------------------------------------
    paths = apply_config_to_paths(paths, cfg)

    # -------------------------------------------------
    # 4. NOW create directories (final locations only)
    # -------------------------------------------------
    for p in (
        paths.config_dir,
        paths.data_dir,
        paths.logs_dir,
        paths.photos_root,
        paths.venv_dir,
    ):
        p.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------
    # 5. Initialize logger & index DB
    # -------------------------------------------------
    logger = init_logger(paths.logs_dir)

    try:
        get_index_api(paths)
    except Exception:
        logger.exception("index_api_init_failed")




    # -------------------------------------------------
    # STARTUP (GUI stub)
    # -------------------------------------------------
    if args.start_up:
        print("Manager UI not implemented yet.")
        print("This will launch the GUI in the future.")
        return 0

    # -------------------------------------------------
    # AUTOSTART
    # -------------------------------------------------

    if args.enable_autostart:
        try:
            set_autostart(True)
        except Exception as e:
            print("Failed to enable autostart:", e)
            return 1
        return 0

    if args.disable_autostart:
        try:
            set_autostart(False)
        except Exception as e:
            print("Failed to disable autostart:", e)
            return 1
        return 0
    # -------------------------------------------------
    # UNINSTALL
    # -------------------------------------------------
    if args.uninstall:
        from core.uninstaller import run_uninstall
        run_uninstall(paths, cfg)
        return 0
    # -------------------------------------------------
    # CLI COMMANDS
    # -------------------------------------------------
    if args.show_paths:
        return cmd_show_paths(paths) or 0

    if args.list_cameras:
        return cmd_list_cameras(logger)

    if args.capture:
        return cmd_capture(paths, cfg, logger, args)

    if args.tail_logs is not None:
        return cmd_tail_logs(paths, args.tail_logs)

    # Default behavior
    print("No command specified.")
    print("This will launch Manager UI by default in the future.")
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
