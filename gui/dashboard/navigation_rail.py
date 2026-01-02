# gui/dashboard/navigation_rail.py
from enum import Enum
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

ico_selfie = "selfie.svg"
ico_selfie_filled = "selfie_filled.svg"

ico_dashboard = "dashboard.svg"
ico_dashboard_filled = "dashboard_filled.svg"

ico_calendar = "today.svg"
ico_calendar_filled = "today_filled.svg"

ico_settings = "settings.svg"
ico_settings_filled = "settings_filled.svg"


class ActionRole(Enum):
    ACTION = "action"
    DEFAULT = "default"
    MENU = "menu"


class NavButton(QWidget):
    clicked = Signal() # Add a Click Signal
    
    def __init__(self, icon_normal, icon_checked, text: str = "", role: ActionRole = ActionRole.DEFAULT, icon_hovered=None) -> None:
        super().__init__()
        self._hovered = False
        self._checked = False
        self._collapsed = False
        self._role = role
        self.page_id = None


        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, True) # Ensure background is painted
        self.setObjectName("NavButton") # Set class name for stylesheet selector
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(48)  # 24px icon + 12px padding top/bottom

    
        # Icons (normal, checked, and optional hovered for action buttons)
        self.icon_normal = icon_normal
        self.icon_checked = icon_checked
        self.icon_hovered = icon_hovered if icon_hovered else icon_normal

        # Root Layout
        nav_button_layout = QHBoxLayout()
        nav_button_layout.setContentsMargins(16, 12, 16, 12)
        nav_button_layout.setSpacing(8)

        # Text Label
        self.txt_label = QLabel()
        self.txt_label.setText(text)

        # Icon Container
        self.icon_container = QWidget()
        icon_layout = QHBoxLayout(self.icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignCenter)

        self.icon_label = QLabel()
        self.icon_label.setPixmap(self.icon_normal.pixmap(24, 24))

        icon_layout.addWidget(self.icon_label)

        nav_button_layout.addWidget(self.icon_container)


        nav_button_layout.addWidget(self.txt_label)
        
        # ACTION buttons expand full width, DEFAULT buttons stay compact
        if self._role == ActionRole.ACTION:
            nav_button_layout.addStretch()
        
        self.setLayout(nav_button_layout)
        
        # Set size policy: DEFAULT/MENU = compact, ACTION = expand
        if self._role == ActionRole.DEFAULT or self._role == ActionRole.MENU:
            self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
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

    def _apply_layout_mode(self):
        layout = self.layout()

        if self._collapsed:
            layout.setAlignment(self.icon_container, Qt.AlignCenter)
        else:
            layout.setAlignment(self.icon_container, Qt.AlignLeft)


    # Update the style of the navbutton
    def updateStyle(self):
        # Material 3 Navigation Rail Color Guidelines:
        # - Default: Container transparent, Icon/Text uses on_surface_variant
        # - Hovered: Container uses surface_container_high (state layer), Icon/Text uses on_surface
        # - Selected: Container uses secondary_container, Icon/Text uses on_secondary_container
        # - FAB/Action: Container uses primary_container, Icon uses on_primary_container

        styleMenu = f"""
                QWidget#NavButton {{ 
                    background-color: transparent; 
                    border-radius: 24px; 
                }}
                QLabel {{ 
                    color: transparent; 
                    background-color: transparent; 
                }}
            """

        # DEFAULT STATE - M3: transparent container, on_surface_variant for icon/text
        styleDefault = f"""
                QWidget#NavButton {{ 
                    background-color: transparent; 
                    border-radius: 24px; 
                }}
                QLabel {{ 
                    color: {vars['on_surface_variant']}; 
                    font-size: 15px;
                    font-weight: 500;
                    background-color: transparent; 
                }}
            """

        # HOVERED STATE - M3: surface_container_high for state layer, on_surface for icon/text
        styleHovered = f"""
                QWidget#NavButton {{ 
                    background-color: {vars['surface_container_high']}; 
                    border-radius: 24px; 
                }}
                QLabel {{ 
                    color: {vars['on_surface']}; 
                    font-size: 15px;
                    font-weight: 500;
                    background-color: transparent; 
                }}
            """

        # CHECKED/SELECTED STATE - M3: secondary_container, on_secondary_container for icon/text
        styleChecked = f"""
                QWidget#NavButton {{ 
                    background-color: {vars['secondary_container']}; 
                    border-radius: 24px; 
                }}
                QLabel {{ 
                    color: {vars['on_secondary_container']};
                    font-size: 15px;
                    font-weight: 500;
                    background-color: transparent; 
                }}
            """

        # ACTION (FAB) DEFAULT - M3: primary_container, on_primary_container
        styleActionDefault = f"""
                QWidget#NavButton {{ 
                    background-color: {vars['primary_container']}; 
                    border-radius: 16px; 
                }}
                QLabel {{ 
                    color: {vars['on_primary_container']}; 
                    background-color: transparent; 
                }}
            """

        # ACTION (FAB) HOVERED - M3: Slightly elevated/highlighted primary_container
        styleActionHovered = f"""
                QWidget#NavButton {{ 
                    background-color: {vars['primary']}; 
                    border-radius: 16px; 
                }}
                QLabel {{ 
                    color: {vars['on_primary']}; 
                    background-color: transparent; 
                }}
            """

        # ACTION (FAB) CHECKED - M3: tertiary_container for emphasis
        styleActionChecked = f"""
                QWidget#NavButton {{ 
                    background-color: {vars['tertiary_container']}; 
                    border-radius: 16px; 
                }}
                QLabel {{ 
                    color: {vars['on_tertiary_container']}; 
                    background-color: transparent; 
                }}
            """

        # Style For Menu Button
        if self._role == ActionRole.MENU:
            self.setStyleSheet(styleMenu)
        
        # Style For Button When Checked
        elif self._checked:
            if self._role == ActionRole.DEFAULT:
                self.setStyleSheet(styleChecked)
            elif self._role == ActionRole.ACTION:
                self.setStyleSheet(styleActionChecked)
                
        # Style For Button When Hovered
        elif self._hovered:
            if self._role == ActionRole.DEFAULT:
                self.setStyleSheet(styleHovered)
            elif self._role == ActionRole.ACTION:
                self.setStyleSheet(styleActionHovered)
        
        # Style For Button When Default
        else:
            if self._role == ActionRole.DEFAULT:
                self.setStyleSheet(styleDefault)
            elif self._role == ActionRole.ACTION:
                self.setStyleSheet(styleActionDefault)

        # Menu Button OR NavButton
        if self._role == ActionRole.MENU:
            # COLLAPSED STATE For Menu Button
            if self._collapsed == False:
                self.txt_label.hide()
                self.icon_label.setPixmap(self.icon_checked.pixmap(24, 24))
            else:
                self.txt_label.hide()
                self.icon_label.setPixmap(self.icon_normal.pixmap(24, 24))
        else:
            # Handle icon states for non-menu buttons
            if self._role == ActionRole.ACTION and self._hovered and self._checked == False:
                # Action button hovered: use hovered icon
                self.icon_label.setPixmap(self.icon_hovered.pixmap(24, 24))
            elif self._checked:
                # Checked state: use filled icon
                self.icon_label.setPixmap(self.icon_checked.pixmap(24, 24))
            else:
                # Default state: use normal icon
                self.icon_label.setPixmap(self.icon_normal.pixmap(24, 24))

            # COLLAPSED STATE For Button 
            if self._collapsed == True:
                self.txt_label.hide()
                self._apply_layout_mode()
            else:
                self.txt_label.show()
                self._apply_layout_mode()
        


