# gui/dashboard/navigation_rail.py
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QButtonGroup, QToolButton,
    QSizePolicy
    )
from gui.theme.theme_vars import theme_vars

menu_icon = QIcon("gui/assets/icons/menu.svg")
menu_open = QIcon("gui/assets/icons/menu_open.svg")

dashboard_icon = QIcon("gui/assets/icons/dashboard.svg")
dashboard_filled = QIcon("gui/assets/icons/dashboard_filled.svg")

today_icon = QIcon("gui/assets/icons/today.svg")
today_filled = QIcon("gui/assets/icons/today_filled.svg")

settings_icon = QIcon("gui/assets/icons/settings.svg")
settings_filled = QIcon("gui/assets/icons/settings_filled.svg")

class NavButton(QWidget):
    def __init__(self, icon, text):
        super().__init__()
        self.icon = icon
        self.text = text
        self.initUI()

    def initUI(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.icon)
        layout.addWidget(self.text)

class NavigationRail(QWidget):

    EXPANDED_WIDTH = 200
    COLLAPSED_WIDTH = 60

    def __init__(self):
        super().__init__()
        
        vars = theme_vars()
        self._is_collapsed = True

        vlayout = QVBoxLayout(self)
        vlayout.setContentsMargins(0, 0, 0, 0)
        vlayout.setSpacing(0)

        # ----- Button -----
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        # Menu Button
        self.btn_menu = QToolButton(self)
        self.btn_menu.setIcon(menu_icon)
        self.btn_menu.clicked.connect(self.toggleCollapsedState)
        self.btn_menu.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_menu.setStyleSheet(btn_style)


        # Dashboard Button
        self.btn_dashboard = QToolButton(self)
        self.btn_dashboard.setCheckable(True)
        self.btn_dashboard.setIcon(dashboard_icon)
        self.btn_dashboard.setText("Dashboard")        
        self._group.addButton(self.btn_dashboard)
        self._group.setId(self.btn_dashboard, 0)
        self.btn_dashboard.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_dashboard.setStyleSheet(btn_style)

        

        # Calendar Button
        self.btn_calendar = QToolButton(self)
        self.btn_calendar.setCheckable(True)
        self.btn_calendar.setIcon(today_icon)
        self.btn_calendar.setText("Calendar")
        self._group.addButton(self.btn_calendar)
        self._group.setId(self.btn_calendar, 1)
        self.btn_calendar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_calendar.setStyleSheet(btn_style)

        # Settings Button
        self.btn_settings = QToolButton(self)
        self.btn_settings.setCheckable(True)
        self.btn_settings.setIcon(settings_icon)
        self.btn_settings.setText("Settings")
        self._group.addButton(self.btn_settings)
        self._group.setId(self.btn_settings, 2)
        self.btn_settings.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_settings.setStyleSheet(btn_style)

        # Dashboard is checked by default
        self.btn_dashboard.setChecked(True)

        vlayout.addWidget(self.btn_menu)
        vlayout.addWidget(self.btn_dashboard)
        vlayout.addWidget(self.btn_calendar)
        vlayout.addStretch()
        vlayout.addWidget(self.btn_settings)

        
        self.applyCollapsedState(self._is_collapsed)

        
    def toggleCollapsedState(self):
        self._is_collapsed = not self._is_collapsed
        self.applyCollapsedState(self._is_collapsed)


    def applyCollapsedState(self, collapsed):
        if collapsed:
            self.setFixedWidth(self.COLLAPSED_WIDTH)
            for self.btn in (self.btn_dashboard, self.btn_calendar, self.btn_settings):
                self.btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
            self.btn_menu.setIcon(menu_icon)
            
        else:
            self.setFixedWidth(self.EXPANDED_WIDTH)
            for self.btn in (self.btn_dashboard, self.btn_calendar, self.btn_settings):
                self.btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self.btn_menu.setIcon(menu_open)
            
            