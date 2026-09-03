# gui/widgets/recap/cards/streak_card.py
"""
StreakCard — count-up current-streak numeral, best-run span track with
per-day dots, tertiary ring when today is captured, milestone chips.
"""
from __future__ import annotations

from typing import List

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gui.theme.theme_vars import theme_vars

from .base import RecapCardBase, PaintedScalar, _d, _int

MAX_TRACK_DOTS = 60
TRACK_H = 92


class _BestRunTrack(QWidget):
    """Best-run span track as a real layout child: the band it paints is
    reserved by the layout, so it can never collide with the numeral or chips
    at any card height (previously painted at a hardcoded y with no
    reservation)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._best = 0
        self.setFixedHeight(TRACK_H)

    def set_best(self, best: int) -> None:
        self._best = max(0, int(best))
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        v = theme_vars()
        track = QRectF(0.0, 0.0, self.width(), float(TRACK_H))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(v["surface_container_highest"]))
        p.drawRoundedRect(track, 12, 12)

        label_f = QFont(self.font())
        label_f.setPixelSize(11)
        label_f.setWeight(QFont.DemiBold)
        p.setFont(label_f)
        p.setPen(QColor(v["on_surface_variant"]))
        p.drawText(QRectF(track.left(), track.top() + 8, track.width(), 14),
                   Qt.AlignHCenter | Qt.AlignVCenter, "BEST RUN")

        dots_n = min(max(self._best, 1), MAX_TRACK_DOTS)
        area = QRectF(track.left() + 14, track.top() + 28,
                      track.width() - 28, track.height() - 38)
        dot_d = max(3.0, min(7.0, area.width() / max(dots_n * 1.6, 1)))
        gap = (area.width() - dot_d) / max(dots_n - 1, 1) if dots_n > 1 else 0.0
        for i in range(dots_n):
            x = area.left() + i * gap
            y = area.center().y() - dot_d / 2
            reached = i < min(self._best, MAX_TRACK_DOTS)
            p.setPen(theme_vars().rgba("outline_variant", 0.9))
            p.setBrush(QColor(v["primary"] if reached else Qt.transparent))
            p.drawEllipse(QRectF(x, y, dot_d, dot_d))

        sub = f"{self._best} days" if self._best > 0 else "no runs yet"
        p.setPen(QColor(v["on_surface"]))
        p.drawText(QRectF(track.left(), track.bottom() - 20, track.width(), 16),
                   Qt.AlignHCenter | Qt.AlignVCenter, sub)


class StreakCard(RecapCardBase):
    CARD_KIND = "streak"

    def build_content(self):
        self.add_section(self._make_title())

        numeral = QWidget()
        num_lay = QHBoxLayout(numeral)
        num_lay.setContentsMargins(0, 6, 0, 6)
        current = _int(_d(_d(self._data, "streaks", {}), "current"))
        best = _int(_d(_d(self._data, "streaks", {}), "best"))
        self._current = max(0, current)
        self._best = max(best, self._current)
        self._scalar = PaintedScalar(font_px=88, color_key="on_surface")
        self._scalar.setMinimumWidth(int(self._scalar.minimumHeight() * 1.4))
        num_lay.addWidget(self._scalar)
        unit_box = QWidget()
        unit_lay = QVBoxLayout(unit_box)
        unit_lay.setContentsMargins(10, 14, 0, 0)
        unit_lay.setSpacing(2)
        self._unit_lbl = QLabel("day\nstreak")
        self._unit_lbl.setObjectName("UnitLabel")
        self._unit_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        unit_lay.addWidget(self._unit_lbl)
        num_lay.addWidget(unit_box)
        num_lay.addStretch()
        self.add_section(numeral)
        self._scalar.set_target(self._current)

        self.add_section(self._make_milestones())

        self._track = _BestRunTrack()
        self._track.set_best(self._best)
        self.add_section(self._track)
        self._lay.addStretch()

    def _make_title(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        title = QLabel("Consistency run")
        title.setObjectName("CardTitle")
        caption = QLabel("Every capture keeps the chain alive.")
        caption.setObjectName("CardCaption")
        lay.addWidget(title)
        lay.addWidget(caption)
        return box

    def _milestone_titles(self) -> List[str]:
        ms = _d(self._data, "milestones", [])
        return [str(m) for m in ms] if isinstance(ms, (list, tuple)) else []

    def _make_milestones(self) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._milestone_chips: List[QLabel] = []
        for text in self._milestone_titles()[:3]:
            chip = QLabel(text)
            chip.setObjectName("MilestoneChip")
            lay.addWidget(chip)
            self._milestone_chips.append(chip)
        lay.addStretch()
        return box

    # ---- painting ------------------------------------------------------------
    def _ring_rect(self) -> QRectF:
        """Pill framing the painted numeral glyphs (card-local coords).

        Sized from QFontMetrics.horizontalAdvance of the formatted value at
        the paint font and centered on the glyph bounds — NOT the scalar's
        full widget box (which is wider than the AlignLeft glyphs and made
        the numeral poke through the left arc).
        """
        scalar = self._scalar
        origin = scalar.mapTo(self, QPoint(0, 0))
        g = scalar.glyph_rect().translated(origin.x(), origin.y())
        pad_x = min(18.0, max(g.width() * 0.18, 10.0))
        pill = g.adjusted(-pad_x, -10.0, pad_x, 10.0)
        # Keep the pill inside the scalar's reserved box so it never slides
        # under the unit label to the right.
        box = QRectF(origin.x(), origin.y(), scalar.width(), scalar.height())
        return pill.intersected(box)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        v = theme_vars()
        radius = 22.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(v["surface_container_high"]))
        p.drawRoundedRect(self.rect(), radius, radius)

        # Current-pill accent around the numeral when today is captured.
        if bool(_d(_d(self._data, "streaks", {}), "has_photo_today")):
            pill = self._ring_rect()
            if pill.isValid():
                pen = QPen(QColor(v["tertiary"]))
                pen.setWidthF(3.0)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)

        p.end()

    # ---- theme -----------------------------------------------------------------
    def apply_theme(self) -> None:
        v = theme_vars()
        accent_fill, accent_on = self.accent()
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
            QLabel#UnitLabel {{
                color: {v['on_surface_variant']};
                font-size: 15px;
                font-weight: 600;
            }}
            QLabel#MilestoneChip {{
                background-color: {accent_fill};
                color: {accent_on};
                border-radius: 11px;
                padding: 3px 12px;
                font-size: 11px;
                font-weight: 700;
            }}
        """)
        self.update()
