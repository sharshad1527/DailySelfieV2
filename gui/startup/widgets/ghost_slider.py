# gui/startup/widgets/ghost_slider.py

from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QFont, QPainterPath
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
        self.track_width = 56
        self.padding_top = 12  
        self.padding_bottom = 12
        
        # Handle properties
        # User wants a visible gap on top/bottom. 
        self.handle_height = 8 
        self.handle_width_extra = 24 
        self.gap_size = 3 

        # Total width needed: track + handle overhang
        self.setFixedWidth(self.track_width + self.handle_width_extra + 4) 
        self.setMinimumHeight(460) 
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
        # Centered horizontally
        x = (self.width() - self.track_width) // 2
        
        # Taking up full height minus padding
        return QRect(
            x,
            self.padding_top,
            self.track_width,
            self.height() - (self.padding_top + self.padding_bottom),
        )

    def _ratio(self):
        if self._max == self._min:
            return 0
        return (self._value - self._min) / (self._max - self._min)

    def _value_to_y(self):
        track = self._track_rect()
        available_height = track.height()
        return (track.y() + track.height()) - int(available_height * self._ratio())

    # --------------------------------------------------
    # Paint
    # --------------------------------------------------

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        v = theme_vars()
        track = self._track_rect()
        y = self._value_to_y()
        
        # 1. Define Shapes
        # ----------------
        
        # Instead of a capsule (width/2), we use a smaller fixed radius.
        radius = 14
        
        # The Fill Level
        fill_top = y
        fill_height = (track.y() + track.height()) - fill_top
        
        # 2. Draw Background (Empty Jar)
        # -----------------------------
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(v.qcolor("surface_container_highest"))
        p.drawRoundedRect(track, radius, radius)
        p.restore()

        # 3. Draw Text (Background Color)
        # -------------------------------
        # Text is drawn at the BOTTOM of the track
        text_rect = QRect(track.x(), (track.y() + track.height()) - 50, track.width(), 40)
        
        p.save()
        font = QFont()
        font.setBold(True)
        font.setPixelSize(24) 
        p.setFont(font)
        
        text = str(int(self._value))
        
        p.setPen(v.qcolor("on_surface_variant"))
        p.drawText(text_rect, Qt.AlignCenter, text)
        p.restore()

        # 4. Draw Fill (The Liquid)
        # -------------------------
        p.save()
        
        track_path = QPainterPath()
        track_path.addRoundedRect(track.x(), track.y(), track.width(), track.height(), radius, radius)
        p.setClipPath(track_path)
        
        fill_rect = QRect(
            track.x(), 
            fill_top, 
            track.width(), 
            fill_height + radius 
        )
        
        p.setPen(Qt.NoPen)
        p.setBrush(v.qcolor("primary"))
        p.drawRect(fill_rect)

        # 5. Draw Text (Fill Color)
        # -------------------------
        # This draws the text *again*, but clipped to the fill rect
        p.setClipRect(fill_rect, Qt.IntersectClip)
        
        p.setPen(v.qcolor("on_primary"))
        p.setFont(font)
        p.drawText(text_rect, Qt.AlignCenter, text)
        
        p.restore()

        # 6. Draw Handle (The Limit Line/Cap)
        # -----------------------------------
        p.save()
        
        current_h = self.handle_height - 2 if self._dragging else self.handle_height
        
        handle_w = self.track_width + self.handle_width_extra
        handle_x = track.center().x() - handle_w // 2
        handle_y = y - current_h // 2
        
        handle_rect = QRect(
            handle_x,
            handle_y,
            handle_w,
            current_h
        )
        
        # Draw the "Gap" (Stroke effect)
        # We draw a larger rect behind the handle using the BACKGROUND color
        # This erases the track/fill visually
        gap_rect = handle_rect.adjusted(-self.gap_size, -self.gap_size, self.gap_size, self.gap_size)
        
        p.setPen(Qt.NoPen)
        # Use 'background' to match the window background
        p.setBrush(v.qcolor("background")) 
        p.drawRoundedRect(gap_rect, (current_h + self.gap_size*2) // 2, (current_h + self.gap_size*2) // 2)

        # Draw the actual Handle
        p.setBrush(v.qcolor("primary"))
        p.drawRoundedRect(handle_rect, current_h // 2, current_h // 2)
        
        p.restore()

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
        
        height = track.height()
        if height <= 0: return 
        
        # Clamp y strictly
        y = max(track.top(), min(track.y() + track.height(), y))
        
        relative_y = y - track.top()
        ratio = 1.0 - (relative_y / height)
        ratio = max(0.0, min(1.0, ratio))
        
        value = int(self._min + ratio * (self._max - self._min))
        self.setValue(value)
