# core/quality.py
"""
Photo quality assessment for the pre-save advisory gate.

Pure OpenCV/numpy — MUST stay free of GUI imports so headless flows and
probes can reuse it. assess_image_quality() never raises on bad input:
unreadable or degenerate frames simply yield no warnings (an advisory
gate must never block a save because analysis failed).

Threshold calibration (synthetic 640x480/1280x720 JPEG probes, 2026-08):
- blur_score = variance of Laplacian; sharp frames land in the thousands,
  flat/out-of-focus frames collapse toward 0 (<100 is reliably soft).
- brightness = grayscale mean; <40 reads as visibly dark indoor footage,
  >215 as blown out / overexposed.
"""
from __future__ import annotations

from typing import Dict, List

BLUR_VAR_THRESHOLD = 100.0
DARK_MEAN_THRESHOLD = 40.0
BRIGHT_MEAN_THRESHOLD = 215.0

# Laplacian statistics are meaningless below this size on a side;
# treat such frames as unreadable rather than guessing.
MIN_FRAME_DIM = 32

WARNING_MESSAGES: Dict[str, str] = {
    "blurry": "Looks blurry",
    "dark": "Too dark",
    "bright": "Too bright",
}


def _no_findings() -> Dict[str, object]:
    return {"blur_score": None, "brightness": None, "warnings": []}


def assess_image_quality(image_bytes: bytes) -> Dict[str, object]:
    """
    Score image bytes (JPEG or any cv2-decodable format) for blur/exposure.

    Returns {"blur_score": float|None, "brightness": float|None,
             "warnings": ["blurry"|"dark"|"bright", ...]}
    Empty warnings = frame passed (or could not be assessed).
    """
    result = _no_findings()
    warnings: List[str] = result["warnings"]
    if not image_bytes:
        return result
    try:
        import cv2
        import numpy as np

        buf = np.frombuffer(bytes(image_bytes), dtype=np.uint8)
        gray = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
        if gray is None or min(gray.shape[:2]) < MIN_FRAME_DIM:
            return result

        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        result["blur_score"] = round(blur_score, 2)
        result["brightness"] = round(brightness, 2)

        if blur_score < BLUR_VAR_THRESHOLD:
            warnings.append("blurry")
        if brightness < DARK_MEAN_THRESHOLD:
            warnings.append("dark")
        elif brightness > BRIGHT_MEAN_THRESHOLD:
            warnings.append("bright")
    except Exception:
        return _no_findings()
    return result
