# gui/widgets/recap/cards/best_shots.py
"""
BestShotsCard — top-quality captures in a 2x2 / 3x3 grid that shrinks to
fit. Thumbs decode lazily per tile through core.thumbs.load_display_pixmap
(256 bucket) guarded by a generation counter; tiles without a decodable
photo degrade to a score/date chip instead of placeholders. Clicking a
tile emits shotClicked(date).
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from core.thumbs import load_display_pixmap
from gui.theme.theme_vars import theme_vars
from gui.widgets.pixmap_utils import active_dpr, scaled_cover_crop

from .base import RecapCardBase, _d


class ShotTile(QWidget):
    """One grid cell: lazy thumb or honest score/date fallback."""

    clicked = Signal(str)

    def __init__(self, date_text: str, score_text: str,
                 path: Optional[Path], parent=None):
        super().__init__(parent)
        self._date = date_text
        self._score = score_text
        self._path = path
        self._pixmap = None
        self._gen = 0
        self.setMinimumSize(96, 96)
        self.setCursor(Qt.PointingHandCursor)

    def load_lazy(self, gen: int) -> None:
        self._gen = gen
        if self._path is None:
            return
        QTimer.singleShot(10, lambda: self._load(gen))

    def _load(self, gen: int) -> None:
        try:
            if gen != self._gen or self._path is None or not self._path.is_file():
                return
            dpr = active_dpr(self)
            pix = load_display_pixmap(self._path, 256.0, dpr)
            if not pix.isNull():
                self._pixmap = scaled_cover_crop(
                    pix, max(64, self.width()), max(64, self.height()), dpr)
                self.update()
        except RuntimeError:
            pass  # tile torn down before the lazy tick fired
        except Exception:
            pass

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            event.accept()
            self.clicked.emit(self._date)
            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        v = theme_vars()
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self._pixmap is not None:
            p.drawPixmap(r, self._pixmap,
                         QRectF(0, 0, self._pixmap.width(), self._pixmap.height()))
            scrim = QRectF(r.left(), r.bottom() - 22, r.width(), 22)
            p.fillRect(scrim, theme_vars().rgba("scrim", 0.55))
            f = QFont(self.font())
            f.setPixelSize(10)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            p.setPen(QColor(v["inverse_on_surface"]))
            p.drawText(scrim, Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(f" {self._score}", Qt.ElideRight, scrim.width() - 6))
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(v["surface_container_highest"]))
            p.drawRoundedRect(r, 12, 12)
            f = QFont(self.font())
            f.setPixelSize(13)
            f.setWeight(QFont.Bold)
            p.setFont(f)
            p.setPen(QColor(v["primary"]))
            p.drawText(r.adjusted(0, -8, 0, 0), Qt.AlignCenter, self._score)
            f2 = QFont(self.font())
            f2.setPixelSize(10)
            p.setFont(f2)
            p.setPen(QColor(v["on_surface_variant"]))
            p.drawText(r.adjusted(0, 14, 0, 0), Qt.AlignHCenter | Qt.AlignTop,
                       p.fontMetrics().elidedText(self._date, Qt.ElideRight, r.width() - 8))
            pen = QPen(QColor(v["outline_variant"]))
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 12, 12)

    def apply_theme(self) -> None:
        self.update()


class BestShotsCard(RecapCardBase):
    CARD_KIND = "best_shots"

    shotClicked = Signal(str)

    def build_content(self):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        title = QLabel("Best shots")
        title.setObjectName("CardTitle")
        caption = QLabel("Ranked by sharpness + exposure.")
        caption.setObjectName("CardCaption")
        lay.addWidget(title)
        lay.addWidget(caption)
        self.add_section(box)

        rows = self._shot_rows()
        n = min(len(rows), 9)
        cols = 3 if n >= 5 else 2
        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setSpacing(8)
        self._tiles: List[ShotTile] = []
        self._gen = 0
        for i, row in enumerate(rows[:n]):
            path = row.get("path")
            tile = ShotTile(str(row.get("date") or row.get("id") or ""),
                            f"#{i + 1}",
                            Path(path) if isinstance(path, str) and path else None)
            tile.clicked.connect(self.shotClicked.emit)
            self._tiles.append(tile)
            grid.addWidget(tile, i // cols, i % cols)
        for i in range(n):
            grid.setColumnStretch(i % cols, 1)
            grid.setRowStretch(i // cols, 1)
        self.add_section(grid_w)
        self._lay.addStretch()
        self._schedule_tiles()

    def _shot_rows(self) -> list:
        rows = _d(self._data, "shot_rows", None)
        if isinstance(rows, (list, tuple)) and rows:
            out = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                date = str(r.get("date") or r.get("id") or "")
                out.append({"path": r.get("path"), "date": date,
                            "score": r.get("score")})
            return out[:9]
        shots = _d(self._data, "top_shots", [])
        out = []
        if isinstance(shots, (list, tuple)):
            for s in shots:
                if isinstance(s, dict):
                    out.append({"path": None,
                                "date": str(s.get("id") or ""),
                                "score": s.get("score")})
        return out[:9]

    def _schedule_tiles(self) -> None:
        self._gen += 1
        gen = self._gen
        for i, tile in enumerate(self._tiles):
            QTimer.singleShot(min(i, 8) * 20 + 30,
                              lambda t=tile, g=gen: t.load_lazy(g))

    def populate(self, recap_data) -> None:
        super().populate(recap_data)

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
        """)
        for tile in getattr(self, "_tiles", []):
            tile.apply_theme()
        self.update()
