# gui/widgets/recap/cards/cover.py
"""
CoverCard — recap title card: dimmed 3x3 photo mosaic backdrop, eyebrow
pill, count-up headline, eligible-period chips, Play + Save PNG actions.
"""
from __future__ import annotations

import calendar as _cal
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from core.thumbs import load_display_pixmap
from gui.theme.theme_vars import theme_vars
from gui.widgets.pixmap_utils import active_dpr, recolored_icon, scaled_cover_crop

from .base import RecapCardBase, PaintedScalar, _d, _int, qss_rgba

ICONS_DIR = Path(__file__).resolve().parents[3] / "assets" / "icons"

_MONTHS = [_cal.month_name[m] for m in range(1, 13)]


class CoverCard(RecapCardBase):
    CARD_KIND = "cover"

    playToggled = Signal(bool)

    def __init__(self, parent=None, accent_index=0):
        self._mosaic: List[Optional[QPixmap]] = [None] * 9
        self._mosaic_gen = 0
        super().__init__(parent, accent_index)

    # ---- content -----------------------------------------------------------
    def build_content(self):
        v = theme_vars()
        accent_fill, accent_on = self.accent()

        top = QWidget()
        top_l = QHBoxLayout(top)
        top_l.setContentsMargins(0, 0, 0, 0)
        self._eyebrow = QLabel(self._eyebrow_text())
        self._eyebrow.setObjectName("EyebrowPill")
        self._eyebrow.setAlignment(Qt.AlignCenter)
        top_l.addWidget(self._eyebrow)
        top_l.addStretch()
        self.add_section(top)

        head = QWidget()
        head_l = QVBoxLayout(head)
        head_l.setContentsMargins(0, 8, 0, 0)
        head_l.setSpacing(2)
        total = _int(_d(self._data, "captures_total"))
        self._scalar = PaintedScalar(font_px=72,
                                     color_key=self._accent_on_key())
        head_l.addWidget(self._scalar)
        self._sub = QLabel("selfies captured")
        self._sub.setObjectName("HeadSub")
        head_l.addWidget(self._sub)
        head_l.addStretch()
        self.add_section(head)
        self._scalar.set_target(total)

        chips_w = QWidget()
        self._chips_lay = QHBoxLayout(chips_w)
        self._chips_lay.setContentsMargins(0, 0, 0, 0)
        self._chips_lay.setSpacing(8)
        self._chips: List[QLabel] = []
        for label in self._eligible_periods()[:5]:
            chip = QLabel(label)
            chip.setObjectName("ScopeChip")
            self._chips_lay.addWidget(chip)
            self._chips.append(chip)
        extra = len(self._eligible_periods()) - 5
        if extra > 0:
            more = QLabel(f"+{extra} more")
            more.setObjectName("ScopeChipMore")
            self._chips_lay.addWidget(more)
            self._chips.append(more)
        self._chips_lay.addStretch()
        self._has_chips = bool(self._chips)
        self.add_section(chips_w)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._lay.addWidget(spacer)
        row = QWidget()
        row_l = QHBoxLayout(row)
        row_l.setContentsMargins(0, 0, 0, 0)
        row_l.setSpacing(10)
        self._play_btn = QPushButton("Pause")
        self._play_btn.setObjectName("PlayButton")
        self._play_btn.setIcon(recolored_icon(
            ICONS_DIR / "pause.svg", QColor(accent_on), active_dpr(self)))
        self._play_btn.setCursor(Qt.PointingHandCursor)
        self._play_btn.setCheckable(True)
        self._play_btn.setChecked(False)
        self._play_btn.clicked.connect(self._on_play_clicked)
        row_l.addWidget(self._play_btn)
        save_fill, save_on = theme_vars()["primary"], theme_vars()["on_primary"]
        self._save_btn = QPushButton("Save PNG")
        self._save_btn.setObjectName("SavePngButton")
        self._save_btn.setIcon(recolored_icon(
            ICONS_DIR / "download.svg", QColor(save_on), active_dpr(self)))
        self._save_btn.setCursor(Qt.PointingHandCursor)
        self._save_btn.clicked.connect(self.request_save_png)
        row_l.addWidget(self._save_btn)
        row_l.addStretch()
        self.add_section(row)

        self._schedule_mosaic()

    def _accent_on_key(self):
        from .base import ACCENT_PAIRS
        return ACCENT_PAIRS[self.accent_index][1]

    def _eyebrow_text(self) -> str:
        year = _int(_d(self._data, "year"))
        month = _d(self._data, "month")
        scope = str(_d(self._data, "scope", "month"))
        if scope == "year" or month is None:
            return f"{year} · YEARLY RECAP"
        m = _MONTHS[_int(month, 1) - 1] if 1 <= _int(month, 1) <= 12 else ""
        return f"{m.upper()} {year} · MONTHLY RECAP"

    def _eligible_periods(self) -> List[str]:
        given = _d(self._data, "eligible_periods")
        labels: List[str] = []
        if isinstance(given, (list, tuple)):
            labels = [str(x) for x in given]
        else:
            monthly = _d(self._data, "monthly")
            if isinstance(monthly, dict):
                for m in range(1, 13):
                    entry = monthly.get(m) or monthly.get(str(m))
                    days = _int(entry.get("days") if isinstance(entry, dict) else entry)
                    if days > 0:
                        labels.append(_MONTHS[m - 1])
        return labels

    # ---- play/pause ----------------------------------------------------------
    def set_paused(self, paused: bool) -> None:
        self._play_btn.blockSignals(True)
        self._play_btn.setChecked(paused)
        self._play_btn.blockSignals(False)
        self._sync_play_visual()

    def _on_play_clicked(self) -> None:
        self.playToggled.emit(bool(self._play_btn.isChecked()))

    def _sync_play_visual(self) -> None:
        paused = self._play_btn.isChecked()
        on_color = QColor(theme_vars()[self._accent_on_key()])
        icon = ICONS_DIR / ("play.svg" if paused else "pause.svg")
        self._play_btn.setIcon(recolored_icon(icon, on_color, active_dpr(self)))
        self._play_btn.setText("Resume" if paused else "Pause")

    # ---- mosaic backdrop -------------------------------------------------------
    def _mosaic_paths(self) -> list:
        paths = _d(self._data, "mosaic_paths", [])
        return [Path(p) for p in paths][:9] if isinstance(paths, (list, tuple)) else []

    def _schedule_mosaic(self) -> None:
        self._mosaic_gen += 1
        gen = self._mosaic_gen
        paths = self._mosaic_paths()
        for i in range(min(len(paths), 9)):
            QTimer.singleShot(20 * i, lambda idx=i, g=gen, p=paths[idx]: self._load_tile(idx, p, g))
        self.update()

    def _load_tile(self, index: int, path: Path, gen: int) -> None:
        try:
            if gen != self._mosaic_gen or not path.is_file():
                return
            dpr = active_dpr(self)
            pix = load_display_pixmap(path, 256.0, dpr)
            if pix.isNull():
                return
            self._mosaic[index] = scaled_cover_crop(pix, 200, 200, dpr)
            self.update()
        except RuntimeError:
            pass  # card torn down before the staggered tick fired
        except Exception:
            pass

    # ---- painting -----------------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        filled = [m for m in self._mosaic if m is not None]
        radius = 22.0
        if filled:
            # Clip mosaic + dim scrim to the card's rounded silhouette so
            # square photo corners never poke past the border radius.
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme_vars()["surface_container_high"]))
            p.drawPath(clip)
            p.save()
            p.setClipPath(clip)
            cols, rows = 3, 3
            cw, ch = w / cols, h / rows
            for r in range(rows):
                for c in range(cols):
                    pix = self._mosaic[r * cols + c]
                    if pix is not None:
                        p.drawPixmap(QRectF(c * cw, r * ch, cw, ch), pix,
                                     QRectF(0, 0, pix.width(), pix.height()))
            p.fillRect(self.rect(), theme_vars().rgba("scrim", 0.55))
            p.restore()
        else:
            p.fillRect(self.rect(), QColor(theme_vars()["surface_container_high"]))
        p.setPen(theme_vars().rgba("outline_variant", 0.9))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), radius, radius)
        p.end()

    # ---- theme --------------------------------------------------------------------
    def apply_theme(self) -> None:
        v = theme_vars()
        accent_fill, accent_on = self.accent()
        self.setStyleSheet(f"""
            QLabel#EyebrowPill {{
                background-color: {accent_fill};
                color: {accent_on};
                border-radius: 12px;
                padding: 4px 14px;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QLabel#HeadSub {{
                color: {qss_rgba(v['on_surface'], 0.92)};
                background: transparent;
                font-size: 17px;
                font-weight: 600;
            }}
            QLabel#ScopeChip {{
                background-color: {qss_rgba(v['on_surface'], 0.10)};
                color: {v['on_surface']};
                border-radius: 11px;
                padding: 3px 12px;
                font-size: 11px;
                font-weight: 600;
            }}
            QLabel#ScopeChipMore {{
                color: {v['on_surface_variant']};
                background: transparent;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton#PlayButton {{
                background-color: {accent_fill};
                color: {accent_on};
                border: none;
                border-radius: 18px;
                padding: 7px 16px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton#PlayButton:hover {{
                background-color: {qss_rgba(accent_fill, 0.85)};
            }}
            QPushButton#SavePngButton {{
                background-color: {v['primary']};
                color: {v['on_primary']};
                border: none;
                border-radius: 18px;
                padding: 7px 16px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton#SavePngButton:hover {{
                background-color: {qss_rgba(v['primary'], 0.85)};
            }}
        """)
        self._sync_play_visual()
        self.update()
