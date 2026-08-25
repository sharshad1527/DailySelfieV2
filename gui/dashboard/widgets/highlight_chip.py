# gui/dashboard/widgets/highlight_chip.py
"""
HighlightChip + RecapEntryCard — dashboard surfaces for highlights & recaps.

HighlightChip: 32px pill (LiftMixin) with a kind-colored 16px icon, 12px w500
label, action hint and a 24px hit-area ✕ that hovers error. Emphasis variant
paints tertiary_container for the top-priority recap_ready chip.
Signals: activated(kind) / dismissed(dismiss_id).

RecapEntryCard: h64 side-column pill launching the recap stage; shows the
newest eligible period ("Rewatch August ▸") plus a year line when both scopes
are eligible (click cycles scope). Unseen periods get a tertiary badge dot.
Height-gated via maybe_visible(h): auto-hides when the side column cannot fit
+76px, or entirely when no eligible period exists.

Chip entrance fades are gated on behavior.motion_enabled via motion tokens.
"""
from __future__ import annotations

import calendar as pycal
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import (
    QPropertyAnimation, QRectF, QSize, Qt, Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout,
)

from core.recap import recap_period_id
from gui.theme import motion_tokens as mt
from gui.theme.theme_vars import theme_vars
from gui.widgets.lift_mixin import LiftMixin
from gui.widgets.pixmap_utils import active_dpr, recolored_icon

ICONS_DIR = Path(__file__).resolve().parents[3] / "gui" / "assets" / "icons"


def _alpha_hex(hex_color: str, alpha_hex: str) -> str:
    return f"#{alpha_hex}{hex_color.lstrip('#').upper()}"


class HighlightChip(LiftMixin, QFrame):
    """One dismissible highlight pill; clicking emits activated(kind)."""

    activated = Signal(str)
    dismissed = Signal(str)

    HEIGHT = 32

    def __init__(self, kind: str, label: str, reason: str = "",
                 dismiss_id: str = "", icon_name: str = "sparkles.svg",
                 color_key: str = "tertiary", emphasis: bool = False,
                 hint: str = "View", parent=None):
        super().__init__()
        self._vars = theme_vars()
        self.kind = str(kind)
        self.dismiss_id = str(dismiss_id)
        self._emphasis = bool(emphasis)
        self._entered = False

        self.setObjectName("HighlightChip")
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(reason)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 4, 0)
        row.setSpacing(6)

        v = self._vars
        icon_color = v["on_tertiary_container"] if emphasis else v[color_key]
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(16, 16)
        icon_lbl.setPixmap(recolored_icon(
            ICONS_DIR / icon_name, QColor(icon_color), active_dpr(self)).pixmap(16, 16))
        row.addWidget(icon_lbl)

        text_color = v["on_tertiary_container"] if emphasis else v["on_surface"]
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {text_color}; font-size: 12px; font-weight: 500;")
        row.addWidget(lbl)

        if not emphasis:
            hint_lbl = QLabel(hint)
            hint_lbl.setStyleSheet(
                f"color: {v['on_surface_variant']}; font-size: 11px;")
            row.addWidget(hint_lbl)

        close_btn = QPushButton(self)
        close_btn.setObjectName("ChipDismiss")
        close_btn.setFixedSize(24, 24)
        close_btn.setIconSize(QSize(12, 12))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setToolTip("Dismiss")
        close_btn.setFocusPolicy(Qt.NoFocus)
        close_btn.setIcon(recolored_icon(
            ICONS_DIR / "close.svg", QColor(v["on_surface_variant"]),
            active_dpr(self)))
        close_btn.setStyleSheet(f"""
            QPushButton#ChipDismiss {{
                background-color: transparent;
                border: none;
                border-radius: 12px;
            }}
            QPushButton#ChipDismiss:hover {{
                background-color: {v['error_container']};
            }}
        """)
        close_btn.clicked.connect(self._on_dismiss_clicked)
        row.addWidget(close_btn)

        bg = v["tertiary_container"] if emphasis else v["surface_container_low"]
        border = ("none" if emphasis else
                  f"1px solid {v['outline_variant']}")
        self.setStyleSheet(f"""
            QFrame#HighlightChip {{
                background-color: {bg};
                border: {border};
                border-radius: 16px;
            }}
        """)
        self.init_lift()

    def _on_dismiss_clicked(self):
        self.dismissed.emit(self.dismiss_id)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self.activated.emit(self.kind)
        super().mouseReleaseEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self._entered:
            return
        self._entered = True
        if not mt.is_motion_enabled():
            return
        try:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.0)
            self.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", self)
            anim.setDuration(mt.duration_base)
            anim.setEasingCurve(mt.curve_enter)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)

            def _detach():
                try:
                    self.setGraphicsEffect(None)
                except RuntimeError:
                    pass

            anim.finished.connect(_detach)
            anim.start()
            self._fade_anim = anim
        except RuntimeError:
            pass


