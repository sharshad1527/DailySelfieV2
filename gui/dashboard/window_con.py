# gui/dashboard/window_con.py
from PySide6.QtCore import Qt, QPoint, QSize
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QApplication, QLabel
)
from PySide6.QtGui import QCursor, QColor

from gui.theme.theme_vars import theme_vars 

class ResizeGrip(QWidget):
    """
    Invisible overlay widget to handle window resizing on edges/corners.
    """
    def __init__(self, parent, edge):
        super().__init__(parent)
        self.edge = edge
        self.setMouseTracking(True) 
        self.setStyleSheet("background: transparent;") 
        self.drag_pos = None

        # Changing cursor icon based on which edge this grip represents
        if edge in (Qt.LeftEdge, Qt.RightEdge):
            self.setCursor(Qt.SizeHorCursor)
        elif edge in (Qt.TopEdge, Qt.BottomEdge):
            self.setCursor(Qt.SizeVerCursor)
        elif edge in (Qt.TopLeftCorner, Qt.BottomRightCorner):
            self.setCursor(Qt.SizeFDiagCursor)
        elif edge in (Qt.TopRightCorner, Qt.BottomLeftCorner):
            self.setCursor(Qt.SizeBDiagCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            win = self.window()
            
            # Map Qt.Corner values to Qt.Edge flags for startSystemResize
            edges = self.edge
            if self.edge == Qt.TopLeftCorner:
                edges = Qt.TopEdge | Qt.LeftEdge
            elif self.edge == Qt.TopRightCorner:
                edges = Qt.TopEdge | Qt.RightEdge
            elif self.edge == Qt.BottomLeftCorner:
                edges = Qt.BottomEdge | Qt.LeftEdge
            elif self.edge == Qt.BottomRightCorner:
                edges = Qt.BottomEdge | Qt.RightEdge

            # Attempt system resize first (smoother, handles OS snapping)
            if win.windowHandle().startSystemResize(edges):
                return
            
            self.start_pos = event.globalPosition().toPoint()
            self.start_geo = win.geometry()
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_pos = None

    def mouseMoveEvent(self, event):
        # We need this to actually process the move!
        if self.drag_pos:
            delta = event.globalPosition().toPoint() - self.drag_pos
            self._resize_window(delta)
            event.accept()

    def _resize_window(self, delta):
        win = self.window()
        if win.isMaximized(): return 
        
        # Use stored start geometry for stable resizing
        x, y, w, h = self.start_geo.x(), self.start_geo.y(), self.start_geo.width(), self.start_geo.height()
        dx, dy = delta.x(), delta.y()

        if self.edge == Qt.LeftEdge:
            x += dx; w -= dx
        elif self.edge == Qt.RightEdge:
            w += dx
        elif self.edge == Qt.TopEdge:
            y += dy; h -= dy
        elif self.edge == Qt.BottomEdge:
            h += dy
        elif self.edge == Qt.TopLeftCorner:
            x += dx; w -= dx; y += dy; h -= dy
        elif self.edge == Qt.TopRightCorner:
            y += dy; h -= dy; w += dx
        elif self.edge == Qt.BottomLeftCorner:
            x += dx; w -= dx; h += dy
        elif self.edge == Qt.BottomRightCorner:
            w += dx; h += dy

        if w > 1100 and h > 620:
            win.setGeometry(x, y, w, h)


class DashboardShell(QMainWindow):
    def __init__(self, width=1100, height=620):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window) # Added Qt.Window for better OS handling
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.resize(width, height)
        self.setMinimumSize(1100, 620)

        vars = theme_vars()

        # 1. Main Container (Rounded, Dark)
        self._container = QWidget(self)
        self.setCentralWidget(self._container)
        self._container.setObjectName("container")
        self._container.setStyleSheet(f"""
            QWidget#container {{
                background-color: {vars["background"]};
                border: 2px solid {vars["outline_variant"]};
                border-radius: 12px;
            }}
        """)

        # Main Top Bar
        self.root_layout = QVBoxLayout(self._container)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        # --- Top Bar (Draggable) --- #
        self._top_bar = QWidget()
        self._top_bar.setFixedHeight(48)
        self._top_bar.setStyleSheet("background: transparent;")
        
        # Connect Mouse Events for Dragging
        self._drag_pos = None
        self._top_bar.mousePressEvent = self._start_drag
        self._top_bar.mouseMoveEvent = self._perform_drag
        self._top_bar.mouseDoubleClickEvent = self._toggle_maximize

        # Top Bar Layout
        self._top_bar_layout = QHBoxLayout(self._top_bar)
        self._top_bar_layout.setContentsMargins(16, 0, 16, 0)
        self._top_bar_layout.addStretch()
         

        self._add_window_controls()
        self.root_layout.addWidget(self._top_bar)

        # --- Content Area --- #
        self._content = QWidget()
        self.root_layout.addWidget(self._content)


        # --- Resize Grips --- #
        self._grips = []
        self._setup_resize_grips()

    # --- Helper Methods --- #

    def _start_drag(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()

    def _perform_drag(self, event):
        if self._drag_pos and event.buttons() & Qt.LeftButton:
            if not self.isMaximized():
                delta = event.globalPosition().toPoint() - self._drag_pos
                self.move(self.pos() + delta)
                self._drag_pos = event.globalPosition().toPoint()

    def _add_window_controls(self):
        var = theme_vars() 
        btn_style = f"""
            QPushButton {{
                background-color: transparent;
                border: 2px solid {var["outline_variant"]}; 
                border-radius: 10px;
                font-weight: bold;
                font-size: 14px;
            }}
            QPushButton:hover {{
                border: 2px solid {var["outline"]};
            }}
            QPushButton:pressed {{
                background-color: {var["outline_variant"]};
            }}
        """

        btn_close_style = f"""
            QPushButton {{
                background-color: transparent;
                border: 2px solid {var["outline_variant"]};
                border-radius:10px;
                font-weight: bold;
                font-size: 14px;
            }}
            QPushButton:hover {{
                border: 2px solid {var["error"]};
                color: {var["error"]};
            }}
            QPushButton:pressed {{
                background-color: {var["error_container"]};
                color: {var["inverse_on_surface"]};
            }}
        """

        btn_min = QPushButton("─")
        btn_min.setFixedSize(32, 32)
        btn_min.setStyleSheet(btn_style)
        btn_min.clicked.connect(self.showMinimized)

        self.btn_max = QPushButton("☐")
        self.btn_max.setFixedSize(32, 32)
        self.btn_max.setStyleSheet(btn_style)
        self.btn_max.clicked.connect(self._toggle_maximize)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(32, 32)
        btn_close.setStyleSheet(btn_close_style) 
        btn_close.clicked.connect(self.close)


        title = QLabel("Daily Selfie")
        title.setStyleSheet(f"""
            QLabel {{
                color: {var["on_surface"]};
                font-size: 14px;
                font-weight: 600;
            }}
        """)

        self._top_bar_layout.insertWidget(0, title)
        # self._top_bar_layout.addWidget(0, title)

        self._top_bar_layout.addWidget(btn_min)
        self._top_bar_layout.addWidget(self.btn_max)
        self._top_bar_layout.addWidget(btn_close)

    def _toggle_maximize(self, event=None):
        if self.isMaximized():
            self.showNormal()
            self._container.setStyleSheet(self._container.styleSheet().replace("border-radius: 0px;", "border-radius: 12px;"))
        else:
            self.showMaximized()
            self._container.setStyleSheet(self._container.styleSheet().replace("border-radius: 12px;", "border-radius: 0px;"))

    def _setup_resize_grips(self):
        self._grips.append(ResizeGrip(self, Qt.LeftEdge))
        self._grips.append(ResizeGrip(self, Qt.RightEdge))
        self._grips.append(ResizeGrip(self, Qt.TopEdge))
        self._grips.append(ResizeGrip(self, Qt.BottomEdge))
        self._grips.append(ResizeGrip(self, Qt.TopLeftCorner))
        self._grips.append(ResizeGrip(self, Qt.TopRightCorner))
        self._grips.append(ResizeGrip(self, Qt.BottomLeftCorner))
        self._grips.append(ResizeGrip(self, Qt.BottomRightCorner))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.rect()
        d = 10
        self._grips[0].setGeometry(0, d, d, rect.height()-2*d) 
        self._grips[1].setGeometry(rect.width()-d, d, d, rect.height()-2*d)
        self._grips[2].setGeometry(d, 0, rect.width()-2*d, d)
        self._grips[3].setGeometry(d, rect.height()-d, rect.width()-2*d, d)
        self._grips[4].setGeometry(0, 0, d, d) 
        self._grips[5].setGeometry(rect.width()-d, 0, d, d) 
        self._grips[6].setGeometry(0, rect.height()-d, d, d) 
        self._grips[7].setGeometry(rect.width()-d, rect.height()-d, d, d) 
        for g in self._grips: g.raise_()