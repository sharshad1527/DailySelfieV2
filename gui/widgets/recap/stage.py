# gui/widgets/recap/stage.py
"""
Recap Stage — modal recap overlay per docs/design/motion-system.md C3.

RecapStage is ALWAYS a child of the caller's content widget (never
top-level). Owns the scrim, the card host (retargeting slide/fade swaps),
progress dots (draining over the 5s dwell @30fps), keyboard/focus trapping,
press-and-hold pause, zone clicks and the 5s auto-advance timer (the timer
is functional feedback and is deliberately NOT gated on motion_enabled;
transitions are).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import (
    Property, QEvent, QObject, QRectF, QSize, Qt, QTimer, QVariantAnimation,
    QParallelAnimationGroup, Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsOpacityEffect, QLabel, QPushButton,
    QWidget,
)

from gui.theme import motion_tokens as mt
from gui.theme.theme_vars import theme_vars
from gui.widgets.pixmap_utils import active_dpr, recolored_icon

from pathlib import Path

from .cards import (
    BestShotsCard, ClockVizCard, CoverCard, FinaleCard, MoodPaletteCard,
    StreakCard, YearColorCard,
)
from .cards.base import qss_rgba

# stage.py sits at gui/widgets/recap/ -> parents[2] is gui/, which owns
# assets/icons (cards/*.py are one level deeper, hence parents[3] there).
ICONS_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons"

SCRIM_ALPHA = 0.78
DWELL_MS = 5000
HOLD_MS = 250
DOT_FPS_MS = 33


# ---------------------------------------------------------------
# Scrim
# ---------------------------------------------------------------
class RecapScrim(QWidget):
    """Full-cover scrim painted at rgba(scrim, .78 * alpha); consumes clicks.

    A plain click (press+release under the hold threshold) emits
    closeRequested; press-and-hold pauses instead via the stage's timer.
    """

    closeRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._alpha = 0.0
        self._visible_lock = False
        self.hide()

    def _get_alpha(self) -> float:
        return self._alpha

    def _set_alpha(self, value: float) -> None:
        self._alpha = max(0.0, min(1.0, float(value)))
        if self._alpha > 0 and not self.isVisible():
            self.show()
        if self._alpha <= 0 and self.isVisible() and not self._visible_lock:
            self.hide()
        self.update()

    alpha = Property(float, _get_alpha, _set_alpha)

    def paintEvent(self, event) -> None:
        if self._alpha <= 0:
            return
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        p.setBrush(theme_vars().rgba("scrim", SCRIM_ALPHA * self._alpha))
        p.drawRect(self.rect())
        p.end()

    def mousePressEvent(self, event) -> None:
        event.accept()
        stage = self.parentWidget()
        if isinstance(stage, RecapStage):
            stage.gesture_press(self)

    def mouseReleaseEvent(self, event) -> None:
        event.accept()
        stage = self.parentWidget()
        if isinstance(stage, RecapStage):
            if stage.gesture_release(self):
                self.closeRequested.emit()


# ---------------------------------------------------------------
# Card host (retarget-not-queue swaps)
# ---------------------------------------------------------------
class RecapCardHost(QFrame):
    """Swaps card widgets with direction-aware ±16px slide + fade (tokens).

    Rapid requests snap-finish the in-flight transition before starting the
    next one (stop-before-start, never queued). Effects live only during
    flight and are detached in finished.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("RecapCardHost")
        self._current: Optional[QWidget] = None
        self._anim: Optional[QParallelAnimationGroup] = None
        self._fading: Optional[QGraphicsOpacityEffect] = None
        self._fading_target: Optional[QWidget] = None

    def current_card(self) -> Optional[QWidget]:
        return self._current

    def set_card(self, widget: QWidget, direction: int) -> None:
        if widget is self._current:
            return
        self._snap_finish()
        old = self._current
        self._current = widget
        widget.setGeometry(self.rect())
        widget.setParent(self)
        widget.show()
        widget.raise_()
        if old is not None and old is not widget:
            old.hide()
        moving = bool(mt.is_motion_enabled()) and direction != 0
        if not moving:
            widget.move(0, 0)
            return
        sign = 1 if direction > 0 else -1
        widget.move(sign * mt.slide_distance, 0)
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)
        self._fading = effect
        self._fading_target = widget
        pos_anim = QVariantAnimation(self)
        pos_anim.setStartValue(float(sign * mt.slide_distance))
        pos_anim.setEndValue(0.0)
        pos_anim.setDuration(mt.duration_base)
        pos_anim.setEasingCurve(mt.curve_enter)
        pos_anim.valueChanged.connect(lambda x, w=widget: w.move(round(x), 0))
        fade_anim = QVariantAnimation(self)
        fade_anim.setStartValue(0.0)
        fade_anim.setEndValue(1.0)
        fade_anim.setDuration(mt.duration_base)
        fade_anim.setEasingCurve(mt.curve_enter)
        fade_anim.valueChanged.connect(effect.setOpacity)
        group = QParallelAnimationGroup(self)
        group.addAnimation(pos_anim)
        group.addAnimation(fade_anim)
        group.finished.connect(self._transition_finished)
        self._anim = group
        group.start()

    def _transition_finished(self) -> None:
        self._fading = None
        target = self._fading_target
        self._fading_target = None
        if target is not None and target.graphicsEffect() is not None:
            target.setGraphicsEffect(None)
        self._anim = None

    def _snap_finish(self) -> None:
        """Stop-before-start: apply end state of any in-flight transition."""
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        cur = self._current
        if cur is not None:
            cur.move(0, 0)
            if cur.graphicsEffect() is not None:
                cur.setGraphicsEffect(None)
        self._fading = None
        self._fading_target = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._current is not None:
            self._current.setGeometry(self.rect())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            event.accept()
            stage = self.parentWidget()
            if isinstance(stage, RecapStage):
                stage.gesture_press(self, event.position())
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            event.accept()
            stage = self.parentWidget()
            if isinstance(stage, RecapStage):
                stage.gesture_release(self, event.position())
            return
        super().mouseReleaseEvent(event)


