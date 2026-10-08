# core/capture.py
from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, NamedTuple, Tuple


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
# Helper: behavior-flag resolution (config.toml driven)
# ---------------------------------------------------------
# Keys resolved by the capture paths, with their DEFAULT_CONFIG fallbacks.
# Every one of these used to be either hardcoded or ignored by the capture
# paths; keeping the table here means the GUI popup, the dashboard page and
# the CLI can never drift on defaults again.
_BEHAVIOR_FLAG_DEFAULTS: Dict[str, bool] = {
    # Capture rules: refuse a second photo for the same local day.
    "one_photo_per_day": True,
    # Advisory quality gate (core/quality.py): show the Retake/Save-Anyway
    # dialog for blurry/dark/bright frames.
    "quality_gate_enabled": True,
}

_TRUTHY_STRINGS = ("1", "true", "on", "yes")


def _coerce_bool(value: Any, default: bool) -> bool:
    """
    Coerce a config value to bool. TOML emits native bools, but hand-edited
    config.toml files routinely carry "true"/"false"/"off" style strings.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _TRUTHY_STRINGS:
            return True
        if v in ("0", "false", "off", "no", ""):
            return False
        return default
    if value is None:
        return default
    return bool(value)


def _read_behavior_config(app_paths) -> Dict[str, Any]:
    """
    Read [behavior] out of the user's config.toml, or {} when no usable
    config path exists. Never raises: a missing/unreadable config must not
    break a capture, and the callers fall back to the DEFAULT_CONFIG values.
    """
    try:
        config_dir = getattr(app_paths, "config_dir", None)
        if config_dir is None:
            return {}
        from core.config import load_config
        cfg = load_config(Path(config_dir) / "config.toml")
        behavior = cfg.get("behavior")
        return dict(behavior) if isinstance(behavior, dict) else {}
    except Exception:
        return {}


def resolve_behavior_flags(app_paths, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, bool]:
    """
    Resolve the capture-relevant behavior booleans: explicit override wins,
    then config.toml, then the DEFAULT_CONFIG fallback.

    Pure apart from reading config.toml (which lives beside the app paths),
    so it is testable without Qt or a camera.
    """
    overrides = overrides or {}
    # Skip the config read entirely when every flag was passed explicitly.
    if all(overrides.get(k) is not None for k in _BEHAVIOR_FLAG_DEFAULTS):
        behavior: Dict[str, Any] = {}
    else:
        behavior = _read_behavior_config(app_paths)
    flags: Dict[str, bool] = {}
    for key, default in _BEHAVIOR_FLAG_DEFAULTS.items():
        if overrides.get(key) is not None:
            flags[key] = _coerce_bool(overrides[key], default)
        else:
            flags[key] = _coerce_bool(behavior.get(key), default)
    return flags


# ---------------------------------------------------------
# Helper: advisory quality decision (shared by every capture path)
# ---------------------------------------------------------
class QualityDecision(NamedTuple):
    """
    Result of scoring one captured frame exactly once.

    should_warn     True only when the advisory gate is enabled AND the frame
                    produced warnings. Callers with a dialog offer
                    Retake / Save Anyway; the CLI just logs it.
    metrics         {"blur_score": float, "brightness": float} whenever the
                    frame could be scored, else None. Reported independently
                    of the gate flag: the gate controls the *dialog*, never
                    the recorded data. Recording metrics even when the gate is
                    off is what keeps recap's best_shot_ranking() and
                    backfill_quality() fed.
    warnings        raw warning keys ("blurry"/"dark"/"bright") for the
                    advisory dialog's message body; empty when unassessable.
    """

    should_warn: bool
    metrics: Optional[Dict[str, float]]
    warnings: Tuple[str, ...]


def evaluate_capture_quality(
    image_bytes: bytes,
    *,
    gate_enabled: bool = True,
    logger=None,
) -> QualityDecision:
    """
    Score a captured frame and decide whether the user should be warned.

    Callers pass raw encoded frame bytes (JPEG or anything cv2 can decode) and
    get back everything they need: whether to show the advisory dialog and the
    metrics to persist. Callers that use the metrics must pass them to
    commit_capture_from_bytes(quality_metrics=...) — the frame is scored once,
    never twice.

    Never raises: a frame that cannot be assessed yields
    QualityDecision(False, None, ()) so a save is never blocked by analysis
    failure. Stays Qt-free so headless callers can reuse it.
    """
    try:
        from core.quality import assess_image_quality
        assessment = assess_image_quality(bytes(image_bytes or b""))
    except Exception as e:
        if logger:
            logger.info("quality_gate_skipped", extra={"meta": {"error": str(e)}})
        return QualityDecision(False, None, ())

    metrics: Optional[Dict[str, float]] = None
    blur = assessment.get("blur_score")
    brightness = assessment.get("brightness")
    if (
        isinstance(blur, (int, float))
        and not isinstance(blur, bool)
        and isinstance(brightness, (int, float))
        and not isinstance(brightness, bool)
    ):
        metrics = {"blur_score": float(blur), "brightness": float(brightness)}

    warnings = tuple(assessment.get("warnings") or ())
    should_warn = bool(gate_enabled and metrics and warnings)
    return QualityDecision(should_warn, metrics, warnings)


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
    logger=None,
    quality_metrics: Optional[Dict[str, Any]] = None,
    one_photo_per_day: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Saves provided JPEG bytes to disk and records the entry.

    Retake-safe (swap-after-save): the new file is written and recorded
    BEFORE the previous photo is removed, so a crash/failure mid-retake
    always leaves at least one valid photo for today.

    quality_metrics: optional {"blur_score": float, "brightness": float}
    from core.quality.assess_image_quality; floats are persisted into the
    DB row and the JSONL audit line when present.

    one_photo_per_day: override for the behavior.one_photo_per_day config
    flag (None = read config.toml, falling back to DEFAULT_CONFIG's True).
    When the flag is False, a second capture for the same local day is
    allowed and supersedes the earlier one, using the same swap-after-save
    retake semantics as allow_retake=True.
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

    # 1. Check Existing (Late check, just in case) — LOCAL-day scope.
    #    behavior.one_photo_per_day=False lifts the same-day block entirely,
    #    so a second capture replaces the first via the retake swap below.
    existing = latest_photo_for_local_day(Path(app_paths.photos_root))
    if one_photo_per_day is None:
        one_photo_per_day = resolve_behavior_flags(app_paths)["one_photo_per_day"]
    if existing:
        if not allow_retake and one_photo_per_day:
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
    if quality_metrics:
        for key in ("blur_score", "brightness"):
            val = quality_metrics.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                index_entry[key] = float(val)

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
    quality_gate_enabled: Optional[bool] = None,
    one_photo_per_day: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Capture one image immediately (CLI Mode).

    quality: JPEG encode quality. Defaults to 90, matching
    DEFAULT_CONFIG["behavior"]["quality"].

    quality_gate_enabled: override for behavior.quality_gate_enabled. There is
    no dialog on this headless path, so the flag only decides whether a poor
    frame is logged as a warning; the metrics are recorded either way.

    one_photo_per_day: override for behavior.one_photo_per_day (None = read
    config.toml, falling back to DEFAULT_CONFIG's True).
    """
    flags = resolve_behavior_flags(
        app_paths,
        overrides={
            "quality_gate_enabled": quality_gate_enabled,
            "one_photo_per_day": one_photo_per_day,
        },
    )
    one_per_day = flags["one_photo_per_day"]

    # [NEW] Check BEFORE opening camera (Fail Fast)
    has_photo, existing_path = check_if_already_captured(app_paths)
    if has_photo and not allow_retake and one_per_day:
        msg = f"Capture blocked: Photo already exists at {existing_path}"
        if logger:
            logger.info("capture_blocked", extra={"meta": {"path": str(existing_path)}})
        return {"success": False, "error": msg}

    # If we get here, either no photo exists OR retake is allowed
    quality_metrics: Optional[Dict[str, float]] = None
    try:
        from core.camera import Camera
        import cv2
        
        with Camera(index=camera_index, width=width, height=height) as cam:
            frame = cam.read_frame()
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
            if not ok: return {"success": False, "error": "Encoding failed"}
            
            jpeg_bytes = buf.tobytes()
            h, w = frame.shape[:2]

            # Advisory quality gate. Same pure helper the GUI paths use; here
            # there is no dialog to show, so a poor frame is only logged. The
            # metrics are persisted regardless so the CLI's photos carry
            # blur_score/brightness just like the GUI ones.
            decision = evaluate_capture_quality(
                jpeg_bytes,
                gate_enabled=flags["quality_gate_enabled"],
                logger=logger,
            )
            quality_metrics = decision.metrics
            if decision.should_warn and logger:
                logger.warning(
                    "quality_gate_warning",
                    extra={"meta": {
                        "warnings": list(decision.warnings),
                        **dict(decision.metrics or {}),
                    }},
                )

    except Exception as e:
        if logger: logger.exception("camera_error")
        return {"success": False, "error": str(e)}

    return commit_capture_from_bytes(
        app_paths, jpeg_bytes, w, h,
        allow_retake=allow_retake, logger=logger,
        quality_metrics=quality_metrics,
        one_photo_per_day=one_per_day,
    )