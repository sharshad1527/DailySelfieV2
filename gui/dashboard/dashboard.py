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

btn_style = """
            QPushButton {
                background-color: transparent;
                border: 2px solid #333333; 
                border-radius: 10px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                border: 2px solid #8B5CF6;
            }
            QPushButton:pressed {
                background-color: #444444;
            }
        """

btn_close_style = """
            QPushButton {
                background-color: transparent;
                border: 2px solid #333333;
                border-radius:10px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                border: 2px solid #E74C3C;
            }
            QPushButton:pressed {
                background-color: #A93226;
            }
        """


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