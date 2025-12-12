#!/usr/bin/env python3
"""
DailySelfie.py

Top-level CLI that wires together core modules:
- paths.get_app_paths
- logging.init_logger / get_logger
- venv_helper.ensure_venv
- camera.list_cameras
- capture.capture_once
- storage helpers for delete/list

Commands:
- --show-paths
- --create-venv
- --list-cameras
- --capture
- --delete-last
- --tail-logs (show last N JSONL entries)

This file intentionally keeps behavior explicit and fails loudly so you can
fix real problems quickly.
"""
from __future__ import annotations
import argparse
import sys
from datetime import datetime

from core.paths import get_app_paths
from core.logging import init_logger, read_jsonl_tail, get_logger
from core.venv_helper import ensure_venv, venv_python

# Index API for DB wiring
from core.index_api import get_api as get_index_api


# Local imports for optional capabilities (delayed to runtime where reasonable)


def cmd_show_paths(paths):
    print("Resolved paths:")
    print(f"os:       {paths.os_name}")
    print(f"home:     {paths.home}")
    print(f"config:   {paths.config_dir}")
    print(f"data:     {paths.data_dir}")
    print(f"logs:     {paths.logs_dir}")
    print(f"photos:   {paths.photos_root}")
    print(f"venv:     {paths.venv_dir}")


def cmd_create_venv(paths, logger, requirements_path=None):
    ok, msg, py = ensure_venv(paths.venv_dir, requirements=requirements_path)
    if ok:
        logger.info("venv_ready", extra={"meta": {"path": str(paths.venv_dir)}})
        print("venv ready:", py)
        return 0
    else:
        logger.error("venv_failed", extra={"meta": {"msg": msg}})
        print("venv failed:", msg)
        return 2


def cmd_list_cameras(logger, max_test=8):
    try:
        from core.camera import list_cameras
    except Exception as e:
        logger.error("camera_list_failed", extra={"meta": {"error": str(e)}})
        print("Camera listing unavailable — install OpenCV or create venv first.")
        return 3
    cams = list_cameras(max_test=max_test, only_available=True)
    if not cams:
        print("No usable cameras detected.")
        return 4
    for i, res in cams.items():
        print(f"{i}: available={res.available} read_ok={res.read_ok} msg={res.message}")
    return 0



def cmd_capture(paths, logger, camera_index=0, width=None, height=None, quality=90, allow_retake=False):
    try:
        from core.capture import capture_once
    except Exception as e:
        logger.error("capture_module_missing", extra={"meta": {"error": str(e)}})
        print("Capture module unavailable — ensure core modules are on PYTHONPATH and OpenCV is installed.")
        return 5

    out = capture_once(paths, camera_index=camera_index, width=width, height=height, quality=quality, logger=logger, allow_retake=allow_retake)
    if out.get("success"):
        print("Captured:", out.get("path"))
        # If index recording returned an error message, show it too (non-fatal)
        if out.get("error"):
            print("Note:", out.get("error"))
        return 0
    else:
        print("Capture failed:", out.get("error"))
        return 6


def cmd_delete_last(paths, logger, for_date: datetime | None = None):
    # lazy import
    try:
        from core.storage import last_image_for_date
    except Exception as e:
        logger.error("storage_missing", extra={"meta": {"error": str(e)}})
        print("Storage module missing")
        return 7
    d = for_date or datetime.now()
    last = last_image_for_date(paths.photos_root, d)
    if not last:
        print("No image found for date", d.strftime("%Y-%m-%d"))
        return 8
    try:
        last.unlink()
        logger.info("deleted_last", extra={"meta": {"path": str(last)}})
        print("Deleted:", last)
        return 0
    except Exception as e:
        logger.exception("delete_failed")
        print("Delete failed:", e)
        return 9


def cmd_tail_logs(paths, n=20):
    try:
        logs = read_jsonl_tail(paths.logs_dir / "dailyselfie.jsonl", max_lines=n)
    except Exception as e:
        print("Failed to read logs:", e)
        return 10
    for item in logs:
        print(item)
    return 0


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    paths = get_app_paths("DailySelfie", ensure=True)
    logger = init_logger(paths.logs_dir)

    # Initialize Index API (DB) early, but tolerate failures.
    index_api = None
    try:
        index_api = get_index_api(paths)
    except Exception as e:
        # Non-fatal: log and continue. capture will fallback to JSONL-only behavior if needed.
        try:
            logger.exception("index_api_init_failed")
        except Exception:
            print("index_api_init_failed:", e)
        index_api = None

    parser = argparse.ArgumentParser(prog="DailySelfie")
    parser.add_argument("--show-paths", action="store_true", help="shows the path where files are stored")
    parser.add_argument("--create-venv", action="store_true", help="allows to create venv, install packages. and setup folders")
    parser.add_argument("--list-cameras", action="store_true", help="lists available cameras")
    parser.add_argument("--capture", action="store_true", help="captures image")
    parser.add_argument("--allow-retake", action="store_true", help="Allow retaking a photo even if one exists for today")
    parser.add_argument("--delete-last", action="store_true", help="deletes last taken image")
    parser.add_argument("--tail-logs", type=int, nargs="?", const=20, help="shows log")
    parser.add_argument("--camera-index", type=int, default=0,help="can be used with --capture")
    parser.add_argument("--width", type=int, help="can be used with --capture")
    parser.add_argument("--height", type=int, help="can be used with --capture")
    parser.add_argument("--quality", type=int, default=90, help="can be used with --capture")
    # index CLI helpers
    parser.add_argument("--migrate-index", action="store_true", help="Migrate existing captures.jsonl into SQLite index.db (one-time)")
    parser.add_argument("--index-info", action="store_true", help="Print index DB info and exit")
    args = parser.parse_args(argv)

    # Handle index CLI operations early
    if getattr(args, "index_info", False):
        try:
            if index_api is None:
                index_api = get_index_api(paths)
            idx = index_api._ensure_indexer()
            print("DB path:", idx.db_path)
            print("Total rows:", idx.count_rows())
        except Exception as e:
            print("Failed to open index DB:", e)
        return 0

    if getattr(args, "migrate_index", False):
        try:
            if index_api is None:
                index_api = get_index_api(paths)
            imported = index_api.migrate_if_needed()
            print(f"Imported {imported} rows into index DB")
        except Exception as e:
            print("Migration failed:", e)
        return 0

    if args.show_paths:
        return cmd_show_paths(paths) or 0
    if args.create_venv:
        # try to find requirements.txt in the current working directory
        import pathlib
        req = pathlib.Path("requirements.txt")
        if not req.exists():
            req = None
        return cmd_create_venv(paths, logger, requirements_path=req)
    if args.list_cameras:
        return cmd_list_cameras(logger)
    if args.capture:
        return cmd_capture(paths, logger, camera_index=args.camera_index, width=args.width, height=args.height, quality=args.quality, allow_retake=args.allow_retake)
    if args.delete_last:
        return cmd_delete_last(paths, logger)
    if args.tail_logs is not None:
        return cmd_tail_logs(paths, n=args.tail_logs)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
