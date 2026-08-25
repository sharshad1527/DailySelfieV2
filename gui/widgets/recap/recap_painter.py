# gui/widgets/recap/recap_painter.py
"""
Offscreen PNG export for recap cards.

render_card_png renders a card widget (or builds one from
(kind, recap_data)) into a QPixmap via QWidget.render, so the PNG shares
the exact paint primitives/theme of the live card at render time.
Requires an initialized QApplication + theme_vars (active theme).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from .cards import (
    BestShotsCard, ClockVizCard, CoverCard, FinaleCard, MoodPaletteCard,
    RecapCardBase, StreakCard, YearColorCard,
)

_CARD_CLASSES = {
    "cover": CoverCard,
    "streak": StreakCard,
    "mood": MoodPaletteCard,
    "best_shots": BestShotsCard,
    "clock": ClockVizCard,
    "year_color": YearColorCard,
    "finale": FinaleCard,
}

_RENDER_SIZE = (560, 720)


def _resolve_input(card_widget_or_data) -> Tuple[Optional[RecapCardBase], Optional[Dict[str, Any]]]:
    """Accepts a card widget | (kind, data) tuple | {'kind','data'} dict."""
    if isinstance(card_widget_or_data, RecapCardBase):
        return card_widget_or_data, None
    if isinstance(card_widget_or_data, dict):
        kind = str(card_widget_or_data.get("kind", ""))
        data = card_widget_or_data.get("data")
        if kind in _CARD_CLASSES:
            return None, {"kind": kind, "data": data}
        raise ValueError(f"unknown recap card kind: {kind!r}")
    if isinstance(card_widget_or_data, tuple) and len(card_widget_or_data) == 2:
        kind, data = card_widget_or_data
        kind = str(kind)
        if kind not in _CARD_CLASSES:
            raise ValueError(f"unknown recap card kind: {kind!r}")
        return None, {"kind": kind, "data": data}
    raise TypeError("render_card_png expects a recap card widget, "
                    "(kind, data) or {'kind','data'}")


def render_card_png(card_widget_or_data, out_path, size: Tuple[int, int] = (1080, 1350)):
    """
    Render one recap card to `out_path` as a PNG of `size` pixels.

    Returns the output Path on success, None on any failure. The widget is
    never shown and never parented; rendering happens offscreen against the
    active theme (theme_vars must already be initialized).
    """
    app = QApplication.instance()
    if app is None:
        return None

    widget, spec = _resolve_input(card_widget_or_data)
    owned = False
    if widget is None:
        cls = _CARD_CLASSES[spec["kind"]]
        widget = cls()
        owned = True

    try:
        out = Path(out_path)
        widget.resize(*_RENDER_SIZE)
        widget.ensurePolished()
        if spec is not None:
            widget.populate(spec["data"] if isinstance(spec["data"], dict) else {})
        else:
            widget.apply_theme()

        # Native-size offscreen render (shares the card's paint primitives),
        # then one smooth scaled blit into the export canvas.
        native = QPixmap(*_RENDER_SIZE)
        native.fill(Qt.transparent)
        widget.render(native, QPoint(0, 0),
                      QRegion(widget.rect()),
                      QWidget.RenderFlag.DrawWindowBackground
                      | QWidget.RenderFlag.DrawChildren)

        pixmap = QPixmap(int(size[0]), int(size[1]))
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            target = QRectF(24, 24, size[0] - 48, size[1] - 48)
            painter.drawPixmap(target, native,
                               QRectF(0, 0, _RENDER_SIZE[0], _RENDER_SIZE[1]))
        finally:
            painter.end()

        out.parent.mkdir(parents=True, exist_ok=True)
        if not pixmap.save(str(out), "PNG"):
            return None
        return out
    except Exception:
        return None
    finally:
        if owned:
            widget.deleteLater()
