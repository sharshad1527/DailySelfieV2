# core/recap.py
"""
Recap & highlight analytics for the DailySelfie dashboard.

Pure, Qt-free layer over the index API:
- Computers turn raw feed data (local date strings, capture rows, mood
  entries, local hours) into Highlight cards.
- compute_highlights / build_recap_stats aggregate them per scope ('month',
  'year', 'all') and keep everything JSON-safe for GUI/CLI consumption.
- backfill_quality fills blur/brightness metrics for older captures.

All day bucketing goes through core.timeutils; malformed input is skipped,
never raised (streak.py precedent).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, asdict
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.logging import get_logger
from core.streak import calculate_streaks
from core.timeutils import local_date_str, today_local_str

logger = get_logger("recap")

# Milestone ladder for active streaks; a card fires only for the highest
# rung reached so long streaks don't re-fire smaller badges.
STREAK_MILESTONES: Tuple[int, ...] = (7, 30, 100)

# Composite best-shot scoring references (quality.py calibration):
# blur scores land in the thousands for sharp frames; brightness is a
# grayscale mean whose ideal sits near mid-gray (128).
# Cross-resolution caveat: variance-of-Laplacian scales with capture
# resolution/compression, so composites are comparable only within the
# same capture resolution.
BLUR_REF_SCORE = 1000.0
MID_GRAY = 128.0
SHARPNESS_WEIGHT = 0.6
EXPOSURE_WEIGHT = 0.4

MOOD_ORDER = ("Awful", "Bad", "Neutral", "Good", "Great")

# Gates
MOOD_MIN_SAMPLES = 5
TIME_PATTERN_MIN_SAMPLES = 10
TIME_PATTERN_MIN_CONSISTENCY = 0.5


@dataclass(frozen=True)
class Highlight:
    kind: str
    title: str
    subtitle: str = ""
    value: str = ""
    date_range: str = ""
    score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------
def _resolve_today(today=None) -> date_cls:
    if today is None:
        today = today_local_str()
    if isinstance(today, datetime):
        today = (today if today.tzinfo is None else today.astimezone()).date()
    if isinstance(today, date_cls):
        return today
    return datetime.strptime(str(today), "%Y-%m-%d").date()


def _parse_day(s: str) -> Optional[date_cls]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _month_bounds(year: int, month: int) -> Tuple[str, str]:
    start = date_cls(year, month, 1)
    end = date_cls(year + 1, 1, 1) if month == 12 else date_cls(year, month + 1, 1)
    return start.isoformat(), (end - timedelta(days=1)).isoformat()


def _year_bounds(year: int) -> Tuple[str, str]:
    return f"{year:04d}-01-01", f"{year:04d}-12-31"


# ---------------------------------------------------------------
# Computers (pure functions -> List[Highlight])
# ---------------------------------------------------------------
def streak_milestones(dates: Sequence[str], today=None) -> List[Highlight]:
    """Active-streak milestone cards (7/30/100) plus a new-record badge.

    No-refire: only the highest reached rung emits a card, and at most one
    record badge per computation (this function is stateless) while the
    current streak IS the all-time best.
    """
    t = _resolve_today(today)
    # calculate_streaks expects a datetime (naive is taken as-is)
    current, best, has_today = calculate_streaks(
        list(dates), today=datetime(t.year, t.month, t.day)
    )
    out: List[Highlight] = []
    if current <= 0:
        return out
    reached = [m for m in STREAK_MILESTONES if current >= m]
    if reached:
        m = max(reached)
        out.append(Highlight(
            kind="streak_milestone",
            title=f"{m}-day streak",
            subtitle=f"Current streak: {current} days",
            value=str(m),
            score=float(m),
        ))
    if has_today and current >= best and best > 0:
        out.append(Highlight(
            kind="streak_record",
            title="New personal record",
            subtitle=f"{current} days and counting",
            value=str(current),
            score=float(current) + 1.0,
        ))
    return out


def throwbacks(stamps: Sequence[str], today=None) -> List[Highlight]:
    """Captures from this calendar day (MM-DD) in previous years.

    Newest-first, today itself excluded; stamps are raw UTC ts strings
    bucketed via timeutils.local_date_str.
    """
    t = _resolve_today(today)
    md = f"{t.month:02d}-{t.day:02d}"
    hits: List[Tuple[str, str]] = []  # (local_date, ts_string)
    for ts in stamps or []:
        d = local_date_str(ts)
        if not d or d == t.isoformat():
            continue
        if d[5:] == md:
            hits.append((d, ts))
    hits.sort(key=lambda x: x[0], reverse=True)
    out: List[Highlight] = []
    for d, _ts in hits:
        years_ago = t.year - int(d[:4])
        unit = "year" if years_ago == 1 else "years"
        out.append(Highlight(
            kind="throwback",
            title=f"{years_ago} {unit} ago today",
            subtitle=d,
            value=d,
            date_range=d,
            score=float(years_ago),
        ))
    return out


def best_shot_composite(blur_score: float, brightness: float) -> float:
    """Sharpness + exposure composite in [0, 100].

    Sharpness saturates at BLUR_REF_SCORE variance-of-Laplacian; exposure is
    closeness to mid-gray. Deterministic and JSON-safe.
    """
    sharpness = min(max(blur_score, 0.0) / BLUR_REF_SCORE, 1.0)
    exposure = 1.0 - min(max(abs(brightness - MID_GRAY) / MID_GRAY, 0.0), 1.0)
    return round((SHARPNESS_WEIGHT * sharpness + EXPOSURE_WEIGHT * exposure) * 100.0, 1)


def best_shot_ranking(rows: Sequence[Dict[str, Any]], top_n: int = 3) -> List[Highlight]:
    """Rank captures by composite quality; rows missing either metric skip."""
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for row in rows or []:
        b, br = row.get("blur_score"), row.get("brightness")
        if b is None or br is None:
            continue
        comp = best_shot_composite(float(b), float(br))
        scored.append((comp, row))
    scored.sort(key=lambda x: (-x[0], str(x[1].get("ts") or ""), str(x[1].get("id") or "")))
    out: List[Highlight] = []
    for rank, (comp, row) in enumerate(scored[: max(0, int(top_n))], 1):
        eid = str(row.get("id") or "")
        out.append(Highlight(
            kind="best_shot",
            title=f"#{rank} sharpest shot",
            subtitle=eid,
            value=eid,
            date_range=local_date_str(row.get("ts")) or "",
            score=comp,
        ))
    return out


def _dominant_mood(entries: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Most frequent mood; ties break toward the most recent occurrence."""
    if not entries:
        return None
    counts: Counter = Counter(e["mood"] for e in entries)
    last_index = {}
    for i, e in enumerate(entries):
        last_index[e["mood"]] = i
    return max(sorted(counts), key=lambda m: (counts[m], last_index[m]))


