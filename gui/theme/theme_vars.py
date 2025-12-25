# gui/theme/theme_vars.py
from __future__ import annotations
from typing import Dict

from PySide6.QtGui import QColor
from gui.theme.theme_controller import ThemeController

_theme_vars: ThemeVars | None = None

class ThemeVars:
    """
    Material 3 token adapter.
    FIX: Now fetches live colors from the controller instead of caching them.
    """

    def __init__(self, controller: ThemeController):
        # CHANGE 1: Store the controller, NOT the colors
        self._controller = controller

        # --------------------------------------------------
        # Material token aliases
        # --------------------------------------------------
        self._map: Dict[str, str] = {
            # ===== Primary =====
            "primary": "primary",
            "on_primary": "onPrimary",
            "primary_container": "primaryContainer",
            "on_primary_container": "onPrimaryContainer",

            # ===== Secondary =====
            "secondary": "secondary",
            "on_secondary": "onSecondary",
            "secondary_container": "secondaryContainer",
            "on_secondary_container": "onSecondaryContainer",

            # ===== Tertiary =====
            "tertiary": "tertiary",
            "on_tertiary": "onTertiary",
            "tertiary_container": "tertiaryContainer",
            "on_tertiary_container": "onTertiaryContainer",

            # ===== Fixed =====
            "primary_fixed": "primaryFixed",
            "primary_fixed_dim": "primaryFixedDim",
            "on_primary_fixed": "onPrimaryFixed",
            "on_primary_fixed_variant": "onPrimaryFixedVariant",

            # ===== Background / Surface =====
            "background": "background",
            "on_background": "onBackground",

            "surface": "surface",
            "on_surface": "onSurface",
            "surface_variant": "surfaceVariant",
            "on_surface_variant": "onSurfaceVariant",
            "surface_dim": "surfaceDim",
            "surface_bright": "surfaceBright",
            "surface_container_lowest": "surfaceContainerLowest",
            "surface_container_low": "surfaceContainerLow",
            "surface_container": "surfaceContainer",
            "surface_container_high": "surfaceContainerHigh",
            "surface_container_highest": "surfaceContainerHighest",

            # ===== Outline / Effects =====
            "outline": "outline",
            "outline_variant": "outlineVariant",
            "scrim": "scrim",
            "shadow": "shadow",

            # ===== Inverse =====
            "inverse_surface": "inverseSurface",
            "inverse_on_surface": "inverseOnSurface",
            "inverse_primary": "inversePrimary",

            # ===== Error =====
            "error": "error",
            "on_error": "onError",
            "error_container": "errorContainer",
            "on_error_container": "onErrorContainer",
        }

    # --------------------------------------------------
    # Accessors
    # --------------------------------------------------
    def __getitem__(self, key: str) -> str:
        token = self._map.get(key)
        if not token:
            raise KeyError(f"Unknown Material key: {key}")

        # CHANGE 2: Ask the controller for the CURRENT colors right now
        # This ensures we get Light colors if the mode just changed to Light
        current_colors = self._controller.colors()
        
        value = current_colors.get(token)
        if not value:
            # Fallback for missing keys (safety)
            return "#FF00FF" 

        return value

    def qcolor(self, key: str) -> QColor:
        return QColor(self[key])

    def rgba(self, key: str, alpha: float) -> QColor:
        c = QColor(self[key])
        c.setAlphaF(max(0.0, min(1.0, alpha)))
        return c

    def keys(self):
        return self._map.keys()


# ==================================================
# Global access
# ==================================================

def init_theme_vars(controller: ThemeController) -> None:
    global _theme_vars
    _theme_vars = ThemeVars(controller)

def theme_vars() -> ThemeVars:
    if _theme_vars is None:
        raise RuntimeError(
            "ThemeVars not initialized. "
            "Call init_theme_vars(theme_controller) before using theme_vars()."
        )
    return _theme_vars