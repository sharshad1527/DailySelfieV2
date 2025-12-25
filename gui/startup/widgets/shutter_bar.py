# gui/startup/widgets/shutter_bar.py

from PySide6.QtCore import Qt, QRect, QSize, Signal, QEvent
from PySide6.QtWidgets import QWidget, QPushButton, QHBoxLayout
from PySide6.QtGui import QPainter, QIcon, QFont, QPixmap, QColor
from pathlib import Path

# Assuming theme_vars is available as in your snippet
from gui.theme.theme_vars import theme_vars

CURRENT_DIR = Path(__file__).resolve().parent
# Adjust path if necessary based on your actual project structure
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

        self.setFixedSize(300, 80)

        # ---- State ----
        self.is_review = False
        self._shutter_pressed = False
        self._timer_value = initial_timer
        self._timer_options = [0, 2, 3, 5]

        # --------------------------------------------------
        # Capture buttons
        # --------------------------------------------------

        # 1. Flash / Light Button
        self.light_btn = QPushButton(self)
        self.light_btn.setCheckable(True)
        self.light_btn.setIconSize(QSize(24, 24))
        self.light_btn.clicked.connect(self._on_light_clicked)
        self.light_btn.installEventFilter(self)

        # 2. Shutter Button
        self.shutter_btn = QPushButton(self)
        self.shutter_btn.setIconSize(QSize(42, 42))
        self.shutter_btn.pressed.connect(self._on_shutter_press)
        self.shutter_btn.released.connect(self._on_shutter_release)
        self.shutter_btn.clicked.connect(self.shutterClicked.emit)
        self.shutter_btn.installEventFilter(self)

        # 3. Timer Button
        self.timer_btn = QPushButton(self)
        self.timer_btn.clicked.connect(self._toggle_timer)
        self.timer_btn.installEventFilter(self)
        
        # Placeholder for the timer icon (loaded in _apply_icon_theme)
        self._timer_icon = QIcon()

        # Set transparency for standard buttons (we paint backgrounds manually)
        for b in (self.light_btn, self.shutter_btn, self.timer_btn):
            b.setStyleSheet("background: transparent; border: none;")

        # --------------------------------------------------
        # Review mode (Save/Discard)
        # --------------------------------------------------

        self.review_container = QWidget(self)
        review_layout = QHBoxLayout(self.review_container)
        review_layout.setContentsMargins(0, 0, 0, 0)
        review_layout.setSpacing(60)

        self.btn_retake = QPushButton("✗")
        self.btn_save = QPushButton("✓")

        for b in (self.btn_retake, self.btn_save):
            b.setFixedSize(54, 54)
            b.installEventFilter(self)

        self.btn_retake.clicked.connect(self.retakeClicked.emit)
        self.btn_save.clicked.connect(self.saveClicked.emit)

        review_layout.addWidget(self.btn_retake)
        review_layout.addWidget(self.btn_save)

        self.setReviewMode(False)

        # Theme Initialization
        self._apply_icon_theme()
        self._apply_review_button_theme()

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    def is_flash_on(self):
        return self.light_btn.isChecked()

    def get_timer_value(self):
        return self._timer_value
        
    def _create_colored_icon(self, icon_name, qcolor):
        """
        Loads an SVG and repaints it with the given QColor.
        This fixes the issue where icons ignore CSS color properties.
        """
        path = ICONS_DIR / icon_name
        if not path.exists():
            return QIcon()

        # Load original
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return QIcon()

        # Create a new transparent pixmap of the same size
        colored_pixmap = QPixmap(pixmap.size())
        colored_pixmap.fill(Qt.transparent)

        # Paint
        painter = QPainter(colored_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        # Draw the mask (original icon)
        painter.drawPixmap(0, 0, pixmap)
        
        # Fill with color using SourceIn (keeps alpha, changes color)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(colored_pixmap.rect(), qcolor)
        painter.end()

        return QIcon(colored_pixmap)

    # --------------------------------------------------
    # Hover tooltips
    # --------------------------------------------------

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Enter:
            if obj == self.light_btn:
                self.hoverStatus.emit("Screen Flash")
            elif obj == self.shutter_btn:
                self.hoverStatus.emit("Capture")
            elif obj == self.timer_btn:
                status = "Timer: Off" if self._timer_value == 0 else f"Timer: {self._timer_value}s"
                self.hoverStatus.emit(status)
            elif obj == self.btn_save:
                self.hoverStatus.emit("Save Photo")
            elif obj == self.btn_retake:
                self.hoverStatus.emit("Discard & Retake")

        elif event.type() == QEvent.Leave:
            self.hoverStatus.emit("")

        return super().eventFilter(obj, event)

    # --------------------------------------------------
    # Layout
    # --------------------------------------------------

    def resizeEvent(self, event):
        h, w = self.height(), self.width()

        self.light_btn.setGeometry(16, (h - 44) // 2, 44, 44)

        self.timer_rect = QRect(w - 52, (h - 50) // 2, 36, 50)
        self.timer_btn.setGeometry(self.timer_rect)

        self.shutter_rect = QRect((w - 160) // 2, (h - 64) // 2, 160, 64)
        self.shutter_btn.setGeometry(self.shutter_rect)

        self.review_container.setGeometry(0, 0, w, h)

    # --------------------------------------------------
    # Paint
    # --------------------------------------------------

    def paintEvent(self, event):
        if self.is_review:
            return

        v = theme_vars()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        # 1. Bar background
        p.setBrush(v.qcolor("surface_container"))
        p.drawRoundedRect(self.rect(), 40, 40)

        # 2. Shutter Background
        # Changes color slightly when pressed
        shutter_color = v.qcolor("primary_fixed_dim") if self._shutter_pressed else v.qcolor("primary")
        p.setBrush(shutter_color)
        p.drawRoundedRect(self.shutter_rect, 32, 32)

        # 3. Flash glow (only when ON)
        if self.light_btn.isChecked():
            glow = self.light_btn.geometry().adjusted(-4, -4, 4, 4)
            p.setBrush(v.rgba("primary", 0.25))
            p.drawEllipse(glow)

        # 4. Timer Background
        active = self._timer_value > 0
        p.setBrush(
            v.qcolor("surface_container_high")
            if active else v.qcolor("surface_container_low")
        )
        p.drawRoundedRect(self.timer_rect, 18, 18)

        # 5. Timer Content (Text or Icon)
        if active:
            p.setPen(v.qcolor("primary"))
            font = QFont()
            font.setBold(True)
            font.setPointSize(11)
            p.setFont(font)
            p.drawText(self.timer_rect, Qt.AlignCenter, f"{self._timer_value}s")
        else:
            # Draw the colorized icon we prepared in _apply_icon_theme
            icon_rect = QRect(
                self.timer_rect.center().x() - 10,
                self.timer_rect.center().y() - 10,
                20,
                20,
            )
            self._timer_icon.paint(p, icon_rect, Qt.AlignCenter)

    # --------------------------------------------------
    # Theme helpers
    # --------------------------------------------------

    def _apply_icon_theme(self):
        """
        Regenerates all icons using the current theme colors.
        Call this when theme changes or button states change (like Flash ON/OFF).
        """
        v = theme_vars()

        # Define colors
        color_inactive = v.qcolor("on_surface_variant")
        color_active = v.qcolor("primary")
        # Shutter icon sits on 'primary' background, so use 'on_primary' (usually white/black)
        color_on_primary = v.qcolor("on_primary")

        # 1. Light Button Icon
        # If checked, use active color; otherwise inactive color.
        flash_color = color_active if self.light_btn.isChecked() else color_inactive
        self.light_btn.setIcon(self._create_colored_icon("light.svg", flash_color))

        # 2. Timer Icon (used in paintEvent)
        # Always use the inactive color for the "off" state icon
        self._timer_icon = self._create_colored_icon("timer.svg", color_inactive)
        
        # 3. Shutter Icon
        self.shutter_btn.setIcon(self._create_colored_icon("shutter.svg", color_on_primary))

        # Trigger a repaint to show changes
        self.update()

    def _apply_review_button_theme(self):
        """
        Applies CSS to the review (Save/Retake) buttons.
        These use standard background colors, so stylesheets work fine here.
        """
        v = theme_vars()

        self.btn_save.setStyleSheet(f"""
            QPushButton {{
                background-color: {v["primary"]};
                color: {v["on_primary"]};
                border-radius: 27px;
                font-size: 24px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {v["primary_container"]};
            }}
        """)

        self.btn_retake.setStyleSheet(f"""
            QPushButton {{
                background-color: {v["surface_container_low"]};
                color: {v["on_surface"]};
                border-radius: 27px;
                font-size: 24px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {v["surface_container"]};
            }}
        """)

    # --------------------------------------------------
    # State changes
    # --------------------------------------------------

    def setReviewMode(self, review: bool):
        self.is_review = review
        self.light_btn.setVisible(not review)
        self.shutter_btn.setVisible(not review)
        self.timer_btn.setVisible(not review)
        self.review_container.setVisible(review)
        self.update()

    def _toggle_timer(self):
        i = self._timer_options.index(self._timer_value)
        self._timer_value = self._timer_options[(i + 1) % len(self._timer_options)]
        self.timerChanged.emit(self._timer_value)

        # Update toast immediately if hovering
        if self.timer_btn.underMouse():
            status = "Timer: Off" if self._timer_value == 0 else f"Timer: {self._timer_value}s"
            self.hoverStatus.emit(status)

        self.update()

    def _on_shutter_press(self):
        self._shutter_pressed = True
        self.update()

    def _on_shutter_release(self):
        self._shutter_pressed = False
        self.update()

    def _on_light_clicked(self):
        # Update icon color (Active vs Inactive)
        self._apply_icon_theme()
        
        # Emit signal
        self.lightToggled.emit(self.light_btn.isChecked())
        self.update()