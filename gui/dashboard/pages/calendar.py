# gui/dashboard/pages/calendar.py
"""
CalendarPage — month grid, day-detail overlay and year data-viz layer per
docs/design/calendar-page.md. Motion per docs/design/motion-system.md C2/C3.
"""
from __future__ import annotations

import calendar as pycal
import math
import time as _time
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import (
    Property,
    QDate,
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QMovie,
    QPainter,
    QPainterPath,
    QPixmap,
    QPen,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.index_api import IndexAPI, get_api
from core.paths import AppPaths, get_app_paths
from core.storage import delete_path
from gui.theme import motion_tokens as mt
from gui.theme.theme_vars import theme_vars
from gui.widgets.error_popup import ErrorToast

from gui.dashboard.pages.dashboard import MOOD_GIF_MAP
from gui.dashboard.widgets.calendar_analytics.mood_legend import MoodLegend
from gui.dashboard.widgets.calendar_analytics.viz_types import (
    MOOD_COLORS,
    MOOD_ORDER,
    DayDecor,
    DecorationController,
    StreakState,
    TodayState,
    paint_mood_dot,
    paint_streak_ring,
)
from gui.dashboard.widgets.calendar_analytics.year_heatmap_strip import YearHeatmapStrip

_paths = get_app_paths("DailySelfie", ensure=False)
ICONS_DIR = _paths.project_root / "gui" / "assets" / "icons"
MOOD_DIR = ICONS_DIR / "mood"

TILE_RADIUS = 10
NOTE_TRUNCATE = 35


# -------------------------------------------------------------
# Shared helpers (patterns copied from pages/dashboard.py)
# -------------------------------------------------------------
def _create_colored_icon(icon_name: str, qcolor: QColor) -> QIcon:
    """Loads an SVG and repaints it with the given QColor."""
    path = ICONS_DIR / icon_name
    if not path.exists():
        return QIcon()
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return QIcon()
    colored_pixmap = QPixmap(pixmap.size())
    colored_pixmap.fill(Qt.transparent)
    painter = QPainter(colored_pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(colored_pixmap.rect(), qcolor)
    painter.end()
    return QIcon(colored_pixmap)


def _rounded_crop_pixmap(path: Optional[Path], w: int, h: int, radius: int) -> Optional[QPixmap]:
    """Crop-fill scaled rounded pixmap (TodaySelfieCard._update_selfie_image pattern)."""
    if not path or not path.exists():
        return None
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    scaled = pixmap.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    if scaled.width() > w or scaled.height() > h:
        x_off = (scaled.width() - w) // 2
        y_off = (scaled.height() - h) // 2
        scaled = scaled.copy(x_off, y_off, w, h)
    rounded = QPixmap(scaled.size())
    rounded.fill(Qt.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(0, 0, scaled.width(), scaled.height(), radius, radius)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    return rounded


def _utc_to_local(ts_value: str) -> Optional[datetime]:
    """UTC ISO ts -> local datetime (else late-night captures land wrong bucket)."""
    if not ts_value:
        return None
    try:
        return datetime.fromisoformat(ts_value.replace("Z", "+00:00")).astimezone()
    except (ValueError, TypeError):
        return None


def _format_time(metadata: Dict[str, Any]) -> str:
    """Local time-of-day string (TodaySelfieInfoBox pattern)."""
    dt_local = _utc_to_local(metadata.get("ts"))
    if dt_local:
        return dt_local.strftime("%I:%M %p")
    eid = metadata.get("id", "")
    if "_" in eid:
        time_part = eid.split("_")[-1]
        if len(time_part) == 6:
            try:
                hour = int(time_part[:2])
                ampm = "AM" if hour < 12 else "PM"
                hour = hour % 12 or 12
                return f"{hour}:{time_part[2:4]} {ampm}"
            except ValueError:
                pass
    return ""


def _secondary_button_style(v) -> str:
    """Secondary pill button (settings.py/_secondary_button_style verbatim)."""
    return f"""
        QPushButton {{
            background-color: {v['surface_container_high']};
            color: {v['on_surface_variant']};
            border: 1px solid {v['outline_variant']};
            border-radius: 16px;
            padding: 0 12px;
            font-size: 11px;
            font-weight: 500;
        }}
        QPushButton:hover {{
            background-color: {v['surface_container_highest']};
            border: 1px solid {v['outline']};
            color: {v['on_surface']};
        }}
    """


# -------------------------------------------------------------
# Small shared components
# -------------------------------------------------------------
class NavIconButton(QPushButton):
    """36x36 r18 icon button: transparent -> surface_container_high hover."""

    def __init__(self, icon_name: str, tooltip: str = "", parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self.setFixedSize(36, 36)
        self.setIconSize(QSize(18, 18))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)
        self.apply_theme()

    def set_active(self, enabled: bool):
        self.setEnabled(bool(enabled))

    def apply_theme(self):
        v = theme_vars()
        color = v.qcolor("on_surface_variant" if self.isEnabled() else "outline_variant")
        self.setIcon(_create_colored_icon(self._icon_name, color))
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 18px;
            }}
            QPushButton:hover {{
                background-color: {v['surface_container_high']};
            }}
            QPushButton:pressed {{
                background-color: {v['surface_container_highest']};
            }}
        """)


class ThumbLabel(QLabel):
    """Scaled rounded thumbnail (copy TodaySelfieCard._update_selfie_image pattern)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: transparent;")
        self._image_path: Optional[Path] = None
        self._radius = TILE_RADIUS
        self._placeholder = ""
        self._resize_gen = 0

    def set_image(self, image_path: Optional[Path], radius: int = TILE_RADIUS):
        self._image_path = image_path
        self._radius = radius
        self._reload()

    def set_placeholder(self, text: str):
        self._placeholder = text
        self._image_path = None
        self.setText(text)

    def _reload(self):
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        pix = _rounded_crop_pixmap(self._image_path, w, h, self._radius)
        if pix is not None:
            self.setText("")
            self.setPixmap(pix)
        else:
            self.setPixmap(QPixmap())
            self.setText(self._placeholder or "Photo unavailable")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._image_path is not None:
            self._resize_gen += 1
            gen = self._resize_gen
            QTimer.singleShot(30, lambda g=gen: self._debounced_reload(g))

    def _debounced_reload(self, gen: int):
        if gen != self._resize_gen:
            return
        try:
            self._reload()
        except RuntimeError:
            pass  # widget destroyed before timer fired


# -------------------------------------------------------------
# Detail: mood picker
# -------------------------------------------------------------
class MoodToggle(QWidget):
    """One mood GIF toggle; selected = primary ring."""

    selected = Signal(str)

    def __init__(self, mood: str, parent=None):
        super().__init__(parent)
        self.mood = mood
        self._selected = False
        self._hovered = False
        self._movie = None
        self.setFixedSize(46, 46)
        self.setCursor(Qt.PointingHandCursor)

        gif_name = MOOD_GIF_MAP.get(mood)
        if gif_name:
            movie = QMovie(str(MOOD_DIR / gif_name))
            if movie.isValid():
                movie.setScaledSize(QSize(30, 30))
                movie.frameChanged.connect(self.update)  # auto-disconnects on destroy
                movie.start()
                self._movie = movie

    def set_selected(self, selected: bool):
        if self._selected != bool(selected):
            self._selected = bool(selected)
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        v = theme_vars()
        rect = QRectF(0, 0, self.width(), self.height())
        if self._selected:
            pen = QPen(v.qcolor("primary"))
            pen.setWidthF(2.0)
            p.setPen(pen)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 14, 14)
        elif self._hovered:
            p.setPen(Qt.NoPen)
            p.setBrush(v.rgba("on_surface", 0.08))
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 14, 14)
        frame = self._movie.currentPixmap() if self._movie else QPixmap()
        if not frame.isNull():
            p.drawPixmap((self.width() - frame.width()) // 2,
                         (self.height() - frame.height()) // 2, frame)
        p.end()

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.set_selected(True)
            self.selected.emit(self.mood)


class MoodPickerRow(QWidget):
    """5 mood GIF toggles (MOOD_GIF_MAP); single-select. Emits moodSelected(str)."""

    moodSelected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._toggles: List[MoodToggle] = []
        for mood in MOOD_ORDER:
            t = MoodToggle(mood)
            t.selected.connect(self._on_selected)
            row.addWidget(t)
            self._toggles.append(t)
        row.addStretch()

    def _on_selected(self, mood: str):
        for t in self._toggles:
            t.set_selected(t.mood == mood)
        self.moodSelected.emit(mood)

    def select_mood(self, mood: Optional[str]):
        for t in self._toggles:
            t.set_selected(t.mood == mood)

    def current_mood(self) -> Optional[str]:
        for t in self._toggles:
            if t._selected:
                return t.mood
        return None


# -------------------------------------------------------------
# Month grid: day tile (custom painted per motion C2)
# -------------------------------------------------------------
class TileState:
    EMPTY_MONTH_DAY = 0
    OTHER_MONTH = 1
    TODAY = 2
    CAPTURED = 3
    BROKEN = 4


class DayTile(QFrame):
    """Day cell. Fully custom-painted so hover paint-scale stays consistent.

    Coordination hooks (Squad A/B): set_mood(), set_in_streak(),
    set_today_state(), set_future().
    """

    clicked = Signal(QDate)

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.setFocusPolicy(Qt.NoFocus)
        self.setMinimumSize(56, 36)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

        self.day: Optional[date_cls] = None
        self.captures: List[Dict[str, Any]] = []
        self.state = TileState.EMPTY_MONTH_DAY
        self.broken = False
        self.decor = DayDecor()
        self.focused = False

        self._hover_progress = 0.0
        self._pressed = False
        self._today_progress = 0.0
        self._pulse_alpha = 1.0
        self._thumb: Optional[QPixmap] = None
        self._thumb_path: Optional[Path] = None
        self._notes_icon: Optional[QPixmap] = None
        self._reload_cb: Optional[Callable[[], None]] = None
        self._resize_gen = 0

        self._hover_anim = QPropertyAnimation(self, b"hoverProgress")
        self._lift_anim = QPropertyAnimation(self, b"pos")
        self._today_anim = QPropertyAnimation(self, b"todayProgress")
        self._today_anim.setDuration(mt.duration_base)
        self._today_anim.setEasingCurve(mt.curve_enter)

    # ----- coordination hooks -----
    def set_mood(self, mood: Optional[str]):
        self.decor.mood = mood if mood in MOOD_COLORS else None
        self.update()

    def set_in_streak(self, state: StreakState):
        self.decor.streak = state
        self.update()

    def set_today_state(self, state: TodayState):
        prev = self.decor.today
        self.decor.today = state
        if state != TodayState.NOT_TODAY and prev == TodayState.NOT_TODAY and mt.is_motion_enabled():
            self._today_anim.stop()
            self._today_anim.setStartValue(0.5)
            self._today_anim.setEndValue(1.0)
            self._today_anim.start()
        elif state == TodayState.NOT_TODAY:
            self._today_anim.stop()
            self._today_progress = 0.0
        self.update()

    def set_future(self, future: bool):
        self.decor.future = bool(future)
        self.update()

    # ----- data binding -----
    def set_cell(self, day: date_cls, other_month: bool,
                 captures: List[Dict[str, Any]], reload_cb=None):
        self.day = day
        self.captures = list(captures)
        self._reload_cb = reload_cb
        self.broken = False
        self._thumb = None
        self._thumb_path = None
        today = date_cls.today()
        if other_month:
            self.state = TileState.OTHER_MONTH
        elif captures:
            last = captures[-1]
            path = Path(last.get("path") or "")
            if not path.exists():
                self.state = TileState.BROKEN
                self.broken = True
            else:
                self.state = TileState.CAPTURED
                self._thumb_path = path
        elif day == today:
            self.state = TileState.TODAY
        else:
            self.state = TileState.EMPTY_MONTH_DAY
        self.update()

    def mark_broken(self):
        """Missing/corrupt image discovered at load time."""
        if not self.broken and self.state in (TileState.CAPTURED, TileState.BROKEN):
            self.state = TileState.BROKEN
            self.broken = True
            self._thumb = None
            self.update()

    def apply_thumb(self, pix: Optional[QPixmap]):
        if pix is None or pix.isNull():
            self.mark_broken()
        else:
            self._thumb = pix
            self.update()

    def is_clickable(self) -> bool:
        return self.state != TileState.OTHER_MONTH and not self.decor.future

    def set_focused(self, focused: bool):
        if self.focused != focused:
            self.focused = focused
            self.update()

    def qdate(self) -> QDate:
        return QDate(self.day.year, self.day.month, self.day.day) if self.day else QDate()

    # ----- animated properties (NavButton fillProgress mechanism) -----
    def _get_hover(self) -> float:
        return self._hover_progress

    def _set_hover(self, value: float):
        self._hover_progress = float(value)
        self.update()

    hoverProgress = Property(float, _get_hover, _set_hover)

    def _get_today(self) -> float:
        return self._today_progress

    def _set_today(self, value: float):
        self._today_progress = float(value)
        ring = self.rect().adjusted(0, 0, 0, 0)
        self.update(ring)

    todayProgress = Property(float, _get_today, _set_today)

    def _animate_hover(self, target: float):
        rising = target > self._hover_progress
        if not mt.is_motion_enabled():
            self._hover_anim.stop()
            self._hover_progress = target
            self.update()
            return
        self._hover_anim.stop()
        self._hover_anim.setDuration(mt.duration_fast)
        self._hover_anim.setEasingCurve(mt.curve_enter if rising else mt.curve_exit)
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def reset_motion(self):
        """Clear lift/hover state (month rebind repositions tiles)."""
        self._base_y = None
        self._hover_anim.stop()
        self._lift_anim.stop()
        self._pressed = False
        if self._hover_progress != 0.0:
            self._hover_progress = 0.0
            self.update()

    def _animate_lift(self, up: bool):
        if not mt.is_motion_enabled():
            return
        if getattr(self, "_base_y", None) is None:
            self._base_y = self.y()
        base_y = self._base_y
        self._lift_anim.stop()
        self._lift_anim.setDuration(mt.duration_fast)
        self._lift_anim.setEasingCurve(mt.curve_enter if up else mt.curve_exit)
        self._lift_anim.setStartValue(self.pos())
        self._lift_anim.setEndValue(QPoint(self.x(), base_y - 2 if up else base_y))
        self._lift_anim.start()

    # ----- events -----
    def enterEvent(self, event):
        if getattr(self, "_base_y", None) is None:
            self._base_y = self.y()
        self._animate_hover(1.0)
        self._animate_lift(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._pressed = False
        self._animate_hover(0.0)
        self._animate_lift(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_clickable():
            self._pressed = True
            self._hover_anim.stop()
            self._hover_progress = 0.0
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        was_pressed = self._pressed
        self._pressed = False
        if was_pressed and self.is_clickable() and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.qdate())
        self.update()
        super().mouseReleaseEvent(event)

    def request_reload(self):
        if self._reload_cb is not None:
            self._reload_cb()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._thumb_path is not None:
            self._resize_gen += 1
            gen = self._resize_gen
            QTimer.singleShot(30, lambda g=gen: self._debounced_reload(g))

    def _debounced_reload(self, gen: int):
        if gen != self._resize_gen:
            return
        try:
            self.request_reload()
        except RuntimeError:
            pass  # tile destroyed before timer fired

    # ----- painting -----
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        v = theme_vars()

        # Hover paint-scale 1.00 -> 1.02 center-origin (C2)
        scale = 1.0 + 0.02 * self._hover_progress
        if self._pressed:
            scale = 1.0
        rect = QRectF(self.rect())
        p.save()
        if abs(scale - 1.0) > 0.001:
            center = rect.center()
            p.translate(center)
            p.scale(scale, scale)
            p.translate(-center)
            p.setClipRect(rect.adjusted(-8, -8, 8, 8))

        clickable = self.is_clickable()
        hovered_fill = self._hover_progress > 0.01 and clickable

        # Background per state
        if self.state == TileState.OTHER_MONTH:
            pass  # dimmed: no fill, faded text below
        elif self.state == TileState.CAPTURED and self._thumb is not None:
            if hovered_fill:
                p.setPen(Qt.NoPen)
                p.setBrush(v.qcolor("surface_container_high"))
                p.drawRoundedRect(rect, TILE_RADIUS, TILE_RADIUS)
        else:
            p.setPen(Qt.NoPen)
            if hovered_fill:
                p.setBrush(v.qcolor("surface_container_high"))
            else:
                p.setBrush(v.qcolor("surface_container_low"))
            p.drawRoundedRect(rect, TILE_RADIUS, TILE_RADIUS)

        # Captured thumb (rounded crop-fill r10) or broken glyph
        if self.state in (TileState.CAPTURED, TileState.BROKEN):
            inset = 3.0
            inner = rect.adjusted(inset, inset, -inset, -inset)
            if self.state == TileState.CAPTURED and self._thumb is not None:
                p.save()
                path = QPainterPath()
                path.addRoundedRect(inner, TILE_RADIUS, TILE_RADIUS)
                p.setClipPath(path)
                p.drawPixmap(inner.toRect(), self._thumb)
                p.restore()
                self._paint_day_chip(p, rect, v)
            else:
                pen = QPen(v.qcolor("outline_variant"))
                pen.setWidthF(1.5)
                pen.setStyle(Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(rect.adjusted(2, 2, -2, -2), TILE_RADIUS, TILE_RADIUS)
                icon = self._get_notes_icon(v)
                if icon is not None:
                    p.drawPixmap(int(rect.center().x() - 10),
                                 int(rect.center().y() - 10), icon)
                self._paint_day_chip(p, rect, v)
        else:
            # Day number centered (dimmed on other-month / future)
            p.setPen(Qt.NoPen)
            color = QColor(v["on_surface"])
            if self.state == TileState.OTHER_MONTH:
                color.setAlphaF(0.38)
            elif self.decor.future:
                color.setAlphaF(0.45)
            p.setPen(color)
            f = p.font()
            f.setPixelSize(11)
            f.setWeight(QFont.Medium)
            p.setFont(f)
            label = str(self.day.day) if self.day else ""
            p.drawText(rect, Qt.AlignCenter, label)

        # Future dim: scrim @ .40 over content
        if self.decor.future and self.state != TileState.OTHER_MONTH:
            p.setPen(Qt.NoPen)
            p.setBrush(v.rgba("background", 0.40))
            p.drawRoundedRect(rect, TILE_RADIUS, TILE_RADIUS)

        # Streak rings
        paint_streak_ring(p, rect, self.decor.streak,
                          v.qcolor("tertiary"), v.qcolor("outline"), inset=2)

        # Today marker (2px primary ring, expansion 0.5 -> 1.0)
        if self.decor.today != TodayState.NOT_TODAY and self.state != TileState.OTHER_MONTH:
            prog = max(0.5, min(1.0, self._today_progress)) if self._today_progress > 0 else 1.0
            ring_rect = rect.adjusted(2, 2, -2, -2)
            shrink = (1.0 - prog) * min(ring_rect.width(), ring_rect.height()) * 0.25
            rr = ring_rect.adjusted(shrink, shrink, -shrink, -shrink)
            alpha = self._pulse_alpha
            if self.decor.today == TodayState.IN_STREAK:
                pen = QPen(v.rgba("primary", alpha))
                pen.setWidthF(2.0)
                pen.setStyle(Qt.SolidLine)
            else:  # AT_RISK: dashed tertiary ring + hollow center
                pen = QPen(v.rgba("tertiary", alpha))
                pen.setWidthF(2.0)
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rr, TILE_RADIUS, TILE_RADIUS)

        # Mood dot (bottom-right, d=6, 1px outline halo)
        if self.decor.mood and self.state != TileState.OTHER_MONTH:
            halo = v.qcolor("surface_container_highest")
            dot_rect = QRectF(rect.right() - 12, rect.bottom() - 12, 9, 9)
            paint_mood_dot(p, dot_rect, MOOD_COLORS[self.decor.mood], halo, d=6)

        # Press state layer (press_alpha fill)
        if self._pressed:
            p.setPen(Qt.NoPen)
            p.setBrush(v.rgba("scrim", mt.press_alpha))
            p.drawRoundedRect(rect, TILE_RADIUS, TILE_RADIUS)

        # Keyboard focus indicator
        if self.focused:
            pen = QPen(v.qcolor("outline"))
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), TILE_RADIUS, TILE_RADIUS)

        p.restore()
        p.end()

    def _paint_day_chip(self, p: QPainter, rect: QRectF, v):
        """Day-number chip overlay (top-left)."""
        if self.day is None:
            return
        f = p.font()
        f.setPixelSize(9)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        text = str(self.day.day)
        metrics = p.fontMetrics()
        w = metrics.horizontalAdvance(text) + 10
        chip = QRectF(rect.x() + 6, rect.y() + 6, w, 14)
        p.setPen(Qt.NoPen)
        p.setBrush(v.rgba("surface_container_highest", 0.85))
        p.drawRoundedRect(chip, 7, 7)
        p.setPen(QColor(v["on_surface"]))
        p.drawText(chip, Qt.AlignCenter, text)

    def _get_notes_icon(self, v) -> Optional[QPixmap]:
        if self._notes_icon is None:
            icon = _create_colored_icon("notes.svg", v.qcolor("on_surface_variant"))
            pm = icon.pixmap(20, 20)
            if pm.isNull():
                return None
            self._notes_icon = pm
        return self._notes_icon


