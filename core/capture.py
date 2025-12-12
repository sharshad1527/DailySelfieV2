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


def capture_once(app_paths, *, camera_index: int = 0, width: Optional[int] = None, height: Optional[int] = None, quality: int = 90, logger=None) -> Dict[str, Any]:
    """Capture one image and save it.

    Parameters
    ----------
    app_paths: object
        Object with attribute `photos_root` (Path). Typically AppPaths from paths.py.
    camera_index: int
        Camera index to use
    width, height: Optional[int]
        Requested camera frame dimensions
    quality: int
        JPEG quality 1-100
    logger: logging.Logger
        Optional logger; if provided used for structured logs

    Returns
    -------
    dict
        keys: success, path, timestamp, error, uuid
    """
    # Local imports to avoid hard import-time dependency on OpenCV in callers
    try:
        from camera import Camera
    except Exception as e:
        msg = f"camera dependency error: {e}"
        if logger:
            logger.error(msg)
        return {"success": False, "path": None, "timestamp": None, "error": msg, "uuid": None}

    try:
        from storage import save_image_bytes
    except Exception as e:
        msg = f"storage dependency error: {e}"
        if logger:
            logger.error(msg)
        return {"success": False, "path": None, "timestamp": None, "error": msg, "uuid": None}

    ts = datetime.now(timezone.utc)
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

    # Save
    try:
        res = save_image_bytes(Path(app_paths.photos_root), ts, jpeg_bytes)
        if not res.success:
            msg = f"save failed: {res.error}"
            if logger:
                logger.error(msg, extra={"meta": {"error": res.error}})
            return {"success": False, "path": None, "timestamp": ts.isoformat(), "error": msg, "uuid": None}
        saved_path = res.path
        # derive uuid from filename
        uuid_token = saved_path.name.split("_")[-1].replace('.jpg', '')
        meta = {"success": True, "path": saved_path, "timestamp": ts.isoformat(), "error": None, "uuid": uuid_token}
        if logger:
            logger.info("capture_saved", extra={"meta": {"path": str(saved_path), "timestamp": ts.isoformat(), "uuid": uuid_token}})
        return meta
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
