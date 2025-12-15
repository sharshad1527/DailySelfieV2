# gui/startup/startup_window.py

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
from PySide6.QtGui import QPixmap

from gui.startup.window_con import BaseFramelessWindow
from gui.startup.widgets.ghost_slider import GhostOpacitySlider
from gui.startup.widgets.shutter_bar import ShutterBar

# [REMOVED] CameraPreviewThread import is no longer needed
# from gui.startup.camera.preview import CameraPreviewThread


class StartupWindow(BaseFramelessWindow):
    def __init__(self):
        super().__init__(width=1000, height=560)

        # ---------- Paths & Config ----------
        from core.config import ensure_config
        from core.paths import get_app_paths

        self.paths = get_app_paths("DailySelfie", ensure=True)
        self.config = ensure_config(self.paths.data_dir / "config")

        # [REMOVED] _preview_thread initialization

        # Build UI
        self._build_content_ui()

        # 🔗 Wire shutter
        self.shutter_bar.shutterClicked.connect(self._on_shutter_clicked)

    # =====================================================
    # UI
    # =====================================================
    def _build_content_ui(self):
        root_layout = QHBoxLayout(self._content)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(16)

        # ---------- LEFT (Ghost slider) ----------
        left_panel = QWidget()
        left_panel.setFixedWidth(90)

        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(2, 0, 0, 0)
        left_layout.setSpacing(6)

        ghost_label = QLabel("Ghost")
        ghost_label.setContentsMargins(34, 0, 0, 0)
        ghost_label.setStyleSheet("color: #B0B0B0;")

        self.ghost_slider = GhostOpacitySlider()

        left_layout.addWidget(ghost_label, alignment=Qt.AlignLeft)
        left_layout.addWidget(self.ghost_slider, 1, alignment=Qt.AlignLeft)

        # ---------- CENTER (Preview Placeholder) ----------
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)

        # [MODIFIED] Placeholder text instead of video feed container
        self.preview = QLabel("Camera Preview\n(Placeholder)")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("""
            QLabel {
                background-color: #1A1A1A;
                border-radius: 12px;
                color: #555555;
                font-size: 18px;
                font-weight: bold;
            }
        """)

        center_layout.addWidget(self.preview, 1)

        # ---------- RIGHT (Controls) ----------
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(12)

        mood_label = QLabel("Mood")
        mood_label.setStyleSheet("color: #B0B0B0;")

        self.mood_group = QButtonGroup(self)
        self.mood_group.setExclusive(True)

        mood_layout = QHBoxLayout()
        for m in ["😀", "🙂", "😐", "😔", "😢"]:
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

        self.shutter_bar = ShutterBar()

        right_layout.addWidget(mood_label)
        right_layout.addLayout(mood_layout)
        right_layout.addWidget(note_label)
        right_layout.addWidget(self.note_edit)
        right_layout.addSpacing(128)
        right_layout.addWidget(self.shutter_bar, alignment=Qt.AlignCenter)
        right_layout.addStretch()

        # ---------- Assemble ----------
        root_layout.addWidget(left_panel, 0)
        root_layout.addWidget(center_panel, 5)
        root_layout.addWidget(right_panel, 2)

    # =====================================================
    # [REMOVED] Camera Preview Methods
    # =====================================================
    # _start_camera_preview, _stop_camera_preview, 
    # _on_frame_ready, and _on_camera_error have been removed.

    # =====================================================
    # Shutter logic
    # =====================================================
    def _on_shutter_clicked(self):
        # [MODIFIED] Capture logic disabled
        print("Shutter clicked (Capture function is currently disabled)")

    # =====================================================
    # Lifecycle
    # =====================================================
    # [REMOVED] showEvent and closeEvent no longer needed for thread management
    # unless you have other lifecycle logic to add.