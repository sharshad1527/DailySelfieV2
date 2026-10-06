"""
Day-bucketing time helpers: UTC ts -> LOCAL date conversions under controlled
timezones, malformed-input tolerance, and filename/prefix helpers.
"""
import os
import re
from datetime import datetime, timezone, tzinfo
from pathlib import Path

import pytest

from core.timeutils import (
    clear_local_tz,
    current_tz,
    filename_stem_local_date,
    get_tz,
    local_date_str,
    local_day_utc_prefixes,
    set_local_tz,
    today_local_str,
)

pytestmark = pytest.mark.core_only  # fast/offline core data-layer tests


class TestExplicitTimezoneArgument:
    """Every helper accepts an explicit tz and honours it without any global state.

    These tests are the cross-platform contract: they never touch os.environ['TZ']
    or time.tzset, so they assert exactly the same thing on Windows as on Linux.
    """

    def test_explicit_tz_overrides_the_default(self, set_tz):
        set_tz("Asia/Kolkata")
        assert local_date_str("2026-08-23T20:30:00Z", tz="UTC") == "2026-08-23"
        assert local_date_str("2026-08-23T20:30:00Z", tz="Asia/Kolkata") == "2026-08-24"

    def test_explicit_tz_works_with_the_default_unset(self):
        assert local_date_str("2026-08-23T20:30:00Z", tz="America/New_York") == "2026-08-23"
        assert local_date_str("2026-08-23T02:30:00Z", tz="America/New_York") == "2026-08-22"

    def test_tzinfo_instance_is_accepted(self):
        from datetime import timezone, timedelta as td
        assert local_date_str("2026-08-23T20:30:00Z", tz=timezone(td(hours=2))) == "2026-08-23"
        assert local_date_str("2026-08-23T20:30:00Z", tz=timezone(td(hours=-7))) == "2026-08-23"
        assert local_date_str("2026-08-23T01:30:00Z", tz=timezone(td(hours=-7))) == "2026-08-22"

    def test_today_local_str_accepts_tz(self, set_tz):
        set_tz("UTC")
        kolkata = today_local_str(tz="Asia/Kolkata")
        utc = today_local_str(tz="UTC")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", kolkata)
        # Kolkata is UTC+5:30, so its "today" is never earlier than UTC's.
        assert kolkata >= utc

    def test_filename_stem_accepts_tz(self, set_tz):
        set_tz("UTC")
        assert filename_stem_local_date("2026-08-23_190000", tz="Asia/Kolkata") == "2026-08-24"
        assert filename_stem_local_date("2026-08-23_190000", tz="UTC") == "2026-08-23"

    def test_prefixes_accept_tz(self, set_tz):
        set_tz("UTC")
        assert local_day_utc_prefixes("2026-08-24", tz="UTC") == ["2026-08-24"]
        assert local_day_utc_prefixes("2026-08-24", tz="Asia/Kolkata") == [
            "2026-08-23",
            "2026-08-24",
        ]
        assert local_day_utc_prefixes("2026-08-24", tz="Pacific/Pago_Pago") == [
            "2026-08-24",
            "2026-08-25",
        ]

    def test_invalid_day_still_returns_empty_with_explicit_tz(self):
        assert local_day_utc_prefixes("junk", tz="Asia/Kolkata") == []

    def test_malformed_ts_still_returns_none_with_explicit_tz(self):
        assert local_date_str("garbage", tz="Asia/Kolkata") is None

    def test_zone_specific_offset_is_used_not_a_fixed_one(self):
        """A zone's offset *on that date* is used, so DST is handled.

        Pacific/Auckland is UTC+13 in January (NZDT) and UTC+12 in April (NZST).
        2026-01-05T11:00Z is exactly local midnight in Auckland -> Jan 6.
        2026-04-05T11:00Z is 23:00 the same day -> Apr 5.
        """
        from datetime import timedelta as td

        assert local_date_str("2026-01-05T11:00:00Z", tz="Pacific/Auckland") == "2026-01-06"
        assert local_date_str("2026-04-05T11:00:00Z", tz="Pacific/Auckland") == "2026-04-05"

        # Fixed offsets disagree with one of the two zone answers above, which
        # is exactly what proves the zone's own rules were applied.
        assert local_date_str(
            "2026-01-05T11:00:00Z", tz=timezone(td(hours=12))
        ) == "2026-01-05"
        assert local_date_str(
            "2026-04-05T11:00:00Z", tz=timezone(td(hours=13))
        ) == "2026-04-06"

    def test_utc_offset_crossing_day_boundary(self):
        """An explicit negative offset rolls the UTC day back correctly."""
        from datetime import timedelta as td

        assert local_date_str("2026-08-23T02:30:00Z", tz=timezone(td(hours=-7))) == "2026-08-22"
        assert local_date_str("2026-08-23T02:30:00Z", tz=timezone(td(hours=2))) == "2026-08-23"


