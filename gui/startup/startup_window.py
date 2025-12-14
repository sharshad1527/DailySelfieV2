# gui/startup/startup_window
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QButtonGroup,
)

from startup.window_con import BaseFramelessWindow
from startup.widgets.ghost_slider import GhostOpacitySlider


class StartupWindow(BaseFramelessWindow):
    def __init__(self):
        super().__init__(width=1000, height=560)
        self._build_content_ui()

    def _build_content_ui(self):
        """
        Builds ONLY the startup layout.
        Ghost slider is functional (value changes),
        but no ghost image logic yet.
        """

        # Root content layout (3 columns)
        root_layout = QHBoxLayout(self._content)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(16)

        # =========================
        # LEFT — Ghost slider
        # =========================
        # left_panel = QWidget()
        # left_layout = QVBoxLayout(left_panel)
        # left_layout.setAlignment(Qt.AlignCenter)
        # left_layout.setSpacing(8)

        # ghost_label = QLabel("Ghost")
        # ghost_label.setAlignment(Qt.AlignCenter)
        # ghost_label.setStyleSheet("color: #B0B0B0;")

        # self.ghost_slider = GhostOpacitySlider(
        #     minimum=0,
        #     maximum=60,
        #     value=30,
        # )

        # # Debug: confirm it moves
        # self.ghost_slider.valueChanged.connect(
        #     lambda v: print(f"Ghost opacity: {v}%")
        # )

        # left_layout.addWidget(ghost_label)
        # left_panel.setFixedWidth(100)
        # left_layout.addWidget(self.ghost_slider, 1)

        # left_panel = QWidget()
        # left_panel.setFixedWidth(120)

        # left_layout = QVBoxLayout(left_panel)
        # left_layout.setContentsMargins(8, 0, 0, 0)
        # left_layout.setSpacing(8)

        # ghost_label = QLabel("Ghost")
        # ghost_label.setContentsMargins(34, 0, 0, 0)
        # ghost_label.setStyleSheet("color: #B0B0B0;")

        # self.ghost_slider = GhostOpacitySlider()
        # left_layout.addWidget(ghost_label, alignment=Qt.AlignLeft)
        # left_layout.addWidget(self.ghost_slider, 1, alignment=Qt.AlignLeft)

        # =========================
        # LEFT — Ghost slider
        # =========================
        left_panel = QWidget()
        left_panel.setFixedWidth(90)  # narrower so preview gains width

        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(2, 0, 0, 0)   # move everything left
        left_layout.setSpacing(6)

        ghost_label = QLabel("Ghost")
        ghost_label.setContentsMargins(34, 0, 0, 0)  # visually align with slider track
        ghost_label.setStyleSheet("color: #B0B0B0;")

        self.ghost_slider = GhostOpacitySlider()
        left_layout.addWidget(ghost_label, alignment=Qt.AlignLeft)
        left_layout.addWidget(self.ghost_slider, 1, alignment=Qt.AlignLeft)


        # =========================
        # CENTER — Camera preview placeholder
        # =========================
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)

        self.preview = QLabel("Camera Preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("""
            QLabel {
                background-color: #1A1A1A;
                color: #666;
                border-radius: 12px;
                font-size: 16px;
            }
        """)

        center_layout.addWidget(self.preview, 1)

        # =========================
        # RIGHT — Mood / Note / Controls
        # =========================
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(12)

        # Mood buttons
        mood_label = QLabel("Mood")
        mood_label.setStyleSheet("color: #B0B0B0;")

        self.mood_group = QButtonGroup(self)
        self.mood_group.setExclusive(True)

        mood_layout = QHBoxLayout()
        moods = ["😀", "🙂", "😐", "😔", "😢"]

        for m in moods:
            btn = QPushButton(m)
            btn.setCheckable(True)
            btn.setFixedSize(40, 40)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #1F1F1F;
                    border-radius: 20px;
                    font-size: 18px;
                }
                QPushButton:checked {
                    background-color: #8B5CF6;
                }
            """)
            self.mood_group.addButton(btn)
            mood_layout.addWidget(btn)

        # Note field
        note_label = QLabel("Note (optional)")
        note_label.setStyleSheet("color: #B0B0B0;")

        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("Anything about today…")
        self.note_edit.setFixedHeight(100)
        self.note_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1A1A1A;
                border-radius: 8px;
                padding: 8px;
                color: #E0E0E0;
            }
        """)

        # Shutter button
        self.shutter_btn = QPushButton("●")
        self.shutter_btn.setFixedSize(72, 72)
        self.shutter_btn.setStyleSheet("""
            QPushButton {
                background-color: #8B5CF6;
                border-radius: 36px;
                font-size: 28px;
                color: white;
            }
            QPushButton:hover {
                background-color: #7C3AED;
            }
        """)

        # Light toggle
        self.light_btn = QPushButton("💡")
        self.light_btn.setCheckable(True)
        self.light_btn.setFixedSize(48, 48)
        self.light_btn.setStyleSheet("""
            QPushButton {
                background-color: #1F1F1F;
                border-radius: 24px;
                font-size: 18px;
            }
            QPushButton:checked {
                background-color: #FACC15;
            }
        """)

        # Assemble right panel
        right_layout.addWidget(mood_label)
        right_layout.addLayout(mood_layout)
        right_layout.addWidget(note_label)
        right_layout.addWidget(self.note_edit)
        right_layout.addStretch()
        right_layout.addWidget(self.shutter_btn, alignment=Qt.AlignCenter)
        right_layout.addWidget(self.light_btn, alignment=Qt.AlignCenter)

        # =========================
        # Add all panels to root
        # =========================
        root_layout.addWidget(left_panel, 0)
        root_layout.addWidget(center_panel, 5)
        root_layout.addWidget(right_panel, 2)
