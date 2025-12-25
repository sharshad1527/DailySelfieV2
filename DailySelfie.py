#!/usr/bin/env python3
"""
DailySelfie.py

The central entry point for the Daily Selfie application.
Handles CLI arguments, installation lifecycle, and launching the GUI.
"""
from __future__ import annotations
import os
os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.qpa.*=false"
import argparse
import sys
from pathlib import Path
import traceback

# Core utilities (fast imports)
from core.paths import get_app_paths
from core.config import load_config, apply_config_to_paths
from core.logging import init_logger, read_jsonl_tail, get_logger
from core.index_api import get_api as get_index_api
from core.autostart_manager import set_autostart
# Import the checker
from core.capture import check_if_already_captured
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
    logger = get_logger("cmd_list_cameras")
    """Debug: List available cameras using OpenCV."""
    logger.info("Scanning for cameras...", extra={"meta": {"max_test": max_test}})
    try:
        from core.camera import list_cameras
    except Exception as e:
        logger.error("camera_list_failed", extra={"meta": {"error": str(e)}})
        # print(f"Error loading camera module: {e}")
        return 3

    cams = list_cameras(max_test=max_test, only_available=True)
    if not cams:
        logger.warning("No usable cameras detected.")
        return 4

    logger.info(f"Found {len(cams)} usable camera(s):")
    for i, res in cams.items():
        logger.info(f"[Index {i}] Available: {res.available}, Read OK: {res.read_ok}\n")
    
    return 0


def cmd_capture(paths, cfg, logger, args):
    logger = get_logger("cmd_capture")

    """Action: Take a single photo immediately (Headless Mode)."""
    from core.capture import capture_once

    beh = cfg["behavior"]

    # Prefer CLI args, fall back to config
    idx = args.camera_index if args.camera_index is not None else beh["camera_index"]
    w = args.width if args.width is not None else beh["width"]
    h = args.height if args.height is not None else beh["height"]
    q = args.quality if args.quality is not None else beh["quality"]
    retake = args.allow_retake or beh["allow_retake"]

    logger.info(f"Capturing with Camera {idx}...")
    
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
        logger.info(f"Success! Photo saved to:\n  {out['path']}")
        return 0
    else:
        # logger.error("Capture failed:",extra={"meta": {out.get('error')}})
        logger.error("Capture failed", extra={"meta": {"error": out.get('error')}})
        return 6


def cmd_tail_logs(paths, n=20):
    """Debug: Print the last N lines of the JSON log."""
    logger = get_logger("cmd_tail_logs")

    log_path = paths.logs_dir / "dailyselfie.jsonl"
    logger.info(f"Reading last {n} entries from: {log_path}\n")
    
    try:
        logs = read_jsonl_tail(log_path, max_lines=n)
    except Exception as e:
        logger.critical(f"Failed to read logs: {e}", exc_info=True)
        return 10

    if not logs:
        logger.info("(Log file is empty or missing)")
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
    # REGISTER THE HOOK IMMEDIATELY
    from core.logging import global_exception_hook
    sys.excepthook = global_exception_hook

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
    grp_run.add_argument("--allow-retake", action="store_true", help="Overwrite existing photo for today if present")
    
    grp_run.add_argument("--show-paths", action="store_true", help="Display all resolved file paths")
    grp_run.add_argument("--list-cameras", action="store_true", help="Scan and list available video devices")
    grp_run.add_argument("--tail-logs", type=int, nargs="?", const=20, metavar="N", help="Show last N log entries (default: 20)")

    # Group: Theme
    grp_theme = parser.add_argument_group("Theme Options")
    grp_theme.add_argument("--show-themes", action="store_true", help="List available themes")
    grp_theme.add_argument("--theme", help="Set active theme by name")
    grp_theme.add_argument("--theme-mode", choices=["dark", "light"], help="Set theme mode")
    grp_theme.add_argument(
        "--theme-contrast",
        choices=["standard", "medium", "high"],
        help="Set theme contrast level",
    )

    # Group: Capture Overrides
    grp_cfg = parser.add_argument_group("Hardware Overrides")
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
        req = Path(__file__).parent / "requirements.txt"
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
    
    cfg = load_config(config_path)
    paths = apply_config_to_paths(bootstrap_paths, cfg)

    from gui.theme.theme_controller import ThemeController
    from gui.theme.theme_loader import list_theme_files

    theme_dir = Path(__file__).parent / "gui/theme/themes"

    # 1. Show Themes (Exit Early)
    if args.show_themes:
        print("Available Themes:")
        for p in list_theme_files(theme_dir):
            print(f"  - {p.stem}")
        return 0

    # 2. Validate Theme Input (Crash Prevention)
    if args.theme:
        available = [p.stem for p in list_theme_files(theme_dir)]
        if args.theme not in available:
            print(f"Error: Theme '{args.theme}' not found. Available themes: {available}")
            return 1

    # 3. Initialize Controller
    theme_controller = ThemeController(cfg, theme_dir)
    theme_controller.initialize()

    # 4. Apply CLI Theme Overrides
    theme_action = False

    if args.theme:
        theme_controller.set_theme(args.theme)
        theme_action = True

    if args.theme_mode:
        theme_controller.set_mode(args.theme_mode)
        theme_action = True

    if args.theme_contrast:
        theme_controller.set_contrast(args.theme_contrast)
        theme_action = True

    if theme_action:
        theme_controller.save(config_path)
        print("✔ Theme updated")
        print(f"  Theme     : {theme_controller.theme_name}")
        print(f"  Mode      : {theme_controller.mode}")
        print(f"  Contrast  : {theme_controller.contrast}")
        # If the user ONLY updated the theme and didn't ask to startup, we exit here?
        # The original logic exited if theme_action was True.
        # But wait, what if they do --theme foo --start-up?
        # The user wants "Theme CLI Overrides logic *before* the if args.start_up: block."
        # If we change theme, we should probably continue if start-up is requested.
        # But the original code had `return 0` inside `if theme_action:`.
        # I will preserve the original behavior of exiting if it's just a config change,
        # UNLESS start-up is also requested.
        if not args.start_up:
             return 0

    
    # -------------------------------------------------
    # START UP GUI LAUNCHER 
    # -------------------------------------------------
    if args.start_up:
        logger = get_logger("startup")

        beh = cfg.get("behavior", {})
        config_allow = beh.get("allow_retake", False)
        final_allow_retake = args.allow_retake or config_allow

        has_photo, existing_path = check_if_already_captured(paths)
        if has_photo and not final_allow_retake:
            logger.warning(
                "Photo already captured for today. Use --allow-retake to overwrite.",
                extra={"meta": {"existing_path": str(existing_path)}}
            )
            return 0

        # ---- THEME INIT MUST COME FIRST ----
        from gui.theme.theme_vars import init_theme_vars
        init_theme_vars(theme_controller)

        # ---- THEN GUI IMPORTS ----
        from PySide6.QtWidgets import QApplication
        from gui.startup.startup_window import StartupWindow

        app = QApplication(sys.argv)
        win = StartupWindow(allow_retake=final_allow_retake)
        win.show()
        return app.exec()


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