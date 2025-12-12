# core/capture.py
"""
High-level capture pipeline for DailySelfie.

- Reads raw frame to determine width/height
- Encodes JPEG bytes with requested quality
- Saves into storage (root/YYYY/MM/YYYY-MM-DD_HHMMSS.jpg)
- Enforces one-photo-per-day; when allow_retake=True deletes previous photo and records deletion
- Appends capture metadata to data/captures.jsonl (append-only)
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

def capture_once(app_paths, *, camera_index: int = 0, width: Optional[int] = None,
                 height: Optional[int] = None, quality: int = 90, logger=None,
                 allow_retake: bool = False) -> Dict[str, Any]:
    """
    Capture one image and save it.

    Returns a dict with keys:
      success: bool
      path: Optional[str]
      timestamp: Optional[str]
      error: Optional[str]
      id: Optional[str]   # derived from filename YYYY-MM-DD_HHMMSS
    """
    try:
        from core.camera import Camera
    except Exception as e:
        msg = f"camera dependency error: {e}"
        if logger:
            logger.error(msg)
        return {"success": False, "path": None, "timestamp": None, "error": msg, "id": None}

    try:
        from core.storage import (
            save_image_bytes,
            last_image_for_date,
            append_capture_index,
            delete_last_image_for_date,
            append_deletion_index,
        )
    except Exception as e:
        msg = f"storage dependency error: {e}"
        if logger:
            logger.error(msg)
        return {"success": False, "path": None, "timestamp": None, "error": msg, "id": None}

    ts = datetime.now(timezone.utc)

    # Check existing image for the day
    existing = last_image_for_date(Path(app_paths.photos_root), ts)
    if existing and not allow_retake:
        msg = f"photo already exists for {ts.date()}: {existing}"
        if logger:
            logger.info("capture_blocked_one_per_day", extra={"meta": {"existing": str(existing), "date": ts.date().isoformat()}})
        return {"success": False, "path": str(existing), "timestamp": ts.isoformat(), "error": msg, "id": None}

    # If retake requested and an existing image exists, delete it and append deletion index
    if existing and allow_retake:
        ok_del, err_del, deleted_path = delete_last_image_for_date(Path(app_paths.photos_root), ts)
        if ok_del:
            if logger:
                logger.info("retake_deleted_previous", extra={"meta": {"path": str(deleted_path)}})
            deletion_entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": "delete",
                "path": str(deleted_path),
                "reason": "retake",
                "id": deleted_path.stem,  # filename without extension (YYYY-MM-DD_HHMMSS)
            }
            index_file = Path(app_paths.data_dir) / "captures.jsonl"
            try:
                append_deletion_index(index_file, deletion_entry)
            except Exception:
                # ensure deletion doesn't block capture; log if available
                if logger:
                    logger.exception("append_deletion_index_failed")
        else:
            if logger:
                logger.warning("retake_delete_failed", extra={"meta": {"path": str(existing), "err": err_del}})

    # Capture raw frame and encode JPEG
    frame = None
    try:
        with Camera(index=camera_index, width=width, height=height) as cam:
            frame = cam.read_frame()  # numpy array
            # encode to JPEG
            import cv2
            ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
            if not ok:
                raise RuntimeError("JPEG encode failed")
            jpeg_bytes = buf.tobytes()
    except Exception as e:
        msg = f"capture failed: {e}"
        if logger:
            logger.exception(msg)
        return {"success": False, "path": None, "timestamp": None, "error": msg, "id": None}

    if frame is None:
        msg = "no frame captured"
        if logger:
            logger.error(msg)
        return {"success": False, "path": None, "timestamp": None, "error": msg, "id": None}

    # derive width/height (numpy shape)
    try:
        height_px, width_px = int(frame.shape[0]), int(frame.shape[1])
    except Exception:
        height_px, width_px = None, None

    # Save bytes
    try:
        res = save_image_bytes(Path(app_paths.photos_root), ts, jpeg_bytes)
        if not res.success:
            msg = f"save failed: {res.error}"
            if logger:
                logger.error(msg, extra={"meta": {"error": res.error}})
            return {"success": False, "path": None, "timestamp": ts.isoformat(), "error": msg, "id": None}

        saved_path = res.path
        # id derived from filename sans extension e.g. "2025-12-12_074512"
        id_token = saved_path.stem

        # Build index entry
        index_entry = {
            "ts": ts.isoformat(),
            "path": str(saved_path),
            "id": id_token,
            "width": width_px,
            "height": height_px,
            "resolution": f"{width_px}x{height_px}" if width_px and height_px else None,
            "mood": None,  # CLI capture has no mood; GUI may update per-uuid sidecar later
            "action": "capture",
        }

        # Append to captures index (data/captures.jsonl)
        index_file = Path(app_paths.data_dir) / "captures.jsonl"
        try:
            append_capture_index(index_file, index_entry)
        except Exception:
            if logger:
                logger.exception("append_capture_index_failed")

        # Log saved image
        if logger:
            logger.info("image_saved", extra={"meta": {"path": str(saved_path), "timestamp": ts.isoformat(), "id": id_token}})

        return {"success": True, "path": str(saved_path), "timestamp": ts.isoformat(), "error": None, "id": id_token}
    except Exception as e:
        msg = f"unexpected save error: {e}"
        if logger:
            logger.exception(msg)
        return {"success": False, "path": None, "timestamp": ts.isoformat(), "error": msg, "id": None}


# Quick CLI test when run directly
if __name__ == "__main__":
    from core.paths import get_app_paths
    from core.logging import init_logger
    p = get_app_paths("DailySelfie", ensure=True)
    logger = init_logger(p.logs_dir)
    out = capture_once(p, camera_index=0, width=640, height=480, quality=85, logger=logger, allow_retake=True)
    print(out)
