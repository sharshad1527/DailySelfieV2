"""
SQLite indexer: record/query roundtrip, JSONL migration gate (skips when the
DB is already stamped and non-empty), corrupt-DB quarantine/recovery, and the
v1 -> v2 quality-metrics schema migration.
"""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from core.index_api import IndexAPI
from core.indexer import SCHEMA_VERSION, Indexer

pytestmark = pytest.mark.core_only  # fast/offline core data-layer tests


def _entry(eid="2026-08-24_063000", ts="2026-08-24T06:30:00+00:00"):
    return {
        "id": eid,
        "ts": ts,
        "path": f"/photos/2026/08/{eid}.jpg",
        "width": 1280,
        "height": 720,
        "resolution": "1280x720",
        "mood": None,
        "notes": None,
        "action": "capture",
    }


class TestIndexerRoundtrip:
    def test_record_and_query_roundtrip(self, tmp_path):
        idx = Indexer(tmp_path / "data" / "index.db")
        idx.init_db()
        try:
            idx.add_capture(_entry())
            row = idx.get_capture_by_id("2026-08-24_063000")
            assert row is not None
            assert row["ts"] == "2026-08-24T06:30:00+00:00"
            assert row["width"] == 1280 and row["height"] == 720
            assert row["action"] == "capture"
            month_rows = idx.get_captures_by_month(2026, 8)
            assert [r["id"] for r in month_rows] == ["2026-08-24_063000"]
        finally:
            idx.close()

    def test_update_meta_persists(self, tmp_path):
        idx = Indexer(tmp_path / "index.db")
        idx.init_db()
        try:
            idx.add_capture(_entry())
            idx.update_meta("2026-08-24_063000", {"mood": "Great", "notes": "felt good"})
            row = idx.get_capture_by_id("2026-08-24_063000")
            assert row["mood"] == "Great"
            assert row["notes"] == "felt good"
        finally:
            idx.close()

    def test_user_version_stamped(self, tmp_path):
        idx = Indexer(tmp_path / "index.db")
        idx.init_db()
        try:
            assert idx.get_user_version() >= 1
        finally:
            idx.close()


class TestMigrationGate:
    def test_migration_runs_once_then_gate_skips(self, tmp_path, monkeypatch):
        api = IndexAPI(SimpleNamespace(data_dir=tmp_path / "data"))
        audit = api.audit_path
        audit.parent.mkdir(parents=True, exist_ok=True)

        lines = [_entry("id-a"), _entry("id-b")]
        audit.write_text("\n".join(json.dumps(e) for e in lines) + "\n", encoding="utf-8")

        calls = {"n": 0}
        original = Indexer.migrate_from_jsonl

        def counting(self, jsonl_path, report_every=1000):
            calls["n"] += 1
            return original(self, jsonl_path, report_every)

        monkeypatch.setattr(Indexer, "migrate_from_jsonl", counting)

        api.init()
        try:
            imported_first = api.migrate_if_needed()
            assert imported_first == 2
            assert calls["n"] == 1
            idx = api._ensure_indexer()
            assert idx.get_user_version() >= 1 and idx.count_rows() > 0

            imported_second = api.migrate_if_needed()
            assert imported_second == 0
            assert calls["n"] == 1
        finally:
            api.close()


class TestCorruptionQuarantine:
    def test_garbage_db_is_quarantined_and_rebuilt_from_audit(self, tmp_path):
        api1 = IndexAPI(SimpleNamespace(data_dir=tmp_path / "data"))
        api1.init()
        entry = _entry("2026-01-02_080000", "2026-01-02T08:00:00+00:00")
        api1.record_capture(entry)
        api1.close()

        db_path = api1.index_db_path
        db_path.write_bytes(b"this is definitely not a sqlite database" * 64)

        api2 = IndexAPI(SimpleNamespace(data_dir=tmp_path / "data"))
        api2.init()
        try:
            quarantined = list(api2.data_dir.glob("index.db.corrupt-*"))
            assert quarantined, "corrupt db was not renamed aside"

            idx = api2._ensure_indexer()
            assert isinstance(idx._conn, sqlite3.Connection)
            assert idx.count_rows() == 1
            recovered = idx.get_capture_by_id("2026-01-02_080000")
            assert recovered is not None
            assert recovered["ts"] == entry["ts"]
            assert recovered["path"] == entry["path"]
        finally:
            api2.close()


def _build_v1_db(db_path):
    """Hand-craft a schema-v1 index.db (pre quality columns), stamped v1."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE captures (
            id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            path TEXT NOT NULL,
            width INTEGER,
            height INTEGER,
            resolution TEXT,
            mood TEXT,
            notes TEXT,
            action TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX idx_ts ON captures(ts);
        """
    )
    conn.execute(
        "INSERT INTO captures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("2025-06-15_071200", "2025-06-15T07:12:00+00:00", "/p/old.jpg",
         800, 600, "800x600", "Good", "legacy row", "capture", 1000.0),
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


