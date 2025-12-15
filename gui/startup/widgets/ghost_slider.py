# gui/startup/widgets/ghost_slider
from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QFont


class GhostOpacitySlider(QWidget):
    valueChanged = Signal(int)
    # Signal for Toast
    hoverStatus = Signal(str)
    def __init__(self, minimum=0, maximum=60, value=30, parent=None):
        super().__init__(parent)

        self._min = minimum
        self._max = maximum
        self._value = value
        self._dragging = False


        # ===== Visual configuration =====
        self.track_width = 30          # thick pipe
        self.padding = 24

        self.handle_height_idle = 12
        self.handle_height_active = 22

        self.bubble_size = 28
        self.bubble_gap = 12

        # Reserve space on the RIGHT (not left)
        self.right_gutter = 24

        # Widget sizing (compact, left-biased)
        self.setFixedWidth(self.track_width + self.bubble_size + self.bubble_gap + self.right_gutter)
        self.setMinimumHeight(300)
        self.setCursor(Qt.PointingHandCursor)

        # Enable Mouse Tracking for Hover
        self.setMouseTracking(True)

    # -------Hover Logic-------
    def enterEvent(self, event):
        self.hoverStatus.emit("Ghost Overlay Transparency")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hoverStatus.emit("")
        super().leaveEvent(event)

    # ---------- Value ----------
    def value(self):
        return self._value

    def setValue(self, v):
        v = max(self._min, min(self._max, v))
        if v != self._value:
            self._value = v
            self.valueChanged.emit(v)
            self.update()

    # ---------- Geometry ----------
    def _track_rect(self):
        """
        Track is biased to the LEFT.
        Space is reserved on the RIGHT so nothing clips.
        """
        track_x = 0 + self.bubble_size + self.bubble_gap

        return QRect(
            track_x,
            self.padding,
            self.track_width,
            self.height() - 2 * self.padding,
        )

    def _ratio(self):
        return (self._value - self._min) / (self._max - self._min)

    def _value_to_y(self):
        track = self._track_rect()
        return track.bottom() - int(track.height() * self._ratio())

    # ---------- Paint ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        track = self._track_rect()
        y = self._value_to_y()

        # Track background
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#242424"))
        p.drawRoundedRect(track, 14, 14)

        # Filled part
        fill_rect = QRect(
            track.x(),
            y,
            track.width(),
            track.bottom() - y,
        )
        p.setBrush(QColor("#8B5CF6"))
        p.drawRoundedRect(fill_rect, 14, 14)

        # Handle (pill)
        handle_h = self.handle_height_active if self._dragging else self.handle_height_idle

        handle_rect = QRect(
            track.x() - 10,
            y - handle_h // 2,
            track.width() + 20,
            handle_h,
        )

        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(
            handle_rect,
            handle_h // 2,
            handle_h // 2,
        )

        # Value bubble (LEFT of track)
        if self._dragging:
            bubble_rect = QRect(
                track.left() - self.bubble_size - self.bubble_gap,
                handle_rect.center().y() - self.bubble_size // 2,
                self.bubble_size,
                self.bubble_size,
            )

            p.setBrush(QColor("#1F1F1F"))
            p.drawEllipse(bubble_rect)

            p.setPen(QColor("#FFFFFF"))
            font = QFont()
            font.setBold(True)
            font.setPointSize(9)
            p.setFont(font)

            p.drawText(
                bubble_rect,
                Qt.AlignCenter,
                str(self._value),
            )

    # ---------- Interaction ----------
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
