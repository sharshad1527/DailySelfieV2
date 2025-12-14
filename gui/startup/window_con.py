from PySide6.QtCore import Qt, QObject, QEvent, QPoint
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
)


# ---------------- Drag Filter --------------------
class DragFilter(QObject):
    def __init__(self, window):
        super().__init__()
        self._window = window
        self._drag_offset = None

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                # position() is local → convert properly
                self._drag_offset = event.position().toPoint()
                return False  # IMPORTANT: allow button clicks

        elif event.type() == QEvent.MouseMove:
            if self._drag_offset and event.buttons() & Qt.LeftButton:
                global_pos = obj.mapToGlobal(event.position().toPoint())
                self._window.move(global_pos - self._drag_offset)
                return False

        elif event.type() == QEvent.MouseButtonRelease:
            self._drag_offset = None
            return False

        return False


# ---------------- Frameless Window ----------------
class BaseFramelessWindow(QMainWindow):
    def __init__(self, width=900, height=520):
        super().__init__()

        # Window flags
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(width, height)

        # Root widget
        self._root = QWidget(self)
        self._root.setObjectName("root")
        self.setCentralWidget(self._root)

        self._root.setStyleSheet("""
            QWidget#root {
                background-color: #121212;
                border-radius: 12px;
            }
        """)

        # Main layout
        self._main_layout = QVBoxLayout(self._root)
        self._main_layout.setContentsMargins(12, 8, 12, 12)
        self._main_layout.setSpacing(0)

        # ---------------- Top Bar ----------------
        self._top_bar = QWidget(self._root)
        self._top_bar.setFixedHeight(42)

        self._top_bar.setStyleSheet("background: transparent;")

        # Install drag filter (THIS is the key)
        self._drag_filter = DragFilter(self)
        self._top_bar.installEventFilter(self._drag_filter)

        self._init_top_bar()
        self._main_layout.addWidget(self._top_bar)

        # Content placeholder
        self._content = QWidget(self._root)
        self._content.setStyleSheet("background: transparent;")
        self._main_layout.addWidget(self._content, 1)

    def _init_top_bar(self):
        layout = QHBoxLayout(self._top_bar)
        layout.setContentsMargins(22, 0, 12, 0)

        title = QLabel("Daily Selfie")
        title.setStyleSheet("""
            QLabel {
                color: #E0E0E0;
                font-size: 14px;
                font-weight: 600;
            }
        """)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(32, 32)
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #B0B0B0;
                border: none;
            }
            QPushButton:hover {
                background-color: #2A2A2A;
                border-radius: 6px;
                color: white;
            }
        """)

        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(close_btn)
