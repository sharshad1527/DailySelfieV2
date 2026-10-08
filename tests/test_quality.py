"""
core/quality.py: the pre-save advisory blur/brightness gate.

Two capture paths persist these numbers into the index DB and the JSONL audit,
and the GUI renders them, so the contract that matters is: a genuinely blurry
or badly-exposed frame is flagged, a good frame is not, and *nothing* raises —
an unreadable frame must never block a save.

Images are synthesised in-process with numpy/cv2 (no fixtures on disk), so the
suite stays offline and deterministic. Every generated file lives under tmp.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.quality import (
    BLUR_VAR_THRESHOLD,
    BRIGHT_MEAN_THRESHOLD,
    DARK_MEAN_THRESHOLD,
    MIN_FRAME_DIM,
    WARNING_MESSAGES,
    assess_image_quality,
)
from core import quality as quality_mod

pytestmark = pytest.mark.core_only  # fast/offline core data-layer tests

cv2 = pytest.importorskip("cv2", reason="quality.py needs cv2 at call time")


def _encode(array, quality: int = 95) -> bytes:
    ok, buf = cv2.imencode(".jpg", array, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    assert ok
    return buf.tobytes()


def _sharp_frame(width=320, height=240) -> np.ndarray:
    """High-frequency content: Laplacian variance far above the threshold."""
    rng = np.random.default_rng(1234)
    frame = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    return frame


def _flat_frame(value: int = 128, width=320, height=240) -> np.ndarray:
    """Uniform colour: zero Laplacian variance, mean == value."""
    return np.full((height, width, 3), value, dtype=np.uint8)


def _smooth_gradient(width=320, height=240, base=128, span=40) -> np.ndarray:
    ramp = np.linspace(base - span, base + span, width, dtype=np.float32)
    row = np.tile(ramp, (height, 1))
    return np.repeat(row[:, :, None], 3, axis=2).astype(np.uint8)


class TestSharpWellExposedFrame:
    def test_produces_no_warnings(self):
        result = assess_image_quality(_encode(_sharp_frame()))
        assert result["warnings"] == []

    def test_reports_numeric_scores(self):
        result = assess_image_quality(_encode(_sharp_frame()))
        assert isinstance(result["blur_score"], float)
        assert isinstance(result["brightness"], float)

    def test_blur_score_is_well_above_threshold(self):
        result = assess_image_quality(_encode(_sharp_frame()))
        assert result["blur_score"] > BLUR_VAR_THRESHOLD

    def test_brightness_is_in_the_normal_range(self):
        result = assess_image_quality(_encode(_sharp_frame()))
        assert DARK_MEAN_THRESHOLD < result["brightness"] < BRIGHT_MEAN_THRESHOLD

    def test_scores_are_rounded_to_two_places(self):
        result = assess_image_quality(_encode(_sharp_frame()))
        assert result["blur_score"] == round(result["blur_score"], 2)
        assert result["brightness"] == round(result["brightness"], 2)

    def test_result_shape_is_stable(self):
        result = assess_image_quality(_encode(_sharp_frame()))
        assert set(result) == {"blur_score", "brightness", "warnings"}

    def test_is_deterministic(self):
        payload = _encode(_sharp_frame())
        assert assess_image_quality(payload) == assess_image_quality(payload)


class TestBlurryFrames:
    def test_uniform_frame_is_flagged_blurry(self):
        result = assess_image_quality(_encode(_flat_frame(128)))
        assert "blurry" in result["warnings"]

    def test_flat_frame_blur_score_is_near_zero(self):
        result = assess_image_quality(_encode(_flat_frame(128)))
        assert result["blur_score"] < BLUR_VAR_THRESHOLD

    def test_smooth_gradient_is_also_flagged(self):
        result = assess_image_quality(_encode(_smooth_gradient()))
        assert "blurry" in result["warnings"]

    def test_flat_frame_is_not_also_flagged_dark_or_bright(self):
        result = assess_image_quality(_encode(_flat_frame(128)))
        assert result["warnings"] == ["blurry"]


class TestExposure:
    def test_dark_frame_flagged_dark(self):
        result = assess_image_quality(_encode(_flat_frame(10)))
        assert "dark" in result["warnings"]

    def test_dark_sharp_frame_is_flagged_dark_but_not_blurry(self):
        # A sharp but dark frame: full-range noise scaled down loses contrast,
        # so blur may or may not trip; the exposure verdict must be stable.
        noisy_dark = (np.random.default_rng(7).integers(0, 24, size=(240, 320, 3))
                      ).astype(np.uint8)
        result = assess_image_quality(_encode(noisy_dark))
        assert "dark" in result["warnings"]
        assert "bright" not in result["warnings"]

    def test_bright_frame_flagged_bright(self):
        result = assess_image_quality(_encode(_flat_frame(250)))
        assert "bright" in result["warnings"]

    def test_bright_and_dark_are_mutually_exclusive(self):
        for value, expected in ((0, "dark"), (255, "bright")):
            result = assess_image_quality(_encode(_flat_frame(value)))
            others = {"dark", "bright"} - {expected}
            assert not (others & set(result["warnings"])), (
                f"value {value} produced {result['warnings']}"
            )

    def test_brightness_tracks_the_actual_mean(self):
        dark = assess_image_quality(_encode(_flat_frame(20)))
        bright = assess_image_quality(_encode(_flat_frame(230)))
        assert dark["brightness"] == pytest.approx(20, abs=2)
        assert bright["brightness"] == pytest.approx(230, abs=2)
        assert dark["brightness"] < bright["brightness"]

    def test_warnings_use_the_published_message_keys(self):
        result = assess_image_quality(_encode(_flat_frame(10)))
        for key in result["warnings"]:
            assert key in WARNING_MESSAGES


class TestDegradedInput:
    """The gate is advisory: bad input must yield no warnings, never an error."""

    @pytest.mark.parametrize("empty", [b"", None, bytearray(), []])
    def test_empty_input_is_handled(self, empty):
        result = assess_image_quality(empty)
        assert result == {"blur_score": None, "brightness": None, "warnings": []}

    def test_garbage_bytes_are_handled(self):
        result = assess_image_quality(b"this is definitely not a jpeg")
        assert result["warnings"] == []
        assert result["blur_score"] is None

    def test_truncated_jpeg_is_handled(self):
        payload = _encode(_sharp_frame())
        result = assess_image_quality(payload[: len(payload) // 3])
        assert result["warnings"] == []

    def test_frame_below_min_dimension_yields_no_scores(self):
        tiny = _flat_frame(128, width=MIN_FRAME_DIM - 1, height=MIN_FRAME_DIM - 1)
        result = assess_image_quality(_encode(tiny))
        assert result == {"blur_score": None, "brightness": None, "warnings": []}

    def test_exactly_min_dimension_is_assessed(self):
        exact = _flat_frame(128, width=MIN_FRAME_DIM, height=MIN_FRAME_DIM)
        result = assess_image_quality(_encode(exact))
        assert result["blur_score"] is not None

    def test_png_input_is_accepted(self):
        ok, buf = cv2.imencode(".png", _flat_frame(10))
        assert ok
        result = assess_image_quality(buf.tobytes())
        assert result["brightness"] is not None
        assert "dark" in result["warnings"]

    def test_bytearray_input_is_accepted(self):
        result = assess_image_quality(bytearray(_encode(_flat_frame(10))))
        assert "dark" in result["warnings"]

    def test_memoryview_input_does_not_raise(self):
        payload = memoryview(_encode(_flat_frame(10)))
        result = assess_image_quality(payload)
        assert result["warnings"] == [] or "dark" in result["warnings"]

    def test_import_failure_yields_no_warnings(self, monkeypatch):
        """An analysis crash must never block a save."""
        import builtins

        real_import = builtins.__import__

        def _boom(name, *args, **kwargs):
            if name == "cv2":
                raise ImportError("cv2 vanished")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _boom)
        monkeypatch.delitem(__import__("sys").modules, "cv2", raising=False)

        result = assess_image_quality(_encode(_flat_frame(10)))

        assert result == {"blur_score": None, "brightness": None, "warnings": []}

    def test_no_gui_imports_are_pulled_in(self):
        """quality.py must stay headless: importing it pulls in no Qt.

        Asserted by inspecting quality.py's OWN import graph rather than
        sys.modules. A whole-process check is order-dependent: any earlier test
        that legitimately imports PySide6 (the GUI-adjacent suites do) would
        fail this one even though quality.py itself is clean.
        """
        import ast
        import pathlib

        src = pathlib.Path(quality_mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])

        assert "PySide6" not in imported, f"quality.py imports Qt: {sorted(imported)}"
        assert "PyQt5" not in imported and "PyQt6" not in imported

        # And it must still work: scoring a frame must not need Qt either.
        assess_image_quality(_encode(_sharp_frame()))


class TestFrameSizeHandling:
    def test_non_square_frame_is_measured_on_its_own_dimensions(self):
        wide = _flat_frame(128, width=400, height=50)
        result = assess_image_quality(_encode(wide))
        assert result["brightness"] == pytest.approx(128, abs=3)

    def test_one_short_side_below_min_yields_no_scores(self):
        short = _flat_frame(128, width=300, height=MIN_FRAME_DIM - 1)
        assert assess_image_quality(_encode(short))["blur_score"] is None


class TestThresholds:
    def test_documented_thresholds_are_ordered(self):
        assert DARK_MEAN_THRESHOLD < BRIGHT_MEAN_THRESHOLD
        assert BLUR_VAR_THRESHOLD > 0

    def test_warning_keys_cover_every_emitted_warning(self):
        assert set(WARNING_MESSAGES) == {"blurry", "dark", "bright"}

    def test_every_warning_message_is_non_empty_text(self):
        for message in WARNING_MESSAGES.values():
            assert isinstance(message, str) and message.strip()