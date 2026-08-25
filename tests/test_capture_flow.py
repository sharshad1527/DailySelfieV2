"""
Capture flow without camera: already-captured detection across the local-day
midnight boundary (UTC-named files), retake swap semantics, block when
allow_retake=False, old-photo preservation when deletion fails, and quality
metric persistence into the DB + JSONL audit.
"""
import json
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core import storage
from core.capture import check_if_already_captured, commit_capture_from_bytes
from core.timeutils import filename_stem_local_date, today_local_str

pytestmark = pytest.mark.core_only  # fast/offline core data-layer tests

FAKE_JPEG = b"\xff\xd8fake-jpeg-bytes"


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
