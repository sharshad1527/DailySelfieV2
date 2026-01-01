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

ico_calendar = "today.svg"
ico_calendar_filled = "today_filled.svg"

ico_settings = "settings.svg"
ico_settings_filled = "settings_filled.svg"

class NavButton(QWidget):
    clicked = Signal() # Add a Click Signal
    
    def __init__(self, icon_normal, icon_checked, text: str = "", isbtnmenu: bool = False) -> None:
        super().__init__()
        self._hovered = False
        self._checked = False
        self._collapsed = False
        self._isbtnmenu = isbtnmenu
        self.page_id = None


        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, True) # Ensure background is painted
        self.setObjectName("NavButton") # Set class name for stylesheet selector
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

        self.icon_normal = icon_normal
        self.icon_checked = icon_checked

        nav_button_layout = QHBoxLayout()
        nav_button_layout.setContentsMargins(12, 12, 10, 10)
        nav_button_layout.setSpacing(8)

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
            # print("NavButton clicked")
            self.clicked.emit()
        

    # Emit the hovered signal when the navbutton is hovered
    def enterEvent(self, event):
        # print("NavButton entered")
        self._hovered = True
        self.updateStyle()

    # Emit the unhovered signal when the navbutton is unhovered
    def leaveEvent(self, event):
        # print("NavButton left")
        self._hovered = False
        self.updateStyle()   

    # Set the checked state of the navbutton
    def setChecked(self, value: bool):
        self._checked = value
        # print("Checked: ", value)
        self.updateStyle()

    # Get the checked state of the navbutton
    def isChecked(self) -> bool:
        return self._checked

    # Set the collapsed state of the navbutton
    def setCollapsed(self, value: bool):
        self._collapsed = value
        # print("Collapsed: ", value)
        self.updateStyle()
            
    # Get the collapsed state of the navbutton
    def isCollapsed(self) -> bool:
        return self._collapsed


    # Update the style of the navbutton
    def updateStyle(self):
        # Style For Menu Button
        if self._isbtnmenu  == True:
            self.setStyleSheet(f"""
                QWidget#NavButton {{ 
                    background-color: transparent; 
                    border-radius: 20px; 
                }}
                QLabel {{ 
                    color: transparent; 
                    background-color: transparent; 
                }}
            """)
        
        # Style For Button When Checked
        elif self._checked:
            # CHECKED STATE
            # Material 3 Rule: Active/Selected items use the Secondary Container color.
            # Color Role: Secondary Container (Background)
            # Content Color: On Secondary Container (Text/Icon)
            self.setStyleSheet(f"""
                QWidget#NavButton {{ 
                    background-color: {vars['primary']}; 
                    border-radius: 20px; 
                }}
                QLabel {{ 
                    color: {vars['on_primary']}; 
                    background-color: transparent; 
                }}
            """)
        
        # Style For Button When Hovered
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
        
        # Style For Button When Default
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

        # Menu Button OR NavButton
        if self._isbtnmenu == True:
            # COLLAPSED STATE For Menu Button
            if self._collapsed == False:
                self.txt_label.hide()
                self.icon_label.setPixmap(self.icon_checked.pixmap(24, 24))
            else:
                self.txt_label.hide()
                self.icon_label.setPixmap(self.icon_normal.pixmap(24, 24))
        else:
            # Checked Or Collapsed
            if self._checked == False:
                self.icon_label.setPixmap(self.icon_normal.pixmap(24, 24))
            else:
                self.icon_label.setPixmap(self.icon_checked.pixmap(24, 24))

            # COLLAPSED STATE For Button 
            if self._collapsed == True:
                self.txt_label.hide()
            else:
                self.txt_label.show()

        


