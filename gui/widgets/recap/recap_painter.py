# gui/widgets/recap/recap_painter.py
"""
Offscreen PNG export for recap cards.

render_card_png renders a card widget (or builds one from
(kind, recap_data)) into a QPixmap via QWidget.render, so the PNG shares
the exact paint primitives/theme of the live card at render time.
Requires an initialized QApplication + theme_vars (active theme).

render_deck_pngs exports a whole deck (RecapStage.cards) as numbered PNGs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from core.logging import get_logger

from .cards import (
    BestShotsCard, ClockVizCard, CoverCard, FinaleCard, MoodPaletteCard,
    PaintedScalar, RecapCardBase, StreakCard, YearColorCard,
)

logger = get_logger("recap_painter")

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


def _paint_host_backdrop(pixmap: QPixmap) -> None:
    """Fill `pixmap` with RecapCardHost's rounded themed backdrop.

    Mirrors RecapStage._apply_theme_chrome's RecapCardHost stylesheet
    (surface_container_high fill, radius 22, outline_variant border) so an
    exported card looks like the card the user was looking at.
    """
    from gui.theme.theme_vars import theme_vars

    try:
        v = theme_vars()
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(pixmap.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(v["surface_container_high"]))
        p.drawRoundedRect(rect, 22.0, 22.0)
        p.setBrush(Qt.NoBrush)
        pen = QPen(QColor(v["outline_variant"]))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 22.0, 22.0)
        p.end()
    except Exception:
        logger.warning("recap_png_backdrop_failed",
                       extra={"meta": {"error": "theme unavailable"}})


def render_card_png(card_widget_or_data, out_path, size: Tuple[int, int] = (1080, 1350)):
    """
    Render one recap card to `out_path` as a PNG of `size` pixels.

    Returns the output Path on success, None on any failure. Passing a LIVE
    card (a widget currently parented in the recap deck) is supported: its
    on-screen geometry is restored before returning, so an export never
    reflows the deck, and its already-decoded mosaic/thumbnails are what
    lands in the PNG.
    """
    app = QApplication.instance()
    if app is None:
        return None

    # _resolve_input lives inside the guard: a card the caller handed us can
    # be torn down between the click and the render, and this function's
    # contract is "None on any failure", never an exception.
    widget = None
    owned = False
    saved_geo = None
    scalars = []
    try:
        widget, spec = _resolve_input(card_widget_or_data)
        if widget is None:
            cls = _CARD_CLASSES[spec["kind"]]
            widget = cls()
            owned = True
        out = Path(out_path)
        saved_geo = widget.geometry()
        widget.resize(*_RENDER_SIZE)
        widget.ensurePolished()
        if spec is not None:
            widget.populate(spec["data"] if isinstance(spec["data"], dict) else {})
        else:
            widget.apply_theme()
        # Settle every count-up scalar onto its target first: PaintedScalar
        # animates from zero, so exporting inside the first 600ms (or any time
        # the dwell timer is mid-card) would otherwise bake "0 captures" into
        # the PNG. Snap, render, then hand the card back mid-animation.
        scalars = widget.findChildren(PaintedScalar)
        for scalar in scalars:
            scalar._kill_anim()
            scalar.snap_to_target()

        # Native-size offscreen render (shares the card's paint primitives),
        # then one smooth scaled blit into the export canvas.
        native = QPixmap(*_RENDER_SIZE)
        native.fill(Qt.transparent)
        # Paint the deck's card-host surface first. On screen every card sits
        # on RecapCardHost, whose stylesheet supplies the rounded
        # surface_container_high backdrop; cards that paint no background of
        # their own (FinaleCard) rely on it and would otherwise export as
        # unreadable text on a transparent/unstyled backdrop.
        _paint_host_backdrop(native)
        # DrawChildren only (deliberately NOT DrawWindowBackground): the card
        # has no themed palette, so drawing Qt's default window background
        # would paint an opaque light panel over the themed backdrop and bury
        # the card's own text. Cards that paint their own background
        # (cover/streak/mood/clock/best_shots) still fill it in their
        # paintEvent, which this flag does run.
        widget.render(native, QPoint(0, 0), QRegion(widget.rect()),
                      QWidget.RenderFlag.DrawChildren)

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
            logger.warning("recap_png_save_failed", extra={"meta": {"path": str(out)}})
            return None
        return out
    except Exception as e:
        logger.warning("recap_png_render_failed",
                       extra={"meta": {"path": str(out_path), "error": str(e)}})
        return None
    finally:
        if owned:
            widget.deleteLater()
        else:
            # Hand a LIVE card back the way we found it: geometry restored and
            # the count-ups re-armed, so an export never freezes the deck.
            for scalar in scalars:
                try:
                    scalar.set_target(scalar._target)
                except RuntimeError:
                    pass
        if saved_geo is not None:
            try:
                widget.setGeometry(saved_geo)
            except RuntimeError:
                pass  # card torn down while the export was in flight


def render_deck_pngs(cards: Iterable[Any], out_dir, size: Tuple[int, int] = (1080, 1350),
                     prefix: str = "recap") -> List[Path]:
    """
    Export a whole deck to `out_dir` as numbered PNGs (deck order).

    Filenames are `<prefix>-NN-<kind>.png`, e.g. `recap-2024-01-01-cover.png`
    where NN is the 1-based deck position and `kind` is the card's
    CARD_KIND. Returns the Paths that were actually written; cards that fail
    to render are skipped (the caller reports the count).
    """
    out_dir = Path(out_dir)
    stem = str(prefix or "recap")
    written: List[Path] = []
    for i, card in enumerate(cards or (), 1):
        kind = str(getattr(card, "CARD_KIND", "") or "card")
        target = out_dir / f"{stem}-{i:02d}-{kind}.png"
        result = render_card_png(card, target, size)
        if result is not None:
            written.append(result)
    return written
