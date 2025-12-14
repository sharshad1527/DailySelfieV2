from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtWidgets import QWidget, QPushButton
from PySide6.QtGui import QPainter, QColor, QIcon


class ShutterBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setFixedHeight(68)
        self.setFixedWidth(240)

        # Internal state
        self._shutter_pressed = False

        # ---------- Buttons (interaction only) ----------
        self.light_btn = QPushButton(self)
        self.light_btn.setCheckable(True)
        self.light_btn.setIcon(QIcon("gui/assets/icons/light.svg"))
        self.light_btn.setIconSize(QSize(20, 20))
        self.light_btn.clicked.connect(self.update)

        self.shutter_btn = QPushButton(self)
        self.shutter_btn.setIcon(QIcon("gui/assets/icons/shutter.svg"))
        self.shutter_btn.setIconSize(QSize(26, 26))
        self.shutter_btn.pressed.connect(self._on_shutter_press)
        self.shutter_btn.released.connect(self._on_shutter_release)

        for btn in (self.light_btn, self.shutter_btn):
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                }
            """)

        self._update_geometry()

    # ---------- Geometry ----------
    def _update_geometry(self):
        h = self.height()

        # Light button (LEFT)
        self.light_btn.setGeometry(
            12,
            (h - 36) // 2,
            36,
            36,
        )

        # Horizontal spacing between light and shutter
        gap = 12

        shutter_x = 12 + 36 + gap
        shutter_width = self.width() - shutter_x - 12

        # Shutter pill (slightly smaller, properly spaced)
        self.shutter_rect = QRect(
            shutter_x,
            12,
            shutter_width,
            h - 24,
        )

    # Shutter button matches segment exactly
        self.shutter_btn.setGeometry(self.shutter_rect)

    def resizeEvent(self, event):
        self._update_geometry()

    # ---------- Paint ----------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Base pill
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#161616"))
        p.drawRoundedRect(self.rect(), 34, 34)

        # Shutter segment (color changes on press)
        if self._shutter_pressed:
            shutter_color = QColor("#6D28D9")  # darker purple
        else:
            shutter_color = QColor("#8B5CF6")

        p.setBrush(shutter_color)
        p.drawRoundedRect(
            self.shutter_rect,
            self.shutter_rect.height() // 2,
            self.shutter_rect.height() // 2,
        )

        # Light glow (subtle, warm)
        if self.light_btn.isChecked():
            glow_rect = self.light_btn.geometry().adjusted(-6, -6, 6, 6)
            p.setBrush(QColor(0, 0, 0, 93))
            p.drawEllipse(glow_rect)

    # ---------- Feedback ----------
    def _on_shutter_press(self):
        self._shutter_pressed = True
        self.update()

    def _on_shutter_release(self):
        self._shutter_pressed = False
        self.update()
