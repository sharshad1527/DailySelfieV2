# core/capture.py
"""
High-level capture pipeline for DailySelfie.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

# ---------------------------------------------------------
# Shared Logic: Commit Bytes -> Disk/DB
# ---------------------------------------------------------
def commit_capture_from_bytes(
    app_paths,
    jpeg_bytes: bytes,
    width: int,
    height: int,
    # [NEW] Added optional metadata arguments
    mood: Optional[str] = None,
    notes: Optional[str] = None,
    allow_retake: bool = False,
    logger=None
) -> Dict[str, Any]:
    """
    Saves provided JPEG bytes to disk and records the entry.
    Handles 'allow_retake' logic (deleting previous photo) automatically.
    """
    ts = datetime.now(timezone.utc)
    
    # 1. Lazy load dependencies
    try:
        from core.storage import (
            save_image_bytes,
            last_image_for_date,
            delete_last_image_for_date,
            append_capture_index,
        )
        from core.metadata import write_meta
    except ImportError as e:
        return {"success": False, "error": f"Import failed: {e}"}

    # 2. Check/Handle Existing (Retake Logic)
    existing = last_image_for_date(Path(app_paths.photos_root), ts)
    
    if existing:
        if not allow_retake:
            msg = f"Photo already exists for {ts.date()}"
            if logger:
                logger.info("capture_blocked", extra={"meta": {"date": str(ts.date())}})
            return {"success": False, "error": msg, "path": str(existing)}
        
        # If retake allowed, delete previous
        ok_del, err_del, deleted_path = delete_last_image_for_date(Path(app_paths.photos_root), ts)
        if ok_del and logger:
            logger.info("retake_deletion", extra={"meta": {"path": str(deleted_path)}})
            try:
                from core.index_api import get_api
                api = get_api(app_paths)
                api.record_deletion(deleted_path.stem, reason="retake")
            except Exception:
                pass 

    # 3. Save New Image
    res = save_image_bytes(Path(app_paths.photos_root), ts, jpeg_bytes)
    if not res.success:
        return {"success": False, "error": f"Save failed: {res.error}"}

    saved_path = res.path
    id_token = saved_path.stem

    # 4. Record to Index (DB/JSONL)
    index_entry = {
        "id": id_token,
        "ts": ts.isoformat(),
        "path": str(saved_path),
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}",
        "mood": mood,   # [MODIFIED] Now saving actual mood
        "notes": notes, # [MODIFIED] Now saving actual notes
        "action": "capture",
    }

    # Try using robust IndexAPI first
    try:
        from core.index_api import get_api
        api = get_api(app_paths)
        api.record_capture(index_entry)
    except Exception as e:
        if logger: logger.warning(f"IndexAPI failed ({e}), falling back to direct JSONL append.")
        try:
            # Fallback 1: Append JSONL
            index_file = Path(app_paths.data_dir) / "captures.jsonl"
            append_capture_index(index_file, index_entry)
            
            # Fallback 2: Write Sidecar (Explicitly writing metadata here)
            sidecar_data = {"id": id_token, "mood": mood, "notes": notes}
            write_meta(Path(app_paths.data_dir), id_token, sidecar_data)
        except Exception:
            pass 

    if logger:
        logger.info("image_saved", extra={"meta": {"path": str(saved_path), "id": id_token}})

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
    """
    Capture one image immediately (CLI Mode).
    CLI mode currently sends None for mood/notes.
    """
    # 1. Open Camera & Snap
    try:
        from core.camera import Camera
        import cv2
        
        with Camera(index=camera_index, width=width, height=height) as cam:
            frame = cam.read_frame()
            
            # Encode to JPEG
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
            if not ok:
                return {"success": False, "error": "JPEG encoding failed"}
            
            jpeg_bytes = buf.tobytes()
            h, w = frame.shape[:2]

    except Exception as e:
        if logger: logger.exception("camera_error")
        return {"success": False, "error": str(e)}

    # 2. Commit
    return commit_capture_from_bytes(
        app_paths, 
        jpeg_bytes, 
        w, h, 
        allow_retake=allow_retake, 
        logger=logger
    )