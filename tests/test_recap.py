"""
Recap analytics: highlight computers (math + gates), aggregators (scope,
sort, top_n, cache invalidation), build_recap_stats sanity on rich and
sparse data, local-hour bucketing, and quality backfill idempotency.
"""
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import core.recap as recap
from core.index_api import IndexAPI
from core.recap import (
    Highlight,
    activity_recaps,
    backfill_quality,
    best_shot_composite,
    best_shot_ranking,
    build_recap_stats,
    compute_highlights,
    mood_trends,
    streak_milestones,
    throwbacks,
    time_of_day_patterns,
)

pytestmark = pytest.mark.core_only  # fast/offline core data-layer tests

TODAY = date(2026, 8, 25)


def _days_back(n, end=TODAY):
    """n consecutive LOCAL days ending at `end` (inclusive), oldest first."""
    return [(end - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def _utc_ts(local_day, hour=6, minute=30):
    naive = datetime.strptime(local_day, "%Y-%m-%d").replace(hour=hour, minute=minute)
    return naive.astimezone().astimezone(timezone.utc).isoformat()


def _make_api(tmp_path):
    api = IndexAPI(SimpleNamespace(data_dir=tmp_path / "data"))
    api.init()
    return api


def _seed(api, local_day, *, hour=6, minute=30, mood=None, blur=None, bright=None):
    ts = _utc_ts(local_day, hour, minute)
    eid = f"{local_day}_{hour:02d}{minute:02d}00"
    entry = {
        "id": eid,
        "ts": ts,
        "path": f"/photos/{eid}.jpg",
        "width": 100,
        "height": 100,
        "resolution": "100x100",
        "mood": mood,
        "notes": None,
        "action": "capture",
    }
    if blur is not None:
        entry["blur_score"] = blur
    if bright is not None:
        entry["brightness"] = bright
    api.record_capture(entry)
    return eid


class TestStreakMilestones:
    def test_highest_rung_only_plus_record(self):
        cards = streak_milestones(_days_back(35), today=TODAY)
        kinds = [c.kind for c in cards]
        assert "streak_milestone" in kinds and "streak_record" in kinds
        milestone = next(c for c in cards if c.kind == "streak_milestone")
        assert milestone.value == "30" and milestone.title == "30-day streak"
        assert not any(c.value == "7" for c in cards)  # no-refire of smaller rungs

    def test_seven_day_band_fires_for_10_day_streak(self):
        cards = streak_milestones(_days_back(10), today=TODAY)
        assert [c.title for c in cards if c.kind == "streak_milestone"] == ["7-day streak"]

    def test_no_cards_when_streak_cold(self):
        stale = [(TODAY - timedelta(days=d)).isoformat() for d in range(60, 40, -1)]
        assert streak_milestones(stale, today=TODAY) == []
        assert streak_milestones([], today=TODAY) == []

    def test_record_requires_photo_today(self):
        ending_yesterday = _days_back(30, end=TODAY - timedelta(days=1))
        cards = streak_milestones(ending_yesterday, today=TODAY)
        assert [c.kind for c in cards] == ["streak_milestone"]


class TestThrowbacks:
    def test_prior_years_newest_first_excluding_today(self, set_tz):
        set_tz("UTC")
        stamps = [
            _utc_ts("2024-08-26"),          # wrong MM-DD
            _utc_ts("2024-08-25"),          # 2 years ago
            _utc_ts("2025-08-25"),          # 1 year ago
            _utc_ts("2026-08-25"),          # today -> excluded
        ]
        cards = throwbacks(stamps, today=TODAY)
        assert [(c.value, c.title, c.score) for c in cards] == [
            ("2025-08-25", "1 year ago today", 1.0),
            ("2024-08-25", "2 years ago today", 2.0),
        ]

    def test_malformed_and_empty_input(self):
        assert throwbacks(["garbage", None, ""], today=TODAY) == []
        assert throwbacks([], today=TODAY) == []


class TestBestShotRanking:
    def test_composite_math_exact(self):
        assert best_shot_composite(1000.0, 128.0) == 100.0   # sharp + mid-gray
        assert best_shot_composite(500.0, 64.0) == 50.0      # half sharp, half exposure
        assert best_shot_composite(2000.0, 255.0) == 60.3    # sharpness capped; blown out
        assert best_shot_composite(0.0, 0.0) == 0.0
        assert best_shot_composite(-50.0, 999.0) == 0.0      # clamped to zero on both axes

    def test_ranking_skips_nulls_and_respects_top_n(self):
        rows = [
            {"id": "a", "ts": _utc_ts("2026-08-01", 6), "blur_score": 1200.0, "brightness": 128.0},
            {"id": "b", "ts": _utc_ts("2026-08-02", 6), "blur_score": 600.0, "brightness": 100.0},
            {"id": "c", "ts": _utc_ts("2026-08-03", 6), "blur_score": None, "brightness": 128.0},
            {"id": "d", "ts": _utc_ts("2026-08-04", 6), "blur_score": 300.0, "brightness": None},
            {"id": "e", "ts": _utc_ts("2026-08-05", 6), "blur_score": 300.0, "brightness": 150.0},
        ]
        ranked = best_shot_ranking(rows, top_n=2)
        assert [h.value for h in ranked] == ["a", "b"]
        assert all(h.kind == "best_shot" for h in ranked)
        full = best_shot_ranking(rows, top_n=3)
        assert [h.value for h in full] == ["a", "b", "e"]

    def test_empty_rows(self):
        assert best_shot_ranking([], top_n=3) == []


class TestMoodTrends:
    def _entries_from_days(self, day_mood_pairs):
        return [{"date": d, "mood": m} for d, m in day_mood_pairs]

    def test_gate_needs_five_recent_samples(self):
        few = self._entries_from_days(list(zip(_days_back(4), ["Good"] * 4)))
        assert mood_trends(few, today=TODAY) == []

    def test_dominant_with_shift_down_vs_prior_window(self):
        prior = list(zip(
            [(TODAY - timedelta(days=d)).isoformat() for d in range(40, 34, -1)],
            ["Great"] * 6,
        ))
        recent = list(zip(_days_back(10), ["Neutral"] * 9 + ["Good"]))
        cards = mood_trends(self._entries_from_days(prior + recent), today=TODAY)
        assert len(cards) == 1
        card = cards[0]
        assert card.title == "Dominant mood: Neutral"
        assert card.subtitle == "Down from Great"
        assert card.score == pytest.approx(0.9)

    def test_tie_breaks_toward_most_recent_mood(self):
        recent = list(zip(_days_back(7), ["Good"] * 3 + ["Bad"] + ["Neutral"] * 3))
        cards = mood_trends(self._entries_from_days(recent), today=TODAY)
        assert cards[0].value == "Neutral"

    def test_steady_when_prior_matches(self):
        prior = list(zip(
            [(TODAY - timedelta(days=d)).isoformat() for d in range(40, 34, -1)],
            ["Good"] * 6,
        ))
        recent = list(zip(_days_back(6), ["Good"] * 6))
        cards = mood_trends(self._entries_from_days(prior + recent), today=TODAY)
        assert cards[0].subtitle == "Steady"


class TestTimeOfDayPatterns:
    def test_modal_hour_with_minimum_consistency(self):
        cards = time_of_day_patterns([8] * 6 + [7] * 4)
        assert len(cards) == 1
        assert cards[0].title == "Usually around 08:00"
        assert cards[0].score == pytest.approx(0.6)

    def test_exact_half_consistency_passes(self):
        cards = time_of_day_patterns([7] * 5 + [8] * 5)
        assert cards[0].title == "Usually around 07:00"  # tie -> earliest hour

    def test_gates_below_thresholds(self):
        assert time_of_day_patterns([7] * 9) == []                      # n < 10
        assert time_of_day_patterns([7] * 4 + [8] * 3 + [9] * 3) == []  # consistency < 0.5
        assert time_of_day_patterns([]) == []


class TestActivityRecaps:
    def test_consecutive_days_full_consistency(self):
        days = _days_back(20)
        cards = activity_recaps(days, today=TODAY)
        card = cards[0]
        assert card.kind == "activity"
        assert card.title == "20 active days"
        assert card.subtitle == "No missed days"
        assert card.value == "100.0% consistent"

    def test_interior_gap_detected(self):
        days = _days_back(20)
        del days[10]  # one missed day inside the span
        card = activity_recaps(days, today=TODAY)[0]
        assert card.subtitle == "1-day longest gap"
        assert card.value == "95.0% consistent"  # 19/20

    def test_sparse_history_spans_to_today(self):
        first = (TODAY - timedelta(days=400)).isoformat()
        last = (TODAY - timedelta(days=200)).isoformat()
        card = activity_recaps([first, last], today=TODAY)[0]
        span = (TODAY - date(2025, 7, 22)).days + 1
        expected = round(2 / span * 100, 1)
        assert card.date_range == f"{first}..{last}"
        assert card.value == f"{expected}% consistent"

    def test_empty_dates(self):
        assert activity_recaps([], today=TODAY) == []


class TestComputeHighlights:
    @pytest.fixture()
    def seeded_api(self, tmp_path, set_tz):
        set_tz("Asia/Kolkata")  # must precede seeding so UTC stamps are deterministic
        api = _make_api(tmp_path)
        eids = {}
        for i, day in enumerate(_days_back(12)):
            if i == 11:
                blur, bright, mood = 1200.0, 128.0, "Good"
            elif i % 2 == 1:
                blur, bright, mood = 600.0, 100.0, "Neutral"
            else:
                blur, bright, mood = 300.0, 150.0, "Neutral"
            eids[day] = _seed(api, day, hour=6, mood=mood, blur=blur, bright=bright)
        yield api, eids
        api.close()

    def test_month_scope_kinds_sorted_and_capped(self, seeded_api):
        api, eids = seeded_api
        cards = compute_highlights(api, "month", (2026, 8), today=TODAY, top_n=12)

        kinds = {c.kind for c in cards}
        assert {"streak_record", "streak_milestone", "best_shot",
                "mood_trend", "time_pattern", "activity"} <= kinds
        assert all(isinstance(c, Highlight) for c in cards)
        scores = [c.score for c in cards]
        assert scores == sorted(scores, reverse=True)

        best = [c for c in cards if c.kind == "best_shot"]
        assert len(best) == 3
        sharpest_day = _days_back(12)[-1]
        assert best[0].value == eids[sharpest_day]

        capped = compute_highlights(api, "month", (2026, 8), today=TODAY, top_n=3)
        assert len(capped) == 3
        # The perfect-composite shot (score 100) outranks every other card
        assert capped[0].kind == "best_shot"
        assert capped[0].value == eids[sharpest_day]

    def test_cache_hit_until_write_bumps_generation(self, seeded_api, monkeypatch):
        api, eids = seeded_api
        calls = {"n": 0}
        original = recap.streak_milestones

        def counting(dates, today=None):
            calls["n"] += 1
            return original(dates, today=today)

        monkeypatch.setattr(recap, "streak_milestones", counting)

        first = compute_highlights(api, "month", (2026, 8), today=TODAY)
        second = compute_highlights(api, "month", (2026, 8), today=TODAY)
        assert calls["n"] == 1  # served from HighlightsCache
        assert first == second

        api.record_deletion(next(iter(eids.values())), reason="test")
        third = compute_highlights(api, "month", (2026, 8), today=TODAY)
        assert calls["n"] == 2  # generation bump invalidated the cache
        assert all(c.value != next(iter(eids.values())) for c in third)

    def test_all_scope_uses_whole_history(self, seeded_api):
        api, _ = seeded_api
        cards = compute_highlights(api, "all", today=TODAY, top_n=12)
        assert any(c.kind == "streak_milestone" for c in cards)

    def test_past_month_activity_spans_through_window_end(self, tmp_path, set_tz):
        set_tz("Asia/Kolkata")
        api = _make_api(tmp_path)
        try:
            for d in range(1, 32):
                _seed(api, f"2026-07-{d:02d}", hour=6, blur=10.0, bright=128.0)

            # Queried from August: consistency must be measured through the
            # window end (Jul 31), not diluted across the inactive Aug 1-25.
            cards = compute_highlights(api, "month", (2026, 7), today=TODAY)
            act = next(c for c in cards if c.kind == "activity")
            assert act.date_range == "2026-07-01..2026-07-31"
            assert act.value == "100.0% consistent"   # 31/31, span capped at Jul 31
        finally:
            api.close()


class TestBuildRecapStats:
    def test_rich_month_stats_are_json_safe(self, tmp_path, set_tz):
        set_tz("Asia/Kolkata")  # must precede seeding so UTC stamps are deterministic
        api = _make_api(tmp_path)
        try:
            for i, day in enumerate(_days_back(12)):
                mood = "Good" if i == 11 else "Neutral"
                _seed(api, day, hour=6, mood=mood, blur=1200.0, bright=128.0)

            stats = build_recap_stats(api, 2026, 8, today=TODAY)

            assert stats["captures_total"] == 12
            assert stats["active_days"] == 12
            assert stats["consistency_pct"] == 100.0
            assert stats["streaks"] == {"current": 12, "best": 12, "has_photo_today": True}
            assert "New personal record" in stats["milestones"]
            assert stats["dominant_mood"] == "Neutral"
            assert stats["distribution"] == {"Good": 1, "Neutral": 11}
            assert stats["favorite_hour"] == 6
            assert stats["top_shots"][0]["score"] == 100.0
            assert stats["throwback_eid"] is None
            assert isinstance(stats["highlights"], list)
            assert all(isinstance(h, dict) for h in stats["highlights"])
            json.dumps(stats)  # must be JSON-safe end to end
        finally:
            api.close()

    def test_year_scope_sums_months(self, tmp_path, set_tz):
        set_tz("Asia/Kolkata")
        api = _make_api(tmp_path)
        try:
            _seed(api, "2026-07-10", hour=7, blur=10.0, bright=10.0)
            _seed(api, "2026-08-10", hour=7, blur=10.0, bright=10.0)
            _seed(api, "2025-01-01", hour=7, blur=10.0, bright=10.0)

            stats = build_recap_stats(api, 2026, today=TODAY)
            assert stats["scope"] == "year"
            assert stats["captures_total"] == 2
            assert stats["month"] is None
        finally:
            api.close()

    def test_sparse_database_yields_safe_defaults(self, tmp_path, set_tz):
        set_tz("Asia/Kolkata")
        api = _make_api(tmp_path)
        try:
            stats = build_recap_stats(api, 2026, 8, today=TODAY)
            assert stats["captures_total"] == 0
            assert stats["active_days"] == 0
            assert stats["consistency_pct"] is None
            assert stats["streaks"] == {"current": 0, "best": 0, "has_photo_today": False}
            assert stats["milestones"] == []
            assert stats["dominant_mood"] is None
            assert stats["distribution"] == {}
            assert stats["favorite_hour"] is None
            assert stats["top_shots"] == []
            assert stats["highlights"] == []
        finally:
            api.close()


class TestLocalHourBucketing:
    def test_capture_times_between_returns_local_hours(self, tmp_path, set_tz):
        set_tz("Asia/Kolkata")  # UTC+05:30
        api = _make_api(tmp_path)
        try:
            idx = api._ensure_indexer()
            # Raw UTC stamps: 2026-08-24T20:30Z -> local Aug 25 02:00 IST;
            # 2026-08-25T05:00Z -> local 10:30 IST.
            for eid, ts in (("u1", "2026-08-24T20:30:00+00:00"),
                            ("u2", "2026-08-25T05:00:00+00:00")):
                idx.add_capture({"id": eid, "ts": ts, "path": f"/p/{eid}.jpg",
                                 "action": "capture"})
            idx.add_capture({
                "id": "raw-bad", "ts": "2026-08-25Tzz", "path": "/p/x.jpg",
                "action": "capture",
            })

            hours = api.get_capture_times_between("2026-08-25", "2026-08-25")
            assert hours == [2, 10]  # malformed row skipped, hours are LOCAL
            assert api.get_capture_times_between("bogus", "2026-08-25") == []
        finally:
            api.close()


def _write_jpeg(path, array):
    import cv2

    ok, buf = cv2.imencode(".jpg", array, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    assert ok
    path.write_bytes(buf.tobytes())


class TestBackfillQuality:
    def test_backfill_updates_scores_skips_missing_and_is_idempotent(self, app_paths):
        import numpy as np

        photos = app_paths.photos_root
        photos.mkdir(parents=True, exist_ok=True)
        rng = np.random.default_rng(42)
        sharp_path = photos / "sharp.jpg"
        flat_path = photos / "flat.jpg"
        dead_path = photos / "dead.jpg"
        broken_path = photos / "broken.jpg"
        _write_jpeg(sharp_path, rng.integers(0, 256, (96, 96), dtype=np.uint8))
        _write_jpeg(flat_path, np.full((96, 96), 110, dtype=np.uint8))
        dead_path.write_bytes(b"\xff\xd8not-really-a-jpeg")
        # missing: /photos/never-existed.jpg is simply never created

        api = IndexAPI(SimpleNamespace(data_dir=app_paths.data_dir))
        api.init()
        try:
            seeds = [
                ("s1", str(sharp_path)),
                ("s2", str(flat_path)),
                ("s3", str(dead_path)),          # undecodable bytes
                ("s4", "/photos/never-existed.jpg"),
            ]
            for eid, path in seeds:
                api._ensure_indexer().add_capture({
                    "id": eid, "ts": "2026-07-01T06:00:00+00:00",
                    "path": path, "action": "capture",
                })

            stats = backfill_quality(api)
            assert stats["updated"] == 2       # s1 + s2 assessed
            assert stats["skipped_missing"] == 1  # s4 only; s3 decodes to NULL metrics

            idx = api._ensure_indexer()
            row_sharp = idx.get_capture_by_id("s1")
            row_flat = idx.get_capture_by_id("s2")
            assert row_sharp["blur_score"] > row_flat["blur_score"]
            assert row_flat["brightness"] is not None
            assert idx.get_capture_by_id("s3")["blur_score"] is None

            rerun = backfill_quality(api)
            assert rerun["updated"] == 0       # idempotent: nothing new to fill
        finally:
            api.close()

    def test_max_batches_caps_work(self, app_paths):
        import numpy as np

        photos = app_paths.photos_root
        photos.mkdir(parents=True, exist_ok=True)
        api = IndexAPI(SimpleNamespace(data_dir=app_paths.data_dir))
        api.init()
        try:
            for i in range(3):
                p = photos / f"img{i}.jpg"
                _write_jpeg(p, np.full((96, 96), 90 + i, dtype=np.uint8))
                api._ensure_indexer().add_capture({
                    "id": f"m{i}", "ts": f"2026-07-0{i+1}T06:00:00+00:00",
                    "path": str(p), "action": "capture",
                })

            stats = backfill_quality(api, batch_size=2, max_batches=1)
            assert stats["batches"] == 1
            assert stats["updated"] == 2
        finally:
            api.close()


class TestBackfillCacheInvalidation:
    def test_backfill_bumps_generation_and_refreshes_cached_highlights(
            self, app_paths, monkeypatch):
        import numpy as np

        photos = app_paths.photos_root
        photos.mkdir(parents=True, exist_ok=True)
        photo = photos / "unscored.jpg"
        _write_jpeg(photo, np.full((96, 96), 128, dtype=np.uint8))

        api = IndexAPI(SimpleNamespace(data_dir=app_paths.data_dir))
        api.init()
        try:
            eid = "bq1"  # unscored: no blur_score/brightness columns yet
            api._ensure_indexer().add_capture({
                "id": eid, "ts": _utc_ts("2026-08-01", 6),
                "path": str(photo), "action": "capture",
            })

            calls = {"n": 0}
            original = recap.streak_milestones

            def counting(dates, today=None):
                calls["n"] += 1
                return original(dates, today=today)

            monkeypatch.setattr(recap, "streak_milestones", counting)

            gen_before = api.generation
            stale = compute_highlights(api, "month", (2026, 8), today=TODAY)
            assert not any(c.kind == "best_shot" for c in stale)
            assert calls["n"] == 1

            stats = backfill_quality(api)
            assert stats["updated"] == 1
            assert api.generation > gen_before   # backfill invalidated the cache

            fresh = compute_highlights(api, "month", (2026, 8), today=TODAY)
            best = [c for c in fresh if c.kind == "best_shot"]
            assert [c.value for c in best] == [eid]
            assert calls["n"] == 2               # recomputed after the bump

            cached = compute_highlights(api, "month", (2026, 8), today=TODAY)
            assert calls["n"] == 2               # served from cache...
            best = [c for c in cached if c.kind == "best_shot"]
            assert [c.value for c in best] == [eid]  # ...with the new best_shot card
        finally:
            api.close()
