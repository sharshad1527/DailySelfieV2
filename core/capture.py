# core/capture.py
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# ---------------------------------------------------------
# New Helper: Pre-check status
# ---------------------------------------------------------
def check_if_already_captured(app_paths) -> Tuple[bool, Optional[Path]]:
    """
    Returns (True, path_to_image) if a photo exists for today.
    Returns (False, None) if no photo exists.
    """
    ts = datetime.now(timezone.utc)
    try:
        from core.storage import last_image_for_date
        existing = last_image_for_date(Path(app_paths.photos_root), ts)
        if existing:
            return True, existing
    except ImportError:
        pass
    return False, None

# ---------------------------------------------------------
# Shared Logic: Commit Bytes -> Disk/DB
# ---------------------------------------------------------
def commit_capture_from_bytes(
    app_paths,
    jpeg_bytes: bytes,
    width: int,
    height: int,
    mood: Optional[str] = None,
    notes: Optional[str] = None,
    allow_retake: bool = False,
    logger=None
) -> Dict[str, Any]:
    """
    Saves provided JPEG bytes to disk and records the entry.
    """
    ts = datetime.now(timezone.utc)
    
    # Lazy load dependencies
    try:
        from core.storage import (
            save_image_bytes, last_image_for_date, delete_last_image_for_date, append_capture_index
        )
        from core.metadata import write_meta
    except ImportError as e:
        return {"success": False, "error": f"Import failed: {e}"}

    # 1. Check Existing (Late check, just in case)
    existing = last_image_for_date(Path(app_paths.photos_root), ts)
    if existing:
        if not allow_retake:
            msg = f"Photo already exists for {ts.date()}"
            if logger:
                logger.info("capture_blocked", extra={"meta": {"date": str(ts.date())}})
            return {"success": False, "error": msg, "path": str(existing)}
        
        # Delete previous if retaking
        delete_last_image_for_date(Path(app_paths.photos_root), ts)
        if logger:
             logger.info("retake_deletion", extra={"meta": {"path": str(existing)}})

    # 2. Save File
    res = save_image_bytes(Path(app_paths.photos_root), ts, jpeg_bytes)
    if not res.success:
        return {"success": False, "error": f"Save failed: {res.error}"}

    saved_path = res.path
    id_token = saved_path.stem

    # 3. Record Index
    index_entry = {
        "id": id_token,
        "ts": ts.isoformat(),
        "path": str(saved_path),
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}",
        "mood": mood,
        "notes": notes,
        "action": "capture",
    }

    try:
        from core.index_api import get_api
        api = get_api(app_paths)
        api.record_capture(index_entry)
    except Exception:
        # Fallback
        try:
            append_capture_index(Path(app_paths.data_dir) / "captures.jsonl", index_entry)
            write_meta(Path(app_paths.data_dir), id_token, {"id": id_token, "mood": mood, "notes": notes})
        except Exception:
            pass 

    if logger:
        logger.info("image_saved", extra={"meta": {"path": str(saved_path)}})

    return {"success": True, "path": str(saved_path), "id": id_token, "timestamp": ts.isoformat()}


# ---------------------------------------------------------
# CLI / One-Shot Capture
# ---------------------------------------------------------
def capture_once(
    app_paths,
    *,
    camera_index: int = 0,
    width: Optional[int] = None,
    height: Optional[int] = None,
    quality: int = 90,
    logger=None,
    allow_retake: bool = False,
) -> Dict[str, Any]:
    """Capture one image immediately (CLI Mode)."""
    
    # [NEW] Check BEFORE opening camera (Fail Fast)
    has_photo, existing_path = check_if_already_captured(app_paths)
    if has_photo and not allow_retake:
        msg = f"Capture blocked: Photo already exists at {existing_path}"
        if logger:
            logger.info("capture_blocked", extra={"meta": {"path": str(existing_path)}})
        return {"success": False, "error": msg}

    # If we get here, either no photo exists OR retake is allowed
    try:
        from core.camera import Camera
        import cv2
        
        with Camera(index=camera_index, width=width, height=height) as cam:
            frame = cam.read_frame()
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
            if not ok: return {"success": False, "error": "Encoding failed"}
            
            jpeg_bytes = buf.tobytes()
            h, w = frame.shape[:2]

    except Exception as e:
        if logger: logger.exception("camera_error")
        return {"success": False, "error": str(e)}

    return commit_capture_from_bytes(
        app_paths, jpeg_bytes, w, h, 
        allow_retake=allow_retake, logger=logger
    )