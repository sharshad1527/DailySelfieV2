# gui/dashboard/pages/selfie.py
import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QByteArray, QBuffer, QIODevice, QSize, QTimer, QEvent, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, 
    QPushButton, QTextEdit, QButtonGroup, QGridLayout,
    QGraphicsOpacityEffect, QFrame, QSizePolicy
)
from PySide6.QtGui import QPixmap, QImage, QPainter, QPainterPath, QFont, QIcon, QMovie

# Core
from core.capture import check_if_already_captured, commit_capture_from_bytes
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
from gui.widgets.motion import install_motion_wrapper
from gui.widgets.pixmap_utils import active_dpr, recolored_icon, scaled_cover_crop

# Theme 
from gui.theme.theme_vars import theme_vars



# Mood name to GIF mapping
MOOD_GIF_MAP = {
    "Great": "cool.gif",
    "Good": "smile.gif",
    "Neutral": "neutral.gif",
    "Bad": "sad.gif",
    "Awful": "sosad.gif",
}

class SelfiePage(QWidget):
    """
    Main startup window for Daily Selfie.
    Handles camera preview, ghost overlay, countdown, and capture.
    """
    # Signal emitted when a photo is saved successfully (for dashboard refresh)
    photoSaved = Signal()
    def __init__(self, allow_retake=False):
        super().__init__()

        self.setContentsMargins(10,10,10,20)

        # Incoming-only page transitions animate this wrapper (motion-system.md)
        self._motion_wrapper = install_motion_wrapper(self)

        self._force_allow_retake = allow_retake

        self._setup_logging()
        self._setup_paths_and_config()
        self._setup_database()

        # State Initialization
        self._current_qimage = None
        self._raw_ghost_image = None
        self._preview_thread = None
        self._stopping_threads = []
        self._countdown_remaining = 0
        self._photo_saved = False  # True when showing a saved photo
        self._review_mode = False  # True when in freeze/review mode (before saving)
        self._saved_metadata = {}  # Metadata of the saved photo
        self._metadata_panel = None  # Reference to metadata panel widget

        initial_timer = self.config.get("behavior", {}).get("timer_duration", 0)
        self._setup_countdown_timer()

        # UI Initialization
        self._build_content_ui(initial_timer)
        self._load_last_photo()
        self._setup_flash_overlay()
        self._connect_signals()

        # Apply initial theme & connect listener
        self._apply_theme()
        v = theme_vars()
        if hasattr(v, "_controller"):
             v._controller.themeChanged.connect(self._on_theme_changed)

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
            get_logger("gui.selfie").info("Migrating history from captures.jsonl...")
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

    def _on_theme_changed(self):
        self._apply_theme()
        self.update()

    def _apply_theme(self):
        v = theme_vars()
        
        # 2. Labels
        lbl_style = f"color: {v['on_surface_variant']};"
        
        self.label_ghost.setStyleSheet(f"color: {v['on_surface_variant']};")
        self.label_mood.setStyleSheet(lbl_style)
        self.label_note.setStyleSheet(lbl_style)

        # 3. Preview Container
        self.preview_lbl.setStyleSheet(f"""
            background-color: {v["surface_container"]};
            border-radius: 16px;
        """)
        
        # 4. Countdown
        self.countdown_lbl.setStyleSheet(f"""
            background: transparent;
            color: {v["on_surface"]};
            font-weight: bold;
        """)

        # 5. Note Edit
        self.note_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {v["surface_container_low"]};
                border: 2px solid {v["outline_variant"]};
                border-radius: 8px;
                padding: 8px;
                color: {v["on_surface"]};
            }}
            QTextEdit:hover {{
                border: 2px solid {v["outline"]};
                background-color: {v["surface_container"]};
            }}
            QTextEdit:focus {{
                border: 2px solid {v["primary"]};
                background-color: {v["surface_container"]};
            }}
        """)

        # 6. Mood Buttons
        emoji_style = f"""
            QPushButton {{
                background-color: transparent;
                border: 2px solid {v["outline_variant"]};
                border-radius: 18px;
            }}
            QPushButton:hover {{
                border: 2px solid {v["outline"]};
            }}
            QPushButton:checked {{
                border: 2px solid {v["primary"]};
            }}
        """
        for btn in self.mood_group.buttons():
            btn.setStyleSheet(emoji_style)

    # ---------------------------------------------------------
    # UI Building
    # ---------------------------------------------------------
    def _build_content_ui(self, initial_timer):
        root = QHBoxLayout(self._motion_wrapper)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(16)

        root.addWidget(self._build_left_panel(), 0)
        root.addWidget(self._build_center_panel(), 5)
        root.addWidget(self._build_right_panel(initial_timer), 2)

    def _build_left_panel(self):
        left = QWidget()
        left.setFixedWidth(90)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0,0,0,0) # Removed Margin
        
        self.ghost_slider = GhostOpacitySlider()

        self.label_ghost = QLabel("Ghost")
        self.label_ghost.setAlignment(Qt.AlignCenter)
        
        # Add both widgets aligned to the same horizontal position
        left_layout.addWidget(self.label_ghost, 0, Qt.AlignHCenter)
        left_layout.addWidget(self.ghost_slider, 1, Qt.AlignHCenter)
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
        # Style set in _apply_theme

        
        self.ghost_lbl = QLabel()
        self.ghost_lbl.setAlignment(Qt.AlignCenter)
        self.ghost_lbl.setStyleSheet("background: transparent;")
        self.ghost_effect = QGraphicsOpacityEffect(self.ghost_lbl)
        self.ghost_effect.setOpacity(0.3)
        self.ghost_lbl.setGraphicsEffect(self.ghost_effect)
        
        self.countdown_lbl = QLabel("")
        self.countdown_lbl.setAlignment(Qt.AlignCenter)
        self.countdown_lbl = QLabel("")
        self.countdown_lbl.setAlignment(Qt.AlignCenter)
        # Style set in _apply_theme

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

        mood_path = get_app_paths("DailySelfie", ensure=False)
        ASSETS_DIR = mood_path.project_root / "gui" / "assets" / "icons" /"mood"
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
                border-radius: 18px;
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
                border: 2px solid {vars["outline_variant"]};
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

        self.label_mood = QLabel("Mood")
        self.label_note = QLabel("Note")

        right_layout.addWidget(self.label_mood)
        right_layout.addLayout(moods_lo)
        right_layout.addWidget(self.label_note)
        right_layout.addWidget(self.note_edit)
        
        # Spacer before toast - can be resized when metadata is shown
        from PySide6.QtWidgets import QSpacerItem
        self._toast_spacer = QSpacerItem(0, 80, QSizePolicy.Minimum, QSizePolicy.Fixed)
        right_layout.addItem(self._toast_spacer)
        
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

        geo = self.window().geometry()
        x = geo.x() + (geo.width() - popup.width()) // 2
        y = geo.y() + (geo.height() - popup.height()) // 3
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
            get_logger("gui.selfie").info("Ghost load error: %s", e)

    def _update_ghost_visuals(self):
        if self._raw_ghost_image and self.ghost_lbl.isVisible():
            pix = self._process_image_for_display(self._raw_ghost_image)
            if pix:
                self.ghost_lbl.setPixmap(pix)

    def _on_ghost_opacity_change(self, value):
        self.ghost_effect.setOpacity(value / 100.0)

    def _process_image_for_display(self, source_image):
        """
        Scales and rounds the corners of the image (dpr-aware).
        Optimized to fail fast if dimensions are invalid.
        """
        container_w = self.preview_lbl.width()
        container_h = self.preview_lbl.height()
        if container_w <= 0 or container_h <= 0: return None

        margin = 8
        target_w = container_w - (margin * 2)
        target_h = container_h - (margin * 2)
        if target_w <= 0: return None

        dpr = self.devicePixelRatioF()

        # Scale + crop in device pixels so HiDPI stays sharp
        pix = QPixmap.fromImage(source_image)
        cropped = scaled_cover_crop(pix, target_w, target_h, dpr)

        cw = max(1, round(container_w * dpr))
        ch = max(1, round(container_h * dpr))
        final_pix = QPixmap(cw, ch)
        final_pix.setDevicePixelRatio(dpr)
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
        
        # Check if today's photo already exists
        today_photo = self._check_today_photo_exists()
        
        if today_photo:
            # Today's photo exists - show it with metadata
            if not self._photo_saved:
                self._load_and_show_today_photo(today_photo)
        else:
            # No photo today - reset any stale review state and start camera
            if self._review_mode and not self._photo_saved:
                # User was in review mode but switched tabs without saving
                # Reset to camera mode
                self._reset_to_camera_mode()
            elif not self._photo_saved:
                self._start_preview()
                if self._raw_ghost_image:
                    self._update_ghost_visuals()

    def _check_today_photo_exists(self):
        """Check if today's photo exists. Returns path if exists, None otherwise."""
        try:
            # Timezone-aware LOCAL-day lookup (UTC-named files) via capture core.
            exists, today_path = check_if_already_captured(self.paths)
            if exists and today_path and today_path.exists():
                return today_path
        except Exception as e:
            get_logger("gui.selfie").warning("Error checking today's photo: %s", e)
        return None
    
    def _load_and_show_today_photo(self, photo_path):
        """Load and display today's existing photo."""
        try:
            # Load the image
            img = QImage(str(photo_path))
            if img.isNull():
                return
            
            self._current_qimage = img
            
            # Get metadata from index
            selfie_id = photo_path.stem
            try:
                metadata = self.index_api.get_item(selfie_id) or {}
            except Exception:
                metadata = {}
            
            self._saved_metadata = {
                "mood": metadata.get("mood"),
                "notes": metadata.get("notes"),
                "width": metadata.get("width") or img.width(),
                "height": metadata.get("height") or img.height(),
                "path": str(photo_path),
                "ts": metadata.get("ts"),
            }
            
            # Display the photo
            pix = self._process_image_for_display(img)
            if pix:
                self.preview_lbl.setPixmap(pix)
            
            self._set_photo_taken_state()
            
        except Exception as e:
            get_logger("gui.selfie").warning("Error loading today's photo: %s", e)
            self._start_preview()
    
    def _reset_to_camera_mode(self):
        """Reset from review mode back to camera mode."""
        self._review_mode = False
        self.shutter_bar.setReviewMode(False)
        self.ghost_slider.setEnabled(True)
        if self._raw_ghost_image:
            self.ghost_lbl.show()
            self._update_ghost_visuals()
        self._current_qimage = None
        self._start_preview()
    
    def activate(self):
        """
        Public method to activate/refresh the selfie page.
        Called when programmatically switching to this tab.
        Runs the same logic as showEvent.
        """
        # Check if today's photo already exists
        today_photo = self._check_today_photo_exists()
        
        if today_photo:
            # Today's photo exists - show it with metadata
            if not self._photo_saved:
                self._load_and_show_today_photo(today_photo)
        else:
            # No photo today - reset any stale review state and start camera
            if self._review_mode and not self._photo_saved:
                self._reset_to_camera_mode()
            elif not self._photo_saved:
                self._start_preview()
                if self._raw_ghost_image:
                    self._update_ghost_visuals()

    def hideEvent(self, event):
        """Stop camera when tab is switched away."""
        self._stop_preview()
        super().hideEvent(event)

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
        self._preview_thread.error_occurred.connect(
            lambda e: get_logger("gui.selfie").warning("Camera preview error: %s", e)
        )
        self._preview_thread.start()

    def _stop_preview(self):
        if self._preview_thread:
            thread = self._preview_thread
            self._preview_thread = None
            thread.stop()
            if thread.isRunning():
                # Keep the reference so the live thread is never garbage-collected
                self._stopping_threads.append(thread)
                thread.finished.connect(lambda: self._stopping_threads.remove(thread))

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
        self._review_mode = True  # Track that we're in review mode
        self.shutter_bar.setReviewMode(True)
        self.ghost_slider.setEnabled(False) 

    def _on_retake(self):
        # Non-destructive: nothing on disk or in the index is removed here.
        # The previous photo is only retired inside commit_capture_from_bytes
        # AFTER the replacement is safely written (swap-after-save).
        
        # Reset photo-saved state
        self._photo_saved = False
        self._review_mode = False
        self._saved_metadata = {}
        
        # Remove metadata panel if it exists
        if self._metadata_panel:
            self._metadata_panel.deleteLater()
            self._metadata_panel = None
        
        # Reset mood selection
        checked_btn = self.mood_group.checkedButton()
        if checked_btn:
            self.mood_group.setExclusive(False)
            checked_btn.setChecked(False)
            self.mood_group.setExclusive(True)
        
        # Reset note text
        self.note_edit.clear()
        
        # Restore toast spacer height
        from PySide6.QtWidgets import QSizePolicy
        if hasattr(self, '_toast_spacer'):
            self._toast_spacer.changeSize(0, 80, QSizePolicy.Minimum, QSizePolicy.Fixed)
            # Real content layout lives on the motion wrapper (install_motion_wrapper)
            root_layout = self._motion_wrapper.layout()
            if root_layout and root_layout.count() > 2:
                right_widget = root_layout.itemAt(2).widget()
                if right_widget and right_widget.layout():
                    right_widget.layout().invalidate()
        
        # Show shutter bar again
        self.shutter_bar.show()
        self.shutter_bar.setReviewMode(False)
        self.ghost_slider.setEnabled(True)
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
        quality = self.config.get("behavior", {}).get("quality", 100)
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
            get_logger("gui.selfie").info("Saved to: %s", result["path"])
            # Instead of closing, show the photo-taken state with metadata
            self._saved_metadata = {
                "mood": selected_mood,
                "notes": selected_note,
                "width": self._current_qimage.width(),
                "height": self._current_qimage.height(),
                "path": result.get("path"),
                "ts": result.get("ts"),  # Capture timestamp if available
            }
            self._set_photo_taken_state()
            # Emit signal for dashboard refresh
            self.photoSaved.emit()
        else:
            get_logger("gui.selfie").warning(
                "Save failed: %s", result.get("error", "unknown error")
            )

    def _set_photo_taken_state(self):
        """Display saved photo with metadata panel and retake button."""
        self._photo_saved = True
        
        # Hide shutter bar and show metadata panel
        self.shutter_bar.hide()
        
        # Reduce toast spacer height to move toast up
        from PySide6.QtWidgets import QSizePolicy
        self._toast_spacer.changeSize(0, 12, QSizePolicy.Minimum, QSizePolicy.Fixed)
        
        # Build and show metadata panel in the right panel area
        self._metadata_panel = self._build_metadata_panel()
        
        # Find the right panel and add metadata panel
        # The right panel is at index 2 of the motion wrapper's inner layout
        # (self.layout() is the 1-item HBox holding only the wrapper)
        root_layout = self._motion_wrapper.layout()
        if root_layout and root_layout.count() > 2:
            right_widget = root_layout.itemAt(2).widget()
            if right_widget:
                right_layout = right_widget.layout()
                if right_layout:
                    # Insert metadata panel before the stretch
                    right_layout.insertWidget(right_layout.count() - 1, self._metadata_panel)
                    # Force layout update
                    right_layout.invalidate()

    def _build_metadata_panel(self):
        """Build the metadata panel showing saved photo info."""
        v = theme_vars()
        
        panel = QFrame()
        panel.setObjectName("MetadataPanel")
        panel.setStyleSheet(f"""
            QFrame#MetadataPanel {{
                background-color: {v['surface_container_low']};
                border-radius: 16px;
            }}
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)  # Reduced spacing
        
        # Status text
        status_label = QLabel("✓ Photo saved!")
        status_label.setStyleSheet(f"""
            color: {v['primary']};
            font-size: 14px;
            font-weight: 600;
        """)
        layout.addWidget(status_label)
        
        # Time taken
        from datetime import datetime
        time_str = datetime.now().strftime("%I:%M %p")
        time_row = QHBoxLayout()
        time_row.setSpacing(6)
        
        saved_icon = self._create_colored_icon("save_clock.svg", v.qcolor('on_surface_variant'))
        time_icon = QLabel()
        time_icon.setPixmap(saved_icon.pixmap(20, 20))
        time_icon.setFixedWidth(20)
        time_row.addWidget(time_icon)
        
        time_label = QLabel(time_str)
        time_label.setStyleSheet(f"""
            color: {v['on_surface']};
            font-size: 11px;
            font-weight: 500;
        """)
        time_row.addWidget(time_label)
        time_row.addStretch()
        layout.addLayout(time_row)
        
        # Resolution
        width = self._saved_metadata.get("width")
        height = self._saved_metadata.get("height")
        if width and height:
            res_row = QHBoxLayout()
            res_row.setSpacing(6)
            
            aspect_icon = self._create_colored_icon("aspect_ratio.svg", v.qcolor('on_surface_variant'))
            res_icon = QLabel()
            res_icon.setPixmap(aspect_icon.pixmap(20, 20))
            res_icon.setFixedWidth(20)
            res_row.addWidget(res_icon)
            
            res_label = QLabel(f"{width} × {height}")
            res_label.setStyleSheet(f"""
                color: {v['on_surface']};
                font-size: 11px;
            """)
            res_row.addWidget(res_label)
            res_row.addStretch()
            layout.addLayout(res_row)
        
        # Separator before mood
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet(f"background-color: {v['outline_variant']};")
        separator.setFixedHeight(1)
        layout.addWidget(separator)
        
        # Mood section
        mood_section_label = QLabel("Mood")
        mood_section_label.setStyleSheet(f"""
            color: {v['on_surface_variant']};
            font-size: 10px;
            font-weight: 500;
        """)
        layout.addWidget(mood_section_label)
        
        mood_value = self._saved_metadata.get("mood")
        if mood_value and mood_value in MOOD_GIF_MAP:
            mood_row = QHBoxLayout()
            mood_row.setSpacing(8)
            
            mood_gif_label = QLabel()
            mood_gif_label.setFixedSize(32, 32)
            mood_gif_label.setAlignment(Qt.AlignCenter)
            
            mood_path = get_app_paths("DailySelfie", ensure=False)
            gif_path = str(mood_path.project_root / "gui" / "assets" / "icons" / "mood" / MOOD_GIF_MAP[mood_value])
            self._mood_movie = QMovie(gif_path)
            if self._mood_movie.isValid():
                self._mood_movie.setScaledSize(QSize(22, 22))
                mood_gif_label.setMovie(self._mood_movie)
                self._mood_movie.start()
            
            mood_gif_label.setStyleSheet(f"""
                background-color: {v['surface_container_low']};
                border: 2px solid {v['outline_variant']};
                border-radius: 8px;
            """)
            mood_row.addWidget(mood_gif_label)
            
            mood_text = QLabel(mood_value)
            mood_text.setStyleSheet(f"""
                color: {v['on_surface']};
                font-size: 11px;
                font-weight: 500;
            """)
            mood_row.addWidget(mood_text)
            mood_row.addStretch()
            layout.addLayout(mood_row)
        else:
            no_mood = QLabel("No mood selected")
            no_mood.setStyleSheet(f"""
                color: {v['on_surface_variant']};
                font-size: 10px;
                font-style: italic;
            """)
            layout.addWidget(no_mood)
        
        # Separator before notes
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.HLine)
        separator2.setStyleSheet(f"background-color: {v['outline_variant']};")
        separator2.setFixedHeight(1)
        layout.addWidget(separator2)
        
        # Notes section
        notes_section_label = QLabel("Notes")
        notes_section_label.setStyleSheet(f"""
            color: {v['on_surface_variant']};
            font-size: 10px;
            font-weight: 500;
        """)
        layout.addWidget(notes_section_label)
        
        note_value = self._saved_metadata.get("notes")
        if note_value:
            note_text = note_value[:50] + "..." if len(note_value) > 50 else note_value
            note_row = QHBoxLayout()
            note_row.setSpacing(6)
            
            notes_icon = self._create_colored_icon("notes.svg", v.qcolor('on_surface_variant'))
            note_icon_label = QLabel()
            note_icon_label.setPixmap(notes_icon.pixmap(16, 16))
            note_icon_label.setFixedWidth(16)
            note_row.addWidget(note_icon_label)
            
            note_label = QLabel(note_text)
            note_label.setWordWrap(True)
            note_label.setStyleSheet(f"""
                color: {v['on_surface_variant']};
                font-size: 10px;
            """)
            note_row.addWidget(note_label)
            note_row.addStretch()
            layout.addLayout(note_row)
        else:
            no_notes = QLabel("No notes")
            no_notes.setStyleSheet(f"""
                color: {v['on_surface_variant']};
                font-size: 10px;
                font-style: italic;
            """)
            layout.addWidget(no_notes)
        
        # Retake button
        retake_btn = QPushButton("Retake Photo")
        retake_btn.setObjectName("RetakeButton")
        retake_btn.setCursor(Qt.PointingHandCursor)
        retake_btn.setFixedHeight(40)
        
        retake_icon = self._create_colored_icon("retake_image.svg", v.qcolor('on_surface_variant'))
        retake_btn.setIcon(retake_icon)
        retake_btn.setIconSize(QSize(16, 16))
        
        retake_btn.setStyleSheet(f"""
            QPushButton#RetakeButton {{
                background-color: {v['surface_container_high']};
                color: {v['on_surface_variant']};
                border: 1px solid {v['outline_variant']};
                border-radius: 20px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton#RetakeButton:hover {{
                background-color: {v['surface_container_highest']};
                border: 1px solid {v['outline']};
                color: {v['on_surface']};
            }}
        """)
        retake_btn.clicked.connect(self._on_retake)
        layout.addWidget(retake_btn)
        
        return panel

    def _create_colored_icon(self, icon_name: str, qcolor):
        """Loads an SVG and repaints it with the given QColor (HiDPI-aware)."""
        mood_path = get_app_paths("DailySelfie", ensure=False)
        ICONS_DIR = mood_path.project_root / "gui" / "assets" / "icons"
        return recolored_icon(ICONS_DIR / icon_name, qcolor, active_dpr(self))

