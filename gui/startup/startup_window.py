from PySide6.QtCore import Qt, QByteArray, QBuffer, QIODevice
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, 
    QPushButton, QTextEdit, QButtonGroup
)
from PySide6.QtGui import QPixmap, QImage

from gui.startup.window_con import BaseFramelessWindow
from gui.startup.widgets.ghost_slider import GhostOpacitySlider
from gui.startup.widgets.shutter_bar import ShutterBar
from gui.startup.camera.preview import CameraPreviewThread
from core.capture import commit_capture_from_bytes

class StartupWindow(BaseFramelessWindow):
    def __init__(self):
        super().__init__(width=1000, height=560)

        # ---------- Paths & Config Setup (CORRECTED) ----------
        from core.config import ensure_config, apply_config_to_paths
        from core.paths import get_app_paths
        
        # 1. Get basic OS paths (bootstrap)
        bootstrap_paths = get_app_paths("DailySelfie", ensure=False)
        
        # 2. Load config
        self.config = ensure_config(bootstrap_paths.config_dir)
        
        # 3. Apply config overrides to paths (FIXES SAVING LOCATION)
        self.paths = apply_config_to_paths(bootstrap_paths, self.config)
        
        # 4. Ensure final directories exist
        for p in (self.paths.data_dir, self.paths.photos_root, self.paths.logs_dir):
            p.mkdir(parents=True, exist_ok=True)

        # ---------- State ----------
        self._current_qimage = None # Stores the frozen frame
        self._preview_thread = None
        
        # ---------- UI ----------
        self._build_content_ui()
        
        # Wire Shutter Bar Signals
        self.shutter_bar.shutterClicked.connect(self._on_shutter)
        self.shutter_bar.saveClicked.connect(self._on_save)
        self.shutter_bar.retakeClicked.connect(self._on_retake)
        # self.shutter_bar.lightToggled.connect(self._toggle_screen_flash) # Optional feature

    def _build_content_ui(self):
        root = QHBoxLayout(self._content)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(16)

        # --- LEFT (Ghost) ---
        left = QWidget()
        left.setFixedWidth(90)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(2,0,0,0)
        
        self.ghost_slider = GhostOpacitySlider()
        left_layout.addWidget(QLabel("Ghost", styleSheet="color:#B0B0B0; margin-left:34px;"))
        left_layout.addWidget(self.ghost_slider, 1, Qt.AlignLeft)

        # --- CENTER (Preview) ---
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0,0,0,0)
        
        self.preview_lbl = QLabel()
        self.preview_lbl.setAlignment(Qt.AlignCenter)
        self.preview_lbl.setStyleSheet("background-color: #1A1A1A; border-radius: 12px;")
        center_layout.addWidget(self.preview_lbl, 1)

        # --- RIGHT (Controls) ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        
        # Moods
        self.mood_group = QButtonGroup(self)
        moods_lo = QHBoxLayout()
        for m in ["😀", "🙂", "😐", "😔", "😢"]:
            b = QPushButton(m)
            b.setCheckable(True)
            b.setFixedSize(40,40)
            b.setStyleSheet("QPushButton{background:#1F1F1F; border-radius:20px; font-size:18px;} QPushButton:checked{background:#8B5CF6;}")
            self.mood_group.addButton(b)
            moods_lo.addWidget(b)
            
        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("Anything about today...")
        self.note_edit.setFixedHeight(100)
        self.note_edit.setStyleSheet("background:#1A1A1A; border-radius:8px; padding:8px; color:#E0E0E0;")
        
        self.shutter_bar = ShutterBar()

        right_layout.addWidget(QLabel("Mood", styleSheet="color:#B0B0B0"))
        right_layout.addLayout(moods_lo)
        right_layout.addWidget(QLabel("Note", styleSheet="color:#B0B0B0"))
        right_layout.addWidget(self.note_edit)
        right_layout.addSpacing(64)
        right_layout.addWidget(self.shutter_bar, alignment=Qt.AlignCenter)
        right_layout.addStretch()

        root.addWidget(left, 0)
        root.addWidget(center, 5)
        root.addWidget(right, 2)

    # ----------------------------------------------------
    # Camera Management
    # ----------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        self._start_preview()

    def closeEvent(self, event):
        self._stop_preview()
        super().closeEvent(event)

    def _start_preview(self):
        if self._preview_thread: return
        
        beh = self.config.get("behavior", {})
        self._preview_thread = CameraPreviewThread(
            camera_index=beh.get("camera_index", 0),
            width=beh.get("width"),
            height=beh.get("height")
        )
        self._preview_thread.frame_ready.connect(self._update_preview)
        self._preview_thread.error_occurred.connect(lambda e: print(f"Camera Error: {e}"))
        self._preview_thread.start()

    def _stop_preview(self):
        if self._preview_thread:
            self._preview_thread.stop()
            self._preview_thread = None

    def _update_preview(self, qimg):
        # Always keep the latest frame in memory
        self._current_qimage = qimg
        
        # Display it
        pix = QPixmap.fromImage(qimg)
        scaled = pix.scaled(
            self.preview_lbl.size(), 
            Qt.KeepAspectRatio, 
            Qt.SmoothTransformation
        )
        self.preview_lbl.setPixmap(scaled)

    # ----------------------------------------------------
    # Capture Workflow
    # ----------------------------------------------------
    def _on_shutter(self):
        """Freeze the preview and enter review mode."""
        if not self._current_qimage:
            print("No frame available to capture.")
            return

        # 1. Stop streaming (Visual Freeze)
        self._stop_preview()
        
        # 2. Update UI for Review
        self.shutter_bar.setReviewMode(True)
        self.ghost_slider.setEnabled(False) 
        self.ghost_slider.setStyleSheet("opacity: 0.3;")

    def _on_retake(self):
        """Discard frozen frame and resume preview."""
        self.shutter_bar.setReviewMode(False)
        self.ghost_slider.setEnabled(True)
        self.ghost_slider.setStyleSheet("")
        
        self._current_qimage = None
        self._start_preview()

    def _on_save(self):
        """Commit the frozen frame to disk."""
        if not self._current_qimage: return

        # 1. Prepare Bytes
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.WriteOnly)
        
        quality = self.config.get("behavior", {}).get("quality", 90)
        self._current_qimage.save(buffer, "JPG", quality)
        jpg_data = byte_array.data()

        # 2. Extract Metadata
        selected_mood = None
        if self.mood_group.checkedButton():
            selected_mood = self.mood_group.checkedButton().text()
        
        raw_note = self.note_edit.toPlainText().strip()
        selected_note = raw_note if raw_note else None

        # 3. Commit (Uses path with config applied)
        beh = self.config.get("behavior", {})
        result = commit_capture_from_bytes(
            self.paths,
            jpeg_bytes=jpg_data,
            width=self._current_qimage.width(),
            height=self._current_qimage.height(),
            mood=selected_mood,
            notes=selected_note,
            allow_retake=beh.get("allow_retake", False)
        )

        if result["success"]:
            print(f"Saved to: {result['path']}")
            self.close()
        else:
            print(f"Save Failed: {result['error']}")