class NavigationRail(QWidget):
    EXPANDED_WIDTH = 200 # 200px
    COLLAPSED_WIDTH = 60 # 60px

    pageSelected = Signal(int)

    def __init__(self):
        super().__init__()
        
        vars = theme_vars()
        self._is_collapsed = False # Defaultly Collapsed
        self._buttons = [] # Button List
        self._menu_button = None # menu button
    

        vlayout = QVBoxLayout(self)
        vlayout.setContentsMargins(0, 0, 10, 10)
        vlayout.setSpacing(8)

        self._apply_icon_theme()

        # Menu Button
        btn_menu = NavButton(self.ico_menu, self.ico_menu_open, "", True)
        # self._buttons.append(btn_menu) # Old
        self._menu_button = btn_menu # New
        btn_menu.clicked.connect(self.toggleCollapsedState)
        vlayout.addWidget(btn_menu)

        # Dashboard Button
        btn_dashboard = NavButton(self.ico_dashboard, self.ico_dashboard_filled, "Dashboard")
        btn_dashboard.page_id = 0
        self._buttons.append(btn_dashboard)
        btn_dashboard.clicked.connect(lambda: self.toggleCheckedState(btn_dashboard))
        vlayout.addWidget(btn_dashboard)

        # Calendar Button
        btn_calendar = NavButton(self.ico_calendar, self.ico_calendar_filled, "Calendar")
        btn_calendar.page_id = 1
        self._buttons.append(btn_calendar)
        btn_calendar.clicked.connect(lambda: self.toggleCheckedState(btn_calendar))
        vlayout.addWidget(btn_calendar)

        vlayout.addStretch()

        # Settings Button
        btn_settings = NavButton(self.ico_settings, self.ico_settings_filled, "Settings")
        btn_settings.page_id = 2
        self._buttons.append(btn_settings)
        btn_settings.clicked.connect(lambda: self.toggleCheckedState(btn_settings))
        vlayout.addWidget(btn_settings)

        btn_dashboard.setChecked(True) # Defaultly Selected

        self.applyCollapsedState(self._is_collapsed)
        

    # Toggle Collapsed State        
    def toggleCollapsedState(self):
        self._is_collapsed = not self._is_collapsed
        
        self.applyCollapsedState(self._is_collapsed)
    
    # Toggle Checked State
    def toggleCheckedState(self, toggle):
        for btn in self._buttons:
            if btn == toggle:
                btn.setChecked(True)
                self.pageSelected.emit(btn.page_id)
            else:
                btn.setChecked(False)

    # Apply Collapsed State
    def applyCollapsedState(self, collapsed):
        if collapsed:
            self.setFixedWidth(self.COLLAPSED_WIDTH)
            for btn in self._buttons:
                btn.setCollapsed(True)
        else:
            self.setFixedWidth(self.EXPANDED_WIDTH)
            for btn in self._buttons:
                btn.setCollapsed(False)
            
    # --------------------------------------------------
    # Theme helpers
    # --------------------------------------------------

    # Create Colored Icon
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

    # Apply Icon Theme
    def _apply_icon_theme(self):

        """
        Regenerates all icons using the current theme colors.
        """
        v = theme_vars()

        # Colors
        primary = v.qcolor("primary")
        on_primary = v.qcolor("on_primary")
        primary_container = v.qcolor("primary_container")
        on_primary_container = v.qcolor("on_primary_container")
        
        # Define colors
        # on_secondary_container = v.qcolor("on_secondary_container")
        # on_surface = v.qcolor("on_surface")
        # on_surface_variant = v.qcolor("on_surface_variant")
        
        # WORKING METHOD SET A PIXMAP TO A QLabel AND SET SIZE 24 24
        # print(ico_menu)
        # self.menu_btn.setPixmap(ico_menu.pixmap(24, 24))
        self.ico_menu = self._create_colored_icon(ico_menu, primary)
        
        self.ico_menu_open = self._create_colored_icon(ico_menu_open, primary)

        self.ico_dashboard = self._create_colored_icon(ico_dashboard, primary)
        
        self.ico_dashboard_filled = self._create_colored_icon(ico_dashboard_filled, on_primary)

        self.ico_calendar = self._create_colored_icon(ico_calendar, primary)

        self.ico_calendar_filled = self._create_colored_icon(ico_calendar_filled, on_primary)

        self.ico_settings = self._create_colored_icon(ico_settings, primary)
        
        self.ico_settings_filled = self._create_colored_icon(ico_settings_filled, on_primary)

        self.update()

