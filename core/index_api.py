# core/index_api.py
"""
Application-level façade for index operations.

Responsibilities:
- Provide simple, safe functions GUI/CLI can call to:
    - record_capture(index_entry)
    - record_deletion(id, reason)
    - list_month(year, month) -> merged DB + sidecar dicts
    - get_item(id) -> merged dict
    - update_meta(id, meta_dict) -> writes sidecar + DB
    - migrate_if_needed(jsonl_path) -> run one-shot migration

Behavior:
- Writes to the append-only audit (captures.jsonl) and to the SQLite index are
  performed under a file lock to preserve ordering and avoid races.
- Sidecar metadata is created/updated atomically (temp -> rename).
- This module purposely does not generate thumbnails; thumbnailing should be
  performed outside the lock asynchronously.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List, Optional
import json
import time
from datetime import datetime, timezone

from core.indexer import Indexer
from core.metadata import read_meta, write_meta, delete_meta, merge_db_and_meta
from core.locks import file_lock, lock_path_for
from core.paths import get_app_paths
from core.storage import append_capture_index, append_deletion_index

# Default DB filename relative to data_dir
DB_FILENAME = "index.db"
AUDIT_FILENAME = "captures.jsonl"


class IndexAPI:
    """
    High-level index API.

    Usage:
        api = IndexAPI(app_paths)
        api.init()  # sets up db
        api.record_capture(index_entry)
        rows = api.list_month(2025, 12)
        api.update_meta("2025-12-12_074512", {"mood": "ok", "notes": "..."})
    """

    def __init__(self, app_paths):
        self.app_paths = app_paths
        self.data_dir: Path = Path(app_paths.data_dir)
        # data_dir already includes /data from config (e.g., ~/.local/share/DailySelfie/data)
        # Store DB and audit files directly in data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.index_db_path: Path = self.data_dir / DB_FILENAME
        self.audit_path: Path = self.data_dir / AUDIT_FILENAME
        self._indexer: Optional[Indexer] = None
        self._change_listeners: List[callable] = []

    def add_index_listener(self, callback) -> None:
        """Register a zero-arg callback fired after successful record_capture /
        record_deletion / update_meta operations."""
        if callback not in self._change_listeners:
            self._change_listeners.append(callback)

    def _notify_changed(self) -> None:
        for cb in list(self._change_listeners):
            try:
                cb()
            except Exception:
                pass

    def init(self) -> None:
        """Initialize the SQLite indexer (create DB if missing)."""
        if self._indexer is None:
            self._indexer = Indexer(self.index_db_path)
            self._indexer.init_db()

    def close(self) -> None:
        """Close DB connection if open."""
        if self._indexer:
            try:
                self._indexer.close()
            except Exception:
                pass
            self._indexer = None

    # ---------------------
    # Low-level helpers
    # ---------------------
    def _ensure_indexer(self) -> Indexer:
        if self._indexer is None:
            self.init()
        assert self._indexer is not None
        return self._indexer

    def _lock_for_audit(self):
        """Return a lock path to use when touching both audit and DB."""
        return lock_path_for(self.index_db_path)

    # ---------------------
    # Public operations
    # ---------------------
    def record_capture(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """
        Record a capture event.

        Steps (under lock):
          1) append entry to captures.jsonl (audit)
          2) add/replace row in SQLite captures table
          3) ensure sidecar metadata exists (writes mood=None if absent)

        Returns the final merged record (DB row merged with sidecar).
        Raises exceptions for serious failures.
        """
        if "id" not in entry:
            raise ValueError("entry must contain 'id'")

        lockpath = self._lock_for_audit()
        idx = self._ensure_indexer()

        with file_lock(lockpath, timeout=10.0):
            # 1: append audit (write the JSONL line)
            try:
                append_capture_index(self.audit_path, entry)
            except Exception as e:
                # Still attempt DB write, but surface the audit failure
                raise RuntimeError(f"Failed to append audit line: {e}")

            # 2: add to DB
            try:
                idx.add_capture(entry)
            except Exception as e:
                raise RuntimeError(f"Failed to write index DB: {e}")

            # 3: ensure sidecar exists (with empty editable fields) if not present
            eid = entry["id"]
            existing_meta = read_meta(self.data_dir, eid)
            if not existing_meta:
                # create stub sidecar with mood=None and empty notes
                try:
                    write_meta(self.data_dir, eid, {"id": eid, "mood": None, "notes": None, "edited_at": datetime.now(timezone.utc).isoformat()})
                except Exception:
                    # non-fatal: continue
                    pass

        # Return final merged record
        db_row = idx.get_capture_by_id(entry["id"])
        merged = merge_db_and_meta(db_row, read_meta(self.data_dir, entry["id"]))
        self._notify_changed()
        return merged

    def record_deletion(self, eid: str, reason: str = "delete") -> Dict[str, Any]:
        """
        Record a deletion event for `eid`.

        Steps (under lock):
          1) append a deletion JSONL line with action='delete'
          2) insert a deletion row in DB (action='delete')
          3) delete sidecar and optionally thumbnail (thumbnail removal left to caller)

        Returns dict representing the deletion row.
        """
        if not eid:
            raise ValueError("eid required")
        ts = datetime.now(timezone.utc).isoformat()
        entry = {
            "id": eid,
            "ts": ts,
            "path": "",  # path optional for delete; DB can accept empty
            "action": "delete",
            "reason": reason,
        }

        lockpath = self._lock_for_audit()
        idx = self._ensure_indexer()
        with file_lock(lockpath, timeout=8.0):
            try:
                append_deletion_index(self.audit_path, entry)
            except Exception as e:
                raise RuntimeError(f"Failed to append deletion audit: {e}")

            try:
                idx.add_capture(entry)
            except Exception as e:
                raise RuntimeError(f"Failed to write deletion to DB: {e}")

            # remove sidecar if present
            try:
                delete_meta(self.data_dir, eid)
            except Exception:
                # non-fatal
                pass

        self._notify_changed()
        return {"id": eid, "ts": ts, "action": "delete", "reason": reason}

    def list_month(self, year: int, month: int) -> List[Dict[str, Any]]:
        """
        Return list of captures for the month, merged with sidecar metadata.
        """
        idx = self._ensure_indexer()
        rows = idx.get_captures_by_month(year, month)
        merged = []
        for r in rows:
            eid = r.get("id")
            meta = read_meta(self.data_dir, eid)
            merged.append(merge_db_and_meta(r, meta))
        return merged

    def get_item(self, eid: str) -> Optional[Dict[str, Any]]:
        """Return merged DB + sidecar for a single item id (or None)."""
        idx = self._ensure_indexer()
        row = idx.get_capture_by_id(eid)
        if not row:
            # maybe it's a sidecar-only item (unlikely), return sidecar if exists
            meta = read_meta(self.data_dir, eid)
            return meta if meta else None
        meta = read_meta(self.data_dir, eid)
        return merge_db_and_meta(row, meta)

    def update_meta(self, eid: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update editable metadata for `eid`. Writes sidecar and updates DB fields.

        Returns the merged result after update.
        """
        if not eid or not meta:
            raise ValueError("eid and meta required")
        idx = self._ensure_indexer()
        lockpath = self._lock_for_audit()
        with file_lock(lockpath, timeout=5.0):
            # write sidecar first (atomic)
            write_meta(self.data_dir, eid, meta)
            # reflect user-editable fields into DB
            db_meta = {}
            if "mood" in meta:
                db_meta["mood"] = meta.get("mood")
            if "notes" in meta:
                db_meta["notes"] = meta.get("notes")
            if db_meta:
                idx.update_meta(eid, db_meta)

        # return merged
        merged = self.get_item(eid)
        self._notify_changed()
        return merged

    def get_all_capture_dates(self) -> List[str]:
        """
        Public façade: sorted unique dates ('YYYY-MM-DD', UTC-bucketed) that
        have captures (action='capture' only).
        """
        idx = self._ensure_indexer()
        return idx.get_all_capture_dates()

    def get_all_capture_stamps(self) -> List[str]:
        """
        Public façade: raw ts strings of every capture row (action='capture'),
        ordered ascending. Callers convert to local time for day bucketing.
        """
        idx = self._ensure_indexer()
        cur = idx._conn.execute(
            "SELECT ts FROM captures WHERE action='capture' AND ts IS NOT NULL ORDER BY ts ASC"
        )
        return [row["ts"] for row in cur.fetchall()]

    def get_moods_since(self, days_back: int) -> List[Dict[str, Any]]:
        """
        Public façade: [{'date': 'YYYY-MM-DD', 'mood': str}, ...] for captures
        with a mood within the last N days (action='capture' only).
        """
        idx = self._ensure_indexer()
        return idx.get_moods_since(days_back)

    def get_capture_counts_by_date(self, year: int) -> Dict[str, int]:
        """
        Capture counts per day for a full year.

        Returns {'YYYY-MM-DD': count} using SQL substr(ts,1,10) GROUP BY over
        rows with action='capture'. Dates are UTC-bucketed (string compare).
        """
        idx = self._ensure_indexer()
        start = f"{year:04d}-01-01"
        end = f"{year + 1:04d}-01-01"
        cur = idx._conn.execute(
            """
            SELECT substr(ts, 1, 10) AS date_str, COUNT(*) AS c
            FROM captures
            WHERE action='capture' AND substr(ts, 1, 10) >= ? AND substr(ts, 1, 10) < ?
            GROUP BY date_str ORDER BY date_str ASC
            """,
            (start, end),
        )
        return {row["date_str"]: int(row["c"]) for row in cur.fetchall()}

    def get_moods_between(self, start: str, end: str) -> List[Dict[str, Any]]:
        """
        Moods for captures whose UTC date bucket falls in [start, end]
        inclusive ('YYYY-MM-DD' strings). Ordered by ts ascending so the LAST
        entry per day is the latest capture's mood.

        Returns [{'date': 'YYYY-MM-DD', 'mood': str}, ...]
        """
        idx = self._ensure_indexer()
        cur = idx._conn.execute(
            """
            SELECT substr(ts, 1, 10) AS date_str, mood
            FROM captures
            WHERE action='capture' AND mood IS NOT NULL
              AND substr(ts, 1, 10) >= ? AND substr(ts, 1, 10) <= ?
            ORDER BY ts ASC
            """,
            (start, end),
        )
        return [{"date": row["date_str"], "mood": row["mood"]} for row in cur.fetchall()]

    def get_last_photo(self) -> Optional[Dict[str, Any]]:
        """
        Get the most recent photo for the 'Ghost View'.
        Returns merged DB row + sidecar metadata.
        """
        idx = self._ensure_indexer()
        row = idx.get_latest_capture()
        if not row:
            return None
        
        # Merge with sidecar data (in case they edited notes on the last photo)
        eid = row["id"]
        meta = read_meta(self.data_dir, eid)
        return merge_db_and_meta(row, meta)

    def get_recent_photos(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get the most recent N photos with merged sidecar metadata.
        Returns list sorted by timestamp descending (newest first).
        """
        idx = self._ensure_indexer()
        rows = idx.get_recent_captures(limit)
        merged = []
        for r in rows:
            eid = r.get("id")
            meta = read_meta(self.data_dir, eid)
            merged.append(merge_db_and_meta(r, meta))
        return merged


    def migrate_if_needed(self, jsonl_path: Optional[Path] = None) -> int:
        """
        Run migration from captures.jsonl into SQLite. If jsonl_path is None, uses the default audit in data_dir.
        Returns number of rows imported (0 if none).
        """
        idx = self._ensure_indexer()
        jsonl = Path(jsonl_path) if jsonl_path else self.audit_path
        if not jsonl.exists():
            return 0
        # run migration under lock
        lockpath = self._lock_for_audit()
        with file_lock(lockpath, timeout=60.0):
            imported = idx.migrate_from_jsonl(jsonl)
        return imported


# Convenience module-level API for simple use
_api_singleton: Optional[IndexAPI] = None


def get_api(app_paths=None) -> IndexAPI:
    global _api_singleton
    if _api_singleton is None:
        if app_paths is None:
            app_paths = get_app_paths("DailySelfie", ensure=True)
        _api_singleton = IndexAPI(app_paths)
        _api_singleton.init()
        _api_singleton.migrate_if_needed()
    return _api_singleton


# CLI helpers for manual operations
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(prog="core.index_api", description="Index API utility")
    parser.add_argument("--data-dir", default="./.ds_dev/data", help="data dir")
    parser.add_argument("--migrate", action="store_true", help="migrate captures.jsonl into DB")
    parser.add_argument("--info", action="store_true", help="print db info")
    args = parser.parse_args()

    app_paths = get_app_paths("DailySelfie", ensure=True)
    app_paths = type("AP", (), {"data_dir": args.data_dir})()  # quick shim
    api = IndexAPI(app_paths)
    api.init()

    if args.migrate:
        n = api.migrate_if_needed()
        print("Imported rows:", n)

    if args.info:
        idx = api._ensure_indexer()
        print("DB path:", idx.db_path)
        print("Total rows:", idx.count_rows())

    api.close()
