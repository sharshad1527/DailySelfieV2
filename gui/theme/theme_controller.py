"""
Theme Controller

Responsibilities:
- Load and manage the active theme
- Persist theme selection to TOML config
- Expose safe access to theme colors
- NOTIFY the app when theme changes (Signals)
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

# Add PySide6 imports for Signals
from PySide6.QtCore import QObject, Signal

from gui.theme.theme_loader import (
    list_theme_files,
    load_theme_by_name,
    ThemeLoaderError,
)
from gui.theme.schema import is_theme_usable, detect_modes_and_contrasts
from gui.theme.theme_model import Theme

from core.config import write_config


# Inherit from QObject to support Signals
class ThemeController(QObject):
    
    # Signal emitted whenever the theme, mode, or contrast changes.
    # The app connects to this to trigger repaints (e.g., ShutterBar.update_theme).
    themeChanged = Signal()

    def __init__(self, cfg: Dict, theme_dir: Path):
        super().__init__() # Initialize QObject
        self._cfg = cfg
        self._theme_dir = theme_dir

        theme_cfg = cfg.get("theme", {})

        self._theme_name: str = theme_cfg.get("name", "")
        self._mode: str = theme_cfg.get("mode", "dark")
        self._contrast: str = theme_cfg.get("contrast", "standard")

        self._theme: Optional[Theme] = None

    # -------------------------------------------------
    # Initialization
    # -------------------------------------------------
    def initialize(self) -> None:
        """
        Load the configured theme.
        Falls back gracefully if theme is missing or invalid.
        """
        if not self._theme_name:
            self._load_first_available()
            return

        try:
            self._load_theme(self._theme_name)
        except ThemeLoaderError:
            self._load_first_available()

    def _load_first_available(self) -> None:
        files = list_theme_files(self._theme_dir)
        if not files:
            self._theme = None
            return

        name = files[0].stem
        self._load_theme(name)
        self._persist()

    def _load_theme(self, name: str) -> None:
        raw = load_theme_by_name(self._theme_dir, name)

        if not is_theme_usable(raw):
            raise ThemeLoaderError(f"Theme '{name}' is not usable")

        self._theme = Theme(raw)
        self._theme_name = name

        # Resolve mode/contrast safely
        availability = detect_modes_and_contrasts(raw)
        if self._mode not in availability:
            self._mode = next(iter(availability))
        if self._contrast not in availability[self._mode]:
            self._contrast = availability[self._mode][0]

    # -------------------------------------------------
    # Persistence
    # -------------------------------------------------
    def _persist(self) -> None:
        self._cfg.setdefault("theme", {})
        self._cfg["theme"].update(
            {
                "name": self._theme_name,
                "mode": self._mode,
                "contrast": self._contrast,
            }
        )

    def save(self, config_path: Path) -> None:
        """Write updated theme settings to config.toml."""
        self._persist()
        write_config(config_path, self._cfg)

    # -------------------------------------------------
    # Public API (Setters now emit Signal)
    # -------------------------------------------------
    def available_themes(self) -> List[str]:
        return [p.stem for p in list_theme_files(self._theme_dir)]

    def available_modes(self) -> List[str]:
        if not self._theme:
            return []
        return self._theme.available_modes()

    def available_contrasts(self) -> List[str]:
        if not self._theme:
            return []
        return self._theme.available_contrasts(self._mode)

    def set_theme(self, name: str) -> None:
        """Switch to a different JSON theme file."""
        if name == self._theme_name:
            return
            
        try:
            self._load_theme(name)
            self._persist()
            # Notify the app!
            self.themeChanged.emit()
        except ThemeLoaderError:
            pass 

    def set_mode(self, mode: str) -> None:
        """Switch between 'light' and 'dark'."""
        if self._theme and self._theme.has_mode(mode):
            if self._mode != mode:
                self._mode = mode
                self._persist()
                # Notify the app!
                self.themeChanged.emit()

    def set_contrast(self, contrast: str) -> None:
        """Switch contrast (e.g. 'standard', 'high')."""
        if self._theme and self._theme.has_contrast(self._mode, contrast):
            if self._contrast != contrast:
                self._contrast = contrast
                self._persist()
                # Notify the app!
                self.themeChanged.emit()

    def colors(self) -> Dict[str, str]:
        if not self._theme:
            return {}
        return self._theme.colors(self._mode, self._contrast)

    # -------------------------------------------------
    # Introspection
    # -------------------------------------------------
    @property
    def theme_name(self) -> str:
        return self._theme_name

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def contrast(self) -> str:
        return self._contrast