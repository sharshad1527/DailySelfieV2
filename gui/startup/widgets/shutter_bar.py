from PySide6.QtCore import Qt, QRect, QSize, Signal, QEvent, QObject
from PySide6.QtWidgets import QWidget, QPushButton, QHBoxLayout
from PySide6.QtGui import QPainter, QColor, QIcon, QFont
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
ICONS_DIR = CURRENT_DIR.parent.parent.parent / "gui" / "assets" / "icons"
class ShutterBar(QWidget):
    # Signals
    shutterClicked = Signal()
    saveClicked = Signal()
    retakeClicked = Signal()
    lightToggled = Signal(bool)
    timerChanged = Signal(int)
    
    hoverStatus = Signal(str) 

    def __init__(self, initial_timer=0, parent=None):
        super().__init__(parent)
        self.setFixedHeight(80) 
        self.setFixedWidth(300) # Compact width

        # Internal state
        self.is_review = False
        self._shutter_pressed = False
        self._timer_value = initial_timer 
        self._timer_options = [0, 2, 3, 5]

        # --- Capture Mode UI ---
        
        # 1. Light Button (Left)
        self.light_btn = QPushButton(self)
        self.light_btn.setCheckable(True)
        self.light_btn.setIcon(QIcon(str(ICONS_DIR / "light.svg")))
        self.light_btn.setIconSize(QSize(24, 24))
        self.light_btn.clicked.connect(self._on_light_clicked)
        self.light_btn.installEventFilter(self)

        # 2. Shutter Button (Center)
        self.shutter_btn = QPushButton(self)
        self.shutter_btn.setIcon(QIcon(str(ICONS_DIR / "shutter.svg")))
        self.shutter_btn.setIconSize(QSize(42, 42)) 
        self.shutter_btn.pressed.connect(self._on_shutter_press)
        self.shutter_btn.released.connect(self._on_shutter_release)
        self.shutter_btn.clicked.connect(self.shutterClicked.emit)
        self.shutter_btn.installEventFilter(self)

        # 3. Timer Button (Right)
        self.timer_btn = QPushButton(self)
        self.timer_btn.clicked.connect(self._toggle_timer)
        self.timer_btn.installEventFilter(self)
        self._timer_icon = QIcon(str(ICONS_DIR / "timer.svg")) 

        # Style capture buttons 
        for btn in (self.light_btn, self.shutter_btn, self.timer_btn):
            btn.setStyleSheet("background: transparent; border: none;")

        # --- Review Mode UI (Hidden by default) ---
        self.review_container = QWidget(self)
        self.review_layout = QHBoxLayout(self.review_container)
        self.review_layout.setContentsMargins(0, 0, 0, 0)
        self.review_layout.setSpacing(60) 

        self.btn_retake = QPushButton("✗")
        self.btn_retake.setFixedSize(54, 54)
        self.btn_retake.clicked.connect(self.retakeClicked.emit)
        self.btn_retake.installEventFilter(self)
        
        self.btn_save = QPushButton("✓") 
        self.btn_save.setFixedSize(54, 54)
        self.btn_save.clicked.connect(self.saveClicked.emit)
        self.btn_save.installEventFilter(self)

        self.btn_retake.setStyleSheet("QPushButton { background-color: #3A3A3A; border-radius: 27px; color: #E0E0E0; font-size: 24px; font-weight: bold; } QPushButton:hover { background-color: #4A4A4A; color: white; }")
        self.btn_save.setStyleSheet("QPushButton { background-color: #8B5CF6; border-radius: 27px; color: white; font-size: 24px; font-weight: bold; } QPushButton:hover { background-color: #7C3AED; }")

        self.review_layout.addWidget(self.btn_retake)
        self.review_layout.addWidget(self.btn_save)

        self.setReviewMode(False)

    # [NEW] Helper to check flash state
    def is_flash_on(self):
        return self.light_btn.isChecked()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Enter:
            if obj == self.light_btn:
                self.hoverStatus.emit("Screen Flash")
            elif obj == self.shutter_btn:
                self.hoverStatus.emit("Capture")
            elif obj == self.timer_btn:
                if self._timer_value == 0:
                    self.hoverStatus.emit("Timer: Off")
                else:
                    self.hoverStatus.emit(f"Timer: {self._timer_value}s")
            elif obj == self.btn_save:
                self.hoverStatus.emit("Save Photo")
            elif obj == self.btn_retake:
                self.hoverStatus.emit("Discard & Retake")
                
        elif event.type() == QEvent.Leave:
            self.hoverStatus.emit("")
            
        return super().eventFilter(obj, event)

    def setReviewMode(self, is_review: bool):
        self.is_review = is_review
        self.light_btn.setVisible(not is_review)
        self.shutter_btn.setVisible(not is_review)
        self.timer_btn.setVisible(not is_review)
        self.review_container.setVisible(is_review)
        self.update()

    def _toggle_timer(self):
        try:
            idx = self._timer_options.index(self._timer_value)
            next_idx = (idx + 1) % len(self._timer_options)
            self._timer_value = self._timer_options[next_idx]
        except ValueError:
            self._timer_value = 0
        
        self.timerChanged.emit(self._timer_value)
        if self.timer_btn.underMouse():
             self.hoverStatus.emit(f"Timer: {self._timer_value}s" if self._timer_value > 0 else "Timer: Off")
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
        
        self.light_btn.setGeometry(16, (h - 44) // 2, 44, 44)

        timer_w, timer_h = 36, 50
        self.timer_rect = QRect(w - 16 - timer_w, (h - timer_h)//2, timer_w, timer_h)
        self.timer_btn.setGeometry(self.timer_rect)

        # Shutter (Center Pill) - Adjusted Size
        shutter_h = 64
        shutter_w = 160
        shutter_x = (w - shutter_w) // 2
        
        self.shutter_rect = QRect(shutter_x, (h - shutter_h)//2, shutter_w, shutter_h)
        self.shutter_btn.setGeometry(self.shutter_rect)

        self.review_container.setGeometry(0, 0, w, h)
        self.review_layout.setAlignment(Qt.AlignCenter)

    def paintEvent(self, event):
        if self.is_review:
            return 

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#161616"))
        p.drawRoundedRect(self.rect(), 40, 40)

        if self._shutter_pressed:
            shutter_color = QColor("#6D28D9")
        else:
            shutter_color = QColor("#8B5CF6")
        
        p.setBrush(shutter_color)
        p.drawRoundedRect(self.shutter_rect, 32, 32) 

        if self.light_btn.isChecked():
            glow_rect = self.light_btn.geometry().adjusted(-4, -4, 4, 4)
            p.setBrush(QColor(255, 255, 255, 30))
            p.drawEllipse(glow_rect)

        if self._timer_value > 0:
            p.setBrush(QColor("#333333")) 
            text_color = QColor("#8B5CF6") 
        else:
            p.setBrush(QColor("#1A1A1A")) 
            text_color = QColor("#666666") 

        p.drawRoundedRect(self.timer_rect, 18, 18)

        if self._timer_value > 0:
            p.setPen(text_color)
            font = QFont()
            font.setBold(True)
            font.setPointSize(11)
            p.setFont(font)
            p.drawText(self.timer_rect, Qt.AlignCenter, f"{self._timer_value}s")
        else:
            icon_size = 20
            icon_x = self.timer_rect.center().x() - icon_size // 2
            icon_y = self.timer_rect.center().y() - icon_size // 2
            icon_draw_rect = QRect(icon_x, icon_y, icon_size, icon_size)
            self._timer_icon.paint(p, icon_draw_rect, Qt.AlignCenter)