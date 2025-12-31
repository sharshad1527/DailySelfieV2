# gui/dashboard/pages/dashboard.py
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout


class DashboardPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("DashboardPage")
        self.setStyleSheet("""
            QWidget#DashboardPage {
                background-color: #fff;
            }
        """)
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.label = QLabel("Dashboard")
        layout.addWidget(self.label)
