# gui/widgets/pixmap_utils.py
"""
DevicePixelRatio-aware pixmap helpers (HiDPI sharpness pass).

All photo/icon scaling sites funnel through these so results carry a correct
devicePixelRatio: logical sizes stay identical at dpr=1 while HiDPI screens
get native-resolution pixels.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor, QGuiApplication, QIcon, QPainter, QPainterPath, QPixmap,
)


def active_dpr(widget=None) -> float:
    """Best-effort device pixel ratio (widget's screen, else primary screen)."""
    try:
        if widget is not None:
            dpr = float(widget.devicePixelRatioF())
            if dpr > 0.0:
                return dpr
    except RuntimeError:
        pass
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        dpr = float(screen.devicePixelRatio())
        if dpr > 0.0:
            return dpr
    return 1.0


def scaled_cover_crop(pixmap: QPixmap, logical_w: int, logical_h: int,
                      dpr: float) -> QPixmap:
    """Cover-fit scale + center crop computed in device pixels.

    The returned pixmap is tagged with `dpr`, so it displays at exactly
    logical_w × logical_h on any screen while holding dpr× real pixels.
    """
    dw = max(1, round(logical_w * dpr))
    dh = max(1, round(logical_h * dpr))
    scaled = pixmap.scaled(dw, dh, Qt.KeepAspectRatioByExpanding,
                           Qt.SmoothTransformation)
    if scaled.width() > dw or scaled.height() > dh:
        x_off = (scaled.width() - dw) // 2
        y_off = (scaled.height() - dh) // 2
        scaled = scaled.copy(x_off, y_off, dw, dh)
    scaled.setDevicePixelRatio(dpr)
    return scaled


def rounded_corners(pixmap: QPixmap, radius: float) -> QPixmap:
    """Clip rounded corners; preserves the pixmap's devicePixelRatio."""
    dpr = float(pixmap.devicePixelRatio()) or 1.0
    out = QPixmap(pixmap.size())
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(
        QRectF(0, 0, pixmap.width() / dpr, pixmap.height() / dpr),
        radius, radius)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return out


def recolored_pixmap(svg_path, qcolor: QColor, dpr: float = 1.0) -> QPixmap:
    """Load an SVG, repaint it with qcolor (SourceIn), rasterized at dpr."""
    source = QPixmap(str(svg_path))
    if source.isNull():
        return source
    dpr = float(dpr or 1.0)
    if dpr > 1.0:
        dev_w = max(1, round(source.width() * dpr))
        dev_h = max(1, round(source.height() * dpr))
        upscaled = QPixmap(dev_w, dev_h)
        upscaled.fill(Qt.transparent)
        painter = QPainter(upscaled)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(QRect(0, 0, dev_w, dev_h), source)
        painter.end()
        source = upscaled
    colored = QPixmap(source.size())
    colored.fill(Qt.transparent)
    painter = QPainter(colored)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.drawPixmap(0, 0, source)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(colored.rect(), qcolor)
    painter.end()
    colored.setDevicePixelRatio(dpr)
    return colored


def recolored_icon(svg_path, qcolor: QColor, dpr: float = 1.0) -> QIcon:
    """recolored_pixmap wrapped as a QIcon (empty on load failure)."""
    pix = recolored_pixmap(svg_path, qcolor, dpr)
    return QIcon(pix) if not pix.isNull() else QIcon()
