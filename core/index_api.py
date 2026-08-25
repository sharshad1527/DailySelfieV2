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
import sqlite3
from datetime import datetime, timedelta, timezone

from core.indexer import Indexer, SCHEMA_VERSION
from core.metadata import read_meta, write_meta, delete_meta, merge_db_and_meta
from core.locks import file_lock, lock_path_for
from core.logging import get_logger
from core.paths import get_app_paths
from core.storage import append_capture_index, append_deletion_index

# Default DB filename relative to data_dir
DB_FILENAME = "index.db"
AUDIT_FILENAME = "captures.jsonl"

logger = get_logger("index_api")


def _local_hour(ts) -> Optional[int]:
    """LOCAL hour (0-23) of a stored UTC ts; None for malformed input."""
    if not isinstance(ts, str):
        return None
    s = ts.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().hour


class HighlightsCache:
    """
    Tiny memo for computed highlight sets.

    Entries are keyed (scope, target) -> (generation, results); a hit is
    served only while its generation matches the API's current change
    counter (bumped by _notify_changed on every write), so any capture,
    deletion or meta edit naturally invalidates everything.
    """

    def __init__(self) -> None:
        self._entries: Dict[Any, Any] = {}

    def get(self, scope: str, target: Any, generation: int):
        hit = self._entries.get((scope, target))
        if hit is not None and hit[0] == generation:
            return hit[1]
        return None

    def put(self, scope: str, target: Any, generation: int, results: Any) -> None:
        self._entries[(scope, target)] = (generation, results)

    def clear(self) -> None:
        self._entries.clear()


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
        self._generation: int = 0
        self.highlights_cache = HighlightsCache()

    @property
    def generation(self) -> int:
        """Monotonic change counter; bumped on every successful write."""
        return self._generation

    def add_index_listener(self, callback) -> None:
        """Register a zero-arg callback fired after successful record_capture /
        record_deletion / update_meta operations."""
        if callback not in self._change_listeners:
            self._change_listeners.append(callback)

    def _notify_changed(self) -> None:
        self._generation += 1
        for cb in list(self._change_listeners):
            try:
                cb()
            except Exception:
                pass

    def init(self) -> None:
        """Initialize the SQLite indexer (create DB if missing).

        If the DB file is corrupt, it is quarantined (renamed with a
        timestamp suffix) and rebuilt fresh; recoverable rows are re-imported
        from captures.jsonl.
        """
        if self._indexer is None:
            candidate: Optional[Indexer] = None
            try:
                candidate = Indexer(self.index_db_path)
                candidate.init_db()
            except sqlite3.DatabaseError as e:
                if candidate is not None:
                    candidate.close()
                self._recover_from_corruption(e)
            else:
                self._indexer = candidate

    def _recover_from_corruption(self, err: Exception) -> None:
        """Quarantine a corrupt index.db, rebuild fresh and re-import JSONL."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        moved: List[str] = []
        if self.index_db_path.exists():
            target = self.index_db_path.with_name(f"{DB_FILENAME}.corrupt-{stamp}")
            self.index_db_path.rename(target)
            moved.append(target.name)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(self.index_db_path) + suffix)
            if sidecar.exists():
                target = sidecar.with_name(sidecar.name + f".corrupt-{stamp}")
                sidecar.rename(target)
                moved.append(target.name)

        fresh = Indexer(self.index_db_path)
        fresh.init_db()
        self._indexer = fresh

        imported = 0
        import_err: Optional[Exception] = None
        try:
            imported = self.migrate_if_needed()
        except Exception as e:
            import_err = e
        logger.warning(
            "index db corrupt (%s); quarantined as %s; rebuilt fresh; "
            "re-imported %d rows from %s%s",
            err, ", ".join(moved) or "-", imported, AUDIT_FILENAME,
            f"; re-import failed: {import_err}" if import_err else "",
        )

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
        Public façade: sorted unique dates ('YYYY-MM-DD', LOCAL-bucketed via
        timeutils) that have captures (action='capture' only).
        """
        idx = self._ensure_indexer()
        return idx.get_all_capture_dates()

    def get_all_capture_stamps(self) -> List[str]:
        """
        Public façade: raw UTC ts strings of every capture row
        (action='capture'), ordered ascending.

        Deliberately NOT converted: callers bucket these stamps themselves via
        core.timeutils (raw feed contract).
        """
        idx = self._ensure_indexer()
        cur = idx._conn.execute(
            "SELECT ts FROM captures WHERE action='capture' AND ts IS NOT NULL ORDER BY ts ASC"
        )
        return [row["ts"] for row in cur.fetchall()]

    def get_moods_since(self, days_back: int) -> List[Dict[str, Any]]:
        """
        Public façade: [{'date': 'YYYY-MM-DD', 'mood': str}, ...] for captures
        with a mood within the last N LOCAL days (action='capture' only).
        """
        idx = self._ensure_indexer()
        return idx.get_moods_since(days_back)

    def get_capture_counts_by_date(self, year: int) -> Dict[str, int]:
        """
        Capture counts per LOCAL day for a full year.

        Returns {'YYYY-MM-DD': count}. Rows are pulled by action='capture' and
        bucketed Python-side via timeutils.local_date_str so a boundary capture
        lands on the user's local day (SQL substr would bucket UTC). Malformed
        ts rows are skipped.
        """
        from core.timeutils import local_date_str

        idx = self._ensure_indexer()
        year_prefix = f"{year:04d}-"
        cur = idx._conn.execute(
            "SELECT ts FROM captures WHERE action='capture'"
        )
        counts: Dict[str, int] = {}
        for row in cur.fetchall():
            d = local_date_str(row["ts"])
            if d and d.startswith(year_prefix):
                counts[d] = counts.get(d, 0) + 1
        return dict(sorted(counts.items()))

    def get_on_this_day(self) -> Optional[Dict[str, Any]]:
        """
        Most recent capture from this calendar day (MM-DD) in a PREVIOUS
        year/month: the row's LOCAL day matches today's MM-DD but is not today.
        action='capture' only; ordered ts DESC, first match wins.

        Matching is done on timeutils-local dates, not substr(ts, 6, 5) of the
        raw UTC ts. Returns merged DB + sidecar dict, or None when no match.
        """
        from core.timeutils import local_date_str

        idx = self._ensure_indexer()
        now = datetime.now().astimezone()
        md = now.strftime("%m-%d")
        today_str = now.strftime("%Y-%m-%d")
        cur = idx._conn.execute(
            "SELECT id, ts FROM captures WHERE action='capture' ORDER BY ts DESC"
        )
        for row in cur.fetchall():
            d = local_date_str(row["ts"])
            if not d or d == today_str:
                continue
            if d[5:] == md:
                full = idx.get_capture_by_id(row["id"])
                if full:
                    return merge_db_and_meta(dict(full), read_meta(self.data_dir, full["id"]))
        return None

    def get_moods_between(self, start: str, end: str) -> List[Dict[str, Any]]:
        """
        Moods for captures whose LOCAL date bucket falls in [start, end]
        inclusive ('YYYY-MM-DD' strings). Rows are bucketed via
        timeutils.local_date_str (stored UTC ts -> machine-local day); rows
        outside the window or with malformed ts are skipped. Ordered by ts
        ascending so the LAST entry per day is the latest capture's mood.

        Returns [{'date': 'YYYY-MM-DD', 'mood': str}, ...]
        """
        from core.timeutils import local_date_str

        idx = self._ensure_indexer()
        cur = idx._conn.execute(
            """
            SELECT ts, mood
            FROM captures
            WHERE action='capture' AND mood IS NOT NULL
            ORDER BY ts ASC
            """
        )
        out: List[Dict[str, Any]] = []
        for row in cur.fetchall():
            d = local_date_str(row["ts"])
            if d and start <= d <= end:
                out.append({"date": d, "mood": row["mood"]})
        return out

    def get_rows_with_quality(self, year: Optional[int] = None,
                              month: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Capture rows (action='capture') with their quality columns for the
        given LOCAL period; year=None means all history.

        Rows are filtered Python-side via timeutils.local_date_str so a
        boundary capture lands on the user's local month/year (SQL substr
        would bucket UTC). Ordered ts ascending.
        """
        from core.timeutils import local_date_str

        idx = self._ensure_indexer()
        year_prefix = f"{year:04d}-" if year else None
        month_prefix = f"{year:04d}-{month:02d}-" if year and month else None
        cur = idx._conn.execute(
            "SELECT * FROM captures WHERE action='capture' ORDER BY ts ASC"
        )
        out: List[Dict[str, Any]] = []
        for row in cur.fetchall():
            d = local_date_str(row["ts"])
            if not d:
                continue
            if month_prefix and not d.startswith(month_prefix):
                continue
            if year_prefix and not d.startswith(year_prefix):
                continue
            out.append(dict(row))
        return out

    def get_capture_times_between(self, start: str, end: str) -> List[int]:
        """
        LOCAL hours (0-23) of captures whose LOCAL day bucket falls in
        [start, end] inclusive ('YYYY-MM-DD' strings).

        The window is converted to UTC ISO bounds covering local midnight to
        midnight so the SQL range matches timeutils bucketing; malformed ts
        rows are skipped. Returned order follows ts ascending.
        """
        idx = self._ensure_indexer()
        try:
            win_start = datetime.strptime(start, "%Y-%m-%d").astimezone()
            win_end = datetime.strptime(end, "%Y-%m-%d").astimezone() + timedelta(days=1)
        except ValueError:
            return []
        start_utc = win_start.astimezone(timezone.utc).isoformat()
        end_utc = win_end.astimezone(timezone.utc).isoformat()
        cur = idx._conn.execute(
            """
            SELECT ts FROM captures
            WHERE action='capture' AND ts >= ? AND ts < ?
            ORDER BY ts ASC
            """,
            (start_utc, end_utc),
        )
        hours: List[int] = []
        for row in cur.fetchall():
            h = _local_hour(row["ts"])
            if h is not None:
                hours.append(h)
        return hours

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
        Skipped when the DB is already schema-stamped (user_version) and non-empty.
        """
        idx = self._ensure_indexer()
        jsonl = Path(jsonl_path) if jsonl_path else self.audit_path
        if not jsonl.exists():
            return 0
        # Already migrated: marker present AND db has rows -> skip re-read
        if idx.get_user_version() >= SCHEMA_VERSION and idx.count_rows() > 0:
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