class TestSchemaMigrationV2:
    def test_v1_db_migrates_to_v2_with_data_intact(self, tmp_path):
        db = tmp_path / "index.db"
        _build_v1_db(db)

        idx = Indexer(db)
        idx.init_db()
        try:
            assert idx.get_user_version() == SCHEMA_VERSION == 2
            cols = idx._table_columns()
            assert "blur_score" in cols and "brightness" in cols
            row = idx.get_capture_by_id("2025-06-15_071200")
            assert row is not None
            assert row["ts"] == "2025-06-15T07:12:00+00:00"
            assert row["mood"] == "Good"
            assert row["blur_score"] is None and row["brightness"] is None

            # New columns are usable post-migration
            idx.update_quality("2025-06-15_071200", 123.4, 88.8)
            assert idx.get_capture_by_id("2025-06-15_071200")["blur_score"] == 123.4
        finally:
            idx.close()

    def test_migration_is_idempotent_across_reopens(self, tmp_path):
        db = tmp_path / "index.db"
        _build_v1_db(db)
        for _ in range(2):
            idx = Indexer(db)
            idx.init_db()
            try:
                assert idx.get_user_version() == 2
                assert idx.count_rows() == 1
            finally:
                idx.close()

    def test_fresh_db_gets_extended_schema_and_v2_stamp(self, tmp_path):
        idx = Indexer(tmp_path / "fresh" / "index.db")
        idx.init_db()
        try:
            assert idx.get_user_version() == 2
            cols = idx._table_columns()
            assert {"blur_score", "brightness"} <= cols
            idx.add_capture(_entry())
            row = idx.get_capture_by_id("2026-08-24_063000")
            assert row["blur_score"] is None and row["brightness"] is None
        finally:
            idx.close()

    def test_add_capture_roundtrips_quality_metrics(self, tmp_path):
        idx = Indexer(tmp_path / "index.db")
        idx.init_db()
        try:
            entry = _entry()
            entry["blur_score"] = 45.75
            entry["brightness"] = 128.25
            idx.add_capture(entry)
            row = idx.get_capture_by_id("2026-08-24_063000")
            assert isinstance(row["blur_score"], float)
            assert row["blur_score"] == pytest.approx(45.75)
            assert row["brightness"] == pytest.approx(128.25)

            # Junk values coerce to NULL rather than raising
            bad = _entry("id-bad")
            bad["blur_score"] = "very-sharp"
            bad["brightness"] = True
            idx.add_capture(bad)
            row_bad = idx.get_capture_by_id("id-bad")
            assert row_bad["blur_score"] is None
            assert row_bad["brightness"] is None
        finally:
            idx.close()

    def test_migrate_from_jsonl_copies_quality_and_nulls_old_lines(self, tmp_path):
        api = IndexAPI(SimpleNamespace(data_dir=tmp_path / "data"))
        audit = api.audit_path
        audit.parent.mkdir(parents=True, exist_ok=True)
        new_line = dict(_entry("with-q"), blur_score=310.5, brightness=110.0)
        old_line = _entry("no-q", ts="2025-02-02T10:00:00+00:00")
        audit.write_text(
            json.dumps(old_line) + "\n" + json.dumps(new_line) + "\n",
            encoding="utf-8",
        )

        api.init()
        try:
            imported = api.migrate_if_needed()
            assert imported == 2
            idx = api._ensure_indexer()
            assert idx.get_user_version() == 2
            row_new = idx.get_capture_by_id("with-q")
            assert row_new["blur_score"] == pytest.approx(310.5)
            assert row_new["brightness"] == pytest.approx(110.0)
            row_old = idx.get_capture_by_id("no-q")
            assert row_old["blur_score"] is None
            assert row_old["brightness"] is None
        finally:
            api.close()

    def test_rows_missing_quality_and_update_quality_plumbing(self, tmp_path):
        idx = Indexer(tmp_path / "index.db")
        idx.init_db()
        try:
            e1, e2 = _entry(), _entry("b", ts="2026-08-20T06:30:00+00:00")
            e2["blur_score"], e2["brightness"] = 900.0, 130.0
            idx.add_capture(e1)
            idx.add_capture(e2)

            missing = idx.get_rows_missing_quality(limit=10)
            assert [r["id"] for r in missing] == ["2026-08-24_063000"]

            idx.update_quality(e1["id"], 42.0, 100.0)
            assert idx.get_rows_missing_quality(limit=10) == []
            row = idx.get_capture_by_id(e1["id"])
            assert row["blur_score"] == pytest.approx(42.0)
        finally:
            idx.close()

    def test_api_rows_with_quality_period_filters(self, tmp_path):
        api = IndexAPI(SimpleNamespace(data_dir=tmp_path / "data"))
        api.init()
        try:
            in_month = _entry()
            in_month["blur_score"], in_month["brightness"] = 10.0, 50.0
            other_month = _entry("2026-07-04_090000", "2026-07-04T09:00:00+00:00")
            other_year = _entry("2025-08-09_090000", "2025-08-09T09:00:00+00:00")
            deleted = _entry("del-1", ts="2026-08-11T09:00:00+00:00")
            deleted["action"] = "delete"
            for e in (in_month, other_month, other_year, deleted):
                api.record_capture(e)

            month_rows = api.get_rows_with_quality(2026, 8)
            assert [r["id"] for r in month_rows] == ["2026-08-24_063000"]

            year_rows = api.get_rows_with_quality(2026)
            assert [r["id"] for r in year_rows] == ["2026-07-04_090000", "2026-08-24_063000"]

            all_rows = api.get_rows_with_quality(None)
            assert len(all_rows) == 3  # delete rows never included
        finally:
            api.close()
