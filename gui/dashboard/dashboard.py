# gui/dashboard/dashboard.py
import sys
from PySide6.QtCore import Qt, QSize, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QButtonGroup, 
    QStackedWidget, QLabel, QApplication, QHBoxLayout
)
try:
    from gui.dashboard.window_con import DashboardShell
except:
    from window_con import DashboardShell


class DashboardWindow(DashboardShell):
    def __init__(self):
        super().__init__()

        self._toggle_maximize()

        

    

# --- Smoke Test ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = DashboardWindow()
    win.show()
    app.exec()