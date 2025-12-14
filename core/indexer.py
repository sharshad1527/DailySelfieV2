# core/indexer.py
"""
SQLite indexer for DailySelfie.

Responsibilities:
- Provide an authoritative, queryable index for captures (id, ts, path, width, height, resolution, mood, notes, action, created_at)
- Support fast queries by month/day for the GUI
- Allow atomic updates of editable fields (mood, notes)
- Provide a one-time migration helper from an append-only JSONL audit (captures.jsonl)

Design notes:
- Uses WAL mode for better concurrent reads while writing.
- Uses INSERT OR REPLACE so later migration runs won't duplicate/raise easily.
- Exposes a small API suitable for GUI/back-end usage.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional
import json
import time
import traceback

# Minimal schema: captures table. id is filename stem (e.g. 2025-12-12_074512)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
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
CREATE INDEX IF NOT EXISTS idx_ts ON captures(ts);
"""

class Indexer:
    """
    Indexer(db_path: Path)

    Example:
        idx = Indexer(Path('./.ds_dev/data/index.db'))
        idx.init_db()
        idx.add_capture({...})
        rows = idx.get_captures_by_month(2025, 12)
        idx.update_meta("2025-12-12_074512", {"mood": "ok", "notes": "feeling good"})
        idx.close()
    """

    def __init__(self, db_path: Path, timeout: float = 30.0):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # allow multi-thread usage if needed; thread-safety must be handled by caller
        self._conn = sqlite3.connect(str(self.db_path), timeout=timeout, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Set WAL and a reasonable synchronous level for performance/durability tradeoff
        try:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
        except Exception:
            # If pragmas fail, continue — still usable
            pass

    def init_db(self) -> None:
        """Create tables and indexes if missing."""
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def add_capture(self, entry: Dict[str, Any]) -> None:
        """
        Insert or replace a capture row.

        entry keys expected:
          - id (required)
          - ts (ISO string, required)
          - path (required)
          - width (optional int)
          - height (optional int)
          - resolution (optional str)
          - mood (optional str)
          - notes (optional str)
          - action (capture|delete) default 'capture'
        """
        now = time.time()
        eid = entry.get("id")
        if not eid:
            raise ValueError("entry must contain 'id' key")

        # Normalize values we store
        ts = entry.get("ts")
        path = entry.get("path")
        width = entry.get("width")
        height = entry.get("height")
        resolution = entry.get("resolution")
        mood = entry.get("mood")
        notes = entry.get("notes")
        action = entry.get("action", "capture")

        self._conn.execute(
            """
            INSERT OR REPLACE INTO captures
            (id, ts, path, width, height, resolution, mood, notes, action, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eid, ts, path, width, height, resolution, mood, notes, action, now),
        )
        self._conn.commit()

    def get_captures_by_month(self, year: int, month: int) -> List[Dict[str, Any]]:
        """
        Return capture rows (action='capture') for a given month, ordered by ts asc.

        Example: get_captures_by_month(2025, 12)
        """
        start = f"{year:04d}-{month:02d}-01T00:00:00"
        if month == 12:
            end = f"{year+1:04d}-01-01T00:00:00"
        else:
            end = f"{year:04d}-{month+1:02d}-01T00:00:00"
        cur = self._conn.execute(
            "SELECT * FROM captures WHERE ts >= ? AND ts < ? AND action='capture' ORDER BY ts ASC",
            (start, end),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_capture_by_id(self, eid: str) -> Optional[Dict[str, Any]]:
        """Return a single capture row by id (or None)."""
        cur = self._conn.execute("SELECT * FROM captures WHERE id = ? LIMIT 1", (eid,))
        row = cur.fetchone()
        return dict(row) if row else None

    def update_meta(self, eid: str, meta: Dict[str, Any]) -> None:
        """
        Update editable metadata fields for a capture.
        Supported fields: mood, notes
        """
        if not meta:
            return
        if "mood" in meta:
            self._conn.execute("UPDATE captures SET mood = ? WHERE id = ?", (meta.get("mood"), eid))
        if "notes" in meta:
            self._conn.execute("UPDATE captures SET notes = ? WHERE id = ?", (meta.get("notes"), eid))
        self._conn.commit()

    def migrate_from_jsonl(self, jsonl_path: Path, report_every: int = 1000) -> int:
        """
        One-time import of existing captures.jsonl into sqlite.
        Returns number of rows imported.
        Robust to malformed lines; skips bad lines and continues.
        """
        jsonl_path = Path(jsonl_path)
        if not jsonl_path.exists():
            return 0
        count = 0
        with jsonl_path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    # skip malformed line
                    continue
                # Determine id
                eid = obj.get("id") or (Path(obj.get("path", "")).stem if obj.get("path") else None)
                if not eid:
                    # nothing meaningful to import
                    continue
                entry = {
                    "id": eid,
                    "ts": obj.get("ts"),
                    "path": obj.get("path"),
                    "width": obj.get("width"),
                    "height": obj.get("height"),
                    "resolution": obj.get("resolution"),
                    "mood": obj.get("mood"),
                    "notes": obj.get("notes"),
                    "action": obj.get("action", obj.get("type", "capture")),
                }
                try:
                    self.add_capture(entry)
                    count += 1
                except Exception:
                    # swallow per-row exceptions but continue
                    continue
                if report_every and (i % report_every == 0):
                    print(f"[indexer] migrated {i} lines...")
        return count
    def get_latest_capture(self) -> Optional[Dict[str, Any]]:
        """Return the most recent capture (by timestamp)."""
        # ORDER BY ts DESC (Desending) puts the newest dates first
        cur = self._conn.execute(
            "SELECT * FROM captures WHERE action='capture' ORDER BY ts DESC LIMIT 1"
        )
        row = cur.fetchone()
        return dict(row) if row else None
    
    def count_rows(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) as c FROM captures")
        row = cur.fetchone()
        return int(row["c"]) if row else 0

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# Lightweight CLI usage convenience for manual testing
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(prog="core.indexer", description="Index DB helper")
    parser.add_argument("--db", default="./.ds_dev/data/index.db", help="DB path")
    parser.add_argument("--migrate", help="Path to captures.jsonl to migrate from (optional)")
    parser.add_argument("--info", action="store_true", help="Print DB info")
    args = parser.parse_args()

    idx = Indexer(Path(args.db))
    idx.init_db()

    if args.migrate:
        print("Migrating from:", args.migrate)
        n = idx.migrate_from_jsonl(Path(args.migrate))
        print("Imported rows:", n)

    if args.info:
        print("DB path:", idx.db_path)
        print("Total rows:", idx.count_rows())

    idx.close()
