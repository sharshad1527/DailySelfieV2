# core/capture.py
from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple


# ---------------------------------------------------------
# Helper: durability flush for a freshly written file
# ---------------------------------------------------------
def _fsync_file_and_dir(path: Path) -> None:
    """Best-effort fsync of a saved file and its parent directory."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)

# ---------------------------------------------------------
# New Helper: Pre-check status
# ---------------------------------------------------------
def latest_photo_for_local_day(photos_root: Path) -> Optional[Path]:
    """
    Newest photo whose LOCAL day is today, searching the candidate UTC-date
    prefixes that can overlap today's local span. Filenames are UTC-named
    ('YYYY-MM-DD_HHMMSS.jpg'), so each hit is re-verified by converting its
    stem to a local date via timeutils — never by string-slicing raw UTC.
    """
    from core.storage import list_images_for_date
    from core.timeutils import (
        filename_stem_local_date,
        local_day_utc_prefixes,
        today_local_str,
    )

    today = today_local_str()
    latest: Optional[Path] = None
    for prefix in local_day_utc_prefixes(today):
        try:
            day = datetime.strptime(prefix, "%Y-%m-%d")
        except ValueError:
            continue
        for img in list_images_for_date(photos_root, day):
            if filename_stem_local_date(img.stem) == today:
                if latest is None or img.name > latest.name:
                    latest = img
    return latest


def check_if_already_captured(app_paths) -> Tuple[bool, Optional[Path]]:
    """
    Returns (True, path_to_image) if a photo exists for the LOCAL day today.
    Returns (False, None) if no photo exists.
    """
    try:
        existing = latest_photo_for_local_day(Path(app_paths.photos_root))
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

    Retake-safe (swap-after-save): the new file is written and recorded
    BEFORE the previous photo is removed, so a crash/failure mid-retake
    always leaves at least one valid photo for today.
    """
    ts = datetime.now(timezone.utc)
    
    # Lazy load dependencies
    try:
        from core.storage import (
            save_image_bytes, delete_path, append_capture_index
        )
        from core.metadata import write_meta
        from core.timeutils import today_local_str
    except ImportError as e:
        return {"success": False, "error": f"Import failed: {e}"}

    # 1. Check Existing (Late check, just in case) — LOCAL-day scope
    existing = latest_photo_for_local_day(Path(app_paths.photos_root))
    if existing:
        if not allow_retake:
            today_str = today_local_str()
            msg = f"Photo already exists for {today_str}"
            if logger:
                logger.info("capture_blocked", extra={"meta": {"date": today_str}})
            return {"success": False, "error": msg, "path": str(existing)}

    # 2. Save new file atomically FIRST; old photo stays untouched until this succeeds
    res = save_image_bytes(Path(app_paths.photos_root), ts, jpeg_bytes)
    if not res.success:
        return {"success": False, "error": f"Save failed: {res.error}"}

    saved_path = res.path
    id_token = saved_path.stem

    # Durability: flush the new JPEG before any destructive step
    try:
        _fsync_file_and_dir(saved_path)
    except OSError as e:
        if logger:
            logger.warning(
                "fsync_failed",
                extra={"meta": {"path": str(saved_path), "error": str(e)}},
            )

    # 3. Record Index (new row first; old photo retired only afterwards)
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

    api = None
    try:
        from core.index_api import get_api
        api = get_api(app_paths)
        api.record_capture(index_entry)
    except Exception as e:
        # Fallback
        if logger:
            logger.warning(f"Database record failed, falling back to JSONL: {e}")
        try:
            append_capture_index(Path(app_paths.data_dir) / "captures.jsonl", index_entry)
            write_meta(Path(app_paths.data_dir), id_token, {"id": id_token, "mood": mood, "notes": notes})
        except Exception:
            pass 

    if logger:
        logger.info("image_saved", extra={"meta": {"path": str(saved_path)}})

    # 4. Swap complete: only now retire the previous photo for today
    if existing:
        try:
            old_path = Path(existing)
            if old_path.exists() and old_path.resolve() != saved_path.resolve():
                ok, err = delete_path(old_path)
                if ok:
                    if logger:
                        logger.info("retake_deletion", extra={"meta": {"path": str(old_path)}})
                    if api is not None:
                        try:
                            api.record_deletion(old_path.stem, reason="retake")
                        except Exception as e:
                            if logger:
                                logger.warning(
                                    f"Deletion audit failed for {old_path.stem}: {e}"
                                )
                else:
                    if logger:
                        logger.warning(
                            "retake_delete_failed",
                            extra={"meta": {"path": str(old_path), "error": err}},
                        )
        except Exception as e:
            # Never fail the commit because cleanup of the superseded file failed;
            # both files remain valid photos for today.
            if logger:
                logger.warning(
                    "retake_delete_failed",
                    extra={"meta": {"path": str(existing), "error": str(e)}},
                )

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