class RecapEntryCard(LiftMixin, QFrame):
    """Side-column 'Rewatch <period>' launcher; cycles month/year scopes."""

    recapLaunchRequested = Signal(tuple)

    FIXED_H = 64
    MIN_FREE_H = 76

    def __init__(self, parent=None):
        super().__init__()
        self._vars = theme_vars()
        self._scopes: List[Tuple] = []
        self._scope_idx = 0
        self._unseen_ids: set = set()
        self._entered = False

        self.setObjectName("RecapEntryCard")
        self.setFixedHeight(self.FIXED_H)
        self.setCursor(Qt.PointingHandCursor)
        self.hide()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        col = QVBoxLayout(self)
        col.setContentsMargins(14, 8, 14, 8)
        col.setSpacing(2)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)

        v = self._vars
        self._icon_lbl = QLabel()
        self._icon_lbl.setFixedSize(20, 20)
        body.addWidget(self._icon_lbl, 0, Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        self._primary_lbl = QLabel("")
        text_col.addWidget(self._primary_lbl)
        self._secondary_lbl = QLabel("")
        self._secondary_lbl.hide()
        text_col.addWidget(self._secondary_lbl)
        text_col.addStretch()
        body.addLayout(text_col)
        body.addStretch()
        col.addLayout(body)
        col.addStretch()

        self.init_lift()
        self.apply_theme()

    # ---- data ---------------------------------------------------------
    def set_eligible(self, periods: Sequence[Tuple],
                     seen_ids: Optional[set] = None) -> None:
        """Bind the newest eligible period (+ its year scope when eligible)."""
        self._unseen_ids = set(seen_ids or ())
        self._scopes = []
        self._scope_idx = 0
        latest = next(iter(periods), None)
        if latest is not None and latest[0] == "month":
            _, y, m = latest
            self._scopes.append(("month", int(y), int(m)))
            if any(p[0] == "year" and p[1] == int(y) for p in periods):
                self._scopes.append(("year", int(y), None))
        elif latest is not None and latest[0] == "year":
            self._scopes.append(("year", int(latest[1]), None))
        self._refresh_labels()
        if not self._scopes:
            self.hide()

    def _current_scope(self) -> Optional[Tuple]:
        return self._scopes[self._scope_idx] if self._scopes else None

    def _refresh_labels(self) -> None:
        scope = self._current_scope()
        if scope is None:
            self._primary_lbl.setText("")
            self._secondary_lbl.setText("")
            return
        kind, y, m = scope
        primary = (f"Rewatch {pycal.month_name[int(m)]} ▸"
                   if kind == "month" else f"Rewatch {int(y)} ▸")
        secondary = ""
        other = self._scopes[(self._scope_idx + 1) % len(self._scopes)]
        okind, oy, om = other
        secondary = (f"Rewatch {pycal.month_name[int(om)]} ▸"
                     if okind == "month" else f"Rewatch {int(oy)} ▸")

        v = self._vars
        unseen = recap_period_id(scope) not in self._unseen_ids
        self._icon_lbl.setPixmap(recolored_icon(
            ICONS_DIR / "sparkles.svg",
            self._vars.qcolor("tertiary" if unseen else "on_surface_variant"),
            active_dpr(self)).pixmap(20, 20))
        self._primary_lbl.setText(primary)
        self._secondary_lbl.setVisible(bool(self._scopes) and len(self._scopes) > 1)
        self._secondary_lbl.setText(secondary)
        self.setToolTip("Open your recap" if len(self._scopes) < 2
                        else "Open your recap (click again to switch period)")

    def maybe_visible(self, available_h: float) -> None:
        """Height gate: show only when the column can fit +76px."""
        if not self._scopes or available_h < self.MIN_FREE_H:
            self.hide()
        else:
            self.show()

    def apply_theme(self) -> None:
        v = self._vars
        self.setStyleSheet(f"""
            QFrame#RecapEntryCard {{
                background-color: {v['surface_container_low']};
                border-radius: 16px;
            }}
        """)
        self._primary_lbl.setStyleSheet(f"""
            color: {v['on_surface']}; font-size: 13px; font-weight: 600;
        """)
        self._secondary_lbl.setStyleSheet(f"""
            color: {v['on_surface_variant']}; font-size: 11px; font-weight: 500;
        """)
        self._refresh_labels()

    # ---- painting / events ---------------------------------------------
    def paintEvent(self, event):
        super().paintEvent(event)
        scope = self._current_scope()
        if scope is None or recap_period_id(scope) in self._unseen_ids:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(theme_vars().qcolor("tertiary"))
        p.drawEllipse(QRectF(self.width() - 18, 8, 8, 8))
        p.end()

    def mouseReleaseEvent(self, event):
        scope = self._current_scope()
        if (event.button() == Qt.LeftButton and scope is not None
                and self.rect().contains(event.position().toPoint())):
            self.recapLaunchRequested.emit(tuple(scope))
            if len(self._scopes) > 1:
                self._scope_idx = (self._scope_idx + 1) % len(self._scopes)
                self._refresh_labels()
        super().mouseReleaseEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self._entered:
            return
        self._entered = True
        if not mt.is_motion_enabled():
            return
        try:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.0)
            self.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", self)
            anim.setDuration(mt.duration_base)
            anim.setEasingCurve(mt.curve_enter)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)

            def _detach():
                try:
                    self.setGraphicsEffect(None)
                except RuntimeError:
                    pass

            anim.finished.connect(_detach)
            anim.start()
            self._fade_anim = anim
        except RuntimeError:
            pass
