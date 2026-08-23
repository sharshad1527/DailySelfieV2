# gui/dashboard/widgets/calendar_analytics/viz_types.py
"""
Shared types, paint primitives and the year-scoped decoration controller for
the calendar data-viz layer (docs/design/calendar-page.md — Squad B).

MOOD_COLORS hexes are intentionally theme-independent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls, datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from core.streak import calculate_streaks

# Fixed mood hexes (theme-independent by design)
MOOD_COLORS: Dict[str, str] = {
    "Great": "#178A38",
    "Good": "#00848C",
    "Neutral": "#8A7500",
    "Bad": "#A34F00",
    "Awful": "#A62D12",
}

MOOD_ORDER: List[str] = ["Great", "Good", "Neutral", "Bad", "Awful"]


class StreakState(Enum):
    NONE = 0
    CURRENT = 1
    BEST_ONLY = 2
    CURRENT_AND_BEST = 3


class TodayState(Enum):
    NOT_TODAY = 0
    IN_STREAK = 1
    AT_RISK = 2


@dataclass
class DayDecor:
    """Per-day visual decoration computed once per year."""
    mood: Optional[str] = None
    streak: StreakState = StreakState.NONE
    today: TodayState = TodayState.NOT_TODAY
    future: bool = False
    capture_count: int = 0


# -------------------------------------------------------------
# Paint primitives (free functions)
# -------------------------------------------------------------
def paint_mood_dot(painter: QPainter, rect: QRectF, hex: str,
                   outline_color: QColor, d: int = 6) -> None:
    """Solid mood dot of diameter `d` centered in `rect`, mandatory 1px outline halo."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    r = QRectF(0.0, 0.0, float(d), float(d))
    r.moveCenter(rect.center())
    pen = QPen(outline_color)
    pen.setWidthF(1.0)
    painter.setPen(pen)
    painter.setBrush(QColor(hex))
    painter.drawEllipse(r)
    painter.restore()


def paint_streak_ring(painter: QPainter, rect: QRectF, state: StreakState,
                      tertiary: QColor, outline: QColor, inset: float = 2) -> None:
    """
    Streak rings inside `rect`: CURRENT solid tertiary; BEST_ONLY dotted
    outline; CURRENT_AND_BEST both (solid outer ring + dotted inner ring).
    """
    if state == StreakState.NONE:
        return
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)

    def _ring(r_inset: float, color: QColor, dotted: bool):
        pen = QPen(color)
        pen.setWidthF(1.5 if dotted else 2.0)
        if dotted:
            pen.setStyle(Qt.DotLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(r_inset, r_inset, -r_inset, -r_inset), 10, 10)

    if state in (StreakState.CURRENT, StreakState.CURRENT_AND_BEST):
        _ring(inset, tertiary, dotted=False)
    if state == StreakState.BEST_ONLY:
        _ring(inset, outline, dotted=True)
    elif state == StreakState.CURRENT_AND_BEST:
        _ring(inset + 3, outline, dotted=True)
    painter.restore()


# -------------------------------------------------------------
# Year-scoped decoration controller
# -------------------------------------------------------------
class DecorationController:
    """
    Computes decorations ONCE per year from FULL history.

    calculate_streaks runs over global dates — never month slices — so the
    Dec→Jan best run rings both grids correctly.
    """

    def __init__(self) -> None:
        self._capture_dates: set = set()
        self._moods_by_day: Dict[str, str] = {}
        self._counts_by_day: Dict[str, int] = {}
        self._today: Optional[date_cls] = None
        self._current_set: set = set()
        self._best_set: set = set()
        self._current_len = 0
        self._best_len = 0
        self._has_photo_today = False
        self._year_cache: Dict[int, Dict[str, DayDecor]] = {}

    # ---------------- state updates ----------------
    def update(self, capture_dates: List[str],
               counts_by_day: Optional[Dict[str, int]] = None,
               moods_by_day: Optional[Dict[str, str]] = None,
               today: Optional[date_cls] = None) -> None:
        """Recompute base sets from full history. Malformed dates skipped
        (streak.py precedent)."""
        self._capture_dates = set()
        for ds in capture_dates or []:
            try:
                self._capture_dates.add(datetime.strptime(ds, "%Y-%m-%d").date())
            except ValueError:
                continue
        self._counts_by_day = dict(counts_by_day or {})
        self._moods_by_day = dict(moods_by_day or {})
        self._today = today or datetime.now().date()
        self._compute_runs()
        self._year_cache.clear()

    def _compute_runs(self) -> None:
        today = self._today
        dates = self._capture_dates

        summary = calculate_streaks(sorted(d.isoformat() for d in dates),
                                    datetime(today.year, today.month, today.day))
        self._current_len, self._best_len, self._has_photo_today = summary

        # Current-run membership: walk back from today (or yesterday when no
        # photo yet today) over consecutive captured days.
        self._current_set = set()
        check = today if today in dates else today - timedelta(days=1)
        while check in dates:
            self._current_set.add(check)
            check -= timedelta(days=1)

        # Best-run membership: longest consecutive run across sorted dates.
        self._best_set = set()
        sorted_dates = sorted(dates)
        best_start, best_run = None, 0
        run_start, run = 0, 0
        prev = None
        for i, d in enumerate(sorted_dates):
            if prev is not None and d - prev == timedelta(days=1):
                run += 1
            else:
                run_start, run = i, 1
            if run > best_run:
                best_run, best_start = run, run_start
            prev = d
        if best_start is not None and best_run > 0:
            self._best_set = set(sorted_dates[best_start:best_start + best_run])

        # Live record (current >= best): tiles show solid tertiary only, so
        # suppress the dotted best ring entirely.
        if self._current_len >= self._best_len:
            self._best_set = set()

    # ---------------- summaries ----------------
    def streak_summary(self):
        """(current, best, has_photo_today) — mirrors StreakSummaryWidget."""
        return (self._current_len, self._best_len, self._has_photo_today)

    @property
    def at_risk(self) -> bool:
        return not self._has_photo_today and self._current_len > 0

    @property
    def current_streak(self) -> int:
        return self._current_len

    @property
    def best_streak(self) -> int:
        return self._best_len

    def decors_for_year(self, year: int) -> Dict[str, DayDecor]:
        """Full-year DayDecor map keyed by 'YYYY-MM-DD' (computed once/year)."""
        cached = self._year_cache.get(year)
        if cached is not None:
            return cached

        today = self._today or datetime.now().date()
        out: Dict[str, DayDecor] = {}
        d = date_cls(year, 1, 1)
        while d.year == year:
            ds = d.isoformat()
            if d in self._current_set and d in self._best_set:
                streak = StreakState.CURRENT_AND_BEST
            elif d in self._current_set:
                streak = StreakState.CURRENT
            elif d in self._best_set:
                streak = StreakState.BEST_ONLY
            else:
                streak = StreakState.NONE

            if d == today:
                tstate = TodayState.IN_STREAK if self._has_photo_today else (
                    TodayState.AT_RISK if self.at_risk else TodayState.NOT_TODAY)
            else:
                tstate = TodayState.NOT_TODAY

            mood = self._moods_by_day.get(ds)
            if mood not in MOOD_COLORS:
                mood = None
            out[ds] = DayDecor(
                mood=mood,
                streak=streak,
                today=tstate,
                future=d > today,
                capture_count=int(self._counts_by_day.get(ds, 0)),
            )
            d += timedelta(days=1)

        self._year_cache[year] = out
        return out
