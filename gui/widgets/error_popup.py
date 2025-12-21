from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, 
    QHBoxLayout, QFrame, QGraphicsDropShadowEffect, QTextEdit
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QColor

class ErrorToast(QDialog):
    def __init__(self, parent=None, level="ERROR", message="", traceback=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground) # Transparent window for shadow support
        
        # Theme Colors
        level_colors = {
            "INFO": "#8B5CF6",    # Purple
            "WARNING": "#F59E0B", # Amber
            "ERROR": "#EF4444",   # Red
            "CRITICAL": "#DC2626" # Dark Red
        }
        accent_color = level_colors.get(level, "#EF4444")
        
        self.full_text = f"[{level}] {message}\n\n{traceback if traceback else ''}"

        # 1. Main Layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # 2. The Visual Container (The Card)
        self.container = QFrame()
        self.container.setObjectName("Container")
        
        # Stylesheet
        self.container.setStyleSheet(f"""
            QFrame#Container {{
                background-color: #1A1A1A;
                
                /* Fixed Purple Border for Top, Right, Bottom */
                border: 2px solid #8B5CF6;
                
                /* Dynamic Color for Left (Overrides the purple on the left side) */
                border-left: 4px solid {accent_color};
                
                border-radius: 14px;
            }}
            QLabel {{ 
                color: #E0E0E0; 
                font-family: sans-serif; 
                border: none; 
            }}
            /* Header Title */
            QLabel#Title {{
                font-weight: bold;
                font-size: 14px;
                color: {accent_color};
            }}
            /* Message Body */
            QLabel#Message {{
                color: #CCCCCC;
                font-size: 13px;
                margin-top: 4px;
                margin-bottom: 12px;
            }}
            /* Action Buttons */
            QPushButton {{
                background-color: #2D2D2D;
                color: #B0B0B0;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: #3D3D3D;
                color: white;
                border: 1px solid #555;
            }}
            /* Primary Action (Dismiss) - Make it Purple */
            QPushButton#DismissBtn {{
                background-color: #5B21B6; 
                color: white;
                border: none;
            }}
            QPushButton#DismissBtn:hover {{
                background-color: #7C3AED; 
            }}
        """)
        
        # 3. Drop Shadow Effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(25)
        if level == "INFO":
            shadow.setColor(QColor(139, 92, 246, 60)) # Faint purple glow
        else:
            shadow.setColor(QColor(0, 0, 0, 180)) # Dark shadow for errors
        shadow.setOffset(0, 8)
        self.container.setGraphicsEffect(shadow)

        main_layout.addWidget(self.container)

        # 4. Content Layout
        content_layout = QVBoxLayout(self.container)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(4)
        
        # Header
        lbl_title = QLabel(f"{level.title()}")
        lbl_title.setObjectName("Title")
        content_layout.addWidget(lbl_title)

        # Message
        lbl_msg = QTextEdit(message)
        lbl_msg.setStyleSheet("""QTextEdit {
                background-color: #1A1A1A;
                border: 2px solid transparent;
                border-radius: 8px;
                padding: 8px;
                color: #E0E0E0;
            }
            QTextEdit:focus {
                border: 2px solid #333333;
                background-color: #1F1F1F;
            }
        """)
        lbl_msg.setObjectName("Message")
        lbl_msg.setReadOnly(True)
        lbl_msg.setMaximumWidth(320)
        content_layout.addWidget(lbl_msg)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        btn_copy = QPushButton("Copy Logs")
        btn_copy.setCursor(Qt.PointingHandCursor)
        btn_copy.clicked.connect(self.copy_to_clipboard)
        
        btn_close = QPushButton("Dismiss")
        btn_close.setObjectName("DismissBtn")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)

        btn_layout.addWidget(btn_copy)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        
        content_layout.addLayout(btn_layout)

        # Auto-close for INFO messages only
        if level in ["INFO"]:
            QTimer.singleShot(4000, self.accept)

    def copy_to_clipboard(self):
        cb = QGuiApplication.clipboard()
        cb.setText(self.full_text)
        sender = self.sender()
        original_text = sender.text()
        sender.setText("Copied!")
        sender.setEnabled(False)
        QTimer.singleShot(2000, lambda: self._reset_copy_btn(sender, original_text))

    def _reset_copy_btn(self, btn, text):
        btn.setText(text)
        btn.setEnabled(True)

# Smoke Test
if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    popup = ErrorToast(level="CRITICAL", message="Direct Test: If you see this, the popup UI is working.", traceback="Fake Traceback:\n  File 'test.py', line 42\n    broken()\nError: This is a simulated crash.")

    popup.show()
    sys.exit(app.exec())


    