# core/thumbs.py
"""
Disk-backed thumbnail cache for selfie photos.

Dashboard surfaces (carousel cards, calendar tiles, today-card preview)
display photos far below their captured resolution. Decoding multi-megapixel
JPEGs for every repaint made scrolling and resizing janky; this module caches
small JPEG derivatives under ``data_dir/thumbs`` keyed by

    {source_stem}_{size_bucket}_{source_mtime_ns}.jpg

so a retake of the same stem automatically gets a fresh entry (the mtime is
part of the key - simplest correct staleness guard; no sidecar files).

Thumbnails are generated with an ASPECT-PRESERVING fit-downscale (not a
cover-crop): a pre-cropped thumb would change the visible field-of-view when
the consumer later cover-crops to a non-square rect, while a fit-downscale
commutes exactly with any downstream center crop. Displayed sizes are
therefore identical to rendering from the original; only sharpness is bounded
by the bucket, which consumers pick >= 1:1 device pixels so no upscaling
occurs.

API:
    get_thumbnail(path, size_px) -> Optional[Path]   # cached path or None
    clear_cache() -> int                             # unused-but-exported util
    load_display_pixmap(path, display_long_px, dpr)  # thumb-aware decoder
"""
from __future__ import annotations

import os
from math import ceil
from pathlib import Path
from typing import Optional, Tuple

# Cache layout constants
_THUMBS_DIRNAME = "thumbs"
_JPEG_QUALITY = 85

# Distinct size buckets (cache key snaps UP to the smallest bucket that is
# >= the requested pixel size). Kept coarse so each photo produces at most a
# couple of files across all surfaces.
_BUCKETS: Tuple[int, ...] = (256, 512, 1024)

# Only bother with the cache when the source exceeds this multiple of the
# display need (device px); below that, decoding the original is already cheap.
_UPSCALE_FACTOR = 2.0


def _cache_dir():
    """Resolve <data_dir>/thumbs (created lazily by callers that write)."""
    from core.paths import get_app_paths
    return get_app_paths("DailySelfie", ensure=False).data_dir / _THUMBS_DIRNAME


def bucket_for(size_px: int) -> Optional[int]:
    """Smallest cache bucket >= size_px, or None when display outgrows all."""
    need = max(1, int(ceil(size_px)))
    for b in _BUCKETS:
        if b >= need:
            return b
    return None


def needs_thumbnail(source_w: int, source_h: int,
                    display_long_px: float, dpr: float) -> bool:
    """True when the source is large enough that a cached thumb pays off."""
    if source_w <= 0 or source_h <= 0:
        return False
    need = max(1.0, float(display_long_px) * float(dpr or 1.0))
    return max(source_w, source_h) > need * _UPSCALE_FACTOR


def _entry_name(src: Path, bucket: int, mtime_ns: int) -> str:
    return f"{src.stem}_{bucket}_{mtime_ns}.jpg"


def get_thumbnail(path: Path, size_px: int) -> Optional[Path]:
    """
    Return a path to a cached JPEG thumbnail of `path` whose long edge is at
    most one bucket above `size_px`, generating it on first use.

    Returns instantly when a matching entry exists (keyed incl. source
    mtime). Returns None on unreadable sources, oversize displays, missing
    Qt app instance, or any generation failure - callers fall back to
    decoding the original.
    """
    src = Path(path)
    try:
        st = src.stat()
    except OSError:
        return None

    bucket = bucket_for(size_px)
    if bucket is None:
        return None

    cdir = _cache_dir()
    cached = cdir / _entry_name(src, bucket, st.st_mtime_ns)
    try:
        if cached.is_file() and cached.stat().st_size > 0:
            return cached
    except OSError:
        return None

    # Generation needs a live GUI application for QPixmap.
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QPixmap
    if QGuiApplication.instance() is None:
        return None

    try:
        pixmap = QPixmap(str(src))
        if pixmap.isNull():
            return None
        scaled = pixmap.scaled(bucket, bucket,
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if scaled.isNull():
            return None
        cdir.mkdir(parents=True, exist_ok=True)
        tmp = cdir / f"{cached.name}.{os.getpid()}.tmp"
        if not scaled.save(str(tmp), "JPEG", _JPEG_QUALITY):
            tmp.unlink(missing_ok=True)
            return None
        os.replace(tmp, cached)  # atomic within the same directory
        return cached
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return None


def clear_cache() -> int:
    """
    Delete every cached thumbnail. Returns the number of files removed.

    Exported for a future Settings integration ("rebuild thumbnails");
    intentionally unused by the GUI today.
    """
    removed = 0
    try:
        entries = list(_cache_dir().glob("*.jpg"))
    except OSError:
        return 0
    for p in entries:
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def load_display_pixmap(path: Path, display_long_px: float,
                        dpr: float = 1.0):
    """
    Decode `path` for on-screen display, serving it from the disk cache when
    the source far exceeds display needs (~2x rule).

    The returned pixmap is NOT dpr-tagged and NOT cropped - callers keep
    their existing scaling pipelines (scaled_cover_crop / custom painters),
    so rendered geometry is identical to loading the original. A null
    QPixmap is returned when nothing could be decoded.
    """
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QImageReader, QPixmap

    src = Path(path)
    pixmap = QPixmap()
    if not src.exists():
        return pixmap

    # Header-only dimension peek (no full decode).
    try:
        size = QImageReader(str(src)).size()
    except Exception:
        size = QSize()

    if (size.isValid()
            and needs_thumbnail(size.width(), size.height(),
                                display_long_px, dpr)):
        bucket = bucket_for(ceil(display_long_px * float(dpr or 1.0)))
        if bucket is not None:
            thumb = get_thumbnail(src, bucket)
            if thumb is not None:
                pixmap = QPixmap(str(thumb))

    if pixmap.isNull():
        pixmap = QPixmap(str(src))
    return pixmap
