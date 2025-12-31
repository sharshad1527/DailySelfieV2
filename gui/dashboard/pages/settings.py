# gui/dashboard/pages/settings.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class SettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("SettingsPage")
        self.setStyleSheet("""
            QWidget#SettingsPage {
                background-color: #fff;
            }
        """)

        layout = QVBoxLayout()
        self.setLayout(layout)
        self.label = QLabel("Settings")
        layout.addWidget(self.label)

