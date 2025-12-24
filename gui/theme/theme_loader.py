# gui/theme/theme_loader.py
"""
Theme Loader

Responsibilities:
- Discover available theme JSON files
- Load a theme JSON file from disk
- Return raw Python dicts (no validation, no interpretation)

This module MUST NOT:
- Apply defaults
- Validate schema
- Decide contrast or mode
- Import Qt or UI code
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


class ThemeLoaderError(Exception):
    """Raised when a theme cannot be loaded."""


def list_theme_files(theme_dir: Path) -> List[Path]:
    """
    Return a list of available theme JSON files.

    Only files with `.json` extension are considered.
    """
    if not theme_dir.exists() or not theme_dir.is_dir():
        return []

    return sorted(
        p for p in theme_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".json"
    )


def load_theme_json(theme_path: Path) -> Dict:
    """
    Load a theme JSON file and return raw data.

    Raises ThemeLoaderError on failure.
    """
    if not theme_path.exists():
        raise ThemeLoaderError(f"Theme file not found: {theme_path}")

    try:
        with theme_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ThemeLoaderError(
            f"Invalid JSON in theme file '{theme_path.name}': {e}"
        ) from e
    except Exception as e:
        raise ThemeLoaderError(
            f"Failed to load theme file '{theme_path.name}': {e}"
        ) from e


def load_theme_by_name(theme_dir: Path, name: str) -> Dict:
    """
    Load a theme by name (without .json extension).
    """
    theme_path = theme_dir / f"{name}.json"
    return load_theme_json(theme_path)
