# gui/dashboard/navigation_rail.py
from enum import Enum
from PySide6.QtWidgets import QLabel
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QIcon, QPixmap, QPainter, QBrush, QColor, QPainterPath
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy
    )

from gui.theme.theme_vars import theme_vars
from gui.widgets.pixmap_utils import active_dpr, recolored_icon
from core.paths import get_app_paths

paths = get_app_paths("DailySelfie", ensure=False)
# ICONS_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"
ICONS_DIR = paths.project_root / "gui" /"assets" / "icons"
# print(ICONS_DIR)

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
        
        # Animation fill progress (0.0 to 1.0)
        self._fill_progress = 0.0
        self._fill_color = QColor(0, 0, 0, 0)  # Will be set based on state
        
        # Fill animation
        self._fill_anim = QPropertyAnimation(self, b"fillProgress")
        self._fill_anim.setDuration(200)  # 200ms for smooth feel
        self._fill_anim.setEasingCurve(QEasingCurve.OutCubic)


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
    def setChecked(self, value: bool, animate: bool = True):
        was_checked = self._checked
        self._checked = value
        
        # Trigger fill animation when becoming checked
        if value and not was_checked:
            if animate:
                self._animateFillIn()
            else:
                # Skip animation, set to full fill immediately
                self._updateFillColor()
                self._fill_progress = 1.0
        elif not value and was_checked:
            self._animateFillOut()
        
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

    # --------------------------------------------------
    # Fill Animation Properties & Methods
    # --------------------------------------------------
    
    def getFillProgress(self) -> float:
        return self._fill_progress
    
    def setFillProgress(self, value: float):
        self._fill_progress = value
        self.update()  # Trigger repaint
    
    fillProgress = Property(float, getFillProgress, setFillProgress)
    
    def _animateFillIn(self):
        """Animate fill expanding from center outward"""
        self._fill_anim.stop()
        self._updateFillColor()
        self._fill_anim.setStartValue(0.5)
        self._fill_anim.setEndValue(1.0)
        self._fill_anim.start()
    
    def _animateFillOut(self):
        """Animate fill shrinking to center (instant for now)"""
        self._fill_progress = 0.0
        self.update()
    
    def _updateFillColor(self):
        """Set fill color based on current role"""
        v = theme_vars()
        if self._role == ActionRole.ACTION:
            self._fill_color = v.qcolor("tertiary_container")
        else:
            self._fill_color = v.qcolor("secondary_container")
    
    def paintEvent(self, event):
        """Custom paint to draw animated horizontal fill"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Only draw animated fill if progress > 0 and checked
        if self._fill_progress > 0 and self._checked:
            rect = self.rect()
            border_radius = 16 if self._role == ActionRole.ACTION else 24
            
            # Calculate fill width from center
            center_x = rect.width() / 2
            fill_half_width = (rect.width() / 2) * self._fill_progress
            
            # Create clipping path for rounded rect
            path = QPainterPath()
            path.addRoundedRect(float(rect.x()), float(rect.y()), 
                                float(rect.width()), float(rect.height()), 
                                border_radius, border_radius)
            painter.setClipPath(path)
            
            # Draw fill from center expanding outward
            fill_left = center_x - fill_half_width
            fill_right = center_x + fill_half_width
            fill_rect = rect.adjusted(int(fill_left), 0, int(fill_right - rect.width()), 0)
            
            painter.setBrush(QBrush(self._fill_color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(fill_rect, border_radius, border_radius)
        
        painter.end()
        
        # Let base class handle children
        super().paintEvent(event)


    def set_icons(self, icon_normal, icon_checked, icon_hovered=None):
        """Rebind themed icons (QIcons are baked per-theme; a plain
        updateStyle() cannot pick up regenerated ones)."""
        self.icon_normal = icon_normal
        self.icon_checked = icon_checked
        self.icon_hovered = icon_hovered if icon_hovered else icon_normal

    # Update the style of the navbutton
    def updateStyle(self):
        # Material 3 Navigation Rail Color Guidelines:
        # - Default: Container transparent, Icon/Text uses on_surface_variant
        # - Hovered: Container uses surface_container_high (state layer), Icon/Text uses on_surface
        # - Selected: Container uses secondary_container, Icon/Text uses on_secondary_container
        # - FAB/Action: Container uses primary_container, Icon uses on_primary_container

        vars = theme_vars()

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

        # CHECKED/SELECTED STATE - M3: transparent bg (painted by paintEvent), on_secondary_container for icon/text
        styleChecked = f"""
                QWidget#NavButton {{ 
                    background-color: transparent; 
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

        # ACTION (FAB) CHECKED - M3: transparent bg (painted by paintEvent), on_tertiary_container for text
        styleActionChecked = f"""
                QWidget#NavButton {{ 
                    background-color: transparent; 
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
        
        self._is_collapsed = True # Defaultly Collapsed
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

        btn_dashboard.setChecked(True, animate=False) # Defaultly Selected

        self.applyCollapsedState(self._is_collapsed)

        controller = getattr(theme_vars(), "_controller", None)
        if controller is not None:
            controller.themeChanged.connect(self._on_theme_changed)

    def _on_theme_changed(self):
        self._apply_icon_theme()
        # NavButtons hold references to the QIcons they were built with, so
        # regenerated icons must be pushed into each button before restyling.
        for btn in self._buttons:
            icons = self._icon_set_for(btn)
            if icons is None:
                continue
            try:
                btn.set_icons(*icons)
                # Checked buttons paint their fill from _fill_color; refresh it
                # so the indicator matches the new theme without restarting the
                # animation.
                btn._updateFillColor()
                if btn._fill_progress > 0:
                    btn.update()
                btn.updateStyle()
            except RuntimeError:
                pass

    def _icon_set_for(self, btn):
        """Current-theme icon triple (normal, checked, hovered) for a button."""
        if getattr(btn, "_role", None) == ActionRole.MENU:
            return (self.ico_menu, self.ico_menu_open, None)
        return {
            0: (self.ico_selfie, self.ico_selfie_filled, self.ico_selfie_hovered),
            1: (self.ico_dashboard, self.ico_dashboard_filled, None),
            2: (self.ico_calendar, self.ico_calendar_filled, None),
            3: (self.ico_settings, self.ico_settings_filled, None),
        }.get(getattr(btn, "page_id", None))

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
        Loads an SVG and repaints it with the given QColor (HiDPI-aware).
        This fixes the issue where icons ignore CSS color properties.
        """
        return recolored_icon(ICONS_DIR / icon_name, qcolor, active_dpr(self))

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

