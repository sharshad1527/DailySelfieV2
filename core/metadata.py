# core/metadata.py
"""
Per-UUID sidecar metadata manager for DailySelfie.

Responsibilities
- Create/read/write/delete per-capture sidecar JSON files at:
    <data_dir>/metadata/<id>.json
- Provide merge logic so GUI can present DB row + sidecar overrides.
- Use atomic write semantics to avoid corrupt sidecars.

Data model (example sidecar):
{
  "id": "2025-12-12_074512",
  "mood": "happy",
  "notes": "Felt good. Tried new haircut.",
  "edited_at": "2025-12-12T07:46:12+00:00"
}

API
- read_meta(data_dir: Path, id: str) -> dict
- write_meta(data_dir: Path, id: str, meta: dict) -> None
- delete_meta(data_dir: Path, id: str) -> None
- merge_db_and_meta(db_entry: dict, meta: dict) -> dict
"""
from __future__ import annotations
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional


def _meta_path(data_dir: Path, eid: str) -> Path:
    """Return the sidecar path for a given id."""
    return Path(data_dir) / "metadata" / f"{eid}.json"


def read_meta(data_dir: Path, eid: str) -> Dict[str, Any]:
    """
    Read the JSON sidecar for `eid`. Returns an empty dict if not present or malformed.
    """
    p = _meta_path(data_dir, eid)
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Corrupted/malformed file — do not raise (GUI can surface error separately).
        return {}


def write_meta(data_dir: Path, eid: str, meta: Dict[str, Any]) -> None:
    """
    Atomically write `meta` dict to the sidecar file for `eid`.
    Ensures parent dirs exist and uses a temp file + rename for atomicity.
    """
    p = _meta_path(data_dir, eid)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Ensure edited_at is set if not provided
    meta_to_write = dict(meta)
    if "edited_at" not in meta_to_write:
        meta_to_write["edited_at"] = datetime.now(timezone.utc).isoformat()

    # Write to temp file then replace
    fd, tmpname = tempfile.mkstemp(dir=str(p.parent), prefix=f".{eid}.tmp.")
    try:
        with open(fd, "w", encoding="utf-8") as tf:
            json.dump(meta_to_write, tf, ensure_ascii=False, indent=None)
            tf.flush()
        tmp_path = Path(tmpname)
        tmp_path.replace(p)
    except Exception:
        # Clean up temp file on error if it still exists
        try:
            tmp = Path(tmpname)
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        raise


def delete_meta(data_dir: Path, eid: str) -> None:
    """
    Delete the sidecar file for `eid` if it exists. No-op if missing.
    """
    p = _meta_path(data_dir, eid)
    try:
        if p.exists():
            p.unlink()
    except Exception as e:
        # Let caller decide how to handle errors; keep it simple here
        raise


def merge_db_and_meta(db_entry: Optional[Dict[str, Any]], meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge a DB entry (authoritative capture row) with a sidecar meta dict.

    - Fields from sidecar override corresponding fields in db_entry for user-editable fields
      (e.g., 'mood', 'notes').
    - Returns a new dict; does not modify inputs.
    - If db_entry is None, returns sidecar (useful when DB missing).
    """
    db_entry = dict(db_entry) if db_entry else {}
    meta = dict(meta) if meta else {}

    merged = dict(db_entry)  # shallow copy

    # Editable fields that sidecar may override
    for k in ("mood", "notes", "edited_at"):
        if k in meta and meta[k] is not None:
            merged[k] = meta[k]
        else:
            # ensure keys exist with None if absent
            merged.setdefault(k, None)

    # Keep DB fields not present in sidecar
    return merged


# Quick manual test when run directly
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(prog="core.metadata", description="Test metadata sidecars")
    parser.add_argument("--data-dir", default="./.ds_dev/data", help="Data dir root")
    parser.add_argument("--id", required=True, help="capture id (filename stem)")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--write", help="JSON string to write as meta")
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if args.show:
        print(read_meta(data_dir, args.id))
    if args.write:
        obj = json.loads(args.write)
        write_meta(data_dir, args.id, obj)
        print("WROTE")
    if args.delete:
        delete_meta(data_dir, args.id)
        print("DELETED")
