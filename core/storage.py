"""
storage.py

File‑system utilities for DailySelfie.

Responsibilities:
- Deterministic folder structure for images (root/YYYY/)
- Atomic writes for image bytes
- Filename generation (timestamp + UUID fragment)
- Query helpers: find last image for a given date, list all images, etc.

Notes:
- This module does not know anything about cameras or JPEG encoding — only raw bytes.
- All timestamps are expected to be timezone‑aware (UTC recommended).
"""
from __future__ import annotations
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List


# -------------------------------------------------------------
# Naming / folder helpers
# -------------------------------------------------------------

def year_folder(root: Path, ts: datetime) -> Path:
    """Return the photos folder for the given timestamp's year and ensure it exists."""
    y = ts.strftime("%Y")
    folder = root / y
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def make_filename(ts: datetime) -> str:
    """Generate filename: YYYY-MM-DD_HHMMSS_<8hex>.jpg"""
    stamp = ts.strftime("%Y-%m-%d_%H%M%S")
    return f"{stamp}_{uuid.uuid4().hex[:8]}.jpg"


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
# Query helpers
# -------------------------------------------------------------

def glob_images(folder: Path) -> List[Path]:
    """Return all .jpg files in a folder (non‑recursive)."""
    if not folder.exists():
        return []
    return sorted(folder.glob("*.jpg"))


def last_image_for_date(root: Path, date: datetime) -> Optional[Path]:
    """Return the last (most recently modified) image for a specific date.

    Images are stored in root/YYYY/, all filenames start with YYYY-MM-DD.
    """
    folder = root / date.strftime("%Y")
    if not folder.exists():
        return None

    prefix = date.strftime("%Y-%m-%d")
    matches = sorted(folder.glob(f"{prefix}*.jpg"), key=lambda p: p.stat().st_mtime)
    return matches[-1] if matches else None


def list_images_for_date(root: Path, date: datetime) -> List[Path]:
    folder = root / date.strftime("%Y")
    if not folder.exists():
        return []
    prefix = date.strftime("%Y-%m-%d")
    return sorted(folder.glob(f"{prefix}*.jpg"))


def list_all_images(root: Path) -> List[Path]:
    """Return all images under the root, recursively by year folders."""
    if not root.exists():
        return []
    imgs: List[Path] = []
    for yfolder in sorted(root.iterdir()):
        if yfolder.is_dir() and yfolder.name.isdigit():
            imgs.extend(sorted(yfolder.glob("*.jpg")))
    return imgs


# -------------------------------------------------------------
# High‑level save pipeline
# -------------------------------------------------------------
@dataclass
class SaveResult:
    success: bool
    path: Optional[Path] = None
    error: Optional[str] = None


def save_image_bytes(root: Path, ts: datetime, data: bytes) -> SaveResult:
    """High‑level convenience wrapper to save image bytes.

    Returns SaveResult(success, path, error).
    """
    try:
        folder = year_folder(root, ts)
        filename = make_filename(ts)
        saved = atomic_write(folder, filename, data)
        return SaveResult(True, saved, None)
    except Exception as e:
        return SaveResult(False, None, str(e))


# -------------------------------------------------------------
# Smoke test
# -------------------------------------------------------------
if __name__ == "__main__":
    import os
    from datetime import datetime, timezone

    test_root = Path(os.getcwd()) / "_storage_test"
    test_root.mkdir(exist_ok=True)

    ts = datetime.now(timezone.utc)
    data = b"fake_jpeg_bytes"

    res = save_image_bytes(test_root, ts, data)
    print("Saved:", res)

    last = last_image_for_date(test_root, ts)
    print("Last for date:", last)
