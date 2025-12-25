# gui/startup/window_con.py
from PySide6.QtCore import Qt, QObject, QEvent
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from gui.theme.theme_vars import theme_vars


class DragFilter(QObject):
    """Allows dragging the frameless window."""
    def __init__(self, window):
        super().__init__()
        self._window = window
        self._drag_offset = None

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._drag_offset = event.position().toPoint()
            return False

        elif event.type() == QEvent.MouseMove and self._drag_offset and event.buttons() & Qt.LeftButton:
            global_pos = obj.mapToGlobal(event.position().toPoint())
            self._window.move(global_pos - self._drag_offset)
            return False

        elif event.type() == QEvent.MouseButtonRelease:
            self._drag_offset = None

        return False


class BaseFramelessWindow(QMainWindow):
    """
    Frameless Material-styled base window.
    """
    def __init__(self, width=900, height=520):
        super().__init__()

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(width, height)

        vars = theme_vars()

        # Root
        self._root = QWidget(self)
        self._root.setObjectName("root")
        self.setCentralWidget(self._root)

        self._root.setStyleSheet(f"""
            QWidget#root {{
                background-color: {vars["background"]};
                border-radius: 12px;
                border: 2px solid {vars["outline_variant"]};
            }}
        """)

        # Layout
        self._main_layout = QVBoxLayout(self._root)
        self._main_layout.setContentsMargins(12, 8, 12, 12)
        self._main_layout.setSpacing(0)

        # Top bar
        self._top_bar = QWidget(self._root)
        self._top_bar.setFixedHeight(42)
        self._top_bar.setStyleSheet("background: transparent;")

        self._drag_filter = DragFilter(self)
        self._top_bar.installEventFilter(self._drag_filter)

        self._init_top_bar()
        self._main_layout.addWidget(self._top_bar)

        # Content placeholder
        self._content = QWidget(self._root)
        self._content.setStyleSheet("background: transparent;")
        self._main_layout.addWidget(self._content, 1)

    def _init_top_bar(self):
        vars = theme_vars()

        layout = QHBoxLayout(self._top_bar)
        layout.setContentsMargins(22, 0, 12, 0)

        title = QLabel("Daily Selfie")
        title.setStyleSheet(f"""
            QLabel {{
                color: {vars["on_surface"]};
                font-size: 14px;
                font-weight: 600;
            }}
        """)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(32, 32)
        close_btn.clicked.connect(self.close)

        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 2px solid {vars["outline_variant"]};
                border-radius: 10px;
                color: {vars["on_surface_variant"]};
                font-weight: bold;
                font-size: 14px;
            }}
            QPushButton:hover {{
                border: 2px solid {vars["error"]};
                color: {vars["error"]};
            }}
            QPushButton:pressed {{
                background-color: {vars["error_container"]};
                color: {vars["inverse_on_surface"]};
            }}
        """)

        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(close_btn)