def mood_trends(moods: Sequence[Dict[str, Any]], window_days: int = 30,
                today=None) -> List[Highlight]:
    """Dominant mood over the recent window vs the equal prior window.

    Gate: needs >= MOOD_MIN_SAMPLES entries inside the recent window.
    Entries are {'date': 'YYYY-MM-DD', 'mood': str}, any order.
    """
    t = _resolve_today(today)
    recent_start = t - timedelta(days=int(window_days) - 1)
    prior_start = recent_start - timedelta(days=int(window_days))
    rs, ps = recent_start.isoformat(), prior_start.isoformat()

    recent, prior = [], []
    for e in moods or []:
        d = e.get("date")
        m = e.get("mood")
        if not d or m is None:
            continue
        if rs <= d <= t.isoformat():
            recent.append({"date": d, "mood": m})
        elif ps <= d < rs:
            prior.append({"date": d, "mood": m})

    if len(recent) < MOOD_MIN_SAMPLES:
        return []

    dom = _dominant_mood(recent)
    dom_count = sum(1 for e in recent if e["mood"] == dom)
    share = round(dom_count / len(recent), 3)

    subtitle = ""
    prev_dom = _dominant_mood(prior) if len(prior) >= MOOD_MIN_SAMPLES else None
    if prev_dom is not None and prev_dom != dom:
        arrow = "Up" if MOOD_ORDER.index(dom) > MOOD_ORDER.index(prev_dom) else "Down"
        subtitle = f"{arrow} from {prev_dom}"
    elif prev_dom is not None:
        subtitle = "Steady"
    else:
        subtitle = "No earlier trend window"

    return [Highlight(
        kind="mood_trend",
        title=f"Dominant mood: {dom}",
        subtitle=subtitle,
        value=str(dom),
        date_range=f"{rs}..{t.isoformat()}",
        score=share,
    )]


def time_of_day_patterns(hours: Sequence[int]) -> List[Highlight]:
    """Usual capture hour card.

    Modal hour of LOCAL-hour ints; gated on n >= TIME_PATTERN_MIN_SAMPLES and
    modal consistency >= TIME_PATTERN_MIN_CONSISTENCY.
    """
    vals = [h for h in (hours or []) if isinstance(h, int)]
    n = len(vals)
    if n < TIME_PATTERN_MIN_SAMPLES:
        return []
    counts: Counter = Counter(vals)
    modal_hour = min(k for k, c in counts.items() if c == max(counts.values()))
    consistency = counts[modal_hour] / n
    if consistency < TIME_PATTERN_MIN_CONSISTENCY:
        return []
    pct = int(round(consistency * 100))
    return [Highlight(
        kind="time_pattern",
        title=f"Usually around {modal_hour:02d}:00",
        subtitle=f"{n} captures analyzed",
        value=f"{pct}% of captures",
        score=round(consistency, 3),
    )]


