# core/timeutils.py
"""
Day-bucketing time helpers for DailySelfie.

Capture timestamps (DB `ts`, JSONL, photo filenames) are UTC by contract,
but users reason in LOCAL calendar days. Every day-bucketing read must go
through these helpers; never string-slice a raw UTC ts as a local date.

Malformed input yields None (streak.py precedent: skip bad data, never raise).

Timezone handling (2026-10):
--------------------------
Day bucketing used to be reachable only by mutating the process-global TZ
(`os.environ["TZ"] = ...; time.tzset()`), which is POSIX-only -- every
TZ-parametrised test silently skipped on Windows. All helpers now accept an
explicit timezone (a `str` IANA key or any `tzinfo`) and the module keeps a
process-local default override, so callers that genuinely want "the machine's
current wall clock" still work unchanged:

    local_date_str(ts)                 # machine-local tz (override-aware)
    local_date_str(ts, tz="Asia/Kolkata")
    timeutils.set_local_tz("Asia/Kolkata")   # override for subsequent calls
    timeutils.clear_local_tz()               # back to the machine's tz

With no override set, behaviour is byte-for-byte identical to the old
process-global-TZ implementation: the conversion goes through
`datetime.astimezone()` with no argument. The override is a module attribute,
not a process-global, so it needs no `time.tzset()` and works identically on
Windows and POSIX.

NOTE: this module is on the stdlib-only pre-venv import chain (it is imported
by installer/probe paths before dependencies are installed). Keep it free of
third-party and Qt imports. `zoneinfo` is stdlib; its IANA database comes from
the OS on POSIX and from the `tzdata` PyPI package on Windows (see
requirements.txt).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, List, Optional, Union

try:  # stdlib since 3.9; present everywhere we support
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except Exception:  # pragma: no cover - only on exotic builds
    ZoneInfo = None  # type: ignore
    ZoneInfoNotFoundError = Exception  # type: ignore

_DATE_FMT = "%Y-%m-%d"

# Any of these are accepted wherever a timezone is expected.
TzLike = Union[str, tzinfo, None]

# Process-local default override (NOT os.environ / time.tzset). None means
# "use the machine's current local timezone", which is the historical
# behaviour. Set via set_local_tz(); tests patch this attribute directly.
_local_tz_override: Optional[tzinfo] = None


def get_tz(value: TzLike) -> Optional[tzinfo]:
    """Coerce `value` to a tzinfo, or None for "machine local".

    Accepts None (machine local), a `str` IANA key ('Asia/Kolkata', 'UTC'),
    or a `tzinfo` instance (returned unchanged). Raises ValueError for an
    unknown key or when `zoneinfo` is unavailable -- a bad timezone is a
    programming error, not data, and silently falling back would hide bugs.
    """
    if value is None:
        return None
    if isinstance(value, tzinfo):
        return value
    if isinstance(value, str):
        if ZoneInfo is None:  # pragma: no cover
            raise ValueError("zoneinfo unavailable; cannot resolve timezone " + value)
        try:
            return ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, KeyError, OSError) as exc:
            raise ValueError(f"Unknown timezone {value!r}: {exc}") from exc
    raise ValueError(f"Not a timezone: {value!r}")


def current_tz() -> Optional[tzinfo]:
    """The timezone default calls use: the override, else None (= machine local)."""
    return _local_tz_override


def set_local_tz(value: TzLike) -> Optional[tzinfo]:
    """Override the timezone used when a caller passes no explicit `tz`.

    Returns the resolved tzinfo. This affects only this module's default
    (no os.environ mutation, no time.tzset), so it is safe on Windows.
    """
    global _local_tz_override
    _local_tz_override = get_tz(value)
    return _local_tz_override


def clear_local_tz() -> None:
    """Drop the default override and go back to the machine's local timezone."""
    global _local_tz_override
    _local_tz_override = None


def _pick(tz: TzLike) -> Optional[tzinfo]:
    """Resolve an explicit `tz` argument, falling back to the default override."""
    if tz is None:
        return _local_tz_override
    return get_tz(tz)


def _as_local(dt: datetime, tz: TzLike = None) -> datetime:
    """Convert an aware UTC datetime to local time under `tz`.

    tz=None with no override keeps the original `dt.astimezone()` call, which
    consults the machine's local timezone.
    """
    resolved = _pick(tz)
    if resolved is None:
        return dt.astimezone()
    return dt.astimezone(resolved)


def _parse_utc(value: Any) -> Optional[datetime]:
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


def local_date_str(utc_ts: Any, tz: TzLike = None) -> Optional[str]:
    """Return the LOCAL calendar day ('YYYY-MM-DD') for a stored UTC ts.

    `utc_ts` may be an ISO/Z string, a datetime, or epoch seconds.
    `tz` may be an IANA key or tzinfo; omitted means the default from
    `current_tz()` (the machine's timezone unless overridden).
    Returns None for malformed/unparseable input.
    """
    dt = _parse_utc(utc_ts)
    if dt is None:
        return None
    return _as_local(dt, tz).strftime(_DATE_FMT)


def today_local_str(tz: TzLike = None) -> str:
    """Local today as 'YYYY-MM-DD' in `tz` (default: `current_tz()`)."""
    resolved = _pick(tz)
    if resolved is None:
        return datetime.now().astimezone().strftime(_DATE_FMT)
    return datetime.now(resolved).strftime(_DATE_FMT)


def filename_stem_local_date(stem: str, tz: TzLike = None) -> Optional[str]:
    """LOCAL date of a UTC-named photo stem 'YYYY-MM-DD_HHMMSS'; None if malformed."""
    if not isinstance(stem, str):
        return None
    try:
        dt = datetime.strptime(stem.strip(), "%Y-%m-%d_%H%M%S")
    except ValueError:
        return None
    return local_date_str(dt, tz=tz)


def local_day_utc_prefixes(day_str: str, tz: TzLike = None) -> List[str]:
    """UTC date prefixes ('YYYY-MM-DD') that can hold photos belonging to the
    LOCAL day `day_str` (a local midnight-to-midnight span crosses at most two
    UTC dates). Returns 1-2 sorted prefixes; empty list if `day_str` is invalid.
    """
    resolved = _pick(tz)
    try:
        naive = datetime.strptime(day_str, _DATE_FMT)
    except ValueError:
        return []
    # A bare local midnight: pin it to the target zone, or let astimezone()
    # apply the machine zone (unchanged behaviour).
    start = naive.replace(tzinfo=resolved) if resolved is not None else naive.astimezone()
    end = start + timedelta(days=1)
    first = start.astimezone(timezone.utc).strftime(_DATE_FMT)
    last = (end - timedelta(seconds=1)).astimezone(timezone.utc).strftime(_DATE_FMT)
    return sorted({first, last})