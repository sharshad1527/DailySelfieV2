# gui/dashboard/navigation_rail.py
from PySide6.QtWidgets import QPushButton
from PySide6.QtWidgets import QLabel
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QButtonGroup, QToolButton,
    QSizePolicy
    )

from gui.theme.theme_vars import theme_vars
from core.paths import get_app_paths

paths = get_app_paths("DailySelfie", ensure=False)
ICONS_DIR = paths.project_root / "gui" / "assets" / "icons"

vars = theme_vars()

# Icons
ico_menu = "menu.svg"
ico_menu_open = "menu_open.svg"

ico_dashboard = "dashboard.svg"
ico_dashboard_filled = "dashboard_filled.svg"

ico_calendar = "calendar.svg"
ico_calendar_filled = "calendar_filled.svg"

ico_settings = "settings.svg"
ico_settings_filled = "settings_filled.svg"

class NavButton(QWidget):
    clicked = Signal() # Add a Click Signal
    
    def __init__(self, icon_normal, icon_checked, text: str = ""):
        super().__init__()
        self._hovered = False
        self._checked = False
        self._collapsed = False

        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, True) # Ensure background is painted
        self.setObjectName("NavButton") # Set class name for stylesheet selector
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

        self.icon_normal = icon_normal
        self.icon_checked = icon_checked

        nav_button_layout = QHBoxLayout()
        nav_button_layout.setContentsMargins(12, 12, 0, 10)
        nav_button_layout.setSpacing(0)

        self.icon_label = QLabel()
        self.icon_label.setPixmap(self.icon_normal.pixmap(24, 24))
        self.txt_label = QLabel()
        self.txt_label.setText(text)

        nav_button_layout.addWidget(self.icon_label)
        nav_button_layout.addWidget(self.txt_label)
        nav_button_layout.addStretch()
        self.setLayout(nav_button_layout)
        self.updateStyle()

    # Emit the clicked signal when the navbutton is clicked
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            print("NavButton clicked")
            self.clicked.emit()

    # Emit the hovered signal when the navbutton is hovered
    def enterEvent(self, event):
        print("NavButton entered")
        self._hovered = True
        self.updateStyle()

    # Emit the unhovered signal when the navbutton is unhovered
    def leaveEvent(self, event):
        print("NavButton left")
        self._hovered = False
        self.updateStyle()   

    # Set the checked state of the navbutton
    def setChecked(self, value: bool):
        self._checked = value
        self.updateStyle()

    # Get the checked state of the navbutton
    def isChecked(self) -> bool:
        return self._checked

    # Set the collapsed state of the navbutton
    def setCollapsed(self, value: bool):
        self._collapsed = value
        if value == True:
            self.txt_label.hide()
            self.icon_label.setPixmap(self.icon_normal.pixmap(24, 24))

        else:
            self.txt_label.show()
            self.icon_label.setPixmap(self.icon_checked.pixmap(24, 24))


    # Get the collapsed state of the navbutton
    def isCollapsed(self) -> bool:
        return self._collapsed

    # Update the style of the navbutton
    def updateStyle(self):
        if self._checked:
            # CHECKED STATE
            # Material 3 Rule: Active/Selected items use the Secondary Container color.
            # Color Role: Secondary Container (Background)
            # Content Color: On Secondary Container (Text/Icon)
            self.setStyleSheet(f"""
                QWidget#NavButton {{ 
                    background-color: {vars['secondary_container']}; 
                    border-radius: 20px; 
                }}
                QLabel {{ 
                    color: {vars['on_secondary_container']}; 
                    background-color: transparent; 
                }}
            """)
        elif self._hovered:
            # HOVER STATE
            # Material 3 Rule: Hover state uses a state layer (usually 8% opacity on surface).
            # Proxy Color: Surface Container Highest (approximates the hover depth).
            # Content Color: On Surface
            self.setStyleSheet(f"""
                QWidget#NavButton {{ 
                    background-color: {vars['surface_container_highest']}; 
                    border-radius: 20px; 
                }}
                QLabel {{ 
                    color: {vars['on_surface']}; 
                    background-color: transparent; 
                }}
            """)
        else:
            # DEFAULT STATE
            # Material 3 Rule: Inactive items sit on the surface (transparent container).
            # Color Role: Transparent
            # Content Color: On Surface Variant (Low emphasis for inactive items)
            self.setStyleSheet(f"""
                QWidget#NavButton {{ 
                    background-color: transparent; 
                    border-radius: 20px; 
                }}
                QLabel {{ 
                    color: {vars['on_surface_variant']}; 
                    background-color: transparent; 
                }}
            """)


