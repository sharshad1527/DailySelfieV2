# gui/widgets/recap/cards/year_color.py
"""
YearColorCard — twelve month bars, height proportional to capture-days,
filled with the month's dominant mood hex (or primary when un-mooded);
empty months render as hollow stubs. Hover shows a per-month tooltip.
Only included in the deck when a monthly matrix is available.
"""
from __future__ import annotations

import calendar as _cal
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gui.dashboard.widgets.calendar_analytics.viz_types import MOOD_COLORS
from gui.theme.theme_vars import theme_vars

from .base import RecapCardBase, _d, _int


class _BarsCanvas(QWidget):
    """Paint surface for the 12 bars; owns its own paintEvent so all
    QPainter use stays inside a legal paint cycle."""

    def __init__(self, card: "YearColorCard", parent=None):
        super().__init__(parent)
        self._card = card
        self.setMinimumHeight(280)
        self.setMouseTracking(True)

    def paintEvent(self, event) -> None:
        card = self._card
        if card is not None:
            card.paint_bars(self)
            return
        p = QPainter(self)
        p.end()

    def mouseMoveEvent(self, event) -> None:
        card = self._card
        if card is not None:
            card.handle_canvas_move(event.position())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        card = self._card
        if card is not None:
            card.handle_canvas_leave()
        super().leaveEvent(event)


class YearColorCard(RecapCardBase):
    CARD_KIND = "year_color"

    def build_content(self):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        title = QLabel("The year in color")
        title.setObjectName("CardTitle")
        caption = QLabel("Bar height = capture-days; tint = dominant mood.")
        caption.setObjectName("CardCaption")
        lay.addWidget(title)
        lay.addWidget(caption)
        self.add_section(box)

        self._hover_month: Optional[int] = None
        canvas = _BarsCanvas(self)
        self._canvas = canvas
        self.add_section(canvas)
        self._lay.addStretch()

    # ---- data ---------------------------------------------------------------
    def _matrix(self) -> Dict[int, Tuple[int, Optional[str]]]:
        """{month: (capture_days, mood_hex_or_None)} parsed defensively."""
        raw = _d(self._data, "monthly")
        out: Dict[int, Tuple[int, Optional[str]]] = {}
        if isinstance(raw, dict):
            for m in range(1, 13):
                entry = raw.get(m, raw.get(str(m)))
                days, mood = 0, None
                if isinstance(entry, dict):
                    days = max(0, _int(entry.get("days")))
                    mood = entry.get("mood") if entry.get("mood") in MOOD_COLORS else None
                elif entry is not None:
                    try:
                        days = max(0, int(entry))
                    except (TypeError, ValueError):
                        days = 0
                out[m] = (days, mood)
        return out

    def _bar_geometry(self) -> QRectF:
        c = self._canvas
        left, top = 16.0, 14.0
        return QRectF(left, top, max(c.width() - left * 2, 10.0),
                      max(c.height() - top - 26.0, 10.0))

    def _month_at(self, pos) -> Optional[int]:
        area = self._bar_geometry()
        slot = area.width() / 12.0
        idx = int((pos.x() - area.left()) / slot)
        return idx + 1 if 0 <= idx < 12 else None

    def _on_canvas_move(self, pos) -> None:
        m = self._month_at(pos)
        if m != self._hover_month:
            self._hover_month = m
            self._sync_tooltip(m)
            self._canvas.update()

    def handle_canvas_move(self, pos) -> None:
        self._on_canvas_move(pos)

    def _on_canvas_leave(self, _event=None) -> None:
        self._hover_month = None
        self._canvas.setToolTip("")
        self._canvas.update()

    def handle_canvas_leave(self) -> None:
        self._on_canvas_leave()

    def _sync_tooltip(self, month: Optional[int]) -> None:
        if month is None:
            self._canvas.setToolTip("")
            return
        days, mood = self._matrix().get(month, (0, None))
        name = _cal.month_name[month]
        tip = f"{name}: {days} capture-day{'s' if days != 1 else ''}"
        if mood:
            tip += f" · mostly {mood}"
        self._canvas.setToolTip(tip)

    # ---- painting --------------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        v = theme_vars()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(v["surface_container_high"]))
        p.drawRoundedRect(self.rect(), 22, 22)
        p.end()

    def paint_bars(self, canvas: QWidget) -> None:
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing)
        v = theme_vars()
        area = self._bar_geometry()
        matrix = self._matrix()
        peak_days = max((d for d, _ in matrix.values()), default=0)
        slot = area.width() / 12.0
        bar_w = min(slot * 0.56, 34.0)

        f_label = QFont(self.font())
        f_label.setPixelSize(10)
        painter.setFont(f_label)

        baseline_pen = QPen(theme_vars().rgba("outline_variant", 0.8))
        baseline_pen.setWidthF(1.0)
        painter.setPen(baseline_pen)
        painter.drawLine(QPointF(area.left(), area.bottom()),
                         QPointF(area.right(), area.bottom()))

        for m in range(1, 13):
            days, mood_hex = matrix.get(m, (0, None))
            cx = area.left() + slot * (m - 1) + slot / 2
            x = cx - bar_w / 2
            letter = QRectF(cx - slot / 2, area.bottom() + 6, slot, 14)
            if days <= 0 or peak_days <= 0:
                stub_h = 8.0
                stub = QRectF(x, area.bottom() - stub_h, bar_w, stub_h)
                painter.setPen(baseline_pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(stub, 3, 3)
                painter.setPen(QColor(v["on_surface_variant"]))
                painter.drawText(letter, Qt.AlignCenter, _cal.month_abbr[m][0])
                continue
            h = area.height() * (days / peak_days)
            bar = QRectF(x, area.bottom() - max(h, 12.0), bar_w, max(h, 12.0))
            fill_hex = mood_hex or v["primary"]
            dimmed = self._hover_month is not None and self._hover_month != m
            painter.setPen(Qt.NoPen)
            painter.setOpacity(0.35 if dimmed else 1.0)
            painter.setBrush(QColor(fill_hex))
            painter.drawRoundedRect(bar, 4, 4)
            painter.setOpacity(1.0)
            painter.setPen(QColor(v["on_surface_variant"]))
            painter.drawText(letter, Qt.AlignCenter, _cal.month_abbr[m][0])
            if self._hover_month == m:
                pen = QPen(QColor(v["on_surface"]))
                pen.setWidthF(1.5)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(pen)
                painter.drawRoundedRect(bar.adjusted(-2, -2, 2, 2), 5, 5)
        painter.end()

    def apply_theme(self) -> None:
        v = theme_vars()
        self.setStyleSheet(f"""
            QLabel#CardTitle {{
                color: {v['on_surface']};
                font-size: 15px;
                font-weight: 700;
            }}
            QLabel#CardCaption {{
                color: {v['on_surface_variant']};
                font-size: 12px;
            }}
        """)
        # The bars live on a separate paint surface; without this they keep
        # stale theme colors until the next hover-driven update.
        self._canvas.update()
        self.update()
