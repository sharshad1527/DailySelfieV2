# core/storage.py
"""
storage.py

File-system utilities for DailySelfie.

Responsibilities:
- Deterministic folder structure for images (root/YYYY/MM/)
- Atomic writes for image bytes
- Filename generation: YYYY-MM-DD_HHMMSS.jpg (no random suffix)
- Query helpers: find last image for a given date, list images, list all images
- Append-only JSONL index helper for saved captures and deletions
"""
from __future__ import annotations
import tempfile
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import os

# -------------------------------------------------------------
# Data structures
# -------------------------------------------------------------
@dataclass
class SaveResult:
    success: bool
    path: Optional[Path] = None
    error: Optional[str] = None


# -------------------------------------------------------------
# Naming / folder helpers (Option C - no random hex)
# -------------------------------------------------------------
def year_month_folder(root: Path, ts: datetime) -> Path:
    """Return the photos folder for the given timestamp's year/month and ensure it exists.
    Structure: root/YYYY/MM/
    """
    y = ts.strftime("%Y")
    m = ts.strftime("%m")
    folder = root / y / m
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def make_date_time_filename(ts: datetime) -> str:
    """Generate filename: YYYY-MM-DD_HHMMSS.jpg (24-hour time, no random suffix)."""
    datepart = ts.strftime("%Y-%m-%d")
    timepart = ts.strftime("%H%M%S")
    return f"{datepart}_{timepart}.jpg"


# -------------------------------------------------------------
# Atomic write
# -------------------------------------------------------------
def atomic_write(dest_folder: Path, filename: str, data: bytes) -> Path:
    """Write bytes atomically by writing into a temporary file in the same directory.

    Returns the final path.
    """
    dest_folder.mkdir(parents=True, exist_ok=True)
    final_path = dest_folder / filename

    # Use NamedTemporaryFile with delete=False to control the final rename.
    with tempfile.NamedTemporaryFile(dir=str(dest_folder), delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    # Atomically replace.
    tmp_path.replace(final_path)
    return final_path


# -------------------------------------------------------------
# Index helper (append-only JSONL for saved captures)
# -------------------------------------------------------------
def append_capture_index(index_path: Path, entry: Dict[str, Any]) -> None:
    """Append a JSON line `entry` into index_path (creates file if missing).

    This is append-only. GUI can create per-uuid sidecar files later for edits.
    """
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()
        try:
            # best-effort durability
            os.fsync(f.fileno())
        except Exception:
            pass


def append_deletion_index(index_path: Path, entry: Dict[str, Any]) -> None:
    """Append a JSON line representing a deletion event into the index_path."""
    # Reuse same semantics as append_capture_index
    append_capture_index(index_path, entry)


# -------------------------------------------------------------
# Query helpers (search under year/month)
# -------------------------------------------------------------
def list_images_for_date(root: Path, date: datetime) -> List[Path]:
    """List images for a specific date (searches year/month folders)."""
    year = date.strftime("%Y")
    prefix = date.strftime("%Y-%m-%d")
    year_dir = root / year
    if not year_dir.exists():
        return []
    imgs: List[Path] = []
    for month_dir in sorted(year_dir.iterdir()):
        if not month_dir.is_dir():
            continue
        imgs.extend(sorted(month_dir.glob(f"{prefix}_*.jpg")))
    return imgs


def last_image_for_date(root: Path, date: datetime) -> Optional[Path]:
    """Return the most-recent image for a specific date searching year/month folders.

    Looks for files starting with YYYY-MM-DD inside root/YYYY/MM/ and returns the newest.
    """
    imgs = list_images_for_date(root, date)
    return imgs[-1] if imgs else None


def list_all_images(root: Path) -> List[Path]:
    """Return all images under the root, recursively by year/month folders."""
    if not root.exists():
        return []
    imgs: List[Path] = []
    for yfolder in sorted(root.iterdir()):
        if not yfolder.is_dir() or not yfolder.name.isdigit():
            continue
        for mfolder in sorted(yfolder.iterdir()):
            if not mfolder.is_dir():
                continue
            imgs.extend(sorted(mfolder.glob("*.jpg")))
    return imgs


def glob_images(folder: Path) -> List[Path]:
    """Return all .jpg files in a folder (non-recursive)."""
    if not folder.exists():
        return []
    return sorted(folder.glob("*.jpg"))


# -------------------------------------------------------------
# Delete helpers (for retake)
# -------------------------------------------------------------
def delete_path(path: Path) -> Tuple[bool, Optional[str]]:
    """Delete a single filesystem path. Returns (success, error_message)."""
    try:
        if not path.exists():
            return False, "path_not_found"
        if path.is_dir():
            return False, "path_is_directory"
        path.unlink()
        return True, None
    except Exception as e:
        return False, str(e)


def delete_last_image_for_date(root: Path, date: datetime) -> Tuple[bool, Optional[str], Optional[Path]]:
    """
    Find the most-recent image for a given date and delete it.
    Returns (success, error_message, deleted_path).
    If no image found: (False, 'no_image', None)
    """
    last = last_image_for_date(root, date)
    if not last:
        return False, "no_image", None
    ok, err = delete_path(last)
    if ok:
        return True, None, last
    return False, err, last


# -------------------------------------------------------------
# High-level save pipeline
# -------------------------------------------------------------
def save_image_bytes(root: Path, ts: datetime, data: bytes) -> SaveResult:
    """High-level convenience wrapper to save image bytes.

    Saves into root/YYYY/MM/ with filename YYYY-MM-DD_HHMMSS.jpg
    Returns SaveResult(success, path, error).
    """
    try:
        folder = year_month_folder(root, ts)
        filename = make_date_time_filename(ts)
        saved = atomic_write(folder, filename, data)
        return SaveResult(True, saved, None)
    except Exception as e:
        return SaveResult(False, None, str(e))


# -------------------------------------------------------------
# Smoke test (keeps behavior from previous file)
# -------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from datetime import timezone

    test_root = Path(os.getcwd()) / "_storage_test"
    test_root.mkdir(exist_ok=True)

    ts = datetime.now(timezone.utc)
    data = b"fake_jpeg_bytes"

    res = save_image_bytes(test_root, ts, data)
    print("Saved:", res)

    last = last_image_for_date(test_root, ts)
    print("Last for date:", last)
