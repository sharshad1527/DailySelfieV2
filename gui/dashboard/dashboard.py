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

from gui.dashboard.navigation_rail import NavigationRail

class DashboardWindow(DashboardShell):
    def __init__(self):
        super().__init__()
        vars = theme_vars()

        self._toggle_maximize()

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._content.setLayout(layout)

        self._navigation_rail = NavigationRail()
        layout.addWidget(self._navigation_rail)


# --- Smoke Test ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = DashboardWindow()
    win.show()
    app.exec()