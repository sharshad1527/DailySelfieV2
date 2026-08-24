"""
Day-bucketing time helpers: UTC ts -> LOCAL date conversions under controlled
timezones, malformed-input tolerance, and filename/prefix helpers.
"""
import re
from datetime import datetime, timezone

import pytest

from core.timeutils import (
    filename_stem_local_date,
    local_date_str,
    local_day_utc_prefixes,
    today_local_str,
)

pytestmark = pytest.mark.core_only  # fast/offline core data-layer tests


class TestLocalDateStrTZBoundaries:
    def test_kolkata_late_evening_utc_is_next_day(self, set_tz):
        set_tz("Asia/Kolkata")
        assert local_date_str("2026-08-23T20:30:00Z") == "2026-08-24"

    def test_kolkata_early_utc_is_same_day(self, set_tz):
        set_tz("Asia/Kolkata")
        assert local_date_str("2026-08-24T06:30:00Z") == "2026-08-24"

    def test_new_york_winter_six_utc_is_same_day(self, set_tz):
        set_tz("America/New_York")
        assert local_date_str("2026-01-15T06:00:00Z") == "2026-01-15"

    def test_new_york_summer_early_utc_is_previous_day(self, set_tz):
        set_tz("America/New_York")
        assert local_date_str("2026-07-15T03:30:00Z") == "2026-07-14"

    def test_new_york_summer_six_utc_is_same_day(self, set_tz):
        set_tz("America/New_York")
        assert local_date_str("2026-07-15T06:00:00Z") == "2026-07-15"

    def test_epoch_seconds_input_respects_tz(self, set_tz):
        set_tz("Asia/Kolkata")
        epoch = datetime(2026, 8, 23, 20, 30, tzinfo=timezone.utc).timestamp()
        assert local_date_str(epoch) == "2026-08-24"

    def test_naive_datetime_interpreted_as_utc(self, set_tz):
        set_tz("Asia/Kolkata")
        assert local_date_str(datetime(2026, 8, 23, 20, 30)) == "2026-08-24"

    def test_offset_suffix_string(self, set_tz):
        set_tz("UTC")
        assert local_date_str("2026-08-23T20:30:00+02:00") == "2026-08-23"


def test_malformed_inputs_yield_none():
    for bad in (None, "", "   ", "garbage", "2026-13-45T99:99:99Z", True, object(), [1, 2]):
        assert local_date_str(bad) is None, f"expected None for {bad!r}"


def test_today_local_str_format():
    value = today_local_str()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
    assert value == datetime.now().astimezone().strftime("%Y-%m-%d")


def test_today_local_str_matches_local_date_str_of_now(set_tz):
    set_tz("Pacific/Kiritimati")
    now_utc = datetime.now(timezone.utc)
    assert today_local_str() == local_date_str(now_utc)


class TestFilenameStem:
    def test_utc_stem_converts_to_local_day(self, set_tz):
        set_tz("Asia/Kolkata")
        assert filename_stem_local_date("2026-08-23_190000") == "2026-08-24"

    def test_malformed_stem_is_none(self):
        assert filename_stem_local_date("not-a-stem") is None
        assert filename_stem_local_date("2026-02-30_120000") is None
        assert filename_stem_local_date(None) is None
        assert filename_stem_local_date(12345) is None


class TestLocalDayUtcPrefixes:
    def test_utc_zone_single_prefix(self, set_tz):
        set_tz("UTC")
        assert local_day_utc_prefixes("2026-08-24") == ["2026-08-24"]

    def test_positive_offset_spans_two_utc_dates(self, set_tz):
        set_tz("Asia/Kolkata")
        assert local_day_utc_prefixes("2026-08-24") == ["2026-08-23", "2026-08-24"]

    def test_negative_offset_spans_two_utc_dates(self, set_tz):
        set_tz("Pacific/Pago_Pago")
        assert local_day_utc_prefixes("2026-08-24") == ["2026-08-24", "2026-08-25"]

    def test_invalid_day_returns_empty(self):
        assert local_day_utc_prefixes("junk-day") == []
        assert local_day_utc_prefixes("") == []