class NavigationRail(QWidget):
    EXPANDED_WIDTH = 200 # 200px
    COLLAPSED_WIDTH = 72 # 60px

    pageSelected = Signal(int)

    def __init__(self):
        super().__init__()
        
        vars = theme_vars()
        self._is_collapsed = False # Defaultly Collapsed
        self._buttons = [] # Button List
    

        vlayout = QVBoxLayout(self)
        vlayout.setContentsMargins(8, 12, 8, 12)
        vlayout.setSpacing(8)

        self._apply_icon_theme()

        # Menu Button
        btn_menu = NavButton(self.ico_menu, self.ico_menu_open, "", ActionRole.MENU)
        self._buttons.append(btn_menu) # Old
        # self._menu_button = btn_menu # New
        btn_menu.clicked.connect(self.toggleCollapsedState)
        vlayout.addWidget(btn_menu)

        btn_selfie = NavButton(self.ico_selfie, self.ico_selfie_filled, "Selfie", ActionRole.ACTION, self.ico_selfie_hovered)
        # btn_selfie.setContentsMargins(0, 10, 0, 10)
        btn_selfie.page_id = 0
        self._buttons.append(btn_selfie)
        btn_selfie.clicked.connect(lambda: self.toggleCheckedState(btn_selfie))
        vlayout.addWidget(btn_selfie)
        vlayout.addSpacing(20)
        # Dashboard Button
        btn_dashboard = NavButton(self.ico_dashboard, self.ico_dashboard_filled, "Dashboard")
        btn_dashboard.page_id = 1
        self._buttons.append(btn_dashboard)
        btn_dashboard.clicked.connect(lambda: self.toggleCheckedState(btn_dashboard))
        vlayout.addWidget(btn_dashboard)

        # Calendar Button
        btn_calendar = NavButton(self.ico_calendar, self.ico_calendar_filled, "Calendar")
        btn_calendar.page_id = 2
        self._buttons.append(btn_calendar)
        btn_calendar.clicked.connect(lambda: self.toggleCheckedState(btn_calendar))
        vlayout.addWidget(btn_calendar)

        vlayout.addStretch()

        # Settings Button
        btn_settings = NavButton(self.ico_settings, self.ico_settings_filled, "Settings")
        btn_settings.page_id = 3
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
        
        Material 3 Navigation Rail Icon Guidelines:
        - Unselected icons: on_surface_variant (medium emphasis)
        - Selected icons: on_secondary_container (matches active indicator)
        - FAB/Action icons: on_primary_container (normal), on_tertiary_container (selected)
        - Menu icons: on_surface (high emphasis for utility)
        """
        v = theme_vars()

        # Material 3 icon colors
        on_surface = v.qcolor("on_surface")  # Menu icons
        on_surface_variant = v.qcolor("on_surface_variant")  # Unselected nav icons
        on_secondary_container = v.qcolor("on_secondary_container")  # Selected nav icons
        on_primary_container = v.qcolor("on_primary_container")  # FAB icons
        on_tertiary_container = v.qcolor("on_tertiary_container")  # FAB selected icons

        # Menu icons - use on_surface for utility icon
        self.ico_menu = self._create_colored_icon(ico_menu, on_surface)
        self.ico_menu_open = self._create_colored_icon(ico_menu_open, on_surface)

        # FAB/Action icons - M3: on_primary_container (normal), on_primary (hover), on_tertiary_container (selected)
        on_primary = v.qcolor("on_primary")  # FAB hover icon
        self.ico_selfie = self._create_colored_icon(ico_selfie, on_primary_container)
        self.ico_selfie_hovered = self._create_colored_icon(ico_selfie, on_primary)  # Hover state
        self.ico_selfie_filled = self._create_colored_icon(ico_selfie_filled, on_tertiary_container)

        # Navigation icons - M3: on_surface_variant (normal), on_secondary_container (selected)
        self.ico_dashboard = self._create_colored_icon(ico_dashboard, on_surface_variant)
        self.ico_dashboard_filled = self._create_colored_icon(ico_dashboard_filled, on_secondary_container)

        self.ico_calendar = self._create_colored_icon(ico_calendar, on_surface_variant)
        self.ico_calendar_filled = self._create_colored_icon(ico_calendar_filled, on_secondary_container)

        self.ico_settings = self._create_colored_icon(ico_settings, on_surface_variant)
        self.ico_settings_filled = self._create_colored_icon(ico_settings_filled, on_secondary_container)

        self.update()

