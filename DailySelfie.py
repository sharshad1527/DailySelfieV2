#!/usr/bin/env python3
"""
DailySelfie.py

The central entry point for the Daily Selfie application.
Handles CLI arguments, installation lifecycle, and launching the GUI.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Core utilities (fast imports)
from core.paths import get_app_paths
from core.config import load_config, apply_config_to_paths
from core.logging import init_logger, read_jsonl_tail
from core.index_api import get_api as get_index_api
from core.autostart_manager import set_autostart


# ---------------------------------------------------------
# Sub-Command Handlers
# ---------------------------------------------------------
def cmd_show_paths(paths):
    """Debug: Print all resolved system paths."""
    print("\n[Resolved Application Paths]")
    print(f"  OS Name       : {paths.os_name}")
    print(f"  Home Dir      : {paths.home}")
    print(f"  Project Root  : {paths.project_root}")
    print(f"  Config Dir    : {paths.config_dir}")
    print(f"  Data Dir      : {paths.data_dir}")
    print(f"  Logs Dir      : {paths.logs_dir}")
    print(f"  Photos Dir    : {paths.photos_root}")
    print(f"  Venv Dir      : {paths.venv_dir}")
    print()


def cmd_list_cameras(logger, max_test=8):
    """Debug: List available cameras using OpenCV."""
    print("\nScanning for cameras...")
    try:
        from core.camera import list_cameras
    except Exception as e:
        logger.error("camera_list_failed", extra={"meta": {"error": str(e)}})
        print(f"Error loading camera module: {e}")
        return 3

    cams = list_cameras(max_test=max_test, only_available=True)
    if not cams:
        print("No usable cameras detected.")
        return 4

    print(f"Found {len(cams)} usable camera(s):")
    for i, res in cams.items():
        print(f"  [Index {i}] Available: {res.available}, Read OK: {res.read_ok}")
    print()
    return 0


def cmd_capture(paths, cfg, logger, args):
    """Action: Take a single photo immediately (Headless Mode)."""
    from core.capture import capture_once

    beh = cfg["behavior"]

    # Prefer CLI args, fall back to config
    idx = args.camera_index if args.camera_index is not None else beh["camera_index"]
    w = args.width if args.width is not None else beh["width"]
    h = args.height if args.height is not None else beh["height"]
    q = args.quality if args.quality is not None else beh["quality"]
    retake = args.allow_retake or beh["allow_retake"]

    print(f"Capturing with Camera {idx}...")
    
    out = capture_once(
        paths,
        camera_index=idx,
        width=w,
        height=h,
        quality=q,
        allow_retake=retake,
        logger=logger,
    )

    if out.get("success"):
        print(f"Success! Photo saved to:\n  {out['path']}")
        return 0
    else:
        print(f"Capture failed: {out.get('error')}")
        return 6


def cmd_tail_logs(paths, n=20):
    """Debug: Print the last N lines of the JSON log."""
    log_path = paths.logs_dir / "dailyselfie.jsonl"
    print(f"Reading last {n} entries from: {log_path}\n")
    
    try:
        logs = read_jsonl_tail(log_path, max_lines=n)
    except Exception as e:
        print(f"Failed to read logs: {e}")
        return 10

    if not logs:
        print("(Log file is empty or missing)")
        return 0

    for item in logs:
        # Simple pretty print
        ts = item.get("ts", "")
        level = item.get("level", "INFO")
        msg = item.get("msg", "")
        print(f"[{ts}] {level}: {msg}")
    return 0


# ---------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------
def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]

    # 1. Bootstrap: Resolve paths relative to OS (before config is loaded)
    bootstrap_paths = get_app_paths("DailySelfie", ensure=False)

    # -------------------------------------------------
    # Argument Parsing (Refined Help)
    # -------------------------------------------------
    parser = argparse.ArgumentParser(
        prog="DailySelfie",
        description="Daily Selfie - A consistent daily photo journaling tool.",
        formatter_class=argparse.RawTextHelpFormatter
    )

    # Group: Lifecycle (Install/Uninstall)
    grp_life = parser.add_argument_group("Lifecycle")
    grp_life.add_argument("--install", action="store_true", help="Run the interactive installation wizard")
    grp_life.add_argument("--uninstall", action="store_true", help="Remove the application and cleanup files")
    grp_life.add_argument("--enable-autostart", action="store_true", help="Enable launching on system login")
    grp_life.add_argument("--disable-autostart", action="store_true", help="Disable launching on system login")

    # Group: Runtime Modes
    grp_run = parser.add_argument_group("Runtime Modes")
    grp_run.add_argument("--start-up", action="store_true", help="Launch the 'Daily Prompt' popup (GUI)")
    grp_run.add_argument("--capture", action="store_true", help="Take a photo immediately (CLI / Headless mode)")
    grp_run.add_argument("--show-paths", action="store_true", help="Display all resolved file paths")
    grp_run.add_argument("--list-cameras", action="store_true", help="Scan and list available video devices")
    grp_run.add_argument("--tail-logs", type=int, nargs="?", const=20, metavar="N", help="Show last N log entries (default: 20)")

    # Group: Capture Overrides
    grp_cfg = parser.add_argument_group("Capture Overrides (for --capture)")
    grp_cfg.add_argument("--allow-retake", action="store_true", help="Overwrite existing photo for today if present")
    grp_cfg.add_argument("--camera-index", type=int, metavar="N", help="Override config camera index")
    grp_cfg.add_argument("--width", type=int, metavar="PX", help="Override target width")
    grp_cfg.add_argument("--height", type=int, metavar="PX", help="Override target height")
    grp_cfg.add_argument("--quality", type=int, metavar="1-100", help="Override JPEG quality")

    args = parser.parse_args(argv)

    # -------------------------------------------------
    # Phase 1: Installation Lifecycle
    # -------------------------------------------------
    if args.install:
        from core.installer import run_install
        req = Path("requirements.txt")
        run_install(
            bootstrap_paths.config_dir, 
            requirements_path=req if req.exists() else None
        )
        return 0

    # -------------------------------------------------
    # Phase 2: Configuration Loading
    # -------------------------------------------------
    config_path = bootstrap_paths.config_dir / "config.toml"
    
    if not config_path.exists():
        print("DailySelfie is not installed.")
        print("Run: python DailySelfie.py --install")
        return 1

    cfg = load_config(config_path)
    # Re-calculate paths based on config (e.g. custom data_dir)
    paths = apply_config_to_paths(bootstrap_paths, cfg)

    # -------------------------------------------------
    # Phase 3: Uninstallation (Requires paths loaded)
    # -------------------------------------------------
    if args.uninstall:
        from core.uninstaller import run_uninstall
        run_uninstall(paths, cfg)
        return 0

    # -------------------------------------------------
    # Phase 4: Autostart Toggles
    # -------------------------------------------------
    if args.enable_autostart:
        set_autostart(True)
        return 0

    if args.disable_autostart:
        set_autostart(False)
        return 0

    # -------------------------------------------------
    # Phase 5: Runtime Initialization
    # -------------------------------------------------
    # Ensure directories exist before running logic
    for p in (paths.config_dir, paths.data_dir, paths.logs_dir, paths.photos_root, paths.venv_dir):
        p.mkdir(parents=True, exist_ok=True)

    # Start Logging
    logger = init_logger(paths.logs_dir)

    # Init Database (SQLite)
    try:
        get_index_api(paths)
    except Exception:
        logger.exception("index_api_init_failed")
        # We continue; some features might work without DB

    # -------------------------------------------------
    # Phase 6: Command Execution
    # -------------------------------------------------
    
    
    # -------------------------------------------------
    # START UP GUI LAUNCHER 
    # -------------------------------------------------
    if args.start_up:
        print("Manager UI not implemented yet.")
        return 0

    # 2. Debug Tools
    if args.show_paths:
        return cmd_show_paths(paths) or 0

    if args.list_cameras:
        return cmd_list_cameras(logger)

    if args.tail_logs is not None:
        return cmd_tail_logs(paths, args.tail_logs)

    # 3. Capture (CLI)
    if args.capture:
        return cmd_capture(paths, cfg, logger, args)

    # No arguments provided? Default to GUI (future) or Help
    if len(argv) == 0:
        # In the future: launch main dashboard
        parser.print_help()
    else:
        parser.print_help()
        
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(130)