# gui/widgets/recap/cards/base.py
"""
RecapCardBase + shared paint helpers for the Recap Stage cards.

Cards are plain QWidget subtrees populated from a build_recap_stats dict
(missing keys degrade, never raise). Accent colors rotate through the
theme container pairs (primary/secondary/tertiary) so consecutive deck
cards never share a chrome accent. Entrance = per-section fade staggered
min(i,8)*20ms (motion-gated), effects detached when finished.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import (
    Property, QEasingCurve, QRectF, QTimer, QVariantAnimation, Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QGraphicsOpacityEffect, QVBoxLayout, QWidget

from gui.theme import motion_tokens as mt
from gui.theme.theme_vars import theme_vars

ACCENT_PAIRS = (
    ("primary_container", "on_primary_container"),
    ("secondary_container", "on_secondary_container"),
    ("tertiary_container", "on_tertiary_container"),
)


def _d(data: Any, key: str, default=None):
    """Defensive mapping lookup (None data / non-dict -> default)."""
    if not isinstance(data, dict):
        return default
    value = data.get(key, default)
    return default if value is None else value


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def qss_rgba(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {max(0.0, min(1.0, alpha)) * 100:.0f}%)"


class PaintedScalar(QWidget):
    """Count-up painted scalar (600ms OutCubic) — cost-ladder friendly."""

    def __init__(self, font_px: int = 56, color_key: str = "on_surface",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._value = 0.0
        self._target = 0.0
        self._fmt = "{:.0f}"
        self._suffix = ""
        self._font_px = int(font_px)
        self._color_key = color_key
        self._anim: Optional[QVariantAnimation] = None
        self.setMinimumHeight(int(font_px * 1.25))

    # ---- configuration --------------------------------------------------
    def set_format(self, fmt: str) -> None:
        self._fmt = fmt

    def set_suffix(self, suffix: str) -> None:
        self._suffix = suffix

    def set_font_px(self, px: int) -> None:
        self._font_px = max(10, int(px))
        self.setMinimumHeight(int(self._font_px * 1.25))
        self.update()

    # ---- animation -------------------------------------------------------
    def set_target(self, target: float, animate: bool = True) -> None:
        self._target = float(target)
        if not animate or not mt.is_motion_enabled():
            self._kill_anim()
            self._value = self._target
            self.update()
            return
        anim = QVariantAnimation(self)
        anim.setStartValue(self._value)
        anim.setEndValue(self._target)
        anim.setDuration(600)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(self._on_tick)
        anim.finished.connect(self._on_done)
        self._kill_anim()
        self._anim = anim
        anim.start()

    def snap_to_target(self) -> None:
        self.set_target(self._target, animate=False)

    def _kill_anim(self) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None

    def _on_tick(self, value) -> None:
        self._value = float(value)
        if self.isVisible():
            self.update()

    def _on_done(self) -> None:
        self._value = self._target
        if self._anim is not None:
            self._anim.deleteLater()
        self._anim = None
        if self.isVisible():
            self.update()

    # ---- painting ----------------------------------------------------------
    def _get_value(self) -> float:
        return self._value

    def _set_value(self, v: float) -> None:
        self._value = float(v)
        self.update()

    value = Property(float, _get_value, _set_value)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        f = QFont(self.font())
        f.setPixelSize(self._font_px)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(theme_vars()[self._color_key]))
        text = self._fmt.format(self._value) + self._suffix
        fm = QFontMetrics(f)
        p.drawText(
            QRectF(0, 0, self.width(), self.height()), Qt.AlignLeft | Qt.AlignVCenter,
            fm.elidedText(text, Qt.ElideRight, self.width()),
        )
        p.end()


class RecapCardBase(QWidget):
    """Common card plumbing: populate/apply_theme/entrance/save signal."""

    savePngRequested = Signal(object)

    CARD_KIND = "base"

    def __init__(self, parent: Optional[QWidget] = None, accent_index: int = 0):
        super().__init__(parent)
        self._data: Dict[str, Any] = {}
        self.accent_index = max(0, int(accent_index)) % len(ACCENT_PAIRS)
        self._sections: List[QWidget] = []
        self._entered = False
        # Armed by the stage once its own open-transition host effect is
        # detached; section fades must never nest inside that effect
        # (one-effect-per-subtree, motion-system.md rule 1).
        self._entrance_armed = False
        self._entrance_timers: List[QTimer] = []
        self._section_anims: List[QVariantAnimation] = []
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(28, 44, 28, 24)
        self._lay.setSpacing(14)

    # ---- data API ---------------------------------------------------------
    @property
    def data(self) -> Dict[str, Any]:
        return self._data

    def populate(self, recap_data: Dict[str, Any]) -> None:
        self._data = recap_data if isinstance(recap_data, dict) else {}
        self.rebuild()

    def accent(self):
        fill_key, on_key = ACCENT_PAIRS[self.accent_index]
        v = theme_vars()
        return v[fill_key], v[on_key]

    # ---- structure --------------------------------------------------------
    def rebuild(self) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._sections = []
        self._cancel_entrance()
        self._entered = False
        self.build_content()
        self.apply_theme()

    def build_content(self) -> None:
        raise NotImplementedError

    def add_section(self, widget: QWidget) -> QWidget:
        self._lay.addWidget(widget)
        self._sections.append(widget)
        return widget

    def apply_theme(self) -> None:
        pass

    # ---- entrance (C2 stagger, motion-gated) -------------------------------
    def arm_entrance(self) -> None:
        """Stage calls this after _open_finished detaches its host effect."""
        self._entrance_armed = True
        self.play_entrance()

    def play_entrance(self) -> None:
        if self._entered or not self.isVisible():
            return
        self._entered = True
        if not mt.is_motion_enabled():
            return
        for i, section in enumerate(self._sections):
            delay = min(i, 8) * mt.stagger_interval
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda sec=section: self._fade_in(sec))
            self._entrance_timers.append(timer)
            timer.start(delay)

    def _cancel_entrance(self) -> None:
        for t in self._entrance_timers:
            t.stop()
        self._entrance_timers = []
        for a in self._section_anims:
            a.stop()
        self._section_anims = []

    def _fade_in(self, section: QWidget) -> None:
        if not mt.is_motion_enabled() or section is None:
            return
        try:
            effect = QGraphicsOpacityEffect(section)
            effect.setOpacity(0.0)
            section.setGraphicsEffect(effect)
            anim = QVariantAnimation(section)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setDuration(mt.duration_base)
            anim.setEasingCurve(mt.curve_enter)
            anim.valueChanged.connect(effect.setOpacity)

            def _done(_effect=effect, _section=section, _anim=anim):
                try:
                    if _section.graphicsEffect() is _effect:
                        _section.setGraphicsEffect(None)
                except RuntimeError:
                    pass
                if _anim in self._section_anims:
                    self._section_anims.remove(_anim)

            anim.finished.connect(_done)
            self._section_anims.append(anim)
            anim.start()
        except RuntimeError:
            pass  # section torn down between timer fire and fade start

    # ---- misc ---------------------------------------------------------------
    def stop_animations(self) -> None:
        """Snap to end state and kill all card-local animations + effects.

        Called by the stage before it attaches its own close-transition
        effect: a section opacity effect left mid-fade would nest inside
        the host grab and trip Qt's one-painter rule.
        """
        self._cancel_entrance()
        widgets = [self] + self._sections + self.findChildren(QWidget)
        for w in widgets:
            try:
                if w.graphicsEffect() is not None:
                    w.setGraphicsEffect(None)
            except RuntimeError:
                pass
        for scalar in self.findChildren(PaintedScalar):
            scalar._kill_anim()
            scalar.snap_to_target()

    def request_save_png(self) -> None:
        self.savePngRequested.emit(self)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._entrance_armed:
            self.play_entrance()
