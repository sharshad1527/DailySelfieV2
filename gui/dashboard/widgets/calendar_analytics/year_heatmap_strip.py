# gui/dashboard/widgets/calendar_analytics/year_heatmap_strip.py
"""
YearHeatmapStrip — ONE custom-painted QWidget rendering a full year of
capture activity (~371 rects in a single paintEvent pass; NO widget-per-tile).

- Intensity fills: rgba(primary, .35 / .60 / 1.0); empty = surface_container_lowest.
- Hover column highlight (outline_variant border) via setMouseTracking.
- Click emits weekClicked(iso_week, anchor_date) where anchor_date is the
  ISO week's Thursday.
- Partial ISO edge weeks render partial columns.
- Weekday gutter is auto-sized from QFontMetrics (full Mon/Wed/Fri when it
  fits within LABEL_GUTTER_MAX px, else single letters); labels are drawn
  right-aligned inside [origin.x, grid_start) so they can never clip at the
  widget's left edge.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime, timedelta
from typing import Dict, Optional

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from gui.theme.theme_vars import theme_vars
from .viz_types import MOOD_COLORS, paint_mood_dot

CELL = 12
GAP = 3
PAD = 4
LABEL_FONT_PX = 9
LABEL_GUTTER_PAD = 5   # breathing room between the widest label and the dots
LABEL_GUTTER_MAX = 40  # keep full Mon/Wed/Fri while the gutter stays <= this

_WEEKDAY_ROWS_FULL = ((0, "Mon"), (2, "Wed"), (4, "Fri"))
_WEEKDAY_ROWS_SHORT = ((0, "M"), (2, "W"), (4, "F"))


def _monday_on_or_before(d: date_cls) -> date_cls:
    return d - timedelta(days=d.weekday())


class YearHeatmapStrip(QWidget):
    weekClicked = Signal(int, object)  # iso_week, anchor QDate-like date

    def __init__(self, parent=None):
        super().__init__(parent)
        self._year: Optional[int] = None
        self._activity: Dict[str, int] = {}
        self._moods: Dict[str, str] = {}
        self._today: Optional[date_cls] = None
        self._hover_col = -1
        self._label_rows, self._gutter_w = self._resolve_labels()
        self.setMouseTracking(True)
        self.setMinimumHeight(7 * CELL + 6 * GAP + PAD * 2)
        self.setMinimumWidth(self._grid_width() + PAD * 2)

    # ---------------- label gutter ----------------
    def _label_font(self) -> QFont:
        f = self.font()
        f.setPixelSize(LABEL_FONT_PX)
        return f

    def _resolve_labels(self):
        """Pick Mon/Wed/Fri vs M/W/F from measured text width.

        Returns (rows, gutter_w) where gutter_w is the widest label advance
        plus LABEL_GUTTER_PAD — no magic numbers.
        """
        fm = QFontMetrics(self._label_font())
        full_w = (max(fm.horizontalAdvance(t) for _, t in _WEEKDAY_ROWS_FULL)
                  + LABEL_GUTTER_PAD)
        if full_w <= LABEL_GUTTER_MAX:
            return _WEEKDAY_ROWS_FULL, full_w
        short_w = (max(fm.horizontalAdvance(t) for _, t in _WEEKDAY_ROWS_SHORT)
                   + LABEL_GUTTER_PAD)
        return _WEEKDAY_ROWS_SHORT, short_w

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.FontChange:
            self._label_rows, self._gutter_w = self._resolve_labels()
            self.setMinimumWidth(self._grid_width() + PAD * 2)
            self.update()
        super().changeEvent(event)

    # ---------------- data ----------------
    def set_year_data(self, year: int, activity: Dict[str, int],
                      moods: Dict[str, str], today: date_cls) -> None:
        self._year = year
        self._activity = dict(activity or {})
        self._moods = dict(moods or {})
        self._today = today
        self._hover_col = -1
        self.update()

    # ---------------- geometry helpers ----------------
    def _grid_width(self) -> int:
        return self._gutter_w + 53 * CELL + 52 * GAP

    def _origin(self) -> QPoint:
        w = self.width()
        x = max(PAD, (w - self._grid_width()) // 2)
        y = PAD
        return QPoint(x, y)

    def _cell_rect(self, col: int, row: int) -> QRectF:
        o = self._origin()
        x = o.x() + self._gutter_w + col * (CELL + GAP)
        y = o.y() + row * (CELL + GAP)
        return QRectF(float(x), float(y), float(CELL), float(CELL))

    def _col_for_date(self, d: date_cls) -> Optional[int]:
        if self._year is None or d.year != self._year:
            return None
        first_mon = _monday_on_or_before(date_cls(self._year, 1, 1))
        col = (d - first_mon).days // 7
        return col if 0 <= col < 53 else None

    def _date_for_cell(self, col: int, row: int) -> Optional[date_cls]:
        if self._year is None:
            return None
        first_mon = _monday_on_or_before(date_cls(self._year, 1, 1))
        d = first_mon + timedelta(days=col * 7 + row)
        return d if d.year == self._year else None

    # ---------------- painting ----------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        v = theme_vars()

        empty = QColor(v["surface_container_lowest"])
        primary = QColor(v["primary"])
        outline_var = QColor(v["outline_variant"])

        fills = [empty]
        for alpha in (0.35, 0.60, 1.0):
            c = QColor(primary)
            c.setAlphaF(alpha)
            fills.append(c)

        # Weekday labels (Mon / Wed / Fri rows), right-aligned inside the
        # gutter so the text box always starts at or after origin.x (>= PAD):
        # never clipped at the widget's left edge, never under the dots.
        p.setPen(QColor(v["on_surface_variant"]))
        p.setFont(self._label_font())
        o = self._origin()
        label_box_w = self._gutter_w - GAP
        for row, label in self._label_rows:
            cell = self._cell_rect(0, row)
            box = QRectF(float(o.x()), cell.top() - 2,
                         float(label_box_w), cell.height() + 4)
            p.drawText(box, Qt.AlignVCenter | Qt.AlignRight, label)

        if self._year is not None:
            for col in range(53):
                for row in range(7):
                    d = self._date_for_cell(col, row)
                    if d is None:
                        continue  # partial edge weeks render partial columns
                    ds = d.isoformat()
                    count = self._activity.get(ds, 0)
                    level = min(count, 3)
                    rect = self._cell_rect(col, row)
                    p.setPen(Qt.NoPen)
                    p.setBrush(fills[max(level, 0)])
                    p.drawRoundedRect(rect, 3, 3)
                    mood = self._moods.get(ds)
                    if mood in MOOD_COLORS and count > 0:
                        paint_mood_dot(p, rect, MOOD_COLORS[mood], empty,
                                       d=max(3, CELL // 3))

            # Hovered week highlight
            if 0 <= self._hover_col < 53:
                pen = QPen(outline_var)
                pen.setWidthF(1.0)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                first = self._cell_rect(self._hover_col, 0).adjusted(-2, -2, 2, 2)
                last_cell = self._cell_rect(self._hover_col, 6)
                bottom_space = max(0.0, self.height() - last_cell.bottom())
                last = last_cell.adjusted(-2, 2, 2, min(float(PAD), bottom_space))
                p.drawRoundedRect(first.united(last), 4, 4)
        p.end()

    # ---------------- interaction ----------------
    def _hit(self, pos: QPoint):
        o = self._origin()
        gx = pos.x() - o.x() - self._gutter_w
        gy = pos.y() - o.y()
        if gx < 0 or gy < 0:
            return None
        col = gx // (CELL + GAP)
        row = gy // (CELL + GAP)
        fx = gx % (CELL + GAP)
        fy = gy % (CELL + GAP)
        if fx > CELL or fy > CELL or col >= 53 or row >= 7:
            return None
        return int(col), int(row)

    def mouseMoveEvent(self, event):
        hit = self._hit(event.position().toPoint())
        col = hit[0] if hit else -1
        if col != self._hover_col:
            old_col = self._hover_col
            self._hover_col = col
            for c in {old_col, col}:
                if 0 <= c < 53:
                    first = self._cell_rect(c, 0).adjusted(-4, -4, 4, 4)
                    last = self._cell_rect(c, 6).adjusted(-4, 0, 4, 10)
                    self.update(first.united(last).toAlignedRect())
            if hit and self._year is not None:
                d = self._date_for_cell(col, hit[1])
                if d is not None:
                    n = self._activity.get(d.isoformat(), 0)
                    tip = f"{d.strftime('%b %d, %Y')} — {n} capture{'s' if n != 1 else ''}"
                    self.setToolTip(tip)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover_col != -1:
            c = self._hover_col
            self._hover_col = -1
            first = self._cell_rect(c, 0).adjusted(-4, -4, 4, 4)
            last = self._cell_rect(c, 6).adjusted(-4, 0, 4, 10)
            self.update(first.united(last).toAlignedRect())
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        hit = self._hit(event.position().toPoint())
        if hit and self._year is not None:
            col, _row = hit
            # Anchor on the ISO week's Thursday (row 3 = Thursday, Monday-first);
            # edge weeks whose Thursday is out-of-year fall back to the first
            # in-year cell in the column.
            anchor = self._date_for_cell(col, 3)
            if anchor is None:
                for r in range(7):
                    d = self._date_for_cell(col, r)
                    if d is not None:
                        anchor = d
                        break
            if anchor is not None:
                self.weekClicked.emit(anchor.isocalendar()[1], anchor)
        super().mousePressEvent(event)