# ---------------------------------------------------------------
# Progress dots
# ---------------------------------------------------------------
class ProgressDots(QWidget):
    """Painted dot segments; the active one drains across the dwell time."""

    SEG_W, GAP, HEIGHT = 30, 9, 5

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._count = 0
        self._active = -1
        self._fraction = 1.0
        self._dwell_ms = DWELL_MS
        self._dirty_left = -1.0
        self._anim: Optional[QVariantAnimation] = None
        self._tick = QTimer(self)
        self._tick.setInterval(DOT_FPS_MS)
        self._tick.timeout.connect(self._repaint_active)

    # ---- API --------------------------------------------------------------
    def set_count(self, count: int) -> None:
        self._count = max(0, int(count))
        self.setMinimumSize(self.sizeHint())
        self._active = min(self._active, self._count - 1)
        self.update()

    def set_active(self, index: int, dwell_ms: int = DWELL_MS,
                   restart_drain: bool = True) -> None:
        index = max(0, int(index))
        changed = index != self._active
        self._active = index
        self._dwell_ms = max(1, int(dwell_ms))
        if restart_drain:
            self.restart_drain()
        elif changed:
            self.update()

    def restart_drain(self) -> None:
        self._kill_anim()
        anim = QVariantAnimation(self)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setDuration(self._dwell_ms)
        anim.valueChanged.connect(self._on_fraction)
        anim.finished.connect(self._on_drain_done)
        self._anim = anim
        self._fraction = 1.0
        self._dirty_left = -1.0
        anim.start()
        self._tick.start()

    def pause(self) -> None:
        if self._anim is not None:
            self._anim.pause()
        self._tick.stop()

    def resume(self) -> None:
        if self._anim is not None:
            self._anim.resume()
        self._tick.start()

    def stop_drain(self) -> None:
        self._kill_anim()
        self._tick.stop()

    def _kill_anim(self) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        self._tick.stop()

    # ---- internals -----------------------------------------------------------
    def _on_fraction(self, value) -> None:
        self._fraction = float(value)

    def _on_drain_done(self) -> None:
        # Final paint of the empty active segment, then stop the 30fps tick
        # so a resting deck costs nothing.
        self._fraction = 0.0
        self._tick.stop()
        self.update(self.active_rect().toRect().adjusted(-1, -1, 2, 2))

    def _repaint_active(self) -> None:
        rect = self.active_rect()
        if self._dirty_left >= 0:
            rect = rect.united(QRectF(self._dirty_left, 0,
                                      self.SEG_W - self._dirty_left + 2, self.height()))
        self._dirty_left = self.active_rect().left()
        self.update(rect.toRect().adjusted(-1, -1, 2, 2))

    def active_rect(self) -> QRectF:
        seg_w = self.SEG_W + self.GAP
        return QRectF(self._active * seg_w, 0, self.SEG_W, self.height())

    def sizeHint(self):
        return QSize(max(self._count * (self.SEG_W + self.GAP) - self.GAP, 1),
                     self.HEIGHT)

    def paintEvent(self, event) -> None:
        if self._count <= 0:
            return
        v = theme_vars()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        radius = h / 2
        done_color = theme_vars().rgba("on_surface", 0.38)
        todo_color = theme_vars().rgba("outline_variant", 0.85)
        for i in range(self._count):
            x = i * (self.SEG_W + self.GAP)
            rect = QRectF(x, 0, self.SEG_W, h)
            if i < self._active:
                p.setPen(Qt.NoPen)
                p.setBrush(done_color)
                p.drawRoundedRect(rect, radius, radius)
            elif i > self._active:
                p.setPen(Qt.NoPen)
                p.setBrush(todo_color)
                p.drawRoundedRect(rect, radius, radius)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(todo_color)
                p.drawRoundedRect(rect, radius, radius)
                fill_w = max(self.SEG_W * self._fraction, 2.0)
                fill = QRectF(x, 0, fill_w, h)
                p.setBrush(QColor(v["primary"]))
                p.drawRoundedRect(fill, radius, radius)
        p.end()


