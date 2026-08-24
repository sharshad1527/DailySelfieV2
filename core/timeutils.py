# core/timeutils.py
"""
Day-bucketing time helpers for DailySelfie.

Capture timestamps (DB `ts`, JSONL, photo filenames) are UTC by contract,
but users reason in LOCAL calendar days. Every day-bucketing read must go
through these helpers; never string-slice a raw UTC ts as a local date.

Malformed input yields None (streak.py precedent: skip bad data, never raise).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

_DATE_FMT = "%Y-%m-%d"


def _parse_utc(value) -> Optional[datetime]:
    """Coerce value to an aware UTC datetime; None on failure.

    Accepts ISO strings (with optional trailing Z / explicit offset),
    aware/naive datetimes, and epoch seconds. Naive input is interpreted
    as UTC because all stored capture ts values are UTC by contract.
    """
    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, bool):
            return None
        elif isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        elif isinstance(value, str):
            s = value.strip()
            if not s:
                return None
            if s.endswith(("Z", "z")):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
        else:
            return None
    except (ValueError, TypeError, OverflowError, OSError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def local_date_str(utc_ts) -> Optional[str]:
    """Return the LOCAL calendar day ('YYYY-MM-DD') for a stored UTC ts.

    `utc_ts` may be an ISO/Z string, a datetime, or epoch seconds.
    Returns None for malformed/unparseable input.
    """
    dt = _parse_utc(utc_ts)
    if dt is None:
        return None
    return dt.astimezone().strftime(_DATE_FMT)


def today_local_str() -> str:
    """Machine-local today as 'YYYY-MM-DD'."""
    return datetime.now().astimezone().strftime(_DATE_FMT)


def filename_stem_local_date(stem: str) -> Optional[str]:
    """LOCAL date of a UTC-named photo stem 'YYYY-MM-DD_HHMMSS'; None if malformed."""
    if not isinstance(stem, str):
        return None
    try:
        dt = datetime.strptime(stem.strip(), "%Y-%m-%d_%H%M%S")
    except ValueError:
        return None
    return local_date_str(dt)


def local_day_utc_prefixes(day_str: str) -> List[str]:
    """UTC date prefixes ('YYYY-MM-DD') that can hold photos belonging to the
    LOCAL day `day_str` (a local midnight-to-midnight span crosses at most two
    UTC dates). Returns 1-2 sorted prefixes; empty list if `day_str` is invalid.
    """
    try:
        start = datetime.strptime(day_str, _DATE_FMT).astimezone()
    except ValueError:
        return []
    end = start + timedelta(days=1)
    first = start.astimezone(timezone.utc).strftime(_DATE_FMT)
    last = (end - timedelta(seconds=1)).astimezone(timezone.utc).strftime(_DATE_FMT)
    return sorted({first, last})
