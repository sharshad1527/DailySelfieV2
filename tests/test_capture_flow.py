"""
Capture flow without camera: already-captured detection across the local-day
midnight boundary (UTC-named files), retake swap semantics, block when
allow_retake=False, old-photo preservation when deletion fails, quality
metric persistence into the DB + JSONL audit, the pure quality-decision
helper shared by every capture path, and the behavior.one_photo_per_day flag.
"""
import copy
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core import storage
from core.capture import (
    _coerce_bool,
    capture_once,
    check_if_already_captured,
    commit_capture_from_bytes,
    evaluate_capture_quality,
    resolve_behavior_flags,
)
from core.config import DEFAULT_CONFIG, write_config
from core.timeutils import filename_stem_local_date, today_local_str

pytestmark = pytest.mark.core_only  # fast/offline core data-layer tests

FAKE_JPEG = b"\xff\xd8fake-jpeg-bytes"


def _flat_jpeg(value=20, size=64):
    """A perfectly uniform JPEG: no detail (blurry) and dark/bright by value."""
    import cv2
    import numpy as np

    frame = np.full((size, size, 3), value, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", frame)
    assert ok
    return buf.tobytes()


def _detailed_jpeg(size=128):
    """A high-contrast checkerboard JPEG: sharp and mid-bright, no warnings."""
    import cv2
    import numpy as np

    frame = np.indices((size, size)).sum(axis=0) % 2 * 255
    frame = np.repeat(frame[:, :, None], 3, axis=2).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    assert ok
    return buf.tobytes()


def _local_noon_utc(day_str: str) -> datetime:
    naive_noon = datetime.strptime(day_str, "%Y-%m-%d").replace(hour=12, minute=0, second=0)
    return naive_noon.astimezone().astimezone(timezone.utc)


def _utc_dt(date_str: str, hhmmss: str) -> datetime:
    return datetime.strptime(
        f"{date_str}T{hhmmss}", "%Y-%m-%dT%H:%M:%S"
    ).replace(tzinfo=timezone.utc)


def _seed_photo(photos_root, ts_utc: datetime, payload=FAKE_JPEG):
    res = storage.save_image_bytes(photos_root, ts_utc, payload)
    assert res.success, res.error
    return res.path


def _jpg_count(root):
    return len(list(root.rglob("*.jpg")))


def test_empty_photos_root_reports_not_captured(tmp_path):
    app_paths = types.SimpleNamespace(photos_root=tmp_path / "photos")
    has, path = check_if_already_captured(app_paths)
    assert has is False
    assert path is None


def test_today_files_detected_across_midnight_boundary(tmp_path, set_tz):
    set_tz("Asia/Kolkata")
    photos_root = tmp_path / "photos"
    today = today_local_str()
    prev_utc_date = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    path_a = _seed_photo(photos_root, _utc_dt(today, "01:00:00"))
    path_b = _seed_photo(photos_root, _utc_dt(prev_utc_date, "19:00:00"))

    assert filename_stem_local_date(path_a.stem) == today
    assert filename_stem_local_date(path_b.stem) == today

    app_paths = types.SimpleNamespace(photos_root=photos_root)
    has, latest = check_if_already_captured(app_paths)
    assert has is True
    assert latest.name == path_a.name


def test_yesterday_only_file_is_not_today(tmp_path, set_tz):
    set_tz("Asia/Kolkata")
    photos_root = tmp_path / "photos"
    today = datetime.strptime(today_local_str(), "%Y-%m-%d")
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    _seed_photo(photos_root, _utc_dt(yesterday, "10:00:00"))

    app_paths = types.SimpleNamespace(photos_root=photos_root)
    has, path = check_if_already_captured(app_paths)
    assert has is False
    assert path is None


def test_retake_swap_leaves_exactly_one_file(app_paths, set_tz):
    set_tz("Asia/Kolkata")
    photos_root = app_paths.photos_root
    _seed_photo(photos_root, _local_noon_utc(today_local_str()))

    result = commit_capture_from_bytes(app_paths, b"retake-bytes", 64, 64, allow_retake=True)

    assert result["success"] is True
    jpgs = list(photos_root.rglob("*.jpg"))
    assert len(jpgs) == 1
    assert jpgs[0].read_bytes() == b"retake-bytes"


def test_allow_retake_false_blocks_commit(app_paths, set_tz):
    set_tz("Asia/Kolkata")
    photos_root = app_paths.photos_root
    before = _seed_photo(photos_root, _local_noon_utc(today_local_str()))

    result = commit_capture_from_bytes(app_paths, b"blocked-bytes", 32, 32, allow_retake=False)

    assert result["success"] is False
    assert "already exists" in result["error"]
    assert _jpg_count(photos_root) == 1
    assert before.read_bytes() == FAKE_JPEG


def test_delete_failure_keeps_old_file_and_still_succeeds(app_paths, set_tz, monkeypatch):
    set_tz("Asia/Kolkata")
    photos_root = app_paths.photos_root
    old_path = _seed_photo(photos_root, _local_noon_utc(today_local_str()))

    def boom(path):
        raise RuntimeError("injected delete failure")

    monkeypatch.setattr(storage, "delete_path", boom)

    result = commit_capture_from_bytes(app_paths, b"new-bytes", 48, 48, allow_retake=True)

    assert result["success"] is True
    assert old_path.exists()
    assert old_path.read_bytes() == FAKE_JPEG
    assert _jpg_count(photos_root) == 2


def test_quality_metrics_persist_to_db_and_jsonl_audit(app_paths):
    result = commit_capture_from_bytes(
        app_paths, b"quality-bytes", 64, 64,
        quality_metrics={"blur_score": 812.5, "brightness": 142.0},
    )

    assert result["success"] is True
    from core.index_api import get_api
    api = get_api(app_paths)
    row = api.get_item(result["id"])
    assert row["blur_score"] == pytest.approx(812.5)
    assert row["brightness"] == pytest.approx(142.0)

    lines = [json.loads(l) for l in
             (Path(app_paths.data_dir) / "captures.jsonl").read_text(encoding="utf-8").splitlines()]
    audit_line = next(l for l in lines if l.get("id") == result["id"])
    assert audit_line["blur_score"] == pytest.approx(812.5)
    assert audit_line["brightness"] == pytest.approx(142.0)


def test_commit_without_metrics_leaves_quality_null_and_absent_in_jsonl(app_paths):
    result = commit_capture_from_bytes(app_paths, b"plain-bytes", 32, 32)

    assert result["success"] is True
    from core.index_api import get_api
    api = get_api(app_paths)
    row = api.get_item(result["id"])
    assert row["blur_score"] is None and row["brightness"] is None

    lines = [json.loads(l) for l in
             (Path(app_paths.data_dir) / "captures.jsonl").read_text(encoding="utf-8").splitlines()]
    audit_line = next(l for l in lines if l.get("id") == result["id"])
    assert "blur_score" not in audit_line
    assert "brightness" not in audit_line


# ---------------------------------------------------------------
# behavior.one_photo_per_day
# ---------------------------------------------------------------
def _write_behavior_config(app_paths, **behavior):
    """Write a full config.toml (DEFAULT_CONFIG + overrides) into the sandbox."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["behavior"].update(behavior)
    write_config(Path(app_paths.config_dir) / "config.toml", cfg)


def test_one_photo_per_day_default_true_blocks_second_capture(app_paths, set_tz):
    set_tz("Asia/Kolkata")
    photos_root = app_paths.photos_root
    before = _seed_photo(photos_root, _local_noon_utc(today_local_str()))

    result = commit_capture_from_bytes(
        app_paths, b"second-bytes", 32, 32, allow_retake=False
    )

    assert result["success"] is False
    assert "already exists" in result["error"]
    assert before.read_bytes() == FAKE_JPEG
    assert _jpg_count(photos_root) == 1


def test_one_photo_per_day_false_allows_second_capture_and_replaces(app_paths, set_tz):
    set_tz("Asia/Kolkata")
    photos_root = app_paths.photos_root
    before = _seed_photo(photos_root, _local_noon_utc(today_local_str()))

    result = commit_capture_from_bytes(
        app_paths, b"second-bytes", 32, 32,
        allow_retake=False, one_photo_per_day=False,
    )

    assert result["success"] is True
    jpgs = list(photos_root.rglob("*.jpg"))
    assert len(jpgs) == 1, "the superseded photo must be retired, not duplicated"
    assert jpgs[0].read_bytes() == b"second-bytes"
    assert not before.exists()


def test_one_photo_per_day_false_read_from_config_file(app_paths, set_tz):
    """No explicit override: commit must read behavior.one_photo_per_day itself."""
    set_tz("Asia/Kolkata")
    photos_root = app_paths.photos_root
    _seed_photo(photos_root, _local_noon_utc(today_local_str()))
    _write_behavior_config(app_paths, one_photo_per_day=False)

    result = commit_capture_from_bytes(app_paths, b"cfg-bytes", 32, 32, allow_retake=False)

    assert result["success"] is True
    assert _jpg_count(photos_root) == 1


def test_one_photo_per_day_true_in_config_still_blocks(app_paths, set_tz):
    set_tz("Asia/Kolkata")
    photos_root = app_paths.photos_root
    _seed_photo(photos_root, _local_noon_utc(today_local_str()))
    _write_behavior_config(app_paths, one_photo_per_day=True)

    result = commit_capture_from_bytes(app_paths, b"cfg-bytes", 32, 32, allow_retake=False)

    assert result["success"] is False
    assert _jpg_count(photos_root) == 1


def test_explicit_override_beats_config_file(app_paths, set_tz):
    set_tz("Asia/Kolkata")
    photos_root = app_paths.photos_root
    _seed_photo(photos_root, _local_noon_utc(today_local_str()))
    _write_behavior_config(app_paths, one_photo_per_day=False)

    result = commit_capture_from_bytes(
        app_paths, b"override-bytes", 32, 32, one_photo_per_day=True
    )

    assert result["success"] is False
    assert "already exists" in result["error"]


def test_resolve_behavior_flags_precedence(app_paths):
    _write_behavior_config(
        app_paths, one_photo_per_day=False, quality_gate_enabled=False
    )

    # config.toml is the source when no override is passed
    assert resolve_behavior_flags(app_paths) == {
        "one_photo_per_day": False,
        "quality_gate_enabled": False,
    }
    # explicit overrides win
    assert resolve_behavior_flags(
        app_paths,
        overrides={"one_photo_per_day": True, "quality_gate_enabled": None},
    ) == {"one_photo_per_day": True, "quality_gate_enabled": False}


def test_resolve_behavior_flags_defaults_without_config(app_paths):
    """No config.toml on disk -> DEFAULT_CONFIG values (True for both flags)."""
    assert resolve_behavior_flags(app_paths) == {
        "one_photo_per_day": True,
        "quality_gate_enabled": True,
    }


def test_resolve_behavior_flags_survives_broken_config(app_paths):
    Path(app_paths.config_dir).mkdir(parents=True, exist_ok=True)
    (Path(app_paths.config_dir) / "config.toml").write_text("this is not toml {{{")

    assert resolve_behavior_flags(app_paths) == {
        "one_photo_per_day": True,
        "quality_gate_enabled": True,
    }


def test_resolve_behavior_flags_skips_config_read_when_all_overridden(app_paths, monkeypatch):
    """Callers that pass both flags must not pay for a config.toml read."""
    _write_behavior_config(app_paths, one_photo_per_day=False, quality_gate_enabled=False)

    import core.capture as capture_module

    def boom(_app_paths):
        raise AssertionError("config.toml must not be read when every flag is overridden")

    monkeypatch.setattr(capture_module, "_read_behavior_config", boom)

    flags = resolve_behavior_flags(
        app_paths, overrides={"one_photo_per_day": False, "quality_gate_enabled": True}
    )
    assert flags == {"one_photo_per_day": False, "quality_gate_enabled": True}


@pytest.mark.parametrize(
    "raw,expected",
    [
        (True, True), (False, False),
        ("true", True), ("True", True), ("on", True), ("1", True), ("yes", True),
        ("false", False), ("off", False), ("0", False), ("no", False), ("", False),
        ("nonsense", True), (None, True), (1, True), (0, False),
    ],
)
def test_coerce_bool_accepts_hand_edited_strings(raw, expected):
    assert _coerce_bool(raw, True) is expected


# ---------------------------------------------------------------
# evaluate_capture_quality (the pure quality-decision helper)
# ---------------------------------------------------------------
def test_evaluate_flags_blurry_dark_frame():
    decision = evaluate_capture_quality(_flat_jpeg(value=20))

    assert decision.should_warn is True
    assert set(decision.warnings) == {"blurry", "dark"}
    assert decision.metrics is not None
    assert decision.metrics["blur_score"] < 100.0
    assert decision.metrics["brightness"] < 40.0


def test_evaluate_flags_blown_out_frame():
    decision = evaluate_capture_quality(_flat_jpeg(value=250))

    assert decision.should_warn is True
    assert "bright" in decision.warnings


def test_evaluate_good_frame_has_no_warnings_but_still_reports_metrics():
    decision = evaluate_capture_quality(_detailed_jpeg())

    assert decision.should_warn is False
    assert decision.warnings == ()
    assert decision.metrics is not None
    assert decision.metrics["blur_score"] >= 100.0
    assert 40.0 <= decision.metrics["brightness"] <= 215.0


def test_evaluate_gate_disabled_suppresses_warning_but_keeps_metrics():
    """The gate controls the dialog only — metrics are still recorded."""
    decision = evaluate_capture_quality(_flat_jpeg(value=20), gate_enabled=False)

    assert decision.should_warn is False
    assert decision.warnings, "raw warnings are still reported for callers"
    assert decision.metrics is not None
    assert decision.metrics["blur_score"] < 100.0


def test_evaluate_undecodable_bytes_is_inert():
    decision = evaluate_capture_quality(b"\xff\xd8not-a-real-jpeg")

    assert decision.should_warn is False
    assert decision.metrics is None
    assert decision.warnings == ()


def test_evaluate_empty_bytes_is_inert():
    decision = evaluate_capture_quality(b"")

    assert decision == (False, None, ())


def test_evaluate_never_raises_when_cv2_missing(monkeypatch):
    """cv2 is a venv-only dependency; assessment must degrade, not explode."""
    import builtins

    jpeg = _flat_jpeg(value=20)  # encode first, while cv2 is still importable

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "cv2":
            raise ImportError("cv2 unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)

    decision = evaluate_capture_quality(jpeg)

    assert decision.should_warn is False
    assert decision.metrics is None
    assert decision.warnings == ()


def test_evaluate_logs_skip_when_assessment_raises(monkeypatch):
    import core.quality as quality_module

    def boom(_bytes):
        raise RuntimeError("injected analysis failure")

    monkeypatch.setattr(quality_module, "assess_image_quality", boom)
    seen = []
    logger = types.SimpleNamespace(info=lambda *a, **k: seen.append((a, k)))

    decision = evaluate_capture_quality(_flat_jpeg(), logger=logger)

    assert decision.metrics is None
    assert seen and seen[0][0][0] == "quality_gate_skipped"


# ---------------------------------------------------------------
# End-to-end: helper output -> commit -> persisted metrics
# ---------------------------------------------------------------
def test_evaluate_then_commit_persists_real_metrics(app_paths):
    decision = evaluate_capture_quality(_flat_jpeg(value=20))

    result = commit_capture_from_bytes(
        app_paths, b"popup-bytes", 64, 64, quality_metrics=decision.metrics
    )

    assert result["success"] is True
    from core.index_api import get_api
    row = get_api(app_paths).get_item(result["id"])
    assert row["blur_score"] == pytest.approx(decision.metrics["blur_score"])
    assert row["brightness"] == pytest.approx(decision.metrics["brightness"])


def test_assessed_metrics_land_in_index_for_a_real_jpeg(app_paths):
    """The popup save sequence end to end: real JPEG -> assess -> commit -> row."""
    import cv2

    jpeg = _flat_jpeg(value=20, size=96)
    decision = evaluate_capture_quality(jpeg)

    result = commit_capture_from_bytes(
        app_paths, jpeg, 96, 96, quality_metrics=decision.metrics
    )

    assert result["success"] is True
    from core.index_api import get_api
    row = get_api(app_paths).get_item(result["id"])
    assert row["blur_score"] is not None
    assert row["brightness"] is not None
    assert row["blur_score"] < 100.0

    audit = [json.loads(l) for l in
             (Path(app_paths.data_dir) / "captures.jsonl").read_text(encoding="utf-8").splitlines()]
    line = next(l for l in audit if l.get("id") == result["id"])
    assert line["blur_score"] == pytest.approx(decision.metrics["blur_score"])
    assert line["brightness"] == pytest.approx(decision.metrics["brightness"])
    assert cv2 is not None


# ---------------------------------------------------------------
# CLI path: capture_once persists metrics + honours the flags
# ---------------------------------------------------------------
def _install_fake_camera(monkeypatch, frame_value=20, size=96):
    """Stub core.camera.Camera with a context manager yielding one flat frame."""
    import numpy as np

    frame = np.full((size, size, 3), frame_value, dtype=np.uint8)

    class FakeCamera:
        def __init__(self, index=0, width=None, height=None):
            self.index = index

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read_frame(self):
            return frame

    monkeypatch.setitem(sys.modules, "core.camera", types.SimpleNamespace(Camera=FakeCamera))


def test_capture_once_persists_quality_metrics(app_paths, monkeypatch):
    _install_fake_camera(monkeypatch)

    result = capture_once(app_paths)

    assert result["success"] is True
    from core.index_api import get_api
    row = get_api(app_paths).get_item(result["id"])
    assert row["blur_score"] is not None
    assert row["blur_score"] < 100.0
    assert row["brightness"] is not None


def test_capture_once_second_shot_blocked_by_default_one_photo_per_day(
    app_paths, monkeypatch, set_tz
):
    set_tz("Asia/Kolkata")
    _install_fake_camera(monkeypatch)
    assert capture_once(app_paths)["success"] is True

    blocked = capture_once(app_paths)

    assert blocked["success"] is False
    assert "already exists" in blocked["error"]
    assert _jpg_count(app_paths.photos_root) == 1


def test_capture_once_second_shot_allowed_when_one_photo_per_day_false(
    app_paths, monkeypatch, set_tz
):
    set_tz("Asia/Kolkata")
    _install_fake_camera(monkeypatch, frame_value=120)
    assert capture_once(app_paths)["success"] is True

    result = capture_once(app_paths, one_photo_per_day=False)

    assert result["success"] is True
    assert _jpg_count(app_paths.photos_root) == 1, "the old photo is replaced"


def test_capture_once_reads_one_photo_per_day_from_config(app_paths, monkeypatch, set_tz):
    set_tz("Asia/Kolkata")
    _install_fake_camera(monkeypatch, frame_value=120)
    _write_behavior_config(app_paths, one_photo_per_day=False)
    assert capture_once(app_paths)["success"] is True

    result = capture_once(app_paths)

    assert result["success"] is True
    assert _jpg_count(app_paths.photos_root) == 1


def test_capture_once_allow_retake_still_overrides_one_photo_per_day(
    app_paths, monkeypatch, set_tz
):
    set_tz("Asia/Kolkata")
    _install_fake_camera(monkeypatch, frame_value=120)
    _write_behavior_config(app_paths, one_photo_per_day=True)
    assert capture_once(app_paths)["success"] is True

    result = capture_once(app_paths, allow_retake=True)

    assert result["success"] is True
    assert _jpg_count(app_paths.photos_root) == 1


def test_capture_once_persists_metrics_when_gate_disabled(app_paths, monkeypatch):
    """Gate off must not mean metrics off — the CLI never shows a dialog."""
    _install_fake_camera(monkeypatch)
    _write_behavior_config(app_paths, quality_gate_enabled=False)

    result = capture_once(app_paths)

    assert result["success"] is True
    from core.index_api import get_api
    row = get_api(app_paths).get_item(result["id"])
    assert row["blur_score"] is not None
    assert row["brightness"] is not None


def test_capture_once_fails_before_opening_camera_when_blocked(app_paths, monkeypatch, set_tz):
    """The fail-fast pre-check must still run before the camera is touched."""
    set_tz("Asia/Kolkata")
    _seed_photo(app_paths.photos_root, _local_noon_utc(today_local_str()))

    def explode(*a, **k):
        raise AssertionError("camera must not be opened when the capture is blocked")

    monkeypatch.setitem(sys.modules, "core.camera", types.SimpleNamespace(Camera=explode))

    result = capture_once(app_paths)

    assert result["success"] is False
    assert "already exists" in result["error"]


def test_capture_once_survives_camera_failure(app_paths, monkeypatch):
    class BoomCamera:
        def __init__(self, **kw):
            raise RuntimeError("no camera")

    monkeypatch.setitem(sys.modules, "core.camera", types.SimpleNamespace(Camera=BoomCamera))

    result = capture_once(app_paths)

    assert result["success"] is False
    assert "no camera" in result["error"]
    assert not (Path(app_paths.photos_root).exists()
                and _jpg_count(app_paths.photos_root))