# -------------------------------------------------------------
# Month grid / header / weekday row / surface
# -------------------------------------------------------------
class MonthGrid(QWidget):
    """QGridLayout 6x7 sp(8); owns keyboard focus index."""

    dayClicked = Signal(QDate)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self._focus_index = -1
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        self.tiles: List[DayTile] = []
        for i in range(42):
            tile = DayTile(i)
            tile.clicked.connect(self._on_tile_clicked)
            tile.installEventFilter(self)
            self.tiles.append(tile)
            layout.addWidget(tile, i // 7, i % 7)
        self._set_focus_index(0, force=True)

    # ----- focus handling -----
    def eventFilter(self, watched, event):
        if event.type() == event.Type.FocusIn and watched in self.tiles:
            self._set_focus_index(self.tiles.index(watched))
        return super().eventFilter(watched, event)

    def _set_focus_index(self, index: int, force: bool = False):
        index = max(0, min(41, int(index)))
        if index == self._focus_index and not force:
            return
        old = self._focus_index
        self._focus_index = index
        if 0 <= old < len(self.tiles):
            self.tiles[old].set_focused(False)
        if 0 <= index < len(self.tiles):
            self.tiles[index].set_focused(True)

    def focusInEvent(self, event):
        if self._focus_index < 0:
            self._set_focus_index(self.default_focus_index())
        super().focusInEvent(event)

    def default_focus_index(self) -> int:
        today = date_cls.today()
        for t in self.tiles:
            if t.day == today:
                return t.index
        month = next((t.day.month for t in self.tiles
                      if t.day and t.state != TileState.OTHER_MONTH), 0)
        for t in self.tiles:
            if t.day and t.day.month == month and t.day.day == 1:
                return t.index
        return next((t.index for t in self.tiles if t.is_clickable()), 0)

    def refocus_default(self):
        self._set_focus_index(self.default_focus_index(), force=True)

    def keyPressEvent(self, event):
        key = event.key()
        cur = self._focus_index if self._focus_index >= 0 else self.default_focus_index()
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            if key == Qt.Key_Left:
                nxt = cur - 1 if cur % 7 > 0 else cur + 6
            elif key == Qt.Key_Right:
                nxt = cur + 1 if cur % 7 < 6 else cur - 6
            elif key == Qt.Key_Up:
                nxt = cur - 7 if cur >= 7 else cur + 35
            else:
                nxt = cur + 7 if cur <= 34 else cur - 35
            self._set_focus_index(nxt)
            event.accept()
        elif key in (Qt.Key_Enter, Qt.Key_Return):
            if 0 <= cur < len(self.tiles):
                tile = self.tiles[cur]
                if tile.is_clickable():
                    self.dayClicked.emit(tile.qdate())
            event.accept()
        elif key == Qt.Key_Escape:
            event.ignore()
        else:
            super().keyPressEvent(event)

    def _on_tile_clicked(self, qd: QDate):
        self.dayClicked.emit(qd)


class WeekdayRow(QWidget):
    """Mon–Sun labels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._labels: List[QLabel] = []
        for name in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
            lbl = QLabel(name)
            lbl.setAlignment(Qt.AlignCenter)
            row.addWidget(lbl, 1)
            self._labels.append(lbl)
        self.apply_theme()

    def apply_theme(self):
        v = theme_vars()
        for lbl in self._labels:
            lbl.setStyleSheet(f"""
                color: {v['on_surface_variant']};
                font-size: 10px;
                font-weight: 600;
            """)


class MonthHeaderBar(QWidget):
    """prev / title / next ... [Today]."""

    prevClicked = Signal()
    nextClicked = Signal()
    todayClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._prev_btn = NavIconButton("chevron_left.svg", "Previous month")
        self._prev_btn.clicked.connect(self.prevClicked.emit)
        row.addWidget(self._prev_btn)

        self.title_lbl = QLabel("")
        row.addWidget(self.title_lbl, 1)

        self._next_btn = NavIconButton("chevron_right.svg", "Next month")
        self._next_btn.clicked.connect(self.nextClicked.emit)
        row.addWidget(self._next_btn)

        self.today_btn = QPushButton("Today")
        self.today_btn.setCursor(Qt.PointingHandCursor)
        self.today_btn.setFixedHeight(32)
        self.today_btn.clicked.connect(self.todayClicked.emit)
        row.addWidget(self.today_btn)
        self.apply_theme()

    def set_title(self, text: str):
        self.title_lbl.setText(text)

    def apply_theme(self):
        v = theme_vars()
        self.title_lbl.setStyleSheet(f"""
            color: {v['on_surface']};
            font-size: 14px;
            font-weight: 600;
        """)
        today_style = _secondary_button_style(v)
        self.today_btn.setStyleSheet(today_style)
        self._prev_btn.apply_theme()
        self._next_btn.apply_theme()


class CalendarSurface(QFrame):
    """Card container (surface_container_highest, radius 12)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CalendarSurface")

    def apply_theme(self):
        v = theme_vars()
        self.setStyleSheet(f"""
            QFrame#CalendarSurface {{
                background-color: {v['surface_container_highest']};
                border-radius: 12px;
            }}
        """)


class EmptyStateView(QWidget):
    """Zero-photos-ever full-surface state with CTA."""

    takeSelfieRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EmptyStateView")
        col = QVBoxLayout(self)
        col.setContentsMargins(12, 12, 12, 12)
        col.setSpacing(12)
        col.addStretch()

        self._icon_lbl = QLabel()
        self._icon_lbl.setAlignment(Qt.AlignCenter)
        col.addWidget(self._icon_lbl)

        title = QLabel("No selfies yet")
        title.setAlignment(Qt.AlignCenter)
        self._title_lbl = title
        col.addWidget(title)

        caption = QLabel("Capture your day")
        caption.setObjectName("CaptionLabel")
        caption.setAlignment(Qt.AlignCenter)
        self._caption_lbl = caption
        col.addWidget(caption)

        col.addSpacing(6)

        # CTA — style = TakeSelfieButton verbatim (pages/dashboard.py)
        self.cta_btn = QPushButton("Take today's selfie")
        self.cta_btn.setObjectName("TakeSelfieButton")
        self.cta_btn.setCursor(Qt.PointingHandCursor)
        self.cta_btn.setFixedHeight(48)
        self.cta_btn.clicked.connect(self.takeSelfieRequested.emit)
        col.addWidget(self.cta_btn, alignment=Qt.AlignCenter)

        col.addStretch()
        self.apply_theme()

    def apply_theme(self):
        v = theme_vars()
        self._icon_lbl.setPixmap(_create_colored_icon(
            "selfie.svg", v.qcolor("on_surface_variant")).pixmap(56, 56))
        self._title_lbl.setStyleSheet(f"""
            color: {v['on_surface']};
            font-size: 16px;
            font-weight: 600;
        """)
        self._caption_lbl.setStyleSheet(f"""
            QLabel#CaptionLabel {{
                color: {v['on_surface_variant']};
                font-size: 12px;
            }}
        """)
        self.cta_btn.setStyleSheet(f"""
            QPushButton#TakeSelfieButton {{
                background-color: {v['primary']};
                color: {v['on_primary']};
                border: none;
                border-radius: 24px;
                padding: 0 24px;
                font-size: 14px;
                font-weight: 500;
            }}
            QPushButton#TakeSelfieButton:hover {{
                background-color: {v['primary']};
                opacity: 0.92;
            }}
            QPushButton#TakeSelfieButton:pressed {{
                background-color: {v['primary']};
                opacity: 0.85;
            }}
        """)


class NoCaptureHint(QLabel):
    """Hint line shown when the viewed month has no captures."""

    def __init__(self, parent=None):
        super().__init__("No selfies captured this month.", parent)
        self.setAlignment(Qt.AlignCenter)
        self.hide()
        self.apply_theme()

    def apply_theme(self):
        v = theme_vars()
        self.setStyleSheet(f"""
            color: {v['on_surface_variant']};
            font-size: 12px;
            font-style: italic;
        """)


# -------------------------------------------------------------
# Day detail overlay: scrim + card + confirm dialog
# -------------------------------------------------------------
class DetailScrim(QWidget):
    """Page-child overlay painting scrim @55% alpha; click-outside closes."""

    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._alpha = 0.0  # animated 0 -> 1; painted alpha = .55 * _alpha
        self.hide()

    def _get_alpha(self) -> float:
        return self._alpha

    def _set_alpha(self, value: float):
        self._alpha = float(value)
        self.update()

    alpha = Property(float, _get_alpha, _set_alpha)

    def paintEvent(self, event):
        if self._alpha <= 0:
            return
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        p.setBrush(theme_vars().rgba("scrim", 0.55 * self._alpha))
        p.drawRect(self.rect())
        p.end()

    def mousePressEvent(self, event):
        event.accept()
        self.closeRequested.emit()


class ConfirmDeleteDialog(QDialog):
    """Frameless styled like the ErrorToast container (#1A1A1A r14, left
    border 4px error #EF4444). std accepted/rejected."""

    def __init__(self, date_title: str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(15, 15, 15, 15)

        container = QFrame()
        container.setObjectName("Container")
        container.setStyleSheet("""
            QFrame#Container {
                background-color: #1A1A1A;
                border: 2px solid #333333;
                border-left: 4px solid #EF4444;
                border-radius: 14px;
            }
            QLabel { color: #E0E0E0; border: none; }
        """)
        outer.addWidget(container)

        col = QVBoxLayout(container)
        col.setContentsMargins(16, 16, 16, 16)
        col.setSpacing(8)

        title = QLabel("Delete selfie")
        title.setStyleSheet("color: #EF4444; font-size: 14px; font-weight: bold;")
        col.addWidget(title)

        msg = QLabel(f"Delete selfie from {date_title}?")
        msg.setStyleSheet("color: #CCCCCC; font-size: 13px;")
        col.addWidget(msg)

        col.addSpacing(4)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setFixedHeight(32)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D; color: #B0B0B0;
                border: 1px solid #333333; border-radius: 16px;
                padding: 0 12px; font-size: 11px; font-weight: 500;
            }
            QPushButton:hover { background-color: #3D3D3D; color: white; border-color: #555555; }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()

        delete_btn = QPushButton("Delete")
        delete_btn.setCursor(Qt.PointingHandCursor)
        delete_btn.setFixedHeight(32)
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #EF4444; color: #FFFFFF;
                border: none; border-radius: 16px;
                padding: 0 12px; font-size: 11px; font-weight: 600;
            }
            QPushButton:hover { background-color: #DC2626; }
        """)
        delete_btn.clicked.connect(self.accept)
        btn_row.addWidget(delete_btn)

        col.addLayout(btn_row)


def _info_label_style(v, size=11, weight=500) -> str:
    return f"""
        color: {v['on_surface']};
        font-size: {size}px;
        font-weight: {weight};
    """


class DetailCard(QFrame):
    """Centered day-detail card (<=720x560, min 420x480), VIEW/EDIT modes."""

    prevDay = Signal()
    nextDay = Signal()
    editRequested = Signal()
    saved = Signal(str)
    deleteConfirmed = Signal(str)
    closeRequested = Signal()

    def __init__(self, api: IndexAPI, parent=None):
        super().__init__(parent)
        self.setObjectName("DetailCard")
        self._api = api
        self._item: Dict[str, Any] = {}
        self._date_str = ""
        self._photo_gen = 0
        self._movies: List[QMovie] = []

        self.setMinimumSize(420, 480)
        self.setMaximumSize(720, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # Header: prev / date-title / next / close
        header = QHBoxLayout()
        header.setSpacing(8)
        self._prev_day_btn = NavIconButton("chevron_left.svg", "Previous captured day")
        self._prev_day_btn.clicked.connect(self.prevDay.emit)
        header.addWidget(self._prev_day_btn)
        self.title_lbl = QLabel("")
        self.title_lbl.setAlignment(Qt.AlignCenter)
        header.addWidget(self.title_lbl, 1)
        self._next_day_btn = NavIconButton("chevron_right.svg", "Next captured day")
        self._next_day_btn.clicked.connect(self.nextDay.emit)
        header.addWidget(self._next_day_btn)
        self._close_btn = NavIconButton("close.svg", "Close")
        self._close_btn.clicked.connect(self.closeRequested.emit)
        header.addWidget(self._close_btn)
        root.addLayout(header)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)
        self._build_view_page()
        self._build_edit_page()
        self.apply_theme()

    # ----- view page -----
    def _build_view_page(self):
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)

        photo_row = QHBoxLayout()
        photo_row.setSpacing(8)

        self.photo_label = ThumbLabel()
        self.photo_label.setMinimumHeight(220)
        photo_row.addWidget(self.photo_label, 1)
        col.addLayout(photo_row, stretch=1)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        self._view_sep = sep
        sep.setFixedHeight(1)
        col.addWidget(sep)

        # Mood row
        mood_row = QHBoxLayout()
        mood_row.setSpacing(8)
        self.mood_gif_lbl = QLabel()
        self.mood_gif_lbl.setFixedSize(28, 28)
        self.mood_gif_lbl.setAlignment(Qt.AlignCenter)
        mood_row.addWidget(self.mood_gif_lbl)
        self.mood_name_lbl = QLabel("")
        mood_row.addWidget(self.mood_name_lbl)
        mood_row.addStretch()
        col.addLayout(mood_row)

        # Note row
        note_row = QHBoxLayout()
        note_row.setSpacing(6)
        self.note_icon_lbl = QLabel()
        self.note_icon_lbl.setFixedSize(16, 16)
        note_row.addWidget(self.note_icon_lbl)
        self.note_lbl = QLabel("")
        self.note_lbl.setWordWrap(True)
        note_row.addWidget(self.note_lbl, 1)
        col.addLayout(note_row)

        # Meta row (time · resolution)
        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        self.time_icon_lbl = QLabel()
        self.time_icon_lbl.setFixedSize(16, 16)
        meta_row.addWidget(self.time_icon_lbl)
        self.time_lbl = QLabel("")
        meta_row.addWidget(self.time_lbl)
        self.res_icon_lbl = QLabel()
        self.res_icon_lbl.setFixedSize(16, 16)
        meta_row.addSpacing(8)
        meta_row.addWidget(self.res_icon_lbl)
        self.res_lbl = QLabel("")
        meta_row.addWidget(self.res_lbl)
        meta_row.addStretch()
        col.addLayout(meta_row)

        col.addStretch()

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setFixedHeight(32)
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        bottom.addWidget(self.delete_btn)
        bottom.addStretch()
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.setFixedHeight(32)
        self.edit_btn.clicked.connect(self.enter_edit_mode)
        bottom.addWidget(self.edit_btn)
        col.addLayout(bottom)

        self._view_page = page
        self._stack.addWidget(page)
        self._stack.setCurrentIndex(0)

    # ----- edit page -----
    def _build_edit_page(self):
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)

        caption = QLabel("How was your day?")
        self._edit_caption_lbl = caption
        col.addWidget(caption)

        self.mood_picker = MoodPickerRow()
        col.addWidget(self.mood_picker)

        self.note_editor = QTextEdit()
        self.note_editor.setPlaceholderText("Add a note…")
        self.note_editor.setMaximumHeight(96)
        col.addWidget(self.note_editor)

        col.addStretch()

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setFixedHeight(32)
        self.cancel_btn.clicked.connect(self.exit_edit_mode)
        bottom.addWidget(self.cancel_btn)
        bottom.addStretch()
        self.save_btn = QPushButton("Save")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setFixedHeight(32)
        self.save_btn.clicked.connect(self._on_save_clicked)
        bottom.addWidget(self.save_btn)
        col.addLayout(bottom)

        self._edit_page = page
        self._stack.addWidget(page)

    # ----- population / modes -----
    def populate(self, item: Dict[str, Any], date_title: str,
                 has_prev: bool = True, has_next: bool = True):
        """Show item in VIEW mode."""
        self._item = dict(item or {})
        self._date_str = date_title
        self.title_lbl.setText(date_title)
        self._prev_day_btn.set_active(has_prev)
        self._next_day_btn.set_active(has_next)
        self._load_photo()
        self._fill_info_rows(self._item)
        self.exit_edit_mode(silent=True)

    def _load_photo(self):
        path = Path(self._item.get("path") or "")
        self._photo_gen += 1
        gen = self._photo_gen
        self.photo_label.set_placeholder("")
        QTimer.singleShot(0, lambda: self._apply_photo(path, gen))

    def _apply_photo(self, path: Path, gen: int):
        if gen != self._photo_gen:
            return  # stale (rapid prev/next)
        self.photo_label.set_image(path if path.exists() else None, radius=14)

    def _fill_info_rows(self, item: Dict[str, Any]):
        v = theme_vars()
        mood = item.get("mood")
        if mood in MOOD_GIF_MAP:
            gif_path = MOOD_DIR / MOOD_GIF_MAP[mood]
            movie = QMovie(str(gif_path))
            if movie.isValid():
                movie.setScaledSize(QSize(22, 22))
                self.mood_gif_lbl.setMovie(movie)
                movie.start()
                self.mood_gif_lbl.setStyleSheet(f"""
                    background-color: {v['surface_container_low']};
                    border: 2px solid {v['outline_variant']};
                    border-radius: 8px;
                """)
                if len(self._movies) > 8:
                    old = self._movies.pop(0)
                    old.stop()
                self._movies.append(movie)
            self.mood_name_lbl.setText(str(mood))
        else:
            self.mood_gif_lbl.clear()
            self.mood_gif_lbl.setStyleSheet("border: none;")
            self.mood_name_lbl.setText("No mood")

        note_value = item.get("notes")
        if note_value:
            note_text = note_value[:NOTE_TRUNCATE] + "…" if len(note_value) > NOTE_TRUNCATE else note_value
            self.note_lbl.setText(note_text)
        else:
            self.note_lbl.setText("No notes")

        time_str = _format_time(item)
        self.time_lbl.setText(time_str or "—")
        width = item.get("width")
        height = item.get("height")
        self.res_lbl.setText(f"{width} × {height}" if width and height else "—")
        self.apply_theme()

    def enter_edit_mode(self):
        self.editRequested.emit()
        self.mood_picker.select_mood(self._item.get("mood"))
        self.note_editor.setPlainText(self._item.get("notes") or "")
        self._stack.setCurrentWidget(self._edit_page)

    def exit_edit_mode(self, silent: bool = False):
        self._stack.setCurrentIndex(0)
        if not silent and hasattr(self, "_item"):
            self._load_photo()

    # ----- actions -----
    def _toast(self, level: str, message: str):
        popup = ErrorToast(self, level=level, message=message)
        geo = self.geometry()
        x = geo.x() + (geo.width() - popup.width()) // 2
        y = geo.y() + (geo.height() - popup.height()) // 2
        popup.move(self.mapTo(self.window(), QPoint(x, y)))
        popup.show()

    def _on_save_clicked(self):
        eid = self._item.get("id")
        if not eid or self._api is None:
            return
        meta = {
            "mood": self.mood_picker.current_mood(),
            "notes": self.note_editor.toPlainText().strip() or None,
        }
        try:
            updated = self._api.update_meta(eid, meta) or {}
        except Exception as e:
            self._toast("ERROR", f"Failed to save changes:\n{e}")
            return
        if isinstance(updated, dict):
            self._item.update(updated)
        self.saved.emit(eid)
        self._fill_info_rows(self._item)
        self.exit_edit_mode()

    def _on_delete_clicked(self):
        eid = self._item.get("id")
        if not eid:
            return
        dlg = ConfirmDeleteDialog(self.title_lbl.text() or "this date", self.window())
        if dlg.exec() == QDialog.Accepted:
            self.deleteConfirmed.emit(eid)

    # ----- theme -----
    def apply_theme(self):
        v = theme_vars()
        self.setStyleSheet(f"""
            QFrame#DetailCard {{
                background-color: {v['surface_container_low']};
                border-radius: 16px;
            }}
        """)
        self.title_lbl.setStyleSheet(f"""
            color: {v['on_surface']};
            font-size: 14px;
            font-weight: 600;
        """)
        self._view_sep.setStyleSheet(f"background-color: {v['outline_variant']};")
        secondary = _secondary_button_style(v)
        self.edit_btn.setStyleSheet(secondary)
        self.cancel_btn.setStyleSheet(secondary)
        self.delete_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {v['surface_container_high']};
                color: {v['error']};
                border: 1px solid {v['error']};
                border-radius: 16px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {v['error_container']};
                border: 1px solid {v['error']};
                color: {v['on_error_container']};
            }}
        """)
        self.save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {v['primary']};
                color: {v['on_primary']};
                border: none;
                border-radius: 16px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton:hover {{ opacity: 0.92; }}
        """)
        self._edit_caption_lbl.setStyleSheet(f"""
            color: {v['on_surface_variant']};
            font-size: 10px;
            font-weight: 500;
        """)
        self.time_lbl.setStyleSheet(_info_label_style(v))
        self.res_lbl.setStyleSheet(_info_label_style(v))
        self.mood_name_lbl.setStyleSheet(_info_label_style(v))
        self.note_lbl.setStyleSheet(f"""
            color: {v['on_surface_variant']};
            font-size: 11px;
        """)
        self.note_icon_lbl.setPixmap(_create_colored_icon(
            "notes.svg", v.qcolor("on_surface_variant")).pixmap(16, 16))
        self.time_icon_lbl.setPixmap(_create_colored_icon(
            "save_clock.svg", v.qcolor("on_surface_variant")).pixmap(16, 16))
        self.res_icon_lbl.setPixmap(_create_colored_icon(
            "aspect_ratio.svg", v.qcolor("on_surface_variant")).pixmap(16, 16))
        self._prev_day_btn.apply_theme()
        self._next_day_btn.apply_theme()
        self._close_btn.apply_theme()


# -------------------------------------------------------------
# Page
# -------------------------------------------------------------
class CalendarPage(QWidget):
    """Root calendar page: state machine view/detail; owns month state."""

    takeSelfieRequested = Signal()
    photoDeleted = Signal()
    dataChanged = Signal()

    def __init__(self, theme_controller=None, cfg=None, config_path=None,
                 app_paths: Optional[AppPaths] = None):
        super().__init__()
        self.setObjectName("CalendarPage")

        # Context injection (SettingsPage pattern)
        if app_paths is None:
            app_paths = get_app_paths("DailySelfie", ensure=False)
        if config_path is None:
            config_path = Path(app_paths.config_dir) / "config.toml"
        self.app_paths = app_paths
        self.config_path = Path(config_path)
        self.cfg = cfg
        self.theme_controller = theme_controller

        self._api: Optional[IndexAPI] = None
        self._loaded = False
        self._empty_mode = False
        self._gen = 0
        self._all_dates: List[str] = []
        self._items_by_day: Dict[str, List[Dict[str, Any]]] = {}
        self._selected_eid: Optional[str] = None
        self._decor = DecorationController()
        self._entrance_refs: List[Any] = []
        self._overlay_anims: List[Any] = []
        self._today_tile: Optional[DayTile] = None
        self._closing = False

        today = date_cls.today()
        self._current_year = today.year
        self._current_month = today.month

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self._surface = CalendarSurface()
        col = QVBoxLayout(self._surface)
        col.setContentsMargins(12, 12, 12, 12)
        col.setSpacing(12)

        self.header_bar = MonthHeaderBar()
        self.header_bar.prevClicked.connect(lambda: self._change_month(-1))
        self.header_bar.nextClicked.connect(lambda: self._change_month(1))
        self.header_bar.todayClicked.connect(self._goto_today)
        col.addWidget(self.header_bar)

        self.weekday_row = WeekdayRow()
        col.addWidget(self.weekday_row)

        self.grid = MonthGrid()
        self.grid.dayClicked.connect(self._on_day_clicked)
        col.addWidget(self.grid, 1)

        self.hint = NoCaptureHint()
        col.addWidget(self.hint)

        self._viz_sep = QFrame()
        self._viz_sep.setFrameShape(QFrame.HLine)
        self._viz_sep.setFixedHeight(1)
        col.addWidget(self._viz_sep)

        viz_row = QHBoxLayout()
        viz_row.setContentsMargins(0, 0, 0, 0)
        viz_row.setSpacing(8)
        self.legend = MoodLegend()
        viz_row.addWidget(self.legend)
        viz_row.addStretch()

        chips_holder = QWidget()
        chips_row = QHBoxLayout(chips_holder)
        chips_row.setContentsMargins(0, 0, 0, 0)
        chips_row.setSpacing(8)
        self.chip_photos = QLabel()
        self.chip_moods = QLabel()
        self.chip_streak = QLabel()
        for c in (self.chip_photos, self.chip_moods, self.chip_streak):
            c.setFixedHeight(28)
            chips_row.addWidget(c, 0, Qt.AlignVCenter)
        self.record_chip = QWidget()
        self.record_chip.setObjectName("RecordChip")
        rec_lay = QHBoxLayout(self.record_chip)
        rec_lay.setContentsMargins(10, 0, 10, 0)
        rec_lay.setSpacing(6)
        self.record_icon_lbl = QLabel()
        self.record_icon_lbl.setFixedSize(16, 16)
        rec_lay.addWidget(self.record_icon_lbl)
        self.record_text_lbl = QLabel("New record!")
        rec_lay.addWidget(self.record_text_lbl)
        self.record_chip.setFixedHeight(28)
        self.record_chip.hide()
        chips_row.addWidget(self.record_chip, 0, Qt.AlignVCenter)
        viz_row.addWidget(chips_holder)
        col.addLayout(viz_row)

        self._heat_card = QFrame()
        self._heat_card.setObjectName("HeatmapCard")
        heat_col = QVBoxLayout(self._heat_card)
        heat_col.setContentsMargins(12, 12, 12, 12)
        heat_col.setSpacing(0)
        self.heatmap = YearHeatmapStrip()
        self.heatmap.weekClicked.connect(
            lambda _w, anchor: self._jump_to_month(anchor.year, anchor.month))
        heat_col.addWidget(self.heatmap, 0, Qt.AlignHCenter)
        col.addWidget(self._heat_card)

        root.addWidget(self._surface)

        self.empty_view = EmptyStateView()
        self.empty_view.takeSelfieRequested.connect(self.takeSelfieRequested.emit)
        self.empty_view.hide()
        root.addWidget(self.empty_view)

        self._scrim: Optional[DetailScrim] = None
        self._card: Optional[DetailCard] = None

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(50)
        self._pulse_timer.timeout.connect(self._on_pulse_tick)

        self._apply_theme()
        if theme_controller is not None:
            theme_controller.themeChanged.connect(self._on_theme_changed)

    # ---------------------------------------------------------
    # Data access
    # ---------------------------------------------------------
    def _ensure_api(self) -> Optional[IndexAPI]:
        if self._api is None:
            try:
                self._api = get_api(self.app_paths)
            except Exception:
                self._api = None
        return self._api

    def _toast(self, level: str, message: str):
        popup = ErrorToast(self, level=level, message=message)
        geo = self.window().geometry()
        x = geo.x() + (geo.width() - popup.width()) // 2
        y = geo.y() + (geo.height() - popup.height()) // 3
        popup.move(x, y)
        popup.show()

    # ---------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self.reload_all()
        self._sync_pulse()

    def hideEvent(self, event):
        self._pulse_timer.stop()
        super().hideEvent(event)

    def refresh(self):
        """Reload everything (photoSaved / external changes)."""
        self.close_detail(instant=True)
        if self._loaded:
            self.reload_all()

    def reload_all(self):
        if self._check_empty_state():
            self._pulse_timer.stop()
            return
        self._load_month(self._current_year, self._current_month)

    def _check_empty_state(self) -> bool:
        api = self._ensure_api()
        try:
            has_any = api is not None and api.get_last_photo() is not None
        except Exception:
            has_any = False
        empty = not has_any
        if empty != self._empty_mode:
            self._empty_mode = empty
            self._surface.setVisible(not empty)
            self.empty_view.setVisible(empty)
        elif self._empty_mode:
            self.empty_view.setVisible(True)
        return empty

    # ---------------------------------------------------------
    # Month loading
    # ---------------------------------------------------------
    def _load_month(self, year: int, month: int):
        self._gen += 1
        gen = self._gen
        self._current_year = int(year)
        self._current_month = int(month)

        api = self._ensure_api()
        rows: List[Dict[str, Any]] = []
        if api is not None:
            try:
                rows = api.list_month(year, month) or []
            except Exception as e:
                self._toast("ERROR", f"Failed to load month:\n{e}")
                rows = []

        by_day: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            dt = _utc_to_local(r.get("ts"))
            key = dt.date().isoformat() if dt else str(r.get("id", ""))[:10]
            by_day.setdefault(key, []).append(r)

        self._items_by_day = by_day
        self.header_bar.set_title(f"{pycal.month_name[self._current_month]} {self._current_year}")
        self.hint.setVisible(len(rows) == 0)

        self._refresh_year_context(year)
        self._bind_tiles(gen)
        self._sync_pulse()

    def _refresh_year_context(self, year: int):
        api = self._ensure_api()
        counts: Dict[str, int] = {}
        moods: Dict[str, str] = {}
        if api is not None:
            try:
                counts = api.get_capture_counts_by_date(year) or {}
            except Exception:
                counts = {}
            try:
                mood_rows = api.get_moods_between(f"{year:04d}-01-01", f"{year:04d}-12-31") or []
                for row in mood_rows:  # ordered asc -> last entry wins
                    moods[row.get("date")] = row.get("mood")
            except Exception:
                moods = {}
            try:
                self._all_dates = api.get_all_capture_dates() or []
            except Exception:
                self._all_dates = []
        self._decor.update(self._all_dates, counts_by_day=counts,
                           moods_by_day=moods, today=date_cls.today())
        self.heatmap.set_year_data(year, counts, moods, date_cls.today())
        self._update_chips()

    def _update_chips(self):
        v = theme_vars()
        photos = sum(len(v_items) for v_items in self._items_by_day.values())
        moods_logged = sum(1 for v_items in self._items_by_day.values()
                           for it in v_items if it.get("mood"))
        cur, best, _has_today = self._decor.streak_summary()
        at_risk = self._decor.at_risk

        self.chip_photos.setText(f"{photos} photo{'s' if photos != 1 else ''} this month")
        self.chip_moods.setText(f"{moods_logged} mood{'s' if moods_logged != 1 else ''} logged")
        streak_text = f"Current {cur} · Best {best}"
        if at_risk:
            streak_text += " (at risk)"
        self.chip_streak.setText(streak_text)

        pill_base = f"""
            background-color: {v['surface_container_high']};
            border: 1px solid {v['outline_variant']};
            border-radius: 14px;
        """
        self.chip_photos.setStyleSheet(f"""
            QLabel {{ color: {v['on_surface_variant']}; font-size: 11px;
                      font-weight: 500; padding: 0 12px; {pill_base} }}
        """)
        self.chip_moods.setStyleSheet(f"""
            QLabel {{ color: {v['on_surface_variant']}; font-size: 11px;
                      font-weight: 500; padding: 0 12px; {pill_base} }}
        """)
        accent = v['tertiary'] if at_risk else v['primary']
        self.chip_streak.setStyleSheet(f"""
            QLabel {{ color: {accent}; font-size: 11px;
                      font-weight: 600; padding: 0 12px; {pill_base} }}
        """)
        new_record = cur > best
        self.record_chip.setVisible(new_record)
        if new_record:
            self.record_icon_lbl.setPixmap(_create_colored_icon(
                "celebration.svg", v.qcolor("tertiary")).pixmap(16, 16))
            self.record_text_lbl.setStyleSheet(f"""
                color: {v['tertiary']}; font-size: 11px; font-weight: 600;
            """)
            self.record_chip.setStyleSheet(f"""
                QWidget#RecordChip {{
                    background-color: {v['surface_container_high']};
                    border: 1px solid {v['outline_variant']};
                    border-radius: 14px;
                }}
            """)

    def _bind_tiles(self, gen: int):
        cal = pycal.Calendar(firstweekday=0)  # Monday-first grid
        days = list(cal.itermonthdates(self._current_year, self._current_month))[:42]
        while len(days) < 42:
            days.append(days[-1] + timedelta(days=1))
        today = date_cls.today()
        self._today_tile = None

        for tile, d in zip(self.grid.tiles, days):
            other = (d.month != self._current_month) or (d.year != self._current_year)
            captures = self._items_by_day.get(d.isoformat(), [])
            tile.reset_motion()
            tile.set_cell(d, other, captures,
                          reload_cb=lambda t=tile, g=gen: self._schedule_thumb(t, g))
            decor = self._decor.decors_for_year(d.year).get(d.isoformat(), DayDecor())
            tile.decor.capture_count = decor.capture_count
            tile.set_mood(decor.mood)
            tile.set_in_streak(decor.streak)
            tile.set_today_state(TodayState.NOT_TODAY if other else decor.today)
            tile.set_future(decor.future)
            if decor.today == TodayState.AT_RISK:
                n = self._decor.current_streak
                tile.setToolTip(f"Take a photo today to keep your {n}-day streak")
            else:
                tile.setToolTip("")
            if d == today and not other:
                self._today_tile = tile

        self.grid.refocus_default()
        self._animate_entrance(gen)
        for i, tile in enumerate(self.grid.tiles):
            if tile.state == TileState.CAPTURED and tile._thumb_path is not None:
                QTimer.singleShot(0, lambda t=tile, g=gen: self._schedule_thumb(t, g))

    def _schedule_thumb(self, tile: DayTile, gen: int):
        if gen != self._gen:
            return
        try:
            if tile.state != TileState.CAPTURED or tile._thumb_path is None:
                return
            w = max(int(tile.width()) - 8, 8)
            h = max(int(tile.height()) - 8, 8)
            pix = _rounded_crop_pixmap(tile._thumb_path, w, h, TILE_RADIUS)
            tile.apply_thumb(pix)
        except RuntimeError:
            pass  # tile destroyed (rapid paging)

    def _animate_entrance(self, gen: int):
        for ref in self._entrance_refs:
            try:
                ref.stop()
            except RuntimeError:
                pass
        self._entrance_refs.clear()
        if not mt.is_motion_enabled() or not self.isVisible():
            return
        for idx, tile in enumerate(self.grid.tiles):
            QTimer.singleShot(min(idx, 8) * mt.stagger_interval,
                              lambda t=tile, g=gen, i=idx: self._run_entrance(t, g))

    def _run_entrance(self, tile: DayTile, gen: int):
        if gen != self._gen:
            return
        try:
            end_pos = tile.pos()
            eff = QGraphicsOpacityEffect(tile)
            tile.setGraphicsEffect(eff)
            op_anim = QPropertyAnimation(eff, b"opacity", tile)
            op_anim.setDuration(mt.duration_base)
            op_anim.setEasingCurve(mt.curve_enter)
            op_anim.setStartValue(0.0)
            op_anim.setEndValue(1.0)
            pos_anim = QPropertyAnimation(tile, b"pos", tile)
            pos_anim.setDuration(mt.duration_base)
            pos_anim.setEasingCurve(mt.curve_enter)
            tile.move(end_pos.x(), end_pos.y() + 6)
            pos_anim.setStartValue(tile.pos())
            pos_anim.setEndValue(end_pos)
            group = QParallelAnimationGroup(tile)
            group.addAnimation(op_anim)
            group.addAnimation(pos_anim)

            def _finished():
                try:
                    tile.setGraphicsEffect(None)
                    tile.move(end_pos)
                except RuntimeError:
                    pass
            group.finished.connect(_finished)
            self._entrance_refs.append(group)
            group.start()
        except RuntimeError:
            pass

    # ---------------------------------------------------------
    # Navigation
    # ---------------------------------------------------------
    def _add_months(self, year: int, month: int, delta: int):
        idx = year * 12 + (month - 1) + delta
        return idx // 12, idx % 12 + 1

    def _change_month(self, delta: int):
        y, m = self._add_months(self._current_year, self._current_month, delta)
        self._load_month(y, m)

    def _goto_today(self):
        t = date_cls.today()
        self._load_month(t.year, t.month)

    def _jump_to_month(self, year: int, month: int):
        self._load_month(int(year), int(month))

    def _on_pulse_tick(self):
        tile = self._today_tile
        if tile is None:
            self._pulse_timer.stop()
            return
        phase = (_time.monotonic() % 1.6) / 1.6
        tile._pulse_alpha = 0.45 + 0.55 * (math.sin(math.pi * phase) ** 2)
        try:
            tile.update(tile.rect())  # invalidate ONLY the today-tile rect
        except RuntimeError:
            self._pulse_timer.stop()

    def _sync_pulse(self):
        should = (self.isVisible() and mt.is_motion_enabled()
                  and self._today_tile is not None and not self._empty_mode)
        if should and not self._pulse_timer.isActive():
            self._pulse_timer.start()
        elif not should:
            self._pulse_timer.stop()

    # ---------------------------------------------------------
    # Detail overlay (scrim + DetailCard, motion C3)
    # ---------------------------------------------------------
    def _ensure_overlays(self):
        if self._card is None:
            self._scrim = DetailScrim(self)
            self._scrim.closeRequested.connect(lambda: self.close_detail())
            self._card = DetailCard(self._ensure_api(), self)
            self._card.prevDay.connect(lambda: self._navigate_detail(-1))
            self._card.nextDay.connect(lambda: self._navigate_detail(1))
            self._card.saved.connect(self._on_card_saved)
            self._card.deleteConfirmed.connect(self._on_delete_confirmed)
            self._card.closeRequested.connect(lambda: self.close_detail())
            self._card.hide()
            self._scrim.hide()

    def _overlay_geometry(self):
        page_w, page_h = self.width(), self.height()
        card_w = max(420, min(720, int(page_w * 0.86)))
        card_h = max(480, min(560, int(page_h * 0.88)))
        x = (page_w - card_w) // 2
        y = (page_h - card_h) // 2
        return QRectF(x, y, card_w, card_h)

    def _find_item_by_eid(self, eid: str) -> Optional[Dict[str, Any]]:
        for items in self._items_by_day.values():
            for it in items:
                if it.get("id") == eid:
                    return it
        return None

    def _nav_bounds(self, item: Dict[str, Any]):
        ts10 = str(item.get("ts", ""))[:10] or str(item.get("id", ""))[:10]
        try:
            idx = self._all_dates.index(ts10)
        except ValueError:
            return True, True
        return idx > 0, idx < len(self._all_dates) - 1

    def _open_detail_for_date(self, d: date_cls):
        items = self._items_by_day.get(d.isoformat()) or []
        if not items:
            return
        item = items[-1]  # multiple captures/day: LAST row wins
        self._selected_eid = item.get("id")
        self._ensure_overlays()
        has_prev, has_next = self._nav_bounds(item)
        title = f"{pycal.month_name[d.month]} {d.day}, {d.year}"
        self._card.populate(item, title, has_prev, has_next)
        self._show_overlays()

    def _on_day_clicked(self, qdate: QDate):
        d = date_cls(qdate.year(), qdate.month(), qdate.day())
        tile = next((t for t in self.grid.tiles if t.day == d), None)
        if tile is not None and not tile.is_clickable():
            return
        if not self._items_by_day.get(d.isoformat()):
            return
        self._open_detail_for_date(d)

    def _navigate_detail(self, step: int):
        if self._card is None or not self._all_dates:
            return
        item = getattr(self._card, "_item", {})
        ts10 = str(item.get("ts", ""))[:10] or str(item.get("id", ""))[:10]
        try:
            idx = self._all_dates.index(ts10)
        except ValueError:
            return
        ni = idx + step
        if ni < 0 or ni >= len(self._all_dates):
            return  # stop at empty boundary
        target = self._all_dates[ni]
        ty, tm = int(target[:4]), int(target[5:7])
        if (ty, tm) != (self._current_year, self._current_month):
            self._load_month(ty, tm)  # wrap across months by auto-loading
        cands = [it for lst in self._items_by_day.values() for it in lst
                 if str(it.get("ts", "")).startswith(target)]
        if not cands:
            return
        pick = cands[-1]
        dt_local = _utc_to_local(pick.get("ts"))
        d = dt_local.date() if dt_local else date_cls(ty, tm, int(target[8:10]))
        self._selected_eid = pick.get("id")
        has_prev, has_next = self._nav_bounds(pick)
        title = f"{pycal.month_name[d.month]} {d.day}, {d.year}"
        self._card.populate(pick, title, has_prev, has_next)
        self._sync_pulse()

    def _scaled_geo(self, scale: float) -> QRect:
        geo = self._overlay_geometry()
        w = int(geo.width() * scale)
        h = int(geo.height() * scale)
        x = int(geo.center().x() - w / 2)
        y = int(geo.center().y() - h / 2)
        return QRect(x, y, w, h)

    def _show_overlays(self):
        if self._scrim is None or self._card is None:
            return
        self._closing = False
        target = self._overlay_geometry()
        self._scrim.setGeometry(0, 0, self.width(), self.height())
        self._scrim.raise_()
        self._card.setGeometry(self._scaled_geo(0.92))
        self._card.setMinimumSize(420, 480)
        self._card.setMaximumSize(720, 560)
        self._card.raise_()
        self._scrim.show()
        self._card.show()

        for ref in list(self._overlay_anims):
            try:
                ref.stop()
            except RuntimeError:
                pass
        self._overlay_anims.clear()

        if not mt.is_motion_enabled():
            self._scrim.alpha = 1.0
            return

        scrim_anim = QPropertyAnimation(self._scrim, b"alpha", self)
        scrim_anim.setDuration(mt.duration_base)
        scrim_anim.setEasingCurve(mt.curve_enter)
        scrim_anim.setStartValue(0.0)
        scrim_anim.setEndValue(1.0)

        eff = QGraphicsOpacityEffect(self._card)
        self._card.setGraphicsEffect(eff)
        op_anim = QPropertyAnimation(eff, b"opacity", self._card)
        op_anim.setDuration(mt.duration_base)
        op_anim.setEasingCurve(mt.curve_enter)
        op_anim.setStartValue(0.0)
        op_anim.setEndValue(1.0)

        geo_anim = QPropertyAnimation(self._card, b"geometry", self._card)
        geo_anim.setDuration(mt.duration_base)
        geo_anim.setEasingCurve(mt.curve_enter)
        geo_anim.setStartValue(self._scaled_geo(0.92))
        geo_anim.setEndValue(QRect(int(target.x()), int(target.y()),
                                   int(target.width()), int(target.height())))

        group = QParallelAnimationGroup(self._card)
        group.addAnimation(scrim_anim)
        group.addAnimation(op_anim)
        group.addAnimation(geo_anim)

        def _finished():
            try:
                if self._card is not None:
                    self._card.setGraphicsEffect(None)
                    g = self._overlay_geometry()
                    self._card.setGeometry(int(g.x()), int(g.y()),
                                           int(g.width()), int(g.height()))
            except RuntimeError:
                pass
        group.finished.connect(_finished)
        self._overlay_anims.append(group)
        group.start()

    def close_detail(self, instant: bool = False):
        if self._scrim is None or self._card is None:
            return
        if instant or not mt.is_motion_enabled():
            self._teardown_overlays()
            return
        if self._closing:
            return
        self._closing = True
        for ref in list(self._overlay_anims):
            try:
                ref.stop()
            except RuntimeError:
                pass
        self._overlay_anims.clear()

        scrim_anim = QPropertyAnimation(self._scrim, b"alpha", self)
        scrim_anim.setDuration(mt.duration_fast)
        scrim_anim.setEasingCurve(mt.curve_exit)
        scrim_anim.setStartValue(self._scrim.alpha)
        scrim_anim.setEndValue(0.0)

        eff = QGraphicsOpacityEffect(self._card)
        self._card.setGraphicsEffect(eff)
        op_anim = QPropertyAnimation(eff, b"opacity", self._card)
        op_anim.setDuration(mt.duration_fast)
        op_anim.setEasingCurve(mt.curve_exit)
        op_anim.setStartValue(1.0)
        op_anim.setEndValue(0.0)

        geo_anim = QPropertyAnimation(self._card, b"geometry", self._card)
        geo_anim.setDuration(mt.duration_fast)
        geo_anim.setEasingCurve(mt.curve_exit)
        geo_anim.setStartValue(self._card.geometry())
        geo_anim.setEndValue(self._scaled_geo(0.96))

        group = QParallelAnimationGroup(self)
        group.addAnimation(scrim_anim)
        group.addAnimation(op_anim)
        group.addAnimation(geo_anim)
        group.finished.connect(self._teardown_overlays)
        self._overlay_anims.append(group)
        group.start()

    def _teardown_overlays(self):
        self._closing = False
        for ref in list(self._overlay_anims):
            try:
                ref.stop()
            except RuntimeError:
                pass
        self._overlay_anims.clear()
        if self._card is not None:
            try:
                self._card.setGraphicsEffect(None)
            except RuntimeError:
                pass
            self._card.hide()
            self._card.deleteLater()
            self._card = None
        if self._scrim is not None:
            self._scrim.hide()
            self._scrim.deleteLater()
            self._scrim = None
        self._selected_eid = None

    # ---------------------------------------------------------
    # Detail actions
    # ---------------------------------------------------------
    def _on_card_saved(self, eid: str):
        self._load_month(self._current_year, self._current_month)
        self.dataChanged.emit()

    def _on_delete_confirmed(self, eid: str):
        item = self._find_item_by_eid(eid)
        path = Path(item.get("path") or "") if item else None
        if path is not None and path.exists():
            success, err = delete_path(path)
            if not success:
                self._toast("ERROR", f"Failed to delete photo:\n{err}")
                return
        api = self._ensure_api()
        try:
            if api is not None:
                api.record_deletion(eid, reason="user_deleted")
        except Exception as e:
            self._toast("ERROR", f"Failed to delete photo:\n{e}")
            return
        self.close_detail(instant=True)
        self.reload_all()
        self.photoDeleted.emit()

    # ---------------------------------------------------------
    # Theme / resize / keys
    # ---------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._scrim is not None and self._scrim.isVisible():
            self._scrim.setGeometry(0, 0, self.width(), self.height())
        if self._card is not None and self._card.isVisible():
            geo = self._overlay_geometry()  # re-center while detail open
            self._card.move(int(geo.x()), int(geo.y()))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._card is not None:
            self.close_detail()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_theme_changed(self):
        self._apply_theme()

    def _apply_theme(self):
        v = theme_vars()
        self.setStyleSheet(f"""
            QWidget#CalendarPage {{
                background-color: {v['background']};
            }}
        """)
        self._surface.apply_theme()
        self.header_bar.apply_theme()
        self.weekday_row.apply_theme()
        self.hint.apply_theme()
        self.legend.apply_theme()
        self.empty_view.apply_theme()
        self._viz_sep.setStyleSheet(f"background-color: {v['outline_variant']};")
        self._heat_card.setStyleSheet(f"""
            QFrame#HeatmapCard {{
                background-color: {v['surface_container_low']};
                border-radius: 16px;
            }}
        """)
        self.heatmap.update()
        if self._card is not None:
            self._card.apply_theme()
        self._update_chips()
