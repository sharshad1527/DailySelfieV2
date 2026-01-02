# gui/dashboard/pages/dashboard.py
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout


class SelfiePage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("SelfiePage")
        self.setStyleSheet("""
            QWidget#SelfiePage {
                background-color: #fff;
            }
        """)
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.label = QLabel("Selfie")
        layout.addWidget(self.label)
