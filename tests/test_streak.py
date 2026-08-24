"""
Streak calculation semantics: current/best/at-risk, synthetic local dates.
Deterministic: every case passes an explicit `today` (naive local date).
"""
import pytest
from datetime import datetime, timedelta

from core.streak import calculate_streaks

pytestmark = pytest.mark.core_only  # fast/offline core data-layer tests

D = datetime(2026, 8, 24)


def _days_ago(n):
    return (D - timedelta(days=n)).strftime("%Y-%m-%d")


TODAY = D.strftime("%Y-%m-%d")


def test_empty_input_zero_everything():
    assert calculate_streaks([], today=D) == (0, 0, False)


def test_today_captured_counts_from_today():
    dates = [_days_ago(2), _days_ago(1), TODAY]
    assert calculate_streaks(dates, today=D) == (3, 3, True)


def test_no_photo_today_at_risk_counts_from_yesterday():
    dates = [_days_ago(2), _days_ago(1)]
    current, best, has_today = calculate_streaks(dates, today=D)
    assert has_today is False
    assert current == 2
    assert best == 2


def test_yesterday_only_gap_breaks_current_but_keeps_best():
    dates = [_days_ago(3), _days_ago(2)]
    current, best, has_today = calculate_streaks(dates, today=D)
    assert current == 0
    assert best == 2
    assert has_today is False


def test_long_run_of_thirty_days():
    dates = [_days_ago(n) for n in range(30)]
    assert calculate_streaks(dates, today=D) == (30, 30, True)


def test_best_exceeds_current_historical_run():
    dates = [_days_ago(n) for n in range(6, 11)] + [TODAY]
    current, best, has_today = calculate_streaks(dates, today=D)
    assert (current, best, has_today) == (1, 5, True)


def test_malformed_date_strings_are_skipped():
    dates = ["not-a-date", "", "2026-13-99", _days_ago(1), TODAY]
    assert calculate_streaks(dates, today=D) == (2, 2, True)


def test_unsorted_input_is_fine_for_best_and_current():
    dates = [TODAY, _days_ago(2), _days_ago(1)]
    assert calculate_streaks(dates, today=D) == (3, 3, True)


def test_aware_today_local_midnight_is_accepted():
    aware_local_midnight = datetime.strptime(TODAY, "%Y-%m-%d").astimezone()
    assert calculate_streaks([TODAY], today=aware_local_midnight) == (1, 1, True)


def test_single_day_no_neighbors():
    assert calculate_streaks([_days_ago(5)], today=D) == (0, 1, False)
