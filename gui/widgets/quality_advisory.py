# gui/widgets/quality_advisory.py
"""
QualityAdvisoryDialog - shared "check your photo" advisory card.

Lives in gui/widgets/ rather than a page module because BOTH capture surfaces
need it: the in-dashboard SelfiePage and the --start-up popup
(gui/startup/startup_window.py). The popup is the lower layer, so importing a
dashboard page from it inverted the dependency. Shared widgets belong here,
next to error_popup.py.

Advisory only: "Save Anyway" always commits, "Retake" aborts the save.
Styled like the calendar ConfirmDeleteDialog (dark card, left accent border).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)

from core.quality import WARNING_MESSAGES
from gui.theme.theme_vars import theme_vars


class QualityAdvisoryDialog(QDialog):
    def __init__(self, warnings, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        v = theme_vars()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(15, 15, 15, 15)

        container = QFrame()
        container.setObjectName("Container")
        container.setStyleSheet(f"""
            QFrame#Container {{
                background-color: {v['surface_container_low']};
                border: 2px solid {v['outline_variant']};
                border-left: 4px solid {v['error']};
                border-radius: 14px;
            }}
            QLabel {{ color: {v['on_surface']}; border: none; }}
        """)
        outer.addWidget(container)

        col = QVBoxLayout(container)
        col.setContentsMargins(16, 16, 16, 16)
        col.setSpacing(8)

        title = QLabel("Check your photo")
        title.setStyleSheet(f"color: {v['error']}; font-size: 14px; font-weight: bold;")
        col.addWidget(title)

        body = QLabel("\n".join(WARNING_MESSAGES.get(w, w) for w in warnings))
        body.setStyleSheet(f"color: {v['on_surface_variant']}; font-size: 13px;")
        col.addWidget(body)

        col.addSpacing(4)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        retake_btn = QPushButton("Retake")
        retake_btn.setCursor(Qt.PointingHandCursor)
        retake_btn.setFixedHeight(32)
        retake_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {v['surface_container_high']};
                color: {v['on_surface_variant']};
                border: 1px solid {v['outline_variant']};
                border-radius: 16px;
                padding: 0 12px; font-size: 11px; font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {v['surface_container_highest']};
                color: {v['on_surface']};
                border-color: {v['outline']};
            }}
        """)
        retake_btn.clicked.connect(self.reject)
        btn_row.addWidget(retake_btn)
        btn_row.addStretch()

        save_btn = QPushButton("Save Anyway")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setFixedHeight(32)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {v['primary']}; color: {v['on_primary']};
                border: none; border-radius: 16px;
                padding: 0 12px; font-size: 11px; font-weight: 600;
            }}
        """)
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(save_btn)

        col.addLayout(btn_row)