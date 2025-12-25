# gui/startup/widgets/ghost_slider.py

from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QFont
from gui.theme.theme_vars import theme_vars


class GhostOpacitySlider(QWidget):
    valueChanged = Signal(int)
    hoverStatus = Signal(str)

    def __init__(self, minimum=0, maximum=60, value=30, parent=None):
        super().__init__(parent)

        self._min = minimum
        self._max = maximum
        self._value = value
        self._dragging = False

        # Geometry
        self.track_width = 30
        self.padding = 24

        self.handle_height_idle = 12
        self.handle_height_active = 22

        self.bubble_size = 28
        self.bubble_gap = 12
        self.right_gutter = 24

        self.setFixedWidth(
            self.track_width + self.bubble_size + self.bubble_gap + self.right_gutter
        )
        self.setMinimumHeight(300)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

    # --------------------------------------------------
    # Hover
    # --------------------------------------------------

    def enterEvent(self, event):
        self.hoverStatus.emit("Ghost Overlay Transparency")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hoverStatus.emit("")
        super().leaveEvent(event)

    # --------------------------------------------------
    # Value
    # --------------------------------------------------

    def value(self):
        return self._value

    def setValue(self, v):
        v = max(self._min, min(self._max, v))
        if v != self._value:
            self._value = v
            self.valueChanged.emit(v)
            self.update()

    # --------------------------------------------------
    # Geometry helpers
    # --------------------------------------------------

    def _track_rect(self):
        x = self.bubble_size + self.bubble_gap
        return QRect(
            x,
            self.padding,
            self.track_width,
            self.height() - 2 * self.padding,
        )

    def _ratio(self):
        return (self._value - self._min) / (self._max - self._min)

    def _value_to_y(self):
        track = self._track_rect()
        return track.bottom() - int(track.height() * self._ratio())

    # --------------------------------------------------
    # Paint
    # --------------------------------------------------

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        track = self._track_rect()
        y = self._value_to_y()

        v = theme_vars()

        # Track background
        p.setPen(Qt.NoPen)
        p.setBrush(v.qcolor("surface_variant"))
        p.drawRoundedRect(track, 14, 14)

        # Track fill
        fill_rect = QRect(
            track.x(),
            y,
            track.width(),
            track.bottom() - y,
        )
        p.setBrush(v.qcolor("primary"))
        p.drawRoundedRect(fill_rect, 14, 14)

        # Handle
        handle_h = (
            self.handle_height_active if self._dragging else self.handle_height_idle
        )

        handle_rect = QRect(
            track.x() - 10,
            y - handle_h // 2,
            track.width() + 20,
            handle_h,
        )

        if self._dragging:
            p.setPen(v.qcolor("primary"))
            p.drawRoundedRect(
                handle_rect.adjusted(1, 1, -1, -1),
                handle_h // 2,
                handle_h // 2,
            )
            p.setPen(Qt.NoPen)

        p.setBrush(
            v.qcolor("surface_container_high")
            if self._dragging
            else v.qcolor("surface_container_highest")
        )
        p.drawRoundedRect(
            handle_rect,
            handle_h // 2,
            handle_h // 2,
        )

        # Value bubble
        if self._dragging:
            bubble_rect = QRect(
                track.left() - self.bubble_size - self.bubble_gap,
                handle_rect.center().y() - self.bubble_size // 2,
                self.bubble_size,
                self.bubble_size,
            )

            p.setBrush(v.qcolor("surface_container"))
            p.drawEllipse(bubble_rect)

            p.setPen(v.qcolor("on_surface"))
            font = QFont()
            font.setBold(True)
            font.setPointSize(9)
            p.setFont(font)

            p.drawText(bubble_rect, Qt.AlignCenter, str(self._value))

    # --------------------------------------------------
    # Interaction
    # --------------------------------------------------

    def mousePressEvent(self, e):
        self._dragging = True
        self._update_from_mouse(e.position().y())
        self.update()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._update_from_mouse(e.position().y())

    def mouseReleaseEvent(self, e):
        self._dragging = False
        self.update()

    def _update_from_mouse(self, y):
        track = self._track_rect()
        y = max(track.top(), min(track.bottom(), y))
        ratio = 1.0 - (y - track.top()) / track.height()
        value = int(self._min + ratio * (self._max - self._min))
        self.setValue(value)