def activity_recaps(dates: Sequence[str], today=None) -> List[Highlight]:
    """One activity card: total days, largest interior gap, consistency %.

    Span runs from the first capture through today (inclusive), so the
    consistency share decays honestly through inactive stretches.
    """
    days = sorted(d for d in (_parse_day(x) for x in (dates or [])) if d is not None)
    if not days:
        return []
    t = _resolve_today(today)
    first, last = days[0], days[-1]
    span_days = max((t - first).days + 1, len(days))
    gaps = [(b - a).days - 1 for a, b in zip(days, days[1:]) if b > a]
    interior_gap = max(gaps) if gaps else 0
    consistency_pct = round(len(days) / span_days * 100.0, 1)

    gap_txt = f"{interior_gap}-day longest gap" if interior_gap > 0 else "No missed days"
    return [Highlight(
        kind="activity",
        title=f"{len(days)} active days",
        subtitle=gap_txt,
        value=f"{consistency_pct}% consistent",
        date_range=f"{first.isoformat()}..{last.isoformat()}",
        score=round(consistency_pct / 100.0, 3),
    )]


# ---------------------------------------------------------------
# Aggregators
# ---------------------------------------------------------------
def _period(scope: str, target: Any, today_d: date_cls) -> Tuple[Optional[int], Optional[int]]:
    """Resolve (year, month) for a scope; (None, None) means all history."""
    scope = (scope or "all").lower()
    if scope == "month":
        if isinstance(target, (tuple, list)) and len(target) >= 2:
            return int(target[0]), int(target[1])
        if target is not None:
            t = _resolve_today(target)
            return t.year, t.month
        return today_d.year, today_d.month
    if scope == "year":
        if target is None:
            return today_d.year, None
        if isinstance(target, (tuple, list)):
            return int(target[0]), None
        return int(target), None
    return None, None


def _window_for(scope: str, year: Optional[int], month: Optional[int],
                today_d: date_cls) -> Tuple[str, str]:
    if year is None:
        return "0001-01-01", today_d.isoformat()
    if month is not None:
        return _month_bounds(year, month)
    return _year_bounds(year)


def compute_highlights(api, scope: str = "all", target: Any = None,
                       today=None, top_n: int = 12) -> List[Highlight]:
    """
    All highlight cards for a scope, score-descending, capped at top_n.

    Whole-history signals (streaks, throwbacks) always consider full
    history; content signals (best shots, mood, hours, activity) respect
    the period. Results memoize in api.highlights_cache keyed
    (scope, target) with generation-based invalidation.
    """
    cache = getattr(api, "highlights_cache", None)
    generation = getattr(api, "generation", 0)
    key_target = tuple(target) if isinstance(target, (list, tuple)) else target
    if cache is not None:
        cached = cache.get(scope, key_target, generation)
        if cached is not None:
            return list(cached[: max(0, int(top_n))])

    today_d = _resolve_today(today)
    year, month = _period(scope, target, today_d)
    win_start, win_end = _window_for(scope, year, month, today_d)

    highlights: List[Highlight] = []

    dates_all = api.get_all_capture_dates()
    highlights += streak_milestones(dates_all, today=today_d)
    highlights += throwbacks(api.get_all_capture_stamps(), today=today_d)

    scoped_rows = api.get_rows_with_quality(year, month)
    highlights += best_shot_ranking(scoped_rows, top_n=min(int(top_n), 3))

    scoped_dates = [d for d in dates_all if win_start <= d <= win_end]
    highlights += activity_recaps(
        scoped_dates,
        today=min(today_d, _parse_day(win_end) or today_d),
    )

    try:
        moods = api.get_moods_between(win_start, win_end)
        highlights += mood_trends(moods, today=today_d)
    except Exception:
        logger.debug("mood_trends skipped", exc_info=True)

    try:
        hours = api.get_capture_times_between(win_start, win_end)
        highlights += time_of_day_patterns(hours)
    except Exception:
        logger.debug("time_of_day_patterns skipped", exc_info=True)

    highlights.sort(key=lambda h: (-h.score, h.kind, h.title))
    if cache is not None:
        cache.put(scope, key_target, generation, list(highlights))
    return highlights[: max(0, int(top_n))]


