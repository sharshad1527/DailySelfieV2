# gui/dashboard/pages/calendar.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class CalendarPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("CalendarPage")
        self.setStyleSheet("""
            QWidget#CalendarPage {
                background-color: #fff;
            }
        """)

        layout = QVBoxLayout()
        self.setLayout(layout)
        self.label = QLabel("Calendar")
        layout.addWidget(self.label)