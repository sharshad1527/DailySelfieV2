# gui/widgets/recap/cards/mood_palette.py
"""
MoodPaletteCard — stacked horizontal mood bar (fixed MOOD_COLORS hexes,
1px outline halo), dominant-mood GIF, comparison line from mood_trend.
Dropped entirely by the stage when the period has zero moods.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen, QMovie
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from gui.theme.theme_vars import theme_vars
from gui.dashboard.widgets.calendar_analytics.viz_types import MOOD_COLORS

from .base import RecapCardBase, _d, _int

MOOD_DIR = Path(__file__).resolve().parents[3] / "assets" / "icons" / "mood"
MOOD_ORDER = ("Great", "Good", "Neutral", "Bad", "Awful")

BAR_H = 18.0
BAR_RADIUS = 9.0
LABEL_GAP = 6.0
LABEL_H = 16.0
SINGLE_FILL_ALPHA = 0.8


def _gif_name(mood: str):
    """Mood->GIF filename from the dashboard map (guarded: optional dep)."""
    try:
        from gui.dashboard.pages.dashboard import MOOD_GIF_MAP
        return MOOD_GIF_MAP.get(mood)
    except Exception:
        return None


class _MoodBar(QWidget):
    """Stacked mood bar + metric-aware labels, as a real layout child so the
    band it paints is reserved (legend rows can never land on the bar)."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._entries: List[tuple] = []
        self.setFixedHeight(int(BAR_H + LABEL_GAP + LABEL_H))

    def set_entries(self, entries: List[tuple]) -> None:
        self._entries = [(m, int(c)) for m, c in entries if int(c) > 0]
        self.update()

    # ---- geometry (pure; shared by painting and probes) ---------------------
    def segment_rects(self) -> List[tuple]:
        """[(mood, QRectF)] in local coords for the currently set entries."""
        total = sum(c for _m, c in self._entries)
        w = self.width()
        if not self._entries or total <= 0 or w <= 0:
            return []
        rects: List[tuple] = []
        x = 0.0
        remaining_w = float(w)
        last = len(self._entries) - 1
        for i, (mood, count) in enumerate(self._entries):
            seg_w = remaining_w if i == last else w * (count / total)
            rects.append((mood, QRectF(x, 0.0, seg_w, BAR_H)))
            x += seg_w
            remaining_w -= seg_w
        return rects

    def label_texts(self) -> List[str]:
        if len(self._entries) == 1:
            mood, _count = self._entries[0]
            return [f"100% {mood}"]
        return [mood for mood, _c in self._entries]

    def label_placements(self) -> List[tuple]:
        """Metrics-aware label layout: [(text, QRectF)] in local coords.

        Labels flow left-to-right sized by their real text advance; anything
        that would overflow the right edge is elided into the remaining
        space or dropped entirely (never clipped mid-glyph, never drawn past
        the bar edge).
        """
        rects = self.segment_rects()
        if not rects:
            return []
        f = QFont(self.font())
        f.setPixelSize(11)
        fm = QFontMetrics(f)
        right = self.width()
        y = BAR_H + LABEL_GAP
        out: List[tuple] = []
        x = 0.0
        ell_w = fm.horizontalAdvance("…")
        for (mood, _seg) in rects:
            text = f"100% {mood}" if len(rects) == 1 else mood
            adv = fm.horizontalAdvance(text)
            if x + adv <= right:
                out.append((text, QRectF(x, y, adv + 2, LABEL_H)))
                x += adv + 14.0
                continue
            if len(rects) > 1 and right - x > ell_w:
                elided = fm.elidedText(mood, Qt.ElideRight, right - x)
                out.append((elided, QRectF(x, y, right - x, LABEL_H)))
            break
        return out

    # ---- painting ------------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        v = theme_vars()
        track = QRectF(0.0, 0.0, self.width(), BAR_H)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(v["surface_container_highest"]))
        p.drawRoundedRect(track, BAR_RADIUS, BAR_RADIUS)

        rects = self.segment_rects()
        single = len(rects) == 1
        if rects:
            clip = QPainterPath()
            clip.addRoundedRect(track, BAR_RADIUS, BAR_RADIUS)
            p.save()
            p.setClipPath(clip)
            for mood, seg in rects:
                color = QColor(MOOD_COLORS[mood])
                p.setBrush(color)
                if single:
                    color.setAlphaF(SINGLE_FILL_ALPHA)
                    p.drawRoundedRect(seg, BAR_RADIUS, BAR_RADIUS)
                else:
                    p.drawRect(seg)
            p.restore()

            pen = QPen(theme_vars().rgba("outline_variant", 0.95))
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5),
                              BAR_RADIUS, BAR_RADIUS)

            f = QFont(self.font())
            f.setPixelSize(11)
            p.setFont(f)
            p.setPen(QColor(v["on_surface_variant"]))
            for text, lrect in self.label_placements():
                p.drawText(lrect, Qt.AlignLeft | Qt.AlignVCenter, text)
        p.end()


