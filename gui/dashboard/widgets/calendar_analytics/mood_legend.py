# gui/dashboard/widgets/calendar_analytics/mood_legend.py
"""
MoodLegend — horizontal legend strip for the calendar data-viz layer.
Solid dots = mood (fixed MOOD_COLORS hexes); hollow circle = no-mood.
"""
from __future__ import annotations

from typing import List

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from gui.theme.theme_vars import theme_vars
from .viz_types import MOOD_COLORS, MOOD_ORDER


class MoodDotLabel(QWidget):
    """Tiny custom-painted dot: filled mood color or hollow ring."""

    def __init__(self, hex: str = None, parent=None):
        super().__init__(parent)
        self._hex = hex
        self.setFixedSize(12, 12)

    def apply_theme(self):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        v = theme_vars()
        r = QRectF(2.0, 2.0, 8.0, 8.0)
        if self._hex:
            pen = QPen(QColor(v["surface_container_low"]))
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.setBrush(QColor(self._hex))
        else:
            pen = QPen(QColor(v["outline_variant"]))
            pen.setWidthF(1.5)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
        p.drawEllipse(r)
        p.end()


class MoodLegend(QFrame):
    """Strip: [● Great ● Good ● Neutral ● Bad ● Awful ○ No mood]."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MoodLegend")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._labels: List[QLabel] = []
        self._dots: List[MoodDotLabel] = []

        for mood in MOOD_ORDER:
            dot = MoodDotLabel(MOOD_COLORS[mood])
            lbl = QLabel(mood)
            row.addWidget(dot)
            row.addWidget(lbl)
            self._dots.append(dot)
            self._labels.append(lbl)

        hollow = MoodDotLabel(None)
        hollow_lbl = QLabel("No mood")
        row.addSpacing(4)
        row.addWidget(hollow)
        row.addWidget(hollow_lbl)
        self._dots.append(hollow)
        self._labels.append(hollow_lbl)
        row.addStretch()

        self.apply_theme()

    def apply_theme(self):
        v = theme_vars()
        for lbl in self._labels:
            lbl.setStyleSheet(f"""
                color: {v['on_surface_variant']};
                font-size: 10px;
            """)
        for dot in self._dots:
            dot.apply_theme()
