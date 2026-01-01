# gui/theme/theme_vars.py
from __future__ import annotations
from typing import Dict

from PySide6.QtGui import QColor
from gui.theme.theme_controller import ThemeController

_theme_vars: ThemeVars | None = None

class ThemeVars:
    """
    Material 3 token adapter.
    """

    def __init__(self, controller: ThemeController):
        self._controller = controller

        # --------------------------------------------------
        # Material token aliases
        # --------------------------------------------------
        self._map: Dict[str, str] = {
            # ===== Primary =====
            # Use for: High-emphasis fills, texts, and icons against surface.
            "primary": "primary",
            # Use for: Text and icons against primary.
            "on_primary": "onPrimary",
            # Use for: Standout fill color against surface, for key components like FAB.
            "primary_container": "primaryContainer",
            # Use for: Text and icons against primary container.
            "on_primary_container": "onPrimaryContainer",

            # ===== Secondary =====
            # Use for: Less prominent fills, text, and icons against surface.
            "secondary": "secondary",
            # Use for: Text and icons against secondary.
            "on_secondary": "onSecondary",
            # Use for: Less prominent tonal containers.
            "secondary_container": "secondaryContainer",
            # Use for: Text and icons against secondary container.
            "on_secondary_container": "onSecondaryContainer",

            # ===== Tertiary =====
            # Use for: Contrasting accents that balance primary/secondary.
            "tertiary": "tertiary",
            # Use for: Text and icons against tertiary.
            "on_tertiary": "onTertiary",
            # Use for: Contrasting tonal containers.
            "tertiary_container": "tertiaryContainer",
            # Use for: Text and icons against tertiary container.
            "on_tertiary_container": "onTertiaryContainer",

            # ===== Fixed =====
            # Use for: Fixed color that doesn't change between light/dark themes.
            "primary_fixed": "primaryFixed",
            "primary_fixed_dim": "primaryFixedDim",
            "on_primary_fixed": "onPrimaryFixed",
            "on_primary_fixed_variant": "onPrimaryFixedVariant",

            # ===== Background / Surface =====
            # Use for: The underlying background of the app.
            "background": "background",
            # Use for: Text and icons against background.
            "on_background": "onBackground",

            # Use for: Surface of components like cards, sheets, menus.
            "surface": "surface",
            # Use for: Text and icons against surface.
            "on_surface": "onSurface",
            # Use for: Variant color for decorative elements or borders.
            "surface_variant": "surfaceVariant",
            # Use for: Medium-emphasis text and icons.
            "on_surface_variant": "onSurfaceVariant",
            
            # Use for: Darker surface area.
            "surface_dim": "surfaceDim",
            # Use for: Bright surface area.
            "surface_bright": "surfaceBright",
            # Use for: Lowest emphasis container.
            "surface_container_lowest": "surfaceContainerLowest",
            # Use for: Low emphasis container.
            "surface_container_low": "surfaceContainerLow",
            # Use for: Default container.
            "surface_container": "surfaceContainer",
            # Use for: High emphasis container.
            "surface_container_high": "surfaceContainerHigh",
            # Use for: Highest emphasis container.
            "surface_container_highest": "surfaceContainerHighest",

            # ===== Outline / Effects =====
            # Use for: Important boundaries, such as text field outlines.
            "outline": "outline",
            # Use for: Decorative boundaries, such as dividers.
            "outline_variant": "outlineVariant",
            # Use for: Overlay for modals.
            "scrim": "scrim",
            # Use for: Shadow color.
            "shadow": "shadow",

            # ===== Inverse =====
            # Use for: Inverted surface background (e.g., snatchbars).
            "inverse_surface": "inverseSurface",
            # Use for: Text/icons on inverse surface.
            "inverse_on_surface": "inverseOnSurface",
            # Use for: Primary color for inverse surface.
            "inverse_primary": "inversePrimary",

            # ===== Error =====
            # Use for: Indicates errors or urgent states.
            "error": "error",
            # Use for: Text and icons on error color.
            "on_error": "onError",
            # Use for: Container for error states.
            "error_container": "errorContainer",
            # Use for: Text and icons on error container.
            "on_error_container": "onErrorContainer",
        }

    # --------------------------------------------------
    # Accessors
    # --------------------------------------------------
    def __getitem__(self, key: str) -> str:
        token = self._map.get(key)
        if not token:
            raise KeyError(f"Unknown Material key: {key}")

        current_colors = self._controller.colors()
        
        value = current_colors.get(token)
        if not value:
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