# gui/dashboard/window_con.py
import sys
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QRect
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QApplication
)

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
        self.start_pos = None

    def mouseMoveEvent(self, event):
        # Fallback manual resize when startSystemResize() failed
        if hasattr(self, 'start_pos') and self.start_pos is not None:
            delta = event.globalPosition().toPoint() - self.start_pos
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

        if w >= 1100 and h >= 620:
            win.setGeometry(x, y, w, h)


class DashboardShell(QMainWindow):
    def __init__(self, width=1100, height=620):
        super().__init__()
        self.setWindowTitle("Daily Selfie - Dashboard")
        
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window) # Added Qt.Window for better OS handling
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Initialize custom maximize tracking early (before any call to _toggle_maximize)
        self._is_maximized_custom = False
        self._normal_geometry = None  # Will be set to actual geometry in showEvent

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
                color: {var["on_surface"]};
                border: 2px solid {var["outline_variant"]}; 
                border-radius: 10px;
                font-weight: bold;
                font-size: 14px;
            }}
            QPushButton:hover {{
                color: {var["on_surface_variant"]};

                border: 2px solid {var["outline"]};
            }}
            QPushButton:pressed {{
                background-color: {var["outline_variant"]};
            }}
        """

        btn_close_style = f"""
            QPushButton {{
                background-color: transparent;
                color: {var["on_surface_variant"]};
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
        btn_min.clicked.connect(self._minimize_window)

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
        # On Linux, use native maximize (smooth animations built-in)
        if sys.platform != 'win32':
            if self.isMaximized():
                self.showNormal()
                self._container.setStyleSheet(self._container.styleSheet().replace("border-radius: 0px;", "border-radius: 12px;"))
            else:
                self.showMaximized()
                self._container.setStyleSheet(self._container.styleSheet().replace("border-radius: 12px;", "border-radius: 0px;"))
            return
        
        # On Windows, animate the geometry for smooth maximize/restore
        if self._is_maximized_custom:
            self._animate_to_geometry(self._normal_geometry, maximizing=False)
        else:
            # Store current geometry before maximizing
            self._normal_geometry = self.geometry()
            screen = QApplication.primaryScreen().availableGeometry()
            self._animate_to_geometry(screen, maximizing=True)

    def _animate_to_geometry(self, target_rect, maximizing):
        """Smoothly animate window geometry change."""
        self._geo_anim = QPropertyAnimation(self, b"geometry")
        self._geo_anim.setDuration(200)  # 200ms for snappy but smooth feel
        self._geo_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._geo_anim.setStartValue(self.geometry())
        self._geo_anim.setEndValue(target_rect)
        
        # Update border radius and state after animation completes
        def on_finished():
            self._is_maximized_custom = maximizing
            if maximizing:
                self._container.setStyleSheet(self._container.styleSheet().replace("border-radius: 12px;", "border-radius: 0px;"))
            else:
                self._container.setStyleSheet(self._container.styleSheet().replace("border-radius: 0px;", "border-radius: 12px;"))
        
        self._geo_anim.finished.connect(on_finished)
        self._geo_anim.start()

    def _minimize_window(self):
        # Store pre-minimize state so we can restore properly
        self._was_maximized_before_minimize = self._is_maximized_custom if sys.platform == 'win32' else self.isMaximized()
        
        # On Windows, animate shrinking before minimize
        if sys.platform == 'win32':
            # Store geometry for restore
            if not self._is_maximized_custom:
                self._normal_geometry = self.geometry()
            
            # Animate shrinking toward taskbar area
            screen = QApplication.primaryScreen().availableGeometry()
            # Shrink toward bottom center (where taskbar usually is)
            target = QRect(
                screen.center().x() - 200,
                screen.bottom() - 100,
                400, 50
            )
            
            self._min_anim = QPropertyAnimation(self, b"geometry")
            self._min_anim.setDuration(150)
            self._min_anim.setEasingCurve(QEasingCurve.InCubic)
            self._min_anim.setStartValue(self.geometry())
            self._min_anim.setEndValue(target)
            self._min_anim.finished.connect(self._do_minimize)
            self._min_anim.start()
        else:
            # On Linux, just minimize normally
            if self.isMaximized():
                self.showNormal()
            self.showMinimized()

    def _do_minimize(self):
        """Actually minimize after animation."""
        self.showMinimized()

    def showEvent(self, event):
        super().showEvent(event)
        
        # Set _normal_geometry to actual geometry on first show if not yet set
        if self._normal_geometry is None:
            self._normal_geometry = self.geometry()
        
        # Restore state after minimize
        if hasattr(self, '_was_maximized_before_minimize') and self._was_maximized_before_minimize:
            self._was_maximized_before_minimize = False
            
            if sys.platform == 'win32':
                # Restore to maximized with animation
                screen = QApplication.primaryScreen().availableGeometry()
                self.setGeometry(screen)
                self._is_maximized_custom = True
                self._container.setStyleSheet(self._container.styleSheet().replace("border-radius: 12px;", "border-radius: 0px;"))
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