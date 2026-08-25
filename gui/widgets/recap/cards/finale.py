# gui/widgets/recap/cards/finale.py
"""
FinaleCard — four count-up stat cells, Save-all (primary) + single-save
(secondary) actions, closing line.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from gui.theme.theme_vars import theme_vars
from gui.widgets.pixmap_utils import active_dpr, recolored_icon

from .base import RecapCardBase, PaintedScalar, _d, _int, qss_rgba

ICONS_DIR = Path(__file__).resolve().parents[3] / "assets" / "icons"


def _float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class FinaleCard(RecapCardBase):
    CARD_KIND = "finale"

    saveAllRequested = Signal()

    def build_content(self):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        title = QLabel("That's a wrap")
        title.setObjectName("CardTitle")
        caption = QLabel("The period, in four numbers.")
        caption.setObjectName("CardCaption")
        lay.addWidget(title)
        lay.addWidget(caption)
        self.add_section(box)

        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 6, 0, 6)
        grid.setSpacing(10)
        self._scalars = []
        for i, (label, value, fmt) in enumerate(self._cells()):
            cell = QWidget()
            cell.setObjectName("StatCell")
            cell_lay = QVBoxLayout(cell)
            cell_lay.setContentsMargins(14, 12, 14, 10)
            cell_lay.setSpacing(2)
            scalar = PaintedScalar(font_px=34, color_key="on_surface")
            scalar.set_format(fmt)
            scalar.setMinimumHeight(44)
            scalar.set_target(value)
            cell_lay.addWidget(scalar)
            name = QLabel(label)
            name.setObjectName("StatLabel")
            cell_lay.addWidget(name)
            self._scalars.append(scalar)
            grid.addWidget(cell, i // 2, i % 2)
        self.add_section(grid_w)

        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 4, 0, 0)
        row_lay.setSpacing(10)
        v = theme_vars()
        self._save_all_btn = QPushButton("Save all as PNG")
        self._save_all_btn.setObjectName("SaveAllButton")
        self._save_all_btn.setIcon(recolored_icon(
            ICONS_DIR / "download.svg", QColor(v["on_primary"]), active_dpr(self)))
        self._save_all_btn.setCursor(Qt.PointingHandCursor)
        self._save_all_btn.clicked.connect(self.saveAllRequested.emit)
        row_lay.addWidget(self._save_all_btn)
        self._save_one_btn = QPushButton("Save this card")
        self._save_one_btn.setObjectName("SaveOneButton")
        self._save_one_btn.setCursor(Qt.PointingHandCursor)
        self._save_one_btn.clicked.connect(self.request_save_png)
        row_lay.addWidget(self._save_one_btn)
        row_lay.addStretch()
        self.add_section(row)

        closing = QLabel(self._closing_line())
        closing.setObjectName("ClosingLine")
        closing.setAlignment(Qt.AlignCenter)
        self.add_section(closing)

    def _cells(self):
        streaks = _d(self._data, "streaks", {})
        consistency = _float(_d(self._data, "consistency_pct"), 0.0)
        return [
            ("captures", max(0, _int(_d(self._data, "captures_total"))), "{:.0f}"),
            ("active days", max(0, _int(_d(self._data, "active_days"))), "{:.0f}"),
            ("consistent", max(0.0, consistency), "{:.1f}%"),
            ("best streak", max(0, _int(_d(streaks, "best"))), "{:.0f}"),
        ]

    def _closing_line(self) -> str:
        dom = str(_d(self._data, "dominant_mood", ""))
        if dom:
            return f"Mostly {dom.lower()} days — see you in the next one."
        return "Every day you show up becomes part of the picture."

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
            QWidget#StatCell {{
                background-color: {qss_rgba(v['on_surface'], 0.06)};
                border-radius: 14px;
            }}
            QLabel#StatLabel {{
                color: {v['on_surface_variant']};
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton#SaveAllButton {{
                background-color: {accent_fill};
                color: {accent_on};
                border: none;
                border-radius: 18px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton#SaveAllButton:hover {{
                background-color: {qss_rgba(accent_fill, 0.85)};
            }}
            QPushButton#SaveOneButton {{
                background-color: transparent;
                color: {v['on_surface_variant']};
                border: 1px solid {v['outline_variant']};
                border-radius: 18px;
                padding: 7px 16px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton#SaveOneButton:hover {{
                background-color: {qss_rgba(v['on_surface'], 0.08)};
            }}
            QLabel#ClosingLine {{
                color: {v['on_surface_variant']};
                background: transparent;
                font-size: 12px;
                font-style: italic;
            }}
        """)
        self.update()