# ---------------------------------------------------------------
# Stage
# ---------------------------------------------------------------
class RecapStage(QWidget):
    """Modal recap overlay; MUST be constructed with a parent content widget."""

    closed = Signal()
    savePngRequested = Signal(object)
    saveAllRequested = Signal()
    shotClicked = Signal(str)

    def __init__(self, parent: QWidget):
        if parent is None:
            raise ValueError("RecapStage requires a parent content widget "
                             "(never top-level)")
        super().__init__(parent)

        self._recap_data: Dict[str, Any] = {}
        self._scope = "month"
        self._invoker: Optional[QWidget] = None
        self._deck: List[QWidget] = []
        self._index = 0
        self._is_open = False
        self._closing = False
        self._paused = False
        self._pause_from_hold = False

        # Held animation/timer refs (GC guard + retargeting)
        self._open_anim: Optional[QParallelAnimationGroup] = None
        self._close_anim: Optional[QParallelAnimationGroup] = None
        self._host_scale_anim: Optional[QVariantAnimation] = None
        self._host_fade_effect: Optional[QGraphicsOpacityEffect] = None
        self._host_scale = 0.96
        self._full_rect = QRectF()

        self.scrim = RecapScrim(self)
        self.scrim.closeRequested.connect(self.close)
        self.host = RecapCardHost(self)
        self.dots = ProgressDots(self)
        self.caption_lbl = QLabel("", self)
        self.caption_lbl.setObjectName("RecapCaption")
        self.caption_lbl.setAlignment(Qt.AlignCenter)
        self.close_btn = QPushButton(self)
        self.close_btn.setObjectName("RecapCloseButton")
        self.close_btn.setFixedSize(34, 34)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip("Close (Esc)")
        self.close_btn.clicked.connect(self.close)

        self._dwell_timer = QTimer(self)
        self._dwell_timer.setSingleShot(True)
        self._dwell_timer.timeout.connect(self._on_dwell_timeout)
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._on_hold_timeout)

        self.hide()

    # ------------------------------------------------------------------
    # Open / close
    # ------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def cards(self) -> List[QWidget]:
        return list(self._deck)

    def open(self, recap_data: Dict[str, Any], scope: str = "month",
             invoker: Optional[QWidget] = None) -> None:
        if self._is_open:
            return
        self._recap_data = dict(recap_data) if isinstance(recap_data, dict) else {}
        self._scope = str(scope or "month")
        self._invoker = invoker
        self._closing = False
        self._paused = False
        self._pause_from_hold = False

        self._build_deck()
        if not self._deck:
            return

        self.fit_to_parent()
        self.scrim.setGeometry(self.rect())
        self._relayout()

        self._index = 0
        self.host.set_card(self._deck[0], 0)
        self.dots.set_count(len(self._deck))
        self.dots.resize(self.dots.sizeHint())
        self._relayout()
        self.dots.set_active(0, DWELL_MS, restart_drain=False)

        self._is_open = True
        self.show()
        self.raise_()
        self._apply_theme_chrome()

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        if mt.is_motion_enabled():
            self.scrim.alpha = 0.0
            self.scrim._visible_lock = True
            self.scrim.show()
            self._host_scale = 0.96
            self._apply_host_geometry()
            effect = QGraphicsOpacityEffect(self.host)
            effect.setOpacity(0.0)
            self.host.setGraphicsEffect(effect)
            self._host_fade_effect = effect

            scrim_anim = QVariantAnimation(self)
            scrim_anim.setStartValue(0.0)
            scrim_anim.setEndValue(1.0)
            scrim_anim.setDuration(mt.duration_base)
            scrim_anim.setEasingCurve(mt.curve_enter)
            scrim_anim.valueChanged.connect(lambda val: setattr(self.scrim, "alpha", val))

            scale_anim = QVariantAnimation(self)
            scale_anim.setStartValue(0.96)
            scale_anim.setEndValue(1.0)
            scale_anim.setDuration(mt.duration_base)
            scale_anim.setEasingCurve(mt.curve_enter)
            scale_anim.valueChanged.connect(self._set_host_scale)

            fade_anim = QVariantAnimation(self)
            fade_anim.setStartValue(0.0)
            fade_anim.setEndValue(1.0)
            fade_anim.setDuration(mt.duration_base)
            fade_anim.setEasingCurve(mt.curve_enter)
            fade_anim.valueChanged.connect(effect.setOpacity)

            group = QParallelAnimationGroup(self)
            group.addAnimation(scrim_anim)
            group.addAnimation(scale_anim)
            group.addAnimation(fade_anim)
            group.finished.connect(self._open_finished)
            self._open_anim = group
            group.start()
        else:
            self.scrim.alpha = 1.0
            self.scrim._visible_lock = False
            self._set_host_scale(1.0)
            # No open-transition effect — entrances can start right away.
            self._arm_deck_entrances()

        self.setFocus(Qt.OtherFocusReason)
        self._connect_theme_changed()
        self._arm_dwell()
        self.dots.restart_drain()

    def close(self) -> None:
        if not self._is_open or self._closing:
            return
        self._closing = True
        self._disarm_timers()

        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

        invoker = self._invoker
        if invoker is not None:
            try:
                invoker.setFocus(Qt.OtherFocusReason)
            except RuntimeError:
                pass
        self._invoker = None

        self._finish_open_now()
        for card in self._deck:
            try:
                card.stop_animations()
            except RuntimeError:
                pass
        # Belt-and-braces: no descendant effect may nest inside the close
        # grab (one-effect-per-subtree, motion-system.md rule 1).
        for child in self.host.findChildren(QWidget):
            try:
                if child.graphicsEffect() is not None:
                    child.setGraphicsEffect(None)
            except RuntimeError:
                pass
        self.dots.stop_drain()

        if mt.is_motion_enabled():
            effect = QGraphicsOpacityEffect(self.host)
            effect.setOpacity(1.0)
            self.host.setGraphicsEffect(effect)
            self._host_fade_effect = effect

            scrim_anim = QVariantAnimation(self)
            scrim_anim.setStartValue(1.0)
            scrim_anim.setEndValue(0.0)
            scrim_anim.setDuration(mt.duration_fast)
            scrim_anim.setEasingCurve(mt.curve_exit)
            scrim_anim.valueChanged.connect(lambda val: setattr(self.scrim, "alpha", val))

            scale_anim = QVariantAnimation(self)
            scale_anim.setStartValue(self._host_scale)
            scale_anim.setEndValue(0.96)
            scale_anim.setDuration(mt.duration_fast)
            scale_anim.setEasingCurve(mt.curve_exit)
            scale_anim.valueChanged.connect(self._set_host_scale)

            fade_anim = QVariantAnimation(self)
            fade_anim.setStartValue(1.0)
            fade_anim.setEndValue(0.0)
            fade_anim.setDuration(mt.duration_fast)
            fade_anim.setEasingCurve(mt.curve_exit)
            fade_anim.valueChanged.connect(effect.setOpacity)

            group = QParallelAnimationGroup(self)
            group.addAnimation(scrim_anim)
            group.addAnimation(scale_anim)
            group.addAnimation(fade_anim)
            group.finished.connect(self._teardown)
            self._close_anim = group
            group.start()
        else:
            self.scrim.alpha = 0.0
            self._teardown()

    def _open_finished(self) -> None:
        if self._open_anim is not None:
            self._open_anim.deleteLater()
            self._open_anim = None
        self.scrim._visible_lock = False
        if self._host_fade_effect is not None:
            self.host.setGraphicsEffect(None)
            self._host_fade_effect = None
        self._set_host_scale(1.0)
        # Host effect is detached — only now may card section-fades attach.
        self._arm_deck_entrances()

    def _arm_deck_entrances(self) -> None:
        if self._closing:
            return
        for card in self._deck:
            try:
                card.arm_entrance()
            except RuntimeError:
                pass

    def _finish_open_now(self) -> None:
        if self._open_anim is not None:
            self._open_anim.stop()
            self._open_anim.deleteLater()
            self._open_anim = None
        self.scrim._visible_lock = False
        if self._host_fade_effect is not None:
            self.host.setGraphicsEffect(None)
            self._host_fade_effect = None

    def _teardown(self) -> None:
        self._disconnect_theme_changed()
        if self._close_anim is not None:
            self._close_anim.deleteLater()
            self._close_anim = None
        if self.host.graphicsEffect() is not None:
            self.host.setGraphicsEffect(None)
        self._host_fade_effect = None
        self._disarm_timers()
        self._is_open = False
        self.hide()
        self.closed.emit()
        self.deleteLater()

    # ------------------------------------------------------------------
    # Deck
    # ------------------------------------------------------------------
    def _build_deck(self) -> None:
        for card in self._deck:
            card.deleteLater()
        self._deck = []

        d = self._recap_data
        counter = {"i": 0}

        def add(card_cls):
            card = card_cls(accent_index=counter["i"] % 3)
            counter["i"] += 1
            card.populate(d)
            card.savePngRequested.connect(self.savePngRequested.emit)
            if isinstance(card, CoverCard):
                card.playToggled.connect(self.set_paused)
            if isinstance(card, FinaleCard):
                card.saveAllRequested.connect(self.saveAllRequested.emit)
            if isinstance(card, BestShotsCard):
                card.shotClicked.connect(self.shotClicked.emit)
            self._deck.append(card)

        distribution = d.get("distribution")
        mood_total = sum(_as_int(v) for v in distribution.values()) \
            if isinstance(distribution, dict) else 0
        shots = d.get("shot_rows") or d.get("top_shots")
        has_shots = isinstance(shots, (list, tuple)) and len(shots) > 0
        favorite_hour = d.get("favorite_hour")
        hours_hist = d.get("hours")

        add(CoverCard)
        add(StreakCard)
        if mood_total > 0:
            add(MoodPaletteCard)
        if has_shots:
            add(BestShotsCard)
        if favorite_hour is not None or isinstance(hours_hist, dict) and hours_hist:
            add(ClockVizCard)
        if isinstance(d.get("monthly"), dict) and d.get("monthly"):
            add(YearColorCard)
        add(FinaleCard)

    # ------------------------------------------------------------------
    # Navigation / dwell
    # ------------------------------------------------------------------
    def advance(self, delta: int, wrap: bool = True) -> None:
        if not self._is_open or self._closing or delta == 0 or not self._deck:
            return
        n = len(self._deck)
        start = self._index
        idx = start + int(delta)
        if idx < 0 or idx >= n:
            if not wrap:
                return
            idx %= n
        direction = 1 if delta > 0 else -1
        jumped = abs(idx - start) != abs(delta)
        self._index = idx
        self.host.set_card(self._deck[idx], 0 if jumped else direction)
        self.dots.set_active(idx, DWELL_MS, restart_drain=not self._paused)
        if not self._paused:
            self._arm_dwell()

    def go_home(self) -> None:
        self._jump_to(0)

    def go_end(self) -> None:
        self._jump_to(len(self._deck) - 1)

    def _jump_to(self, idx: int) -> None:
        if not self._deck:
            return
        idx = max(0, min(int(idx), len(self._deck) - 1))
        if idx == self._index:
            return
        self._index = idx
        self.host.set_card(self._deck[idx], 0)
        self.dots.set_active(idx, DWELL_MS, restart_drain=not self._paused)
        if not self._paused:
            self._arm_dwell()

    def _arm_dwell(self) -> None:
        if self._closing or not self._is_open:
            return
        self._dwell_timer.stop()
        self._dwell_timer.start(DWELL_MS)

    def _disarm_timers(self) -> None:
        self._dwell_timer.stop()
        self._hold_timer.stop()

    def _on_dwell_timeout(self) -> None:
        if not self._paused:
            self.advance(+1)

    def set_paused(self, paused: bool, from_hold: bool = False) -> None:
        if self._closing:
            return
        paused = bool(paused)
        if paused == self._paused and not from_hold:
            return
        self._paused = paused
        self._update_caption()
        for card in self._deck:
            if isinstance(card, CoverCard):
                card.set_paused(paused)
        if paused:
            self._dwell_timer.stop()
            self.dots.pause()
        else:
            # Dwell restarts full-length; the dot drain follows the timer.
            self.dots.restart_drain()
            self._arm_dwell()

    def toggle_pause(self) -> None:
        self.set_paused(not self._paused)

    # ------------------------------------------------------------------
    # Press-and-hold / zone clicks
    # ------------------------------------------------------------------
    def gesture_press(self, source: QWidget, local_pos=None) -> None:
        if self._closing:
            return
        if not self._paused:
            self._hold_timer.start(HOLD_MS)

    def gesture_release(self, source: QWidget, local_pos=None) -> bool:
        """Handle a release; True = treat as a plain click (scrim closes)."""
        if self._closing:
            return False
        self._hold_timer.stop()
        if self._pause_from_hold:
            self._pause_from_hold = False
            self.set_paused(False)
            return False
        if isinstance(source, RecapScrim):
            return True  # closeRequested fires even while button-paused
        if isinstance(source, RecapCardHost):
            width = max(source.width(), 1)
            x = float(local_pos.x()) if local_pos is not None else width / 2
            self.advance(-1 if x / width < 0.4 else +1)
        return False

    def _on_hold_timeout(self) -> None:
        if self._closing:
            return
        self._pause_from_hold = True
        self.set_paused(True)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------
    def fit_to_parent(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.scrim.setGeometry(self.rect())
        self._relayout()

    def _card_size(self):
        w = max(min(self.width() - 72, 520), 260)
        h = max(min(self.height() - 170, 700), 240)
        return w, h

    def _relayout(self) -> None:
        cw, ch = self._card_size()
        margin_top = 26
        self._full_rect = QRectF((self.width() - cw) / 2.0, margin_top, cw, ch)
        self._apply_host_geometry()

        btn_x = int(self._full_rect.right() - self.close_btn.width() - 10)
        btn_y = int(self._full_rect.top() + 8)
        self.close_btn.move(btn_x, btn_y)
        self.close_btn.raise_()

        dots_y = int(self._full_rect.bottom()) + 14
        self.dots.move(int((self.width() - self.dots.width()) / 2), dots_y)
        cap_y = dots_y + self.dots.height() + 6
        self.caption_lbl.setGeometry(0, cap_y, self.width(),
                                     max(self.height() - cap_y - 6, 18))
        self._update_caption()

    def _apply_host_geometry(self) -> None:
        r = QRectF(self._full_rect)
        dw = r.width() * (1.0 - self._host_scale)
        dh = r.height() * (1.0 - self._host_scale)
        scaled = r.adjusted(dw / 2, dh / 2, -dw / 2, -dh / 2)
        self.host.setGeometry(scaled.toRect())
        self.host.raise_()

    def _set_host_scale(self, value: float) -> None:
        self._host_scale = float(value)
        self._apply_host_geometry()

    # ------------------------------------------------------------------
    # Theme / captions
    # ------------------------------------------------------------------
    def _connect_theme_changed(self) -> None:
        try:
            theme_vars()._controller.themeChanged.connect(self.apply_theme)
        except (RuntimeError, AttributeError, TypeError):
            pass

    def _disconnect_theme_changed(self) -> None:
        try:
            theme_vars()._controller.themeChanged.disconnect(self.apply_theme)
        except (RuntimeError, AttributeError, TypeError):
            pass

    def apply_theme(self) -> None:
        self._apply_theme_chrome()
        for card in self._deck:
            card.apply_theme()
        self.update()

    def _apply_theme_chrome(self) -> None:
        v = theme_vars()
        self.close_btn.setIcon(recolored_icon(
            ICONS_DIR / "close.svg", QColor(v["on_surface"]), active_dpr(self)))
        self.host.setStyleSheet(f"""
            QFrame#RecapCardHost {{
                background-color: {v['surface_container_high']};
                border-radius: 22px;
                border: 1px solid {qss_rgba(v['outline_variant'], 0.7)};
            }}
        """)
        self.caption_lbl.setStyleSheet(f"""
            QLabel#RecapCaption {{
                color: {qss_rgba(v['on_surface'], 0.75)};
                background: transparent;
                font-size: 11px;
                font-weight: 500;
            }}
        """)
        self.close_btn.setStyleSheet(f"""
            QPushButton#RecapCloseButton {{
                background-color: {qss_rgba(v['surface_container_highest'], 0.9)};
                border-radius: 17px;
                border: 1px solid {qss_rgba(v['outline_variant'], 0.6)};
            }}
            QPushButton#RecapCloseButton:hover {{
                background-color: {v['surface_container_highest']};
            }}
        """)
        self.dots.update()
        self._update_caption()

    def _update_caption(self) -> None:
        if self._paused:
            self.caption_lbl.setText("Paused")
        else:
            self.caption_lbl.setText(
                "Click left / right to browse  ·  Hold to pause  ·  Esc closes")

    # ------------------------------------------------------------------
    # Events: keys + focus trap
    # ------------------------------------------------------------------
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Resize and watched is self.parentWidget() \
                and self._is_open:
            self.fit_to_parent()
            return False
        if event.type() == QEvent.KeyPress and self._is_open and not self._closing:
            key = event.key()
            if key == Qt.Key_Escape:
                self.close()
                return True
            if key == Qt.Key_Left:
                self.advance(-1)
                return True
            if key == Qt.Key_Right:
                self.advance(+1)
                return True
            if key == Qt.Key_Home:
                self.go_home()
                return True
            if key == Qt.Key_End:
                self.go_end()
                return True
            if key == Qt.Key_Space:
                focused = QApplication.focusWidget()
                if isinstance(focused, QPushButton) and self.isAncestorOf(focused):
                    return False
                self.toggle_pause()
                return True
            if key in (Qt.Key_Tab, Qt.Key_Backtab):
                return self._trap_focus(key == Qt.Key_Backtab)
        return super().eventFilter(watched, event)

    def _focus_chain(self) -> List[QWidget]:
        out: List[QWidget] = []
        for w in self.findChildren(QWidget):
            if not w.isVisible() or not w.isEnabled() or not w.focusPolicy() & (
                    Qt.TabFocus | Qt.StrongFocus):
                continue
            out.append(w)
        out.sort(key=lambda w: (w.mapTo(self, w.rect().center()).y(),
                                w.mapTo(self, w.rect().center()).x()))
        return out

    def _trap_focus(self, backwards: bool) -> bool:
        chain = self._focus_chain()
        if not chain:
            self.setFocus(Qt.TabFocusReason)
            return True
        focused = QApplication.focusWidget()
        try:
            idx = chain.index(focused) if focused in chain else -1
        except RuntimeError:
            idx = -1
        nxt = (idx + (-1 if backwards else 1)) % len(chain) if idx >= 0 \
            else (len(chain) - 1 if backwards else 0)
        chain[nxt].setFocus(Qt.TabFocusReason if not backwards
                            else Qt.BacktabFocusReason)
        return True


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