class MoodPaletteCard(RecapCardBase):
    CARD_KIND = "mood"

    def build_content(self):
        self.add_section(self._make_title())

        top = QWidget()
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(0, 4, 0, 4)
        top_lay.setSpacing(14)

        gif_holder = QWidget()
        gif_holder.setFixedSize(84, 84)
        gif_holder.setObjectName("GifHolder")
        gif_lay = QVBoxLayout(gif_holder)
        gif_lay.setContentsMargins(8, 8, 8, 8)
        self._gif_lbl = QLabel()
        self._gif_lbl.setAlignment(Qt.AlignCenter)
        self._movie: Optional[QMovie] = self._load_movie()
        if self._movie is not None:
            self._gif_lbl.setMovie(self._movie)
            self._movie.start()
        else:
            dominant = str(_d(self._data, "dominant_mood", ""))
            self._gif_lbl.setText(dominant[:2].upper() or "-")
        gif_lay.addWidget(self._gif_lbl)
        top_lay.addWidget(gif_holder)

        text_box = QWidget()
        text_lay = QVBoxLayout(text_box)
        text_lay.setContentsMargins(0, 0, 0, 0)
        text_lay.setSpacing(2)
        self._dominant_lbl = QLabel(self._dominant_line())
        self._dominant_lbl.setObjectName("DominantLabel")
        self._dominant_lbl.setWordWrap(True)
        text_lay.addWidget(self._dominant_lbl)
        self._compare_lbl = QLabel(self._comparison_line())
        self._compare_lbl.setObjectName("CompareLabel")
        text_lay.addWidget(self._compare_lbl)
        text_lay.addStretch()
        top_lay.addWidget(text_box, 1)
        self.add_section(top)

        legend = QWidget()
        legend_lay = QVBoxLayout(legend)
        legend_lay.setContentsMargins(0, 0, 0, 0)
        legend_lay.setSpacing(4)
        total = sum(self._counts().values()) or 1
        self._legend_rows: List[QWidget] = []
        for mood in MOOD_ORDER:
            count = self._counts().get(mood, 0)
            if count <= 0:
                continue
            row = QWidget()
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(2, 0, 2, 0)
            row_lay.setSpacing(8)
            dot = QLabel()
            dot.setFixedSize(10, 10)
            dot.setObjectName(f"Dot_{mood}")
            row_lay.addWidget(dot)
            name = QLabel(mood)
            name.setObjectName("LegendName")
            row_lay.addWidget(name)
            row_lay.addStretch()
            pct = QLabel(f"{count / total * 100:.0f}%")
            pct.setObjectName("LegendPct")
            row_lay.addWidget(pct)
            legend_lay.addWidget(row)
            self._legend_rows.append(row)

        self._bar = _MoodBar()
        self._bar.set_entries(
            [(m, self._counts()[m]) for m in MOOD_ORDER if m in self._counts()])
        self.add_section(self._bar)
        self.add_section(legend)
        self._lay.addStretch()

    # ---- helpers -----------------------------------------------------------
    def _counts(self) -> Dict[str, int]:
        raw = _d(self._data, "distribution", {})
        out: Dict[str, int] = {}
        if isinstance(raw, dict):
            for mood in MOOD_ORDER:
                n = _int(raw.get(mood))
                if n > 0:
                    out[mood] = n
        return out

    def _load_movie(self) -> Optional[QMovie]:
        try:
            dominant = str(_d(self._data, "dominant_mood", ""))
            gif_name = _gif_name(dominant)
            if not gif_name:
                return None
            path = MOOD_DIR / gif_name
            if not path.is_file():
                return None
            movie = QMovie(str(path), parent=self)
            movie.setCacheMode(QMovie.CacheAll)
            return movie
        except Exception:
            return None

    def _dominant_line(self) -> str:
        dom = str(_d(self._data, "dominant_mood", ""))
        return f"Dominant mood: {dom}" if dom else "Moods logged"

    def _comparison_line(self) -> str:
        for h in _d(self._data, "highlights", []) or []:
            if isinstance(h, dict) and h.get("kind") == "mood_trend":
                sub = str(h.get("subtitle") or "").strip()
                arrow = "▲" if sub.startswith("Up") else ("▼" if sub.startswith("Down") else "•")
                return f"{arrow} {sub}" if sub else ""
        return ""

    def _make_title(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        title = QLabel("Mood palette")
        title.setObjectName("CardTitle")
        caption = QLabel("How the period felt, one entry at a time.")
        caption.setObjectName("CardCaption")
        lay.addWidget(title)
        lay.addWidget(caption)
        return box

    # ---- painting ------------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        v = theme_vars()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(v["surface_container_high"]))
        p.drawRoundedRect(self.rect(), 22, 22)
        p.end()

    # ---- theme -----------------------------------------------------------------
    def apply_theme(self) -> None:
        v = theme_vars()
        accent_fill, accent_on = self.accent()
        qss = f"""
            QLabel#CardTitle {{
                color: {v['on_surface']};
                font-size: 15px;
                font-weight: 700;
            }}
            QLabel#CardCaption {{
                color: {v['on_surface_variant']};
                font-size: 12px;
            }}
            QWidget#GifHolder {{
                background-color: {accent_fill};
                border-radius: 16px;
            }}
            QLabel#DominantLabel {{
                color: {v['on_surface']};
                font-size: 17px;
                font-weight: 700;
            }}
            QLabel#CompareLabel {{
                color: {v['tertiary']};
                font-size: 12px;
                font-weight: 600;
            }}
            QLabel#LegendName {{
                color: {v['on_surface']};
                font-size: 12px;
            }}
            QLabel#LegendPct {{
                color: {v['on_surface_variant']};
                font-size: 12px;
                font-weight: 600;
            }}
        """
        for mood in MOOD_COLORS:
            qss += (f"\nQLabel#Dot_{mood} {{ background-color: {MOOD_COLORS[mood]};"
                    f" border-radius: 5px; }}\n")
        self.setStyleSheet(qss)
        self.update()
