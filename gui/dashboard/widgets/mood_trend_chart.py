# gui/dashboard/widgets/mood_trend_chart.py
"""
MoodTrendChart — compact custom-painted mood sparkline for the dashboard.

Single paintEvent pass (YearHeatmapStrip pattern): x=day, y=mood ordinal
(MOOD_ORDER), MOOD_COLORS dots joined by subtle line segments broken across
missing days; hover tooltip with date + mood; today ring; inline mini legend
that degrades to dots-only when the card is narrow.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime, timedelta
from typing import Dict, List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QPropertyAnimation
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from gui.theme import motion_tokens as mt
from gui.theme.theme_vars import theme_vars
from .calendar_analytics.viz_types import MOOD_COLORS, MOOD_ORDER

PAD_L = 10.0
PAD_R = 10.0
PAD_T = 8.0
LEGEND_H = 16.0
DOT_D = 7.0


def play_entrance_fade(widget: QWidget) -> None:
    """One-shot opacity entrance gated on behavior.motion_enabled; effect is
    detached in finished so steady state stays effect-free (motion-system.md).
    Animation ref is held on the widget as a GC guard."""
    if not mt.is_motion_enabled():
        return
    try:
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(mt.duration_base)
        anim.setEasingCurve(mt.curve_enter)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def _detach():
            try:
                widget.setGraphicsEffect(None)
            except RuntimeError:
                pass

        anim.finished.connect(_detach)
        widget._entrance_anim = anim
        anim.start()
    except RuntimeError:
        pass


class MoodTrendChart(QWidget):
    """Paints up to `days` trailing days of mood ordinals; missing days stay
    empty gaps and line segments never bridge them."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._days = 14
        self._values: Dict[int, str] = {}  # day index (0=oldest) -> mood
        self._today: Optional[date_cls] = datetime.now().date()
        self.setMouseTracking(True)
        self.setMinimumHeight(48)

    # ---------------- data ----------------
    def set_moods(self, rows: List[Dict[str, str]], days: int = 14) -> None:
        """rows: [{'date': 'YYYY-MM-DD', 'mood': str}, ...] any order; when a
        day has several captures the FIRST row seen wins (get_moods_since
        returns ts DESC, so that is the latest capture's mood)."""
        self._days = max(2, int(days))
        today = datetime.now().date()
        self._today = today
        start = today - timedelta(days=self._days - 1)
        by_day: Dict[date_cls, str] = {}
        for r in rows or []:
            mood = r.get("mood")
            if mood not in MOOD_COLORS:
                continue
            try:
                d = datetime.strptime(r.get("date", ""), "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            if start <= d <= today:
                by_day.setdefault(d, mood)
        self._values = {(d - start).days: m for d, m in by_day.items()}
        self.update()

    # ---------------- geometry ----------------
    def _date_for(self, idx: int) -> Optional[date_cls]:
        if self._today is None:
            return None
        return self._today - timedelta(days=(self._days - 1 - idx))

    def _plot_rect(self) -> QRectF:
        w = max(20.0, self.width() - PAD_L - PAD_R)
        h = max(12.0, self.height() - PAD_T - LEGEND_H - 2.0)
        return QRectF(PAD_L, PAD_T, w, h)

    def _center_for(self, idx: int, ordinal: int) -> QPointF:
        r = self._plot_rect()
        step_x = r.width() / (self._days - 1)
        step_y = r.height() / max(1, len(MOOD_ORDER) - 1)
        return QPointF(r.left() + idx * step_x, r.top() + ordinal * step_y)

    def _nearest(self, pos: QPointF) -> int:
        best, best_d = -1, 144.0  # 12px hit radius (squared)
        for idx in range(self._days):
            mood = self._values.get(idx)
            if mood is None:
                continue
            c = self._center_for(idx, MOOD_ORDER.index(mood))
            dx = pos.x() - c.x()
            dy = pos.y() - c.y()
            d = dx * dx + dy * dy
            if d < best_d:
                best, best_d = idx, d
        return best

    # ---------------- painting ----------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        v = theme_vars()

        if not self._values:
            p.setPen(QColor(v["on_surface_variant"]))
            f = p.font()
            f.setPixelSize(10)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, "No mood data yet")
            p.end()
            return

        line_color = QColor(v["on_surface_variant"])
        line_color.setAlphaF(0.35)

        # Segments between consecutive present days only — gaps break lines.
        pen = QPen(line_color)
        pen.setWidthF(1.2)
        p.setPen(pen)
        prev_idx: Optional[int] = None
        for idx in sorted(self._values):
            if prev_idx is not None and idx == prev_idx + 1:
                a = self._center_for(prev_idx, MOOD_ORDER.index(self._values[prev_idx]))
                b = self._center_for(idx, MOOD_ORDER.index(self._values[idx]))
                p.drawLine(a, b)
            prev_idx = idx

        halo = QColor(v["surface_container_low"])
        primary = QColor(v["primary"])
        for idx, mood in self._values.items():
            c = self._center_for(idx, MOOD_ORDER.index(mood))
            dot = QRectF(0.0, 0.0, DOT_D, DOT_D)
            dot.moveCenter(c)
            pen = QPen(halo)
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.setBrush(QColor(MOOD_COLORS[mood]))
            p.drawEllipse(dot)
            if self._date_for(idx) == self._today:
                ring = QRectF(0.0, 0.0, DOT_D + 7.0, DOT_D + 7.0)
                ring.moveCenter(c)
                pen = QPen(primary)
                pen.setWidthF(1.5)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(ring)

        self._paint_legend(p, v)
        p.end()

    def _paint_legend(self, p: QPainter, v) -> None:
        f = p.font()
        f.setPixelSize(9)
        p.setFont(f)
        fm = QFontMetrics(f)
        text_color = QColor(v["on_surface_variant"])
        yc = self.height() - LEGEND_H / 2.0
        x = PAD_L
        for mood in MOOD_ORDER:
            if x + DOT_D > self.width():
                break
            dot = QRectF(0.0, 0.0, 5.0, 5.0)
            dot.moveCenter(QPointF(x + 2.5, yc))
            pen = QPen(QColor(v["outline_variant"]))
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.setBrush(QColor(MOOD_COLORS[mood]))
            p.drawEllipse(dot)
            x += 8.0
            label_w = fm.horizontalAdvance(mood)
            if x + label_w > self.width():
                continue  # no room for this label; keep scanning dots
            p.setPen(text_color)
            rect = QRectF(x, yc - fm.height() / 2.0, label_w + 2, float(fm.height()))
            p.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, mood)
            x += label_w + 8.0

    # ---------------- interaction ----------------
    def mouseMoveEvent(self, event):
        idx = self._nearest(event.position())
        if 0 <= idx < self._days and idx in self._values:
            d = self._date_for(idx)
            tip = f"{d.strftime('%b %d, %Y')} — {self._values[idx]}" if d else ""
        else:
            tip = ""
        if tip != self.toolTip():
            self.setToolTip(tip)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.setToolTip("")
        super().leaveEvent(event)
