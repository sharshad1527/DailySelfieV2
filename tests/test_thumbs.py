"""
Thumbnail cache, Qt-free surface only: bucket snapping, the 2x rule,
cache-hit/staleness keying (mtime_ns), None fallbacks, and clear_cache.
Thumbnail GENERATION itself requires a live QGuiApplication and is left to
the future GUI test suite.
"""
import os

import pytest

from core import thumbs

pytestmark = pytest.mark.core_only  # fast/offline core data-layer tests


class TestBucketFor:
    def test_snaps_up_to_smallest_sufficient_bucket(self):
        assert thumbs.bucket_for(1) == 256
        assert thumbs.bucket_for(255) == 256
        assert thumbs.bucket_for(256) == 256
        assert thumbs.bucket_for(257) == 512
        assert thumbs.bucket_for(512) == 512
        assert thumbs.bucket_for(513) == 1024
        assert thumbs.bucket_for(1024) == 1024

    def test_oversize_returns_none(self):
        assert thumbs.bucket_for(1025) is None
        assert thumbs.bucket_for(4096) is None


class TestNeedsThumbnail:
    def test_large_source_far_over_display_need(self):
        assert thumbs.needs_thumbnail(4000, 3000, 300.0, 1.0) is True

    def test_small_source_within_two_x_rule(self):
        assert thumbs.needs_thumbnail(600, 400, 300.0, 1.0) is False

    def test_exactly_two_x_is_not_needed(self):
        assert thumbs.needs_thumbnail(600, 600, 300.0, 1.0) is False

    def test_dpr_multiplies_display_need(self):
        assert thumbs.needs_thumbnail(1300, 1300, 300.0, 2.0) is True
        assert thumbs.needs_thumbnail(1200, 1200, 300.0, 2.0) is False
        assert thumbs.needs_thumbnail(1200, 1200, 300.0, 1.0) is True

    def test_degenerate_dimensions(self):
        assert thumbs.needs_thumbnail(0, 100, 50.0, 1.0) is False
        assert thumbs.needs_thumbnail(100, -1, 50.0, 1.0) is False


def _seed_cache_entry(data_dir, src_path, bucket, mtime_ns, payload=b"thumbjpg"):
    cdir = data_dir / "thumbs"
    cdir.mkdir(parents=True, exist_ok=True)
    entry = cdir / f"{src_path.stem}_{bucket}_{mtime_ns}.jpg"
    entry.write_bytes(payload)
    return entry


class TestGetThumbnailCacheHits:
    def test_missing_source_returns_none(self, tmp_path):
        assert thumbs.get_thumbnail(tmp_path / "nope.jpg", 256) is None

    def test_oversize_display_returns_none_before_any_io(self, tmp_path):
        src = tmp_path / "photo.jpg"
        src.write_bytes(b"x")
        assert thumbs.get_thumbnail(src, 2000) is None

    def test_valid_cached_entry_returned_without_generation(self, app_paths, tmp_path):
        src = tmp_path / "selfie.jpg"
        src.write_bytes(b"original")
        mtime_ns = src.stat().st_mtime_ns
        entry = _seed_cache_entry(app_paths.data_dir, src, 256, mtime_ns)

        result = thumbs.get_thumbnail(src, 256)
        assert result == entry
        assert result.read_bytes() == b"thumbjpg"

    def test_zero_byte_entry_treated_as_miss(self, app_paths, tmp_path):
        src = tmp_path / "empty-entry.jpg"
        src.write_bytes(b"original")
        mtime_ns = src.stat().st_mtime_ns
        _seed_cache_entry(app_paths.data_dir, src, 256, mtime_ns, payload=b"")

        # No live QGuiApplication in core-only runs -> miss falls through to None.
        assert thumbs.get_thumbnail(src, 256) is None

    def test_retake_mtime_change_invalidates_old_entry(self, app_paths, tmp_path):
        src = tmp_path / "retaken.jpg"
        src.write_bytes(b"v1")
        old_ns = src.stat().st_mtime_ns
        _seed_cache_entry(app_paths.data_dir, src, 256, old_ns)

        os.utime(src, ns=(old_ns + 1_000_000, old_ns + 1_000_000))

        # Old entry no longer matches the new mtime key; without a GUI app
        # generation bails out, so the stale thumb must NOT be served.
        assert thumbs.get_thumbnail(src, 256) is None


class TestClearCache:
    def test_removes_only_jpg_entries_and_counts(self, app_paths):
        cdir = app_paths.data_dir / "thumbs"
        cdir.mkdir(parents=True, exist_ok=True)
        keep = cdir / "keep.txt"
        keep.write_text("not a thumb")
        for i in range(3):
            (cdir / f"t{i}_256_1.jpg").write_bytes(b"x")

        removed = thumbs.clear_cache()
        assert removed == 3
        assert keep.exists()
        assert list(cdir.glob("*.jpg")) == []

    def test_missing_cache_dir_returns_zero(self, app_paths):
        assert not (app_paths.data_dir / "thumbs").exists()
        assert thumbs.clear_cache() == 0
