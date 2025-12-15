from PySide6.QtCore import Qt, QByteArray, QBuffer, QIODevice, QSize, QTimer
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, 
    QPushButton, QTextEdit, QButtonGroup
)
from PySide6.QtGui import QPixmap, QImage, QPainter, QPainterPath, QFont

from gui.startup.window_con import BaseFramelessWindow
from gui.startup.widgets.ghost_slider import GhostOpacitySlider
from gui.startup.widgets.shutter_bar import ShutterBar
from gui.startup.camera.preview import CameraPreviewThread
from core.capture import commit_capture_from_bytes

class StartupWindow(BaseFramelessWindow):
    def __init__(self):
        super().__init__(width=1000, height=560)

        # ---------- Paths & Config Setup ----------
        from core.config import ensure_config, apply_config_to_paths, write_config
        from core.paths import get_app_paths
        
        bootstrap_paths = get_app_paths("DailySelfie", ensure=False)
        self.config_path = bootstrap_paths.config_dir / "config.toml"
        
        # Load Config
        self.config = ensure_config(bootstrap_paths.config_dir)
        self.paths = apply_config_to_paths(bootstrap_paths, self.config)
        
        # Ensure directories
        for p in (self.paths.data_dir, self.paths.photos_root, self.paths.logs_dir):
            p.mkdir(parents=True, exist_ok=True)

        # ---------- State ----------
        self._current_qimage = None 
        self._preview_thread = None
        
        # Get last saved timer value (default 0)
        initial_timer = self.config.get("behavior", {}).get("timer_duration", 0)
        
        # Countdown State
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)
        self._countdown_remaining = 0

        # ---------- UI ----------
        self._build_content_ui(initial_timer)
        
        # Signals
        self.shutter_bar.shutterClicked.connect(self._on_shutter_clicked)
        self.shutter_bar.saveClicked.connect(self._on_save)
        self.shutter_bar.retakeClicked.connect(self._on_retake)

    def _build_content_ui(self, initial_timer):
        root = QHBoxLayout(self._content)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(16)

        # --- LEFT ---
        left = QWidget()
        left.setFixedWidth(90)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(2,0,0,0)
        
        self.ghost_slider = GhostOpacitySlider()
        left_layout.addWidget(QLabel("Ghost", styleSheet="color:#B0B0B0; margin-left:34px;"))
        left_layout.addWidget(self.ghost_slider, 1, Qt.AlignLeft)

        # --- CENTER (Preview + Overlay) ---
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0,0,0,0)
        
        # Container for stacking overlay
        self.preview_container = QWidget()
        # We use a grid layout to stack widgets on top of each other
        from PySide6.QtWidgets import QGridLayout
        stack_layout = QGridLayout(self.preview_container)
        stack_layout.setContentsMargins(0,0,0,0)

        # 1. The Camera View
        self.preview_lbl = QLabel()
        self.preview_lbl.setAlignment(Qt.AlignCenter)
        self.preview_lbl.setStyleSheet("background-color: #333333; border-radius: 16px;")
        
        # 2. The Countdown Overlay (Hidden by default)
        self.countdown_lbl = QLabel("")
        self.countdown_lbl.setAlignment(Qt.AlignCenter)
        self.countdown_lbl.setStyleSheet("background: transparent; color: white; font-weight: bold;")
        self.countdown_lbl.setFont(QFont("Arial", 96))
        self.countdown_lbl.hide()

        # Add both to same cell (0,0) to stack them
        stack_layout.addWidget(self.preview_lbl, 0, 0)
        stack_layout.addWidget(self.countdown_lbl, 0, 0)

        center_layout.addWidget(self.preview_container, 1)

        # --- RIGHT ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        
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
        
        # Pass initial timer to bar
        self.shutter_bar = ShutterBar(initial_timer=initial_timer)

        right_layout.addWidget(QLabel("Mood", styleSheet="color:#B0B0B0"))
        right_layout.addLayout(moods_lo)
        right_layout.addWidget(QLabel("Note", styleSheet="color:#B0B0B0"))
        right_layout.addWidget(self.note_edit)
        right_layout.addSpacing(120)
        right_layout.addWidget(self.shutter_bar, alignment=Qt.AlignCenter)
        right_layout.addStretch()

        root.addWidget(left, 0)
        root.addWidget(center, 5)
        root.addWidget(right, 2)

    # ----------------------------------------------------
    # Camera Logic
    # ----------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        self._start_preview()

    def closeEvent(self, event):
        # [NEW] Save Timer Config on Close
        try:
            current_timer = self.shutter_bar.get_timer_value()
            if self.config["behavior"].get("timer_duration") != current_timer:
                self.config["behavior"]["timer_duration"] = current_timer
                from core.config import write_config
                write_config(self.config_path, self.config)
                print(f"Saved timer setting: {current_timer}s")
        except Exception as e:
            print(f"Failed to save config: {e}")

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
        self._current_qimage = qimg 
        if self.preview_lbl.width() <= 0: return

        # Border logic
        margin = 8
        target_w = self.preview_lbl.width() - (margin * 2)
        target_h = self.preview_lbl.height() - (margin * 2)
        if target_w <= 0: return

        pix = QPixmap.fromImage(qimg)
        scaled = pix.scaled(QSize(target_w, target_h), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        
        crop_x = (scaled.width() - target_w) // 2
        crop_y = (scaled.height() - target_h) // 2
        cropped = scaled.copy(crop_x, crop_y, target_w, target_h)

        final_pix = QPixmap(self.preview_lbl.size())
        final_pix.fill(Qt.transparent)
        painter = QPainter(final_pix)
        painter.setRenderHint(QPainter.Antialiasing)
        
        path = QPainterPath()
        path.addRoundedRect(margin, margin, target_w, target_h, 12, 12)
        painter.setClipPath(path)
        painter.drawPixmap(margin, margin, cropped)
        painter.end()
        
        self.preview_lbl.setPixmap(final_pix)

    # ----------------------------------------------------
    # Countdown & Capture Logic
    # ----------------------------------------------------
    def _on_shutter_clicked(self):
        """Initiate capture sequence (Timer or Instant)."""
        if not self._current_qimage: return

        # 1. Get Timer Value
        delay = self.shutter_bar.get_timer_value()

        if delay == 0:
            self._capture_now()
        else:
            self._start_countdown(delay)

    def _start_countdown(self, seconds):
        """Start visual countdown."""
        # Hide Ghost to clear view
        self.ghost_slider.setEnabled(False)
        self.ghost_slider.setStyleSheet("opacity: 0.0;") # Hide completely
        
        # Disable inputs
        self.shutter_bar.setEnabled(False)
        
        self._countdown_remaining = seconds
        self.countdown_lbl.setText(str(seconds))
        self.countdown_lbl.show()
        
        # Start tick (1 second intervals)
        self._countdown_timer.start(1000)

    def _on_countdown_tick(self):
        self._countdown_remaining -= 1
        
        if self._countdown_remaining > 0:
            self.countdown_lbl.setText(str(self._countdown_remaining))
        else:
            # Time's up!
            self._countdown_timer.stop()
            self.countdown_lbl.hide()
            self.shutter_bar.setEnabled(True)
            self._capture_now()

    def _capture_now(self):
        """Freeze and enter review."""
        self._stop_preview()
        self.shutter_bar.setReviewMode(True)
        # Dim ghost slider to show it's disabled in review
        self.ghost_slider.setEnabled(False) 
        self.ghost_slider.setStyleSheet("opacity: 0.3;")

    def _on_retake(self):
        self.shutter_bar.setReviewMode(False)
        self.ghost_slider.setEnabled(True)
        self.ghost_slider.setStyleSheet("") # Restore visibility
        self._current_qimage = None
        self._start_preview()

    def _on_save(self):
        if not self._current_qimage: return

        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.WriteOnly)
        
        quality = self.config.get("behavior", {}).get("quality", 90)
        self._current_qimage.save(buffer, "JPG", quality)
        jpg_data = byte_array.data()

        selected_mood = None
        if self.mood_group.checkedButton():
            selected_mood = self.mood_group.checkedButton().text()
        
        raw_note = self.note_edit.toPlainText().strip()
        selected_note = raw_note if raw_note else None

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