def build_recap_stats(api, year: int, month: Optional[int] = None,
                      today=None) -> Dict[str, Any]:
    """JSON-safe recap snapshot for one month (or whole year).

    Scope follows the arguments exactly (no implicit 'today' fallback):
    month given -> that month; else the whole year.
    """
    today_d = _resolve_today(today)
    win_start, win_end = _month_bounds(year, month) if month else _year_bounds(year)

    dates_all = api.get_all_capture_dates()
    scoped_dates = [d for d in dates_all if win_start <= d <= win_end]
    rows_scoped = api.get_rows_with_quality(year, month)

    # Consistency spans from each period's first capture through its last
    # day (end of month / Dec 31), capped at today.
    period_end = min(_parse_day(win_end) or today_d, today_d)
    consistency_pct = None
    if scoped_dates:
        first = _parse_day(scoped_dates[0])
        span = max((period_end - first).days + 1, len(scoped_dates))
        consistency_pct = round(len(scoped_dates) / span * 100.0, 1)

    current, best, has_today = calculate_streaks(
        dates_all, today=datetime(today_d.year, today_d.month, today_d.day)
    )

    moods = api.get_moods_between(win_start, win_end)
    distribution: Dict[str, int] = dict(sorted(Counter(
        m["mood"] for m in moods if m.get("mood") is not None
    ).items()))

    hours = api.get_capture_times_between(win_start, win_end)
    favorite_hour: Optional[int] = None
    if hours:
        hc = Counter(hours)
        favorite_hour = min(k for k, c in hc.items() if c == max(hc.values()))

    top_shots = [
        {"id": h.value, "score": h.score}
        for h in best_shot_ranking(rows_scoped, top_n=3)
    ]

    tb = throwbacks(api.get_all_capture_stamps(), today=today_d)
    throwback_eid = tb[0].value if tb else None

    highlights = [h.to_dict() for h in compute_highlights(
        api,
        "month" if month else "year",
        (year, month) if month else year,
        today=today_d,
    )]
    milestone_kinds = ("streak_milestone", "streak_record")
    milestones = [h["title"] for h in highlights if h["kind"] in milestone_kinds]

    dominant = _dominant_mood([{"date": m["date"], "mood": m["mood"]}
                               for m in moods if m.get("mood") is not None])

    return {
        "scope": "month" if month else "year",
        "year": int(year),
        "month": int(month) if month else None,
        "captures_total": len(rows_scoped),
        "active_days": len(scoped_dates),
        "consistency_pct": consistency_pct,
        "streaks": {
            "current": current,
            "best": best,
            "has_photo_today": has_today,
        },
        "milestones": milestones,
        "dominant_mood": dominant,
        "distribution": distribution,
        "favorite_hour": favorite_hour,
        "top_shots": top_shots,
        "throwback_eid": throwback_eid,
        "highlights": highlights,
    }


# ---------------------------------------------------------------
# Quality backfill
# ---------------------------------------------------------------
def backfill_quality(api, batch_size: int = 50, max_batches: Optional[int] = None,
                     logger=None) -> Dict[str, int]:
    """
    Assess quality metrics for capture rows still missing them.

    Reads each row's photo file, scores it via core.quality.assess_image_
    quality and UPDATEs the row in batches. Rows whose file is missing or
    undecodable stay NULL (skipped); re-runs are therefore idempotent.
    When any row was updated, the API change counter is bumped so memoized
    highlight caches are invalidated.
    Returns {"updated": N, "batches": N, "skipped_missing": N}.
    """
    from core.quality import assess_image_quality

    log = logger or get_logger("recap.backfill")
    idx = api._ensure_indexer()
    updated = skipped_missing = batches = 0
    offset = 0
    batch_size = max(1, int(batch_size))
    while True:
        rows = idx._conn.execute(
            """
            SELECT id, path FROM captures
            WHERE action='capture' AND blur_score IS NULL
            ORDER BY ts ASC
            LIMIT ? OFFSET ?
            """,
            (batch_size, offset),
        ).fetchall()
        if not rows:
            break
        offset += len(rows)
        batches += 1
        for row in rows:
            p = Path(row["path"]) if row["path"] else None
            if p is None or not p.is_file():
                skipped_missing += 1
                continue
            try:
                qm = assess_image_quality(p.read_bytes())
            except Exception:
                skipped_missing += 1
                continue
            if qm.get("blur_score") is None:
                # Undecodable bytes: leave NULL rather than guess.
                continue
            idx.update_quality(row["id"], qm["blur_score"], qm["brightness"])
            updated += 1
        log.info("backfill_quality_batch", extra={"meta": {
            "batch": batches, "updated": updated,
            "skipped_missing": skipped_missing,
        }})
        if max_batches is not None and batches >= max(0, int(max_batches)):
            break
        if len(rows) < batch_size:
            break
    if updated and hasattr(api, "_notify_changed"):
        api._notify_changed()
    log.info("backfill_quality_done", extra={"meta": {
        "updated": updated, "batches": batches,
        "skipped_missing": skipped_missing,
    }})
    return {"updated": updated, "batches": batches, "skipped_missing": skipped_missing}
