# gui/widgets/recap/cards/clock_viz.py
"""
ClockVizCard — one paintEvent draws a 24h dial: a dot per capture hour
(colored by the dominant mood hex, else primary), an arc highlighting the
peak hour, and night/morning/afternoon/evening band counts beside it.
"""
from __future__ import annotations

import math
from typing import Dict, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gui.dashboard.widgets.calendar_analytics.viz_types import MOOD_COLORS
from gui.theme.theme_vars import theme_vars

from .base import RecapCardBase, _d, _int

BANDS = (
    ("Night", range(22, 24), range(0, 5)),
    ("Morning", range(5, 11), ()),
    ("Afternoon", range(11, 17), ()),
    ("Evening", range(17, 22), ()),
)


class ClockVizCard(RecapCardBase):
    CARD_KIND = "clock"

    def build_content(self):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        title = QLabel("Capture clock")
        title.setObjectName("CardTitle")
        caption = QLabel("When you usually show up.")
        caption.setObjectName("CardCaption")
        lay.addWidget(title)
        lay.addWidget(caption)
        self.add_section(box)
        dial = QWidget()
        dial.setMinimumHeight(300)
        self._dial = dial
        self.add_section(dial)
        self._lay.addStretch()

    def _histogram(self) -> Dict[int, int]:
        raw = _d(self._data, "hours")
        out: Dict[int, int] = {}
        if isinstance(raw, dict):
            for k, c in raw.items():
                h = _int(k, -1)
                if 0 <= h <= 23:
                    n = _int(c)
                    if n > 0:
                        out[h] = out.get(h, 0) + n
        peak = _d(self._data, "favorite_hour")
        if not out and peak is not None:
            h = _int(peak, -1)
            if 0 <= h <= 23:
                out[h] = 1
        return out

    def _peak_hour(self) -> Optional[int]:
        hist = self._histogram()
        if not hist:
            return None
        mx = max(hist.values())
        return min(h for h, c in hist.items() if c == mx)

    def _mood_hex(self) -> str:
        dom = str(_d(self._data, "dominant_mood", ""))
        return MOOD_COLORS.get(dom, theme_vars()["primary"])

    @staticmethod
    def _band_counts(hist: Dict[int, int]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for name, *ranges in BANDS:
            total = 0
            for rng in ranges:
                for h in rng:
                    total += hist.get(h, 0)
            counts[name] = total
        return counts

    def _dial_geometry(self) -> tuple:
        """(dial QRectF, arc_r) — pure so probes assert the painted geometry."""
        side = min(self.width() * 0.52, self.height() - 96.0)
        side = max(side, 120.0)
        cx = self.width() * 0.30
        cy = self.height() * 0.56
        dial = QRectF(cx - side / 2, cy - side / 2, side, side)
        arc_r = self._arc_radius(side / 2, cx)
        return dial, arc_r

    def _arc_radius(self, dial_r: float, cx: float) -> float:
        """Peak-arc radius clamped to leave a gutter before the band labels.

        The unclamped dial_r + 5 overshoots into the label column at narrow
        widths; clamp (floored at the rim so the arc never sinks inside the
        dial face).
        """
        limit = self.width() * 0.58 - 6.0 - cx
        return max(dial_r, min(dial_r + 5.0, limit))

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        v = theme_vars()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(v["surface_container_high"]))
        p.drawRoundedRect(self.rect(), 22, 22)

        dial, arc_r = self._dial_geometry()
        side = dial.width()
        cx = dial.center().x()
        cy = dial.center().y()

        pen = QPen(theme_vars().rgba("outline_variant", 0.9))
        pen.setWidthF(1.5)
        p.setPen(pen)
        p.setBrush(QColor(v["surface_container_highest"]))
        p.drawEllipse(dial)

        f = QFont(self.font())
        f.setPixelSize(10)
        p.setFont(f)
        p.setPen(QColor(v["on_surface_variant"]))
        for hour, label in ((0, "00"), (6, "06"), (12, "12"), (18, "18")):
            ang = math.radians(hour * 15.0 - 90.0)
            lx = dial.center().x() + math.cos(ang) * (side / 2 - 12)
            ly = dial.center().y() + math.sin(ang) * (side / 2 - 12)
            p.drawText(QRectF(lx - 12, ly - 8, 24, 16),
                       Qt.AlignCenter, label)

        hist = self._histogram()
        peak = self._peak_hour()
        if peak is not None:
            pen = QPen(QColor(v["tertiary"]))
            pen.setWidthF(4.0)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            span_deg = 30.0
            start = peak * 15.0 - 90.0 - span_deg / 2
            arc_rect = QRectF(dial.center().x() - arc_r, dial.center().y() - arc_r,
                              arc_r * 2, arc_r * 2)
            p.drawArc(arc_rect, int(start * 16), int(span_deg * 16))

        max_count = max(hist.values()) if hist else 1
        dot_hex = self._mood_hex()
        for hour, count in sorted(hist.items()):
            frac = math.sqrt(count / max_count) if max_count else 0.3
            radius = 4.0 + 9.0 * frac
            dist = side / 2 - 18 - 14 * frac
            ang = math.radians(hour * 15.0 - 90.0)
            pos = QPointF(dial.center().x() + math.cos(ang) * dist,
                          dial.center().y() + math.sin(ang) * dist)
            p.setPen(QPen(theme_vars().rgba("outline_variant", 0.95)))
            p.setBrush(QColor(dot_hex))
            p.drawEllipse(pos, radius, radius)

        bands = self._band_counts(hist)
        f2 = QFont(self.font())
        f2.setPixelSize(13)
        f2.setWeight(QFont.DemiBold)
        p.setFont(f2)
        list_x = self.width() * 0.58
        row_y = cy - 64
        for i, (name, count) in enumerate(bands.items()):
            y = row_y + i * 34
            p.setPen(QColor(v["on_surface_variant"]))
            f3 = QFont(self.font())
            f3.setPixelSize(11)
            p.setFont(f3)
            p.drawText(QRectF(list_x, y, 110, 14), Qt.AlignLeft | Qt.AlignVCenter, name)
            p.setFont(f2)
            p.setPen(QColor(v["on_surface"]))
            p.drawText(QRectF(list_x, y + 12, 110, 20), Qt.AlignLeft | Qt.AlignVCenter,
                       str(count))
        p.end()

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
        self.update()
