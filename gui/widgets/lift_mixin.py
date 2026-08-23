# gui/widgets/lift_mixin.py
"""
LiftMixin — C1 standardized card hover-lift (docs/design/motion-system.md).

enter: pos.y −2px 150ms OutCubic · leave: back 150ms InCubic · press: snap to
baseline instantly. Position animation ONLY (no shadows, no layout
invalidation). Gated on behavior.motion_enabled — when off, end states are
applied instantly while the hover surface tint is kept (state feedback is not
motion). Animation refs are held as members (GC guard) and retargeted via
stop-before-start.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPropertyAnimation, Qt
from PySide6.QtGui import QCursor

from gui.theme import motion_tokens as mt
from gui.theme.theme_vars import theme_vars


class LiftMixin:
    """Mixin for stylesheet cards; call init_lift() after the layout is set.

    Standard cards: enter lifts pos.y −2px and swaps bg
    surface_container_low→surface_container (C1). Image cards (opt in via
    ``LIFT_IMAGE_CARD = True``): no movement; hover swaps a stylesheet border
    outline_variant→outline, falling back to the bg swap when the stored
    stylesheet carries no border.
    """

    LIFT_DISTANCE = 2
    LIFT_IMAGE_CARD = False

    def init_lift(self):
        self._lift_base_y = self.y()
        self._lift_anim = QPropertyAnimation(self, b"pos", self)
        self._lift_hovered = False
        self._lift_pressed = False
        self._lift_lifted = False
        self._lift_style_sheet = None

    # ----- geometry -----------------------------------------------------
    def _lift_target_y(self, lifted: bool) -> int:
        return self._lift_base_y - (self.LIFT_DISTANCE if lifted else 0)

    def _lift_go(self, lifted: bool):
        if self.LIFT_IMAGE_CARD:
            return  # image-card variant keeps layout stable (border swap only)
        self._lift_lifted = lifted
        target = self._lift_target_y(lifted)
        anim = self._lift_anim
        if not mt.is_motion_enabled():
            anim.stop()
            self.move(self.x(), target)
            return
        anim.stop()
        anim.setDuration(mt.duration_fast)
        anim.setEasingCurve(mt.curve_enter if lifted else mt.curve_exit)
        anim.setStartValue(self.pos())
        anim.setEndValue(QPoint(self.x(), target))
        anim.start()

    def _lift_snap(self):
        self._lift_anim.stop()
        self._lift_lifted = False
        self.move(self.x(), self._lift_base_y)

    # ----- hover tint (kept even when motion is off) ---------------------
    def _lift_apply_tint(self, hovered: bool):
        if hovered:
            if self._lift_style_sheet is None:
                self._lift_style_sheet = self.styleSheet()
            base = self._lift_style_sheet
            # Stylesheets store RESOLVED hex, not token names — resolve via
            # theme_vars and string-replace the resolved values.
            v = theme_vars()
            if self.LIFT_IMAGE_CARD:
                border_low = v["outline_variant"]
                if border_low in base:
                    self.setStyleSheet(base.replace(border_low, v["outline"]))
                    return
            self.setStyleSheet(base.replace(
                v["surface_container_low"], v["surface_container"]))
        elif self._lift_style_sheet is not None:
            self.setStyleSheet(self._lift_style_sheet)

    def _lift_cursor_inside(self) -> bool:
        return self.rect().contains(self.mapFromGlobal(QCursor.pos()))

    # ----- events ---------------------------------------------------------
    def enterEvent(self, event):
        self._lift_hovered = True
        if not self._lift_lifted:
            self._lift_base_y = self.y()
        self._lift_apply_tint(True)
        if not self._lift_pressed:
            self._lift_go(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._lift_hovered = False
        if self._lift_cursor_inside():
            return  # moved onto a child widget; card is still hovered
        self._lift_apply_tint(False)
        if self._lift_pressed:
            self._lift_snap()
        else:
            self._lift_go(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._lift_pressed = True
            self._lift_snap()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._lift_pressed = False
            if self._lift_hovered:
                self._lift_go(True)
        super().mouseReleaseEvent(event)
