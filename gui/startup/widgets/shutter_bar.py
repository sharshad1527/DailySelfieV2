from PySide6.QtCore import Qt, QRect, QSize, Signal
from PySide6.QtWidgets import QWidget, QPushButton, QHBoxLayout
from PySide6.QtGui import QPainter, QColor, QIcon

class ShutterBar(QWidget):
    # Signals
    shutterClicked = Signal()
    saveClicked = Signal()
    retakeClicked = Signal()
    lightToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(68)
        self.setFixedWidth(260) # Increased slightly for review buttons

        # Internal state
        self.is_review = False
        self._shutter_pressed = False

        # --- Capture Mode UI ---
        self.light_btn = QPushButton(self)
        self.light_btn.setCheckable(True)
        self.light_btn.setIcon(QIcon("gui/assets/icons/light.svg"))
        self.light_btn.setIconSize(QSize(20, 20))
        self.light_btn.clicked.connect(self._on_light_clicked) # Handle visual update

        self.shutter_btn = QPushButton(self)
        self.shutter_btn.setIcon(QIcon("gui/assets/icons/shutter.svg"))
        self.shutter_btn.setIconSize(QSize(26, 26))
        # Logic for visual feedback
        self.shutter_btn.pressed.connect(self._on_shutter_press)
        self.shutter_btn.released.connect(self._on_shutter_release)
        # Logic for action
        self.shutter_btn.clicked.connect(self.shutterClicked.emit)

        # Style capture buttons
        for btn in (self.light_btn, self.shutter_btn):
            btn.setStyleSheet("background: transparent; border: none;")

        # --- Review Mode UI (Hidden by default) ---
        self.review_container = QWidget(self)
        self.review_layout = QHBoxLayout(self.review_container)
        self.review_layout.setContentsMargins(0, 0, 0, 0)
        self.review_layout.setSpacing(20)

        self.btn_retake = QPushButton("✗")
        self.btn_retake.setFixedSize(48, 48)
        self.btn_retake.clicked.connect(self.retakeClicked.emit)
        
        self.btn_save = QPushButton("✓") 
        self.btn_save.setFixedSize(48, 48)
        self.btn_save.clicked.connect(self.saveClicked.emit)

        # Styling for Save/Retake
        self.btn_retake.setStyleSheet("""
            QPushButton { background-color: #3A3A3A; border-radius: 24px; color: #E0E0E0; font-size: 20px; font-weight: bold; }
            QPushButton:hover { background-color: #4A4A4A; color: white; }
        """)
        self.btn_save.setStyleSheet("""
            QPushButton { background-color: #8B5CF6; border-radius: 24px; color: white; font-size: 20px; font-weight: bold; }
            QPushButton:hover { background-color: #7C3AED; }
        """)

        self.review_layout.addWidget(self.btn_retake)
        self.review_layout.addWidget(self.btn_save)

        # Initialize State
        self.setReviewMode(False)

    def setReviewMode(self, is_review: bool):
        """Toggle between Capture (Shutter/Light) and Review (Save/Retake)"""
        self.is_review = is_review
        
        # Visibility
        self.light_btn.setVisible(not is_review)
        self.shutter_btn.setVisible(not is_review)
        self.review_container.setVisible(is_review)
        
        self.update() # Trigger repaint for background

    def _on_shutter_press(self):
        self._shutter_pressed = True
        self.update()

    def _on_shutter_release(self):
        self._shutter_pressed = False
        self.update()

    def _on_light_clicked(self):
        # Emit signal and update visuals
        self.lightToggled.emit(self.light_btn.isChecked())
        self.update()

    def resizeEvent(self, event):
        h = self.height()
        w = self.width()
        
        # --- Geometry for Capture Mode ---
        # Light button (LEFT)
        self.light_btn.setGeometry(12, (h - 36) // 2, 36, 36)

        # Shutter pill (RIGHT)
        gap = 12
        shutter_x = 12 + 36 + gap
        shutter_width = w - shutter_x - 12
        
        self.shutter_rect = QRect(shutter_x, 12, shutter_width, h - 24)
        self.shutter_btn.setGeometry(self.shutter_rect)

        # --- Geometry for Review Mode ---
        self.review_container.setGeometry(0, 0, w, h)
        self.review_layout.setAlignment(Qt.AlignCenter)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # 1. Base pill (Dark Grey) - Always visible
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#161616"))
        p.drawRoundedRect(self.rect(), 34, 34)

        # Only draw capture-specific visuals if NOT in review mode
        if not self.is_review:
            # 2. Shutter segment (Purple, changes on press)
            if self._shutter_pressed:
                shutter_color = QColor("#6D28D9")  # darker purple
            else:
                shutter_color = QColor("#8B5CF6")

            p.setBrush(shutter_color)
            # Use self.shutter_rect calculated in resizeEvent
            if hasattr(self, 'shutter_rect'):
                p.drawRoundedRect(
                    self.shutter_rect,
                    self.shutter_rect.height() // 2,
                    self.shutter_rect.height() // 2,
                )

            # 3. Light glow (Subtle, warm)
            if self.light_btn.isChecked():
                # Get geometry relative to parent
                glow_rect = self.light_btn.geometry().adjusted(-6, -6, 6, 6)
                p.setBrush(QColor(255, 255, 255, 30)) # White glow, low opacity
                p.drawEllipse(glow_rect)