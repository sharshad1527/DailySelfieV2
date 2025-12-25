# gui/startup/startup_window.py
import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QByteArray, QBuffer, QIODevice, QSize, QTimer, QEvent
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, 
    QPushButton, QTextEdit, QButtonGroup, QGridLayout,
    QGraphicsOpacityEffect
)
from PySide6.QtGui import QPixmap, QImage, QPainter, QPainterPath, QFont

# Core
from core.capture import commit_capture_from_bytes
from core.index_api import get_api
from core.logging import get_logger
from core.config import ensure_config, apply_config_to_paths, write_config
from core.paths import get_app_paths

# GUI Components
from gui.startup.window_con import BaseFramelessWindow
from gui.startup.widgets.ghost_slider import GhostOpacitySlider
from gui.startup.widgets.shutter_bar import ShutterBar
from gui.startup.widgets.gif_button import GifButton
from gui.startup.camera.preview import CameraPreviewThread
from gui.qt_logging import QtSignalingHandler, install_qt_logger
from gui.widgets.error_popup import ErrorToast

# Theme 
from gui.theme.theme_vars import theme_vars



class StartupWindow(BaseFramelessWindow):
    """
    Main startup window for Daily Selfie.
    Handles camera preview, ghost overlay, countdown, and capture.
    """
    def __init__(self, allow_retake=False):
        super().__init__(width=1000, height=560)

        self._force_allow_retake = allow_retake

        self._setup_logging()
        self._setup_paths_and_config()
        self._setup_database()

        # State Initialization
        self._current_qimage = None
        self._raw_ghost_image = None
        self._preview_thread = None
        self._countdown_remaining = 0

        initial_timer = self.config.get("behavior", {}).get("timer_duration", 0)
        self._setup_countdown_timer()

        # UI Initialization
        self._build_content_ui(initial_timer)
        self._load_last_photo()
        self._setup_flash_overlay()
        self._connect_signals()

    def _setup_logging(self):
        install_qt_logger()
        self.log_handler = QtSignalingHandler()
        self.log_handler.setLevel(logging.WARNING)
        
        root_logger = get_logger()
        root_logger.addHandler(self.log_handler)
        self.log_handler.emitter.new_log.connect(self._on_log_received)

    def _setup_paths_and_config(self):
        bootstrap_paths = get_app_paths("DailySelfie", ensure=False)
        self.config_path = bootstrap_paths.config_dir / "config.toml"
        self.config = ensure_config(bootstrap_paths.config_dir)
        self.paths = apply_config_to_paths(bootstrap_paths, self.config)
        
        for p in (self.paths.data_dir, self.paths.photos_root, self.paths.logs_dir):
            p.mkdir(parents=True, exist_ok=True)

    def _setup_database(self):
        self.index_api = get_api(self.paths)
        idx = self.index_api._ensure_indexer()
        if idx.count_rows() == 0:
            print("Migrating history from captures.jsonl...")
            self.index_api.migrate_if_needed()

    def _setup_countdown_timer(self):
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)

    def _setup_flash_overlay(self):
        self.flash_overlay = QWidget(self)
        self.flash_overlay.setStyleSheet("background-color: white;")
        self.flash_overlay.hide()
        self.flash_overlay.setAttribute(Qt.WA_TransparentForMouseEvents)

    def _connect_signals(self):
        self.shutter_bar.shutterClicked.connect(self._on_shutter_clicked)
        self.shutter_bar.saveClicked.connect(self._on_save)
        self.shutter_bar.retakeClicked.connect(self._on_retake)
        
        self.shutter_bar.hoverStatus.connect(self._update_toast)
        self.ghost_slider.hoverStatus.connect(self._update_toast)
        self.ghost_slider.valueChanged.connect(self._on_ghost_opacity_change)

    # ---------------------------------------------------------
    # UI Building
    # ---------------------------------------------------------
    def _build_content_ui(self, initial_timer):
        root = QHBoxLayout(self._content)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(16)

        root.addWidget(self._build_left_panel(), 0)
        root.addWidget(self._build_center_panel(), 5)
        root.addWidget(self._build_right_panel(initial_timer), 2)

    def _build_left_panel(self):
        left = QWidget()
        left.setFixedWidth(90)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(2,0,0,0)
        
        self.ghost_slider = GhostOpacitySlider()
        vars = theme_vars()

        label = QLabel("Ghost")
        label.setStyleSheet(f"""
            color: {vars["on_surface_variant"]};
            margin-left: 34px;
        """)
        left_layout.addWidget(label)

        left_layout.addWidget(self.ghost_slider, 1, Qt.AlignLeft)
        return left

    def _build_center_panel(self):
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0,0,0,0)
        
        self.preview_container = QWidget()
        stack_layout = QGridLayout(self.preview_container)
        stack_layout.setContentsMargins(0,0,0,0)

        # Layers: Preview -> Ghost -> Countdown
        self.preview_lbl = QLabel()
        self.preview_lbl.setAlignment(Qt.AlignCenter)
        vars = theme_vars()

        self.preview_lbl.setStyleSheet(f"""
            background-color: {vars["surface_container"]};
            border-radius: 16px;
        """)

        
        self.ghost_lbl = QLabel()
        self.ghost_lbl.setAlignment(Qt.AlignCenter)
        self.ghost_lbl.setStyleSheet("background: transparent;")
        self.ghost_effect = QGraphicsOpacityEffect(self.ghost_lbl)
        self.ghost_effect.setOpacity(0.3)
        self.ghost_lbl.setGraphicsEffect(self.ghost_effect)
        
        self.countdown_lbl = QLabel("")
        self.countdown_lbl.setAlignment(Qt.AlignCenter)
        self.countdown_lbl.setStyleSheet(f"""
            background: transparent;
            color: {vars["on_surface"]};
            font-weight: bold;
        """)

        self.countdown_lbl.setFont(QFont("Arial", 96))
        self.countdown_lbl.hide()

        stack_layout.addWidget(self.preview_lbl, 0, 0)
        stack_layout.addWidget(self.ghost_lbl, 0, 0)
        stack_layout.addWidget(self.countdown_lbl, 0, 0)

        center_layout.addWidget(self.preview_container, 1)
        return center

    def _build_right_panel(self, initial_timer):
        right = QWidget()
        right_layout = QVBoxLayout(right)
        
        # Mood
        self.mood_group = QButtonGroup(self)
        moods_lo = QHBoxLayout()
        moods_lo.setSpacing(12)

        ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons" / "mood"
        mood_data = [
            ("cool.gif", "Great"), 
            ("smile.gif", "Good"), 
            ("neutral.gif", "Neutral"), 
            ("sad.gif", "Bad"), 
            ("sosad.gif", "Awful")
        ]

        vars = theme_vars()

        emoji_style = f"""
            QPushButton {{
                background-color: transparent;
                border: 2px solid {vars["outline_variant"]};
                border-radius: 20px;
            }}
            QPushButton:hover {{
                border: 2px solid {vars["outline"]};
            }}
            QPushButton:checked {{
                border: 2px solid {vars["primary"]};
            }}
        """
                
        for filename, desc in mood_data:
            gif_path = str(ASSETS_DIR / filename)
            b = GifButton(gif_path)
            b.setFixedSize(44, 44)
            b.setIconSize(QSize(32, 32))
            b.setStyleSheet(emoji_style)
            b.setProperty("toast_text", desc)
            b.installEventFilter(self)
            
            self.mood_group.addButton(b)
            moods_lo.addWidget(b)

        # Note
        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("Anything about today...")
        self.note_edit.setFixedHeight(100)
        vars = theme_vars()

        self.note_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {vars["surface_container_low"]};
                border: 2px solid transparent;
                border-radius: 8px;
                padding: 8px;
                color: {vars["on_surface"]};
            }}
            QTextEdit:hover {{
                border: 2px solid {vars["outline"]};
                background-color: {vars["surface_container"]};
            }}
            QTextEdit:focus {{
                border: 2px solid {vars["primary"]};
                background-color: {vars["surface_container"]};
            }}
        """)

        
        self.toast_msg = QLabel("")
        self.toast_msg.setAlignment(Qt.AlignCenter)
        self.toast_msg.setFixedHeight(30)
        self.toast_msg.setStyleSheet("background: transparent; color: transparent;")

        self.shutter_bar = ShutterBar(initial_timer=initial_timer)

        right_layout.addWidget(QLabel("Mood", styleSheet="color:#B0B0B0"))
        right_layout.addLayout(moods_lo)
        right_layout.addWidget(QLabel("Note", styleSheet="color:#B0B0B0"))
        right_layout.addWidget(self.note_edit)
        
        right_layout.addSpacing(80) 
        right_layout.addWidget(self.toast_msg, alignment=Qt.AlignCenter)
        right_layout.addSpacing(8)
        right_layout.addWidget(self.shutter_bar, alignment=Qt.AlignCenter)
        right_layout.addStretch()
        return right

    # ---------------------------------------------------------
    # Logic & Events
    # ---------------------------------------------------------
    def _on_log_received(self, log_entry):
        level = log_entry["level"]
        msg = log_entry["msg"]
        exc = log_entry.get("exc")

        popup = ErrorToast(self, level=level, message=msg, traceback=exc)

        geo = self.geometry()
        x = geo.x() + (geo.width() - popup.width()) // 2
        y = geo.y() + (geo.height() - popup.height()) // 2
        popup.move(x, y)
        popup.show()

    def _load_last_photo(self):
        try:
            entry = self.index_api.get_last_photo()
            if entry and entry.get("path"):
                p = Path(entry["path"])
                if p.exists():
                    img = QImage(str(p))
                    if not img.isNull():
                        self._raw_ghost_image = img.convertToFormat(QImage.Format_Grayscale8)
                        self._update_ghost_visuals()
        except Exception as e:
            print(f"Ghost load error: {e}")

    def _update_ghost_visuals(self):
        if self._raw_ghost_image and self.ghost_lbl.isVisible():
            pix = self._process_image_for_display(self._raw_ghost_image)
            if pix:
                self.ghost_lbl.setPixmap(pix)

    def _on_ghost_opacity_change(self, value):
        self.ghost_effect.setOpacity(value / 100.0)

    def _process_image_for_display(self, source_image):
        """
        Scales and rounds the corners of the image.
        Optimized to fail fast if dimensions are invalid.
        """
        container_w = self.preview_lbl.width()
        container_h = self.preview_lbl.height()
        if container_w <= 0 or container_h <= 0: return None

        margin = 8
        target_w = container_w - (margin * 2)
        target_h = container_h - (margin * 2)
        if target_w <= 0: return None

        # Scale
        # Note: Optimization could be done here by caching the scaled pixmap
        # if the container size hasn't changed, but for a live preview we need to redraw.
        pix = QPixmap.fromImage(source_image)
        scaled = pix.scaled(QSize(target_w, target_h), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        
        crop_x = (scaled.width() - target_w) // 2
        crop_y = (scaled.height() - target_h) // 2
        cropped = scaled.copy(crop_x, crop_y, target_w, target_h)

        final_pix = QPixmap(QSize(container_w, container_h))
        final_pix.fill(Qt.transparent)
        
        painter = QPainter(final_pix)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw rounded rect mask
        path = QPainterPath()
        path.addRoundedRect(margin, margin, target_w, target_h, 12, 12)
        
        painter.setClipPath(path)
        painter.drawPixmap(margin, margin, cropped)
        painter.end()
        return final_pix

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Enter:
            text = obj.property("toast_text")
            if text:
                self._update_toast(text)
        elif event.type() == QEvent.Leave:
            if obj.property("toast_text"):
                self._update_toast("")
        return super().eventFilter(obj, event)

    def _update_toast(self, text):
        if text:
            self.toast_msg.setText(text)
            vars = theme_vars()

            self.toast_msg.setStyleSheet(f"""
                background-color: {vars["surface_container_high"]};
                color: {vars["on_surface_variant"]};
                border: 2px solid {vars["primary"]};
                border-radius: 12px;
                padding: 0 12px;
                font-size: 12px;
                font-weight: 600;
            """)

        else:
            self.toast_msg.setText("")
            self.toast_msg.setStyleSheet("background: transparent; color: transparent;")

    def resizeEvent(self, event):
        self.flash_overlay.resize(self.size())
        if self._raw_ghost_image:
            self._update_ghost_visuals()
        super().resizeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._start_preview()
        if self._raw_ghost_image:
            self._update_ghost_visuals()

    def closeEvent(self, event):
        try:
            current_timer = self.shutter_bar.get_timer_value()
            if self.config["behavior"].get("timer_duration") != current_timer:
                self.config["behavior"]["timer_duration"] = current_timer
                write_config(self.config_path, self.config)
        except Exception:
            pass
        self._stop_preview()
        if self.index_api:
            self.index_api.close()
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
        pix = self._process_image_for_display(qimg)
        if pix:
            self.preview_lbl.setPixmap(pix)

    def _on_shutter_clicked(self):
        if not self._current_qimage: return
        delay = self.shutter_bar.get_timer_value()
        if delay == 0:
            self._capture_now()
        else:
            self._start_countdown(delay)

    def _start_countdown(self, seconds):
        self.ghost_lbl.hide() 
        self.ghost_slider.setEnabled(False)
        self.ghost_slider.setStyleSheet("opacity: 0.0;")
        self.shutter_bar.setEnabled(False)
        self._countdown_remaining = seconds
        self.countdown_lbl.setText(str(seconds))
        self.countdown_lbl.show()
        self._countdown_timer.start(1000)

    def _on_countdown_tick(self):
        self._countdown_remaining -= 1
        if self._countdown_remaining > 0:
            self.countdown_lbl.setText(str(self._countdown_remaining))
        else:
            self._countdown_timer.stop()
            self.countdown_lbl.hide()
            self.shutter_bar.setEnabled(True)
            self._capture_now()

    def _capture_now(self):
        if self.shutter_bar.is_flash_on():
            self.flash_overlay.show()
            self.flash_overlay.raise_()
            QTimer.singleShot(800, self._perform_freeze)
        else:
            self._perform_freeze()

    def _perform_freeze(self):
        self.flash_overlay.hide()
        self._stop_preview()
        self.ghost_lbl.hide()
        self.shutter_bar.setReviewMode(True)
        self.ghost_slider.setEnabled(False) 
        self.ghost_slider.setStyleSheet("opacity: 0.3;")

    def _on_retake(self):
        self.shutter_bar.setReviewMode(False)
        self.ghost_slider.setEnabled(True)
        self.ghost_slider.setStyleSheet("")
        if self._raw_ghost_image:
            self.ghost_lbl.show()
            self._update_ghost_visuals()
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
            selected_mood = self.mood_group.checkedButton().property("toast_text")
        
        raw_note = self.note_edit.toPlainText().strip()
        selected_note = raw_note if raw_note else None

        beh = self.config.get("behavior", {})
        
        # Use the override if present, otherwise fall back to config
        effective_allow_retake = self._force_allow_retake or beh.get("allow_retake", False)

        result = commit_capture_from_bytes(
            self.paths,
            jpeg_bytes=jpg_data,
            width=self._current_qimage.width(),
            height=self._current_qimage.height(),
            mood=selected_mood,
            notes=selected_note,
            allow_retake=effective_allow_retake
        )

        if result["success"]:
            print(f"Saved to: {result['path']}")
            self.close()
        else:
            print(f"Save Failed: {result['error']}")
