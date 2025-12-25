# gui/theme/schema.py
"""
Theme Schema Validation

Responsibilities:
- Inspect raw Material theme JSON
- Detect available modes (dark/light)
- Detect available contrast levels per mode
- Ensure minimum required color keys exist

This module MUST NOT:
- Modify theme data
- Apply defaults
- Raise fatal errors for missing optional fields
"""

from __future__ import annotations
from typing import Dict, List, Set


REQUIRED_COLOR_KEYS = {
    "background",
    "onBackground",
    "primary",
    "onPrimary",
}


def _extract_schemes(theme: Dict) -> Dict[str, Dict]:
    """
    Extract scheme definitions from theme JSON.

    Supports both:
    - { "schemes": { ... } }
    - flat scheme dicts (fallback)
    """
    if "schemes" in theme and isinstance(theme["schemes"], dict):
        return theme["schemes"]

    # Fallback: try to treat top-level keys as schemes
    return {
        k: v for k, v in theme.items()
        if isinstance(v, dict)
    }


def _has_required_keys(scheme: Dict) -> bool:
    """Check if a color scheme has minimum required keys."""
    return REQUIRED_COLOR_KEYS.issubset(scheme.keys())


def detect_modes_and_contrasts(theme: Dict) -> Dict[str, List[str]]:
    """
    Detect available modes and contrast levels.

    Returns:
        {
            "dark": ["standard", "high"],
            "light": ["standard"]
        }
    """
    schemes = _extract_schemes(theme)

    availability: Dict[str, Set[str]] = {
        "dark": set(),
        "light": set(),
    }

    for scheme_name, scheme_data in schemes.items():
        if not isinstance(scheme_data, dict):
            continue

        if not _has_required_keys(scheme_data):
            continue

        name = scheme_name.lower()

        # Detect mode
        if name.startswith("dark"):
            mode = "dark"
        elif name.startswith("light"):
            mode = "light"
        else:
            continue

        # Detect contrast
        if "high" in name:
            contrast = "high"
        elif "medium" in name:
            contrast = "medium"
        else:
            contrast = "standard"

        availability[mode].add(contrast)

    # Convert sets to sorted lists
    return {
        mode: sorted(list(contrasts))
        for mode, contrasts in availability.items()
        if contrasts
    }


def is_theme_usable(theme: Dict) -> bool:
    """
    Determine whether a theme is usable at all.

    A theme is usable if it has at least:
    - one mode
    - one contrast level
    """
    availability = detect_modes_and_contrasts(theme)
    return bool(availability)
