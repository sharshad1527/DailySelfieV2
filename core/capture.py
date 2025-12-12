"""
capture.py

High-level capture pipeline for DailySelfie.

This module composes camera.py, storage.py and logging utilities to perform a
single capture operation with clear outcome reporting.

Functions
---------
- capture_once(app_paths, *, camera_index=0, width=None, height=None, quality=90, logger=None)
    Capture one JPEG from the requested camera index and save it into the
    year-folder under app_paths.photos_root. Returns a dict with keys:
    {"success": bool, "path": Optional[Path], "timestamp": Optional[datetime], "error": Optional[str], "uuid": Optional[str]}

Design notes
------------
- This function does not create venvs or install dependencies; it expects camera
  and storage modules to be importable (OpenCV present for camera operations).
- It fails loudly in its return value so the caller (CLI/GUI) can present
  actionable errors.

"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any


def capture_once(app_paths, *, camera_index: int = 0, width: Optional[int] = None, height: Optional[int] = None,
                 quality: int = 90, logger=None, allow_retake: bool = False) -> Dict[str, Any]:
    """Capture one image and save it. Enforces one-photo-per-day unless allow_retake=True."""
    try:
        from core.camera import Camera  # package-qualified
    except Exception as e:
        msg = f"camera dependency error: {e}"
        if logger:
            logger.error(msg)
        return {"success": False, "path": None, "timestamp": None, "error": msg, "uuid": None}

    try:
        from core.storage import save_image_bytes, last_image_for_date
    except Exception as e:
        msg = f"storage dependency error: {e}"
        if logger:
            logger.error(msg)
        return {"success": False, "path": None, "timestamp": None, "error": msg, "uuid": None}

    ts = datetime.now(timezone.utc)

    # Single-photo-per-day check
    existing = last_image_for_date(Path(app_paths.photos_root), ts)
    if existing and not allow_retake:
        msg = f"photo already exists for {ts.date()}: {existing}"
        if logger:
            logger.info("capture_blocked_one_per_day", extra={"meta": {"existing": str(existing), "date": ts.date().isoformat()}})
        return {"success": False, "path": str(existing), "timestamp": ts.isoformat(), "error": msg, "uuid": None}

    jpeg_bytes: Optional[bytes] = None
    try:
        with Camera(index=camera_index, width=width, height=height) as cam:
            jpeg_bytes = cam.read_jpeg(quality=quality)
    except Exception as e:
        msg = f"capture failed: {e}"
        if logger:
            logger.exception(msg)
        return {"success": False, "path": None, "timestamp": None, "error": msg, "uuid": None}

    if not jpeg_bytes:
        msg = "no bytes captured"
        if logger:
            logger.error(msg)
        return {"success": False, "path": None, "timestamp": None, "error": msg, "uuid": None}

    try:
        res = save_image_bytes(Path(app_paths.photos_root), ts, jpeg_bytes)
        if not res.success:
            msg = f"save failed: {res.error}"
            if logger:
                logger.error(msg, extra={"meta": {"error": res.error}})
            return {"success": False, "path": None, "timestamp": ts.isoformat(), "error": msg, "uuid": None}
        saved_path = res.path
        uuid_token = saved_path.name.split("_")[-1].replace(".jpg", "")
        # Log the saved photo with structured metadata (so GUI can read logs)
        if logger:
            logger.info("image_saved", extra={"meta": {"path": str(saved_path), "timestamp": ts.isoformat(), "uuid": uuid_token}})
        return {"success": True, "path": str(saved_path), "timestamp": ts.isoformat(), "error": None, "uuid": uuid_token}
    except Exception as e:
        msg = f"unexpected save error: {e}"
        if logger:
            logger.exception(msg)
        return {"success": False, "path": None, "timestamp": ts.isoformat(), "error": msg, "uuid": None}


# Quick CLI test when run directly
if __name__ == "__main__":
    from paths import get_app_paths
    from logging import init_logger
    p = get_app_paths("DailySelfie", ensure=True)
    logger = init_logger(p.logs_dir)
    out = capture_once(p, camera_index=0, width=640, height=480, quality=85, logger=logger)
    print(out)
