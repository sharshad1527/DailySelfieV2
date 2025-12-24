# gui/theme/theme_model.py
"""
Theme Model

Responsibilities:
- Wrap raw Material theme JSON
- Provide safe access to color schemes
- Handle fallback logic for missing modes or contrast levels

This module MUST NOT:
- Load files
- Modify config
- Apply Qt styles
"""

from __future__ import annotations
from typing import Dict, List

from gui.theme.schema import detect_modes_and_contrasts


class Theme:
    def __init__(self, raw: Dict):
        self._raw = raw
        self._availability = detect_modes_and_contrasts(raw)

    # -------------------------------------------------
    # Availability
    # -------------------------------------------------
    def available_modes(self) -> List[str]:
        """Return available modes (e.g. ['dark', 'light'])."""
        return list(self._availability.keys())

    def available_contrasts(self, mode: str) -> List[str]:
        """Return available contrasts for a given mode."""
        return self._availability.get(mode, [])

    def has_mode(self, mode: str) -> bool:
        return mode in self._availability

    def has_contrast(self, mode: str, contrast: str) -> bool:
        return contrast in self._availability.get(mode, [])

    # -------------------------------------------------
    # Color Access
    # -------------------------------------------------
    def colors(self, mode: str, contrast: str) -> Dict[str, str]:
        """
        Return color dictionary for given mode + contrast.

        Fallback rules:
        - If mode not available → use first available mode
        - If contrast not available → use 'standard' or first available
        """
        mode = self._resolve_mode(mode)
        contrast = self._resolve_contrast(mode, contrast)

        scheme_key = self._scheme_key(mode, contrast)
        schemes = self._raw.get("schemes", {})

        return schemes.get(scheme_key, {})

    # -------------------------------------------------
    # Internal helpers
    # -------------------------------------------------
    def _resolve_mode(self, mode: str) -> str:
        if mode in self._availability:
            return mode
        # fallback to first available mode
        return next(iter(self._availability))

    def _resolve_contrast(self, mode: str, contrast: str) -> str:
        available = self._availability.get(mode, [])
        if contrast in available:
            return contrast
        if "standard" in available:
            return "standard"
        return available[0]

    @staticmethod
    def _scheme_key(mode: str, contrast: str) -> str:
        """
        Convert mode + contrast into Material scheme key.
        """
        if contrast == "standard":
            return mode
        return f"{mode}-{contrast}-contrast"
