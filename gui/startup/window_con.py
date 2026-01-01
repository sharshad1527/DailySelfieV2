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

        self._root.setObjectName("root")
        self.setCentralWidget(self._root)
        
        # Initial style application handled by child class or explicit call, 
        # but let's do it here to be safe if used directly.
        self.update_window_theme()

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
        layout = QHBoxLayout(self._top_bar)
        layout.setContentsMargins(22, 0, 12, 0)

        self._title_lbl = QLabel("Daily Selfie")
        
        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(32, 32)
        self._close_btn.clicked.connect(self.close)

        layout.addWidget(self._title_lbl)
        layout.addStretch()
        layout.addWidget(self._close_btn)
        
        # Apply styles
        self.update_window_theme()

    def update_window_theme(self):
        """Re-applies theme variables to window elements."""
        vars = theme_vars()

        # 1. Root Container (Background & Border)
        self._root.setStyleSheet(f"""
            QWidget#root {{
                background-color: {vars["background"]};
                border-radius: 12px;
                border: 2px solid {vars["outline_variant"]};
            }}
        """)

        # 2. Title
        if hasattr(self, "_title_lbl"):
            self._title_lbl.setStyleSheet(f"""
                QLabel {{
                    color: {vars["on_surface"]};
                    font-size: 14px;
                    font-weight: 600;
                }}
            """)

        # 3. Close Button
        if hasattr(self, "_close_btn"):
            self._close_btn.setStyleSheet(f"""
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
