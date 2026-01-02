# gui/dashboard/dashboard.py
import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QButtonGroup, 
    QStackedWidget, QLabel, QApplication, QHBoxLayout
)
from gui.theme.theme_vars import theme_vars 

try:
    from gui.dashboard.window_con import DashboardShell
except:
    from window_con import DashboardShell

from gui.dashboard.pages.selfie import SelfiePage
from gui.dashboard.pages.dashboard import DashboardPage
from gui.dashboard.pages.calendar import CalendarPage
from gui.dashboard.pages.settings import SettingsPage
from gui.dashboard.navigation_rail import NavigationRail

class DashboardWindow(DashboardShell):
    def __init__(self):
        super().__init__()
        vars = theme_vars()
        self._pages = QStackedWidget()

        self._toggle_maximize()

        layout = QHBoxLayout()
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(0)

        self._content.setLayout(layout)

        self._navigation_rail = NavigationRail()
        layout.addWidget(self._navigation_rail)
        
        self._pages.insertWidget(1, SelfiePage())
        self._pages.insertWidget(2, DashboardPage())
        self._pages.insertWidget(3, CalendarPage())
        self._pages.insertWidget(4, SettingsPage())

        layout.addWidget(self._pages, 1)
        self._pages.setCurrentIndex(1)
        self._navigation_rail.pageSelected.connect(self._onPageSelected)
        layout.addStretch()

    def _onPageSelected(self, index: int):
        self._pages.setCurrentIndex(index)
        



# --- Smoke Test ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = DashboardWindow()
    win.show()
    app.exec()