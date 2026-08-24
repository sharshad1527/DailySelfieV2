"""
SQLite indexer: record/query roundtrip, JSONL migration gate (skips when the
DB is already stamped and non-empty), and corrupt-DB quarantine/recovery.
"""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from core.index_api import IndexAPI
from core.indexer import Indexer

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
