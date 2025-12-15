from PySide6.QtCore import Qt, QRect, QSize, Signal
from PySide6.QtWidgets import QWidget, QPushButton, QHBoxLayout
from PySide6.QtGui import QPainter, QColor, QIcon, QFont

class ShutterBar(QWidget):
    # Signals
    shutterClicked = Signal()
    saveClicked = Signal()
    retakeClicked = Signal()
    lightToggled = Signal(bool)
    timerChanged = Signal(int) 

    def __init__(self, initial_timer=0, parent=None):
        super().__init__(parent)
        self.setFixedHeight(80) 
        self.setFixedWidth(320)

        # Internal state
        self.is_review = False
        self._shutter_pressed = False
        self._timer_value = initial_timer 
        self._timer_options = [0, 2, 3, 5]

        # --- Capture Mode UI ---
        
        # 1. Light Button (Left)
        self.light_btn = QPushButton(self)
        self.light_btn.setCheckable(True)
        self.light_btn.setIcon(QIcon("gui/assets/icons/light.svg"))
        self.light_btn.setIconSize(QSize(24, 24))
        self.light_btn.clicked.connect(self._on_light_clicked)

        # 2. Shutter Button (Center)
        self.shutter_btn = QPushButton(self)
        self.shutter_btn.setIcon(QIcon("gui/assets/icons/shutter.svg"))
        self.shutter_btn.setIconSize(QSize(32, 32))
        self.shutter_btn.pressed.connect(self._on_shutter_press)
        self.shutter_btn.released.connect(self._on_shutter_release)
        self.shutter_btn.clicked.connect(self.shutterClicked.emit)

        # 3. Timer Button (Right)
        self.timer_btn = QPushButton(self)
        self.timer_btn.clicked.connect(self._toggle_timer)
        # We store the icon here to paint it manually
        self._timer_icon = QIcon("gui/assets/icons/timer.svg") 

        # Style capture buttons 
        for btn in (self.light_btn, self.shutter_btn, self.timer_btn):
            btn.setStyleSheet("background: transparent; border: none;")

        # --- Review Mode UI (Hidden by default) ---
        self.review_container = QWidget(self)
        self.review_layout = QHBoxLayout(self.review_container)
        self.review_layout.setContentsMargins(0, 0, 0, 0)
        self.review_layout.setSpacing(30)

        self.btn_retake = QPushButton("✗")
        self.btn_retake.setFixedSize(54, 54)
        self.btn_retake.clicked.connect(self.retakeClicked.emit)
        
        self.btn_save = QPushButton("✓") 
        self.btn_save.setFixedSize(54, 54)
        self.btn_save.clicked.connect(self.saveClicked.emit)

        self.btn_retake.setStyleSheet("QPushButton { background-color: #3A3A3A; border-radius: 27px; color: #E0E0E0; font-size: 24px; font-weight: bold; } QPushButton:hover { background-color: #4A4A4A; color: white; }")
        self.btn_save.setStyleSheet("QPushButton { background-color: #8B5CF6; border-radius: 27px; color: white; font-size: 24px; font-weight: bold; } QPushButton:hover { background-color: #7C3AED; }")

        self.review_layout.addWidget(self.btn_retake)
        self.review_layout.addWidget(self.btn_save)

        self.setReviewMode(False)

    def setReviewMode(self, is_review: bool):
        self.is_review = is_review
        
        # Toggle visibility
        self.light_btn.setVisible(not is_review)
        self.shutter_btn.setVisible(not is_review)
        self.timer_btn.setVisible(not is_review)
        self.review_container.setVisible(is_review)
        
        self.update()

    def _toggle_timer(self):
        # Cycle: 0 -> 2 -> 3 -> 5 -> 0
        try:
            idx = self._timer_options.index(self._timer_value)
            next_idx = (idx + 1) % len(self._timer_options)
            self._timer_value = self._timer_options[next_idx]
        except ValueError:
            self._timer_value = 0
        
        self.timerChanged.emit(self._timer_value)
        self.update()

    def _on_shutter_press(self):
        self._shutter_pressed = True
        self.update()

    def _on_shutter_release(self):
        self._shutter_pressed = False
        self.update()

    def _on_light_clicked(self):
        self.lightToggled.emit(self.light_btn.isChecked())
        self.update()

    def get_timer_value(self):
        return self._timer_value

    def resizeEvent(self, event):
        h = self.height()
        w = self.width()
        
        # --- Geometry for Capture Mode ---
        
        # 1. Light (Left Circle)
        self.light_btn.setGeometry(16, (h - 44) // 2, 44, 44)

        # 3. Timer (Right Vertical Pill)
        # 36px wide, 50px tall
        timer_w, timer_h = 36, 50
        self.timer_rect = QRect(w - 16 - timer_w, (h - timer_h)//2, timer_w, timer_h)
        self.timer_btn.setGeometry(self.timer_rect)

        # 2. Shutter (Center Pill)
        shutter_h = 56
        shutter_w = 100
        shutter_x = (w - shutter_w) // 2
        
        self.shutter_rect = QRect(shutter_x, (h - shutter_h)//2, shutter_w, shutter_h)
        self.shutter_btn.setGeometry(self.shutter_rect)

        # --- Geometry for Review Mode ---
        self.review_container.setGeometry(0, 0, w, h)
        self.review_layout.setAlignment(Qt.AlignCenter)

    def paintEvent(self, event):
        if self.is_review:
            return 

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # 1. Base pill (Container Background)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#161616"))
        p.drawRoundedRect(self.rect(), 40, 40)

        # 2. Shutter Button (Purple Pill)
        if self._shutter_pressed:
            shutter_color = QColor("#6D28D9")
        else:
            shutter_color = QColor("#8B5CF6")
        
        p.setBrush(shutter_color)
        p.drawRoundedRect(self.shutter_rect, 28, 28)

        # 3. Light Button Glow
        if self.light_btn.isChecked():
            glow_rect = self.light_btn.geometry().adjusted(-4, -4, 4, 4)
            p.setBrush(QColor(255, 255, 255, 30))
            p.drawEllipse(glow_rect)

        # 4. Timer Button (Vertical Pill)
        # Background changes if Active
        if self._timer_value > 0:
            p.setBrush(QColor("#333333")) # Active background
            text_color = QColor("#8B5CF6") # Purple Text
        else:
            p.setBrush(QColor("#1A1A1A")) # Inactive background
            text_color = QColor("#666666") # Dim Text

        p.drawRoundedRect(self.timer_rect, 18, 18)

        # Draw Content (Icon or Text)
        if self._timer_value > 0:
            p.setPen(text_color)
            font = QFont()
            font.setBold(True)
            font.setPointSize(11) # Slightly smaller to fit '2s'
            p.setFont(font)
            # Draw "2s", "3s", "5s"
            p.drawText(self.timer_rect, Qt.AlignCenter, f"{self._timer_value}s")
        else:
            # Draw the Icon
            # Calculate a square area inside the vertical pill for the icon
            icon_size = 20
            icon_x = self.timer_rect.center().x() - icon_size // 2
            icon_y = self.timer_rect.center().y() - icon_size // 2
            icon_draw_rect = QRect(icon_x, icon_y, icon_size, icon_size)
            
            # Use active/inactive color logic for icon if desired, or just draw it
            # The icon itself might be black/white. We can assume it's white/light.
            self._timer_icon.paint(p, icon_draw_rect, Qt.AlignCenter)