class NavigationRail(QWidget):
    # Just Changed Value to low because of testing
    EXPANDED_WIDTH = 200 # 200px
    COLLAPSED_WIDTH = 60 # 60px

    def __init__(self):
        super().__init__()
        
        vars = theme_vars()
        self._is_collapsed = False
    

        vlayout = QVBoxLayout(self)
        vlayout.setContentsMargins(0, 0, 0, 0)
        vlayout.setSpacing(0)

        v = theme_vars()

        # Define colors
        color_inactive = v.qcolor("on_surface_variant")
        color_active = v.qcolor("primary")
        # Shutter icon sits on 'primary' background, so use 'on_primary' (usually white/black)
        color_on_primary = v.qcolor("on_primary")
        
        ico_menu = self._create_colored_icon("menu.svg", color_inactive)
        ico_menu_open = self._create_colored_icon("menu_open.svg", color_active)

        
        self.sample = NavButton(ico_menu, ico_menu_open, "Menu")
        self.sample.clicked.connect(self.toggleCollapsedState)
        # self.sample.setChecked(True)
        # sample.setCollapsed(True)
        vlayout.addWidget(self.sample)

        vlayout.addStretch()


        self.applyCollapsedState(self._is_collapsed)

        # self._apply_icon_theme()

        
    def toggleCollapsedState(self):
        self._is_collapsed = not self._is_collapsed
        
        self.applyCollapsedState(self._is_collapsed)


    def applyCollapsedState(self, collapsed):
        if collapsed:
            self.setFixedWidth(self.COLLAPSED_WIDTH)
            # Just A test
            self.sample.setCollapsed(True)
            
        else:
            self.setFixedWidth(self.EXPANDED_WIDTH)
            # Just A test
            self.sample.setCollapsed(False)
            
    # --------------------------------------------------
    # Theme helpers
    # --------------------------------------------------

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

    def _apply_icon_theme(self):

        """
        Regenerates all icons using the current theme colors.
        """
        v = theme_vars()

        # Define colors
        color_inactive = v.qcolor("on_surface_variant")
        color_active = v.qcolor("primary")
        # Shutter icon sits on 'primary' background, so use 'on_primary' (usually white/black)
        color_on_primary = v.qcolor("on_primary")
        
        ico_menu = self._create_colored_icon("menu.svg", color_active)

        # WORKING METHOD SET A PIXMAP TO A QLabel AND SET SIZE 24 24
        # print(ico_menu)
        # self.menu_btn.setPixmap(ico_menu.pixmap(24, 24))

        self.ico_menu_open_themed = self._create_colored_icon("menu_open.svg", color_active)

        ico_dashboard_themed = self._create_colored_icon("dashboard.svg", color_active)
        ico_dashboard_filled_themed = self._create_colored_icon("dashboard_filled.svg", color_active)

        ico_calendar_themed = self._create_colored_icon("calendar.svg", color_active)
        ico_calendar_filled_themed = self._create_colored_icon("calendar_filled.svg", color_active)

        ico_settings_themed = self._create_colored_icon("settings.svg", color_active)
        ico_settings_filled_themed = self._create_colored_icon("settings_filled.svg", color_active)

        # EXAMPLES FROM SHUTTERBAR
        # 1. Light Button Icon
        # If checked, use active color; otherwise inactive color.
        # flash_color = color_active if self.light_btn.isChecked() else color_inactive
        # self.light_btn.setIcon(self._create_colored_icon("light.svg", flash_color))

        # # 2. Timer Icon (used in paintEvent)
        # # Always use the inactive color for the "off" state icon
        # self._timer_icon = self._create_colored_icon("timer.svg", color_inactive)
        
        # # 3. Shutter Icon
        # self.shutter_btn.setIcon(self._create_colored_icon("shutter.svg", color_on_primary))

        # Trigger a repaint to show changes
        self.update()