class TestGetTz:
    def test_none_means_machine_local(self):
        assert get_tz(None) is None

    def test_string_is_resolved_to_zoneinfo(self):
        resolved = get_tz("Asia/Kolkata")
        assert isinstance(resolved, tzinfo)
        assert resolved is not None

    def test_tzinfo_passes_through_unchanged(self):
        value = timezone.utc
        assert get_tz(value) is value

    @pytest.mark.parametrize("bad", ["Not/AZone", "", "Mars/Olympus"])
    def test_unknown_zone_raises_value_error(self, bad):
        with pytest.raises(ValueError):
            get_tz(bad)

    @pytest.mark.parametrize("bad", [123, 4.5, [], object()])
    def test_non_tz_types_raise_value_error(self, bad):
        with pytest.raises(ValueError):
            get_tz(bad)

    def test_utc_is_available_as_a_key(self):
        assert get_tz("UTC") is not None


class TestDefaultOverride:
    @pytest.fixture(autouse=True)
    def _restore_default(self):
        """Never let an override leak into another test."""
        original = current_tz()
        yield
        clear_local_tz()
        if original is not None:
            set_local_tz(original)

    def test_override_changes_the_default_used_by_helpers(self):
        assert current_tz() is None, "the module starts with no override"
        set_local_tz("Asia/Kolkata")

        assert current_tz() is not None
        assert local_date_str("2026-08-23T20:30:00Z") == "2026-08-24"

    def test_clear_restores_machine_local(self):
        set_local_tz("Pacific/Kiritimati")
        assert current_tz() is not None

        clear_local_tz()

        assert current_tz() is None
        # Back to the machine's own zone.
        expected = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
        assert today_local_str() == expected

    def test_set_local_tz_returns_the_resolved_zone(self):
        resolved = set_local_tz("Asia/Kolkata")
        assert isinstance(resolved, tzinfo)
        assert current_tz() is resolved

    def test_set_local_tz_rejects_an_unknown_zone(self):
        with pytest.raises(ValueError):
            set_local_tz("Not/AZone")
        assert current_tz() is None, "a bad zone must not install an override"

    def test_explicit_argument_beats_the_default_override(self):
        set_local_tz("Asia/Kolkata")
        assert local_date_str("2026-08-23T20:30:00Z") == "2026-08-24"
        assert local_date_str("2026-08-23T20:30:00Z", tz="UTC") == "2026-08-23"


class TestWindowsPortability:
    """Guards the regression this refactor exists to prevent.

    If anyone reintroduces a dependency on os.environ['TZ'] / time.tzset, these
    fail. time.tzset is deleted to simulate windows-latest, where it does not
    exist.
    """

    def test_tz_tests_pass_without_time_tzset(self, monkeypatch):
        import time as time_module

        monkeypatch.delenv("TZ", raising=False)
        monkeypatch.delattr(time_module, "tzset", raising=False)
        assert not hasattr(time_module, "tzset"), "this test must simulate Windows"

        # Exactly what the set_tz-parametrised tests rely on, done explicitly.
        set_local_tz("Asia/Kolkata")
        try:
            assert local_date_str("2026-08-23T20:30:00Z") == "2026-08-24"
            assert local_date_str("2026-07-15T03:30:00Z", tz="America/New_York") == "2026-07-14"
            assert local_day_utc_prefixes("2026-08-24") == ["2026-08-23", "2026-08-24"]
            assert filename_stem_local_date("2026-08-23_190000") == "2026-08-24"
        finally:
            clear_local_tz()

    def test_tz_tests_do_not_mutate_the_process_tz(self, set_tz, monkeypatch):
        monkeypatch.delenv("TZ", raising=False)
        set_tz("Asia/Kolkata")
        set_tz("America/New_York")
        assert "TZ" not in os.environ, "the suite must not depend on process-global TZ"

    def test_timeutils_imports_only_stdlib(self):
        """Pre-venv import chain: no third-party, no Qt."""
        import core.timeutils as tu

        source = Path(tu.__file__).read_text(encoding="utf-8")
        forbidden = ("import cv2", "import numpy", "import PySide", "from PySide",
                     "import requests", "import tomli")
        for needle in forbidden:
            assert needle not in source, f"timeutils must not import {needle!r}"


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
