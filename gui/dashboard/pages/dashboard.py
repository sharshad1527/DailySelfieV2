# gui/dashboard/pages/dashboard.py
from datetime import datetime
from pathlib import Path
from typing import Tuple

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap, QIcon, QPainter, QMovie
from PySide6.QtWidgets import QFrame, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QSizePolicy

from gui.theme.theme_vars import theme_vars
from core.storage import last_image_for_date, delete_path
from core.paths import get_app_paths
from core.index_api import get_api
from core.streak import calculate_streaks

# Asset paths
_paths = get_app_paths("DailySelfie", ensure=False)
ICONS_DIR = _paths.project_root / "gui" / "assets" / "icons"
MOOD_DIR = ICONS_DIR / "mood"

# Mood name to GIF mapping
MOOD_GIF_MAP = {
    "Great": "cool.gif",
    "Good": "smile.gif",
    "Neutral": "neutral.gif",
    "Bad": "sad.gif",
    "Awful": "sosad.gif",
}

class RecentSelfieCarouselPlaceholder(QFrame):
    """
    Placeholder for recent selfie carousel (horizontal list).
    """
    def __init__(self):
        super().__init__()

        vars = theme_vars()

        self.setObjectName("RecentSelfieCarousel")
        self.setFixedHeight(120)

        self.setStyleSheet(f"""
            QFrame#RecentSelfieCarousel {{
                background-color: {vars['surface_container_low']};
                border-radius: 12px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        label = QLabel("Recent Selfies (Carousel)")
        label.setAlignment(Qt.AlignCenter)

        layout.addWidget(label)


class TodaySelfieCard(QFrame):
    """
    Primary dashboard card showing today's selfie (image fills the card).
    Emits image_resized signal with the displayed image height.
    """
    image_resized = Signal(int)  # Emits the displayed image height
    
    def __init__(self):
        super().__init__()
        self._vars = theme_vars()
        self._image_path = None
        self._metadata = {}
        self._current_image_height = 0

        self.setObjectName("TodaySelfieCard")
        self.setMinimumHeight(250)
        self.setMinimumWidth(250)

        self.setStyleSheet(f"""
            QFrame#TodaySelfieCard {{
                background-color: {self._vars['surface_container_low']};
                border-radius: 16px;
            }}
        """)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(0)

        self._content_widget = None

        self._check_today_selfie()

    def _check_today_selfie(self):
        """Check if today's selfie exists and set the appropriate state."""
        try:
            app_paths = get_app_paths("DailySelfie", ensure=True)
            # Photos are stored in data_dir/photos, not photos_root
            photos_root = Path(app_paths.data_dir) / "photos"
            today = datetime.now()
            
            today_selfie_path = last_image_for_date(photos_root, today)
            
            if today_selfie_path and today_selfie_path.exists():
                # Get metadata from index API
                selfie_id = today_selfie_path.stem  # e.g., "2026-01-02_040733"
                try:
                    api = get_api(app_paths)
                    metadata = api.get_item(selfie_id) or {}
                except Exception:
                    metadata = {}
                
                self.set_taken_state(today_selfie_path, metadata)
            else:
                self.set_empty_state()
        except Exception:
            # If anything goes wrong, default to empty state
            self.set_empty_state()

    def _clear_content(self):
        """Remove existing content widget and selfie label if any."""
        if self._content_widget:
            self._layout.removeWidget(self._content_widget)
            self._content_widget.deleteLater()
            self._content_widget = None
        
        # Also remove selfie_label if it exists (added directly in set_taken_state)
        if hasattr(self, 'selfie_label') and self.selfie_label:
            self._layout.removeWidget(self.selfie_label)
            self.selfie_label.deleteLater()
            self.selfie_label = None
        
        # Reset internal state
        self._image_path = None
        self._metadata = {}
        self._current_image_height = 0

    def set_empty_state(self):
        """
        Configure card UI for 'no selfie taken today'.
        Shows primary button and secondary caption.
        """
        self._clear_content()

        # Create container for empty state content
        self._content_widget = QWidget()
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        # Add stretch to center content vertically
        content_layout.addStretch()

        # Primary button: "Take today's selfie"
        self.take_selfie_btn = QPushButton("Take today's selfie")
        self.take_selfie_btn.setObjectName("TakeSelfieButton")
        self.take_selfie_btn.setCursor(Qt.PointingHandCursor)
        self.take_selfie_btn.setFixedHeight(48)
        self.take_selfie_btn.setStyleSheet(f"""
            QPushButton#TakeSelfieButton {{
                background-color: {self._vars['primary']};
                color: {self._vars['on_primary']};
                border: none;
                border-radius: 24px;
                padding: 0 24px;
                font-size: 14px;
                font-weight: 500;
            }}
            QPushButton#TakeSelfieButton:hover {{
                background-color: {self._vars['primary']};
                opacity: 0.92;
            }}
            QPushButton#TakeSelfieButton:pressed {{
                background-color: {self._vars['primary']};
                opacity: 0.85;
            }}
        """)
        content_layout.addWidget(self.take_selfie_btn, alignment=Qt.AlignCenter)

        # Secondary text: "Capture your day"
        self.caption_label = QLabel("Capture your day")
        self.caption_label.setObjectName("CaptionLabel")
        self.caption_label.setAlignment(Qt.AlignCenter)
        self.caption_label.setStyleSheet(f"""
            QLabel#CaptionLabel {{
                color: {self._vars['on_surface_variant']};
                font-size: 12px;
            }}
        """)
        content_layout.addWidget(self.caption_label)

        # Add stretch to center content vertically
        content_layout.addStretch()

        self._layout.addWidget(self._content_widget)

    def _create_colored_icon(self, icon_name: str, qcolor):
        """
        Loads an SVG and repaints it with the given QColor.
        """
        path = ICONS_DIR / icon_name
        if not path.exists():
            return QIcon()

        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return QIcon()

        colored_pixmap = QPixmap(pixmap.size())
        colored_pixmap.fill(Qt.transparent)

        painter = QPainter(colored_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(0, 0, pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(colored_pixmap.rect(), qcolor)
        painter.end()

        return QIcon(colored_pixmap)

    def _create_rounded_pixmap(self, pixmap: QPixmap, radius: int) -> QPixmap:
        """
        Create a pixmap with rounded corners by clipping.
        """
        from PySide6.QtGui import QPainterPath
        
        rounded = QPixmap(pixmap.size())
        rounded.fill(Qt.transparent)
        
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        path = QPainterPath()
        path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), radius, radius)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        
        return rounded

    def set_taken_state(self, image_path: Path, metadata: dict = None):
        """
        Configure card to show just the selfie image, filling the entire card.
        """
        self._clear_content()
        self._metadata = metadata or {}
        self._image_path = image_path

        # self._content_widget = QWidget()
        # self._content_widget.setStyleSheet("background-color: transparent;")
        # content_layout = QVBoxLayout(self._content_widget)
        # content_layout.setContentsMargins(0, 0, 0, 0)
        # content_layout.setSpacing(0)
        
        self.selfie_label = QLabel()
        self.selfie_label.setAlignment(Qt.AlignCenter)
        self.selfie_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.selfie_label.setStyleSheet("background-color: transparent;")
        
        # content_layout.addWidget(self.selfie_label)
        # self._layout.addWidget(self._content_widget)

        self.layout().addWidget(self.selfie_label)
        
        self._update_selfie_image()
    
    def get_metadata(self):
        """Return the metadata for external widgets."""
        return getattr(self, '_metadata', {})

    def get_image_path(self):
        """Return the image path for external widgets."""
        return getattr(self, '_image_path', None)

    def has_selfie(self):
        """Return True if selfie exists."""
        return getattr(self, '_image_path', None) is not None
    
    def _create_bordered_rounded_pixmap(self, pixmap: QPixmap, radius: int, border_width: int, border_color) -> QPixmap:
        """Create a pixmap with rounded corners and a border."""
        from PySide6.QtGui import QPainterPath, QPen
        
        total_size = pixmap.size() + QSize(border_width * 2, border_width * 2)
        result = QPixmap(total_size)
        result.fill(Qt.transparent)
        
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw border
        # path = QPainterPath()
        # path.addRoundedRect(border_width/2, border_width/2, 
        #                    total_size.width() - border_width, 
        #                    total_size.height() - border_width, 
        #                    radius, radius)
        # painter.setPen(QPen(border_color, border_width))
        # painter.drawPath(path)
        
        # Draw image inside
        inner_path = QPainterPath()
        inner_path.addRoundedRect(border_width, border_width, 
                                  pixmap.width(), pixmap.height(), 
                                  radius - border_width/2, radius - border_width/2)
        painter.setClipPath(inner_path)
        painter.drawPixmap(border_width, border_width, pixmap)
        painter.end()
        
        return result
    
    def _update_selfie_image(self):
        """Update selfie image to fill the card and emit height signal."""
        if not self._image_path:
            return
            
        BORDER_RADIUS = 16
        BORDER_WIDTH = 3
        
        # Use the card's own width, let height be determined by image aspect ratio
        card_width = self.width() - 16  # Small padding
        
        if card_width < 100:
            card_width = 300
        
        pixmap = QPixmap(str(self._image_path))
        if not pixmap.isNull():
            # Scale to fit width, let height be natural
            scaled = pixmap.scaledToWidth(card_width, Qt.SmoothTransformation)
            
            # Apply rounded corners and border
            bordered_pixmap = self._create_bordered_rounded_pixmap(
                scaled, BORDER_RADIUS, BORDER_WIDTH, 
                self._vars.qcolor('outline_variant')
            )
            self.selfie_label.setPixmap(bordered_pixmap)
            
            # Calculate total height (image + border + card padding)
            image_height = bordered_pixmap.height() + 16
            
            # Set card to fixed height based on image
            if image_height != self._current_image_height:
                self._current_image_height = image_height
                self.setFixedHeight(image_height)
                self.image_resized.emit(image_height)
    
    def resizeEvent(self, event):
        """Handle resize to update image."""
        super().resizeEvent(event)
        if self._image_path:
            self._update_selfie_image()

class StreakSummaryWidget(QFrame):
    """
    Read-only summary showing current and longest streak with status icon.
    """
    def __init__(self):
        super().__init__()

        self._vars = theme_vars()

        self.setObjectName("StreakSummaryWidget")
        self.setMinimumHeight(90)

        self.setStyleSheet(f"""
            QFrame#StreakSummaryWidget {{
                background-color: {self._vars['surface_container_low']};
                border-radius: 16px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Fetch streak data
        current, best, has_photo_today = self._get_streaks()
        
        # Title row with icon
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        
        # Status icon based on today's photo status
        self._status_icon = QLabel()
        icon_name = "streak.svg" if has_photo_today else "nostreak.svg"
        colored_icon = self._create_colored_icon(
            icon_name,
            self._vars.qcolor('tertiary') if has_photo_today else self._vars.qcolor('on_surface_variant')
        )
        self._status_icon.setPixmap(colored_icon.pixmap(20, 20))
        self._status_icon.setFixedSize(20, 20)
        title_row.addWidget(self._status_icon)
        
        # Title label
        title = QLabel("Streak")
        title.setStyleSheet(f"""
            color: {self._vars['on_surface']};
            font-size: 14px;
            font-weight: 600;
        """)
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)
        
        # Current streak value (large)
        current_text = f"{current} day{'s' if current != 1 else ''}"
        if not has_photo_today and current > 0:
            current_text += " (at risk)"
        
        # Use tertiary color when at risk, primary when safe
        streak_color = self._vars['tertiary'] if (not has_photo_today and current > 0) else self._vars['primary']
        
        current_label = QLabel(current_text)
        current_label.setStyleSheet(f"""
            color: {streak_color};
            font-size: 18px;
            font-weight: 700;
        """)
        layout.addWidget(current_label)
        
        # Horizontal separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet(f"background-color: {self._vars['outline_variant']};")
        separator.setFixedHeight(1)
        layout.addWidget(separator)
        
        # Best streak row
        best_row = QHBoxLayout()
        best_row.setSpacing(6)
        
        best_icon = self._create_colored_icon("timer.svg", self._vars.qcolor('on_surface_variant'))
        best_icon_label = QLabel()
        best_icon_label.setPixmap(best_icon.pixmap(16, 16))
        best_icon_label.setFixedSize(16, 16)
        best_row.addWidget(best_icon_label)
        
        best_label = QLabel(f"Best: {best} days")
        best_label.setStyleSheet(f"""
            color: {self._vars['on_surface_variant']};
            font-size: 13px;
            font-weight: 500;
        """)
        best_row.addWidget(best_label)
        best_row.addStretch()
        layout.addLayout(best_row)
        
        # Days to beat best streak
        days_to_beat = best - current + 1
        if days_to_beat > 0 and current > 0:
            beat_label = QLabel(f"{days_to_beat} more day{'s' if days_to_beat != 1 else ''} to beat record")
            beat_label.setStyleSheet(f"""
                color: {self._vars['on_surface_variant']};
                font-size: 11px;
                font-style: italic;
            """)
            layout.addWidget(beat_label)
        elif current > best:
            # Current streak IS the record
            record_row = QHBoxLayout()
            record_row.setSpacing(6)
            
            celebration_icon = self._create_colored_icon("celebration.svg", self._vars.qcolor('tertiary'))
            celebration_label = QLabel()
            celebration_label.setPixmap(celebration_icon.pixmap(16, 16))
            celebration_label.setFixedSize(16, 16)
            record_row.addWidget(celebration_label)
            
            record_label = QLabel("New record!")
            record_label.setStyleSheet(f"""
                color: {self._vars['tertiary']};
                font-size: 11px;
                font-weight: 600;
            """)
            record_row.addWidget(record_label)
            record_row.addStretch()
            layout.addLayout(record_row)
    
    def _create_colored_icon(self, icon_name: str, qcolor):
        """Loads an SVG and repaints it with the given QColor."""
        path = ICONS_DIR / icon_name
        if not path.exists():
            return QIcon()

        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return QIcon()

        colored_pixmap = QPixmap(pixmap.size())
        colored_pixmap.fill(Qt.transparent)

        painter = QPainter(colored_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawPixmap(0, 0, pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(colored_pixmap.rect(), qcolor)
        painter.end()

        return QIcon(colored_pixmap)
    
    def _get_streaks(self) -> Tuple[int, int, bool]:
        """Fetch dates from DB and calculate streaks."""
        try:
            app_paths = get_app_paths("DailySelfie", ensure=True)
            api = get_api(app_paths)
            dates = api._ensure_indexer().get_all_capture_dates()
            return calculate_streaks(dates)
        except Exception:
            return (0, 0, False)


class MoodSummaryWidget(QFrame):
    """
    Widget showing mood summary.
    """
    def __init__(self):
        super().__init__()

        vars = theme_vars()

        self.setObjectName("MoodSummaryWidget")
        self.setMinimumHeight(90)

        self.setStyleSheet(f"""
            QFrame#MoodSummaryWidget {{
                background-color: {vars['surface_container_low']};
                border-radius: 16px;
            }}
        """)

        layout = QVBoxLayout(self)

        title = QLabel("Mood (last 30 days)")
        value = QLabel("—")

        layout.addWidget(title)
        layout.addWidget(value)

        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)


class TodaySelfieInfoBox(QFrame):
    """
    Info box showing mood, note, and retake button for today's selfie.
    Placed between selfie card and side column.
    """
    delete_requested = Signal()  # Emitted when user deletes today's photo
    
    def __init__(self, selfie_card: TodaySelfieCard):
        super().__init__()
        self._vars = theme_vars()
        self._selfie_card = selfie_card
        self._image_path = None
        self._metadata = {}

        self.setObjectName("TodaySelfieInfoBox")
        self.setMinimumWidth(160)
        self.setMaximumWidth(200)
        
        self.setStyleSheet(f"""
            QFrame#TodaySelfieInfoBox {{
                background-color: {self._vars['surface_container_low']};
                border-radius: 16px;
            }}
        """)

        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(10)
        self._layout.setContentsMargins(12, 12, 12, 12)

        self._build_content()
        
        # Connect to selfie card's height signal to sync heights
        self._selfie_card.image_resized.connect(self._on_image_resized)
    
    def _on_image_resized(self, height: int):
        """Match height to the selfie card's image height."""
        self.setFixedHeight(height)

    def _create_colored_icon(self, icon_name: str, qcolor):
        """Loads an SVG and repaints it with the given QColor."""
        path = ICONS_DIR / icon_name
        if not path.exists():
            return QIcon()

        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return QIcon()

        colored_pixmap = QPixmap(pixmap.size())
        colored_pixmap.fill(Qt.transparent)

        painter = QPainter(colored_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawPixmap(0, 0, pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(colored_pixmap.rect(), qcolor)
        painter.end()

        return QIcon(colored_pixmap)

    def _build_content(self):
        """Build the info box content based on selfie state."""
        if not self._selfie_card.has_selfie():
            placeholder = QLabel("No selfie yet")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet(f"""
                color: {self._vars['on_surface_variant']};
                font-size: 12px;
                font-style: italic;
            """)
            self._layout.addWidget(placeholder)
            self._layout.addStretch()
            return

        metadata = self._selfie_card.get_metadata()

        # Status text with checkmark
        status_label = QLabel("Today's selfie")
        status_label.setStyleSheet(f"""
            color: {self._vars['primary']};
            font-size: 14px;
            font-weight: 600;
        """)
        self._layout.addWidget(status_label)

        # ---- Time taken (convert UTC to local) ----
        time_str = ""
        ts_value = metadata.get("ts")
        if ts_value:
            try:
                from datetime import datetime, timezone
                # Parse ISO timestamp (it's in UTC)
                dt_utc = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
                # Convert to local timezone
                dt_local = dt_utc.astimezone()
                time_str = dt_local.strftime("%I:%M %p")  # e.g., "09:37 AM"
            except:
                pass
        
        if not time_str:
            # Fallback: extract from id (e.g., "2026-01-02_040733")
            selfie_id = metadata.get("id", "")
            if "_" in selfie_id:
                time_part = selfie_id.split("_")[-1]
                if len(time_part) == 6:
                    try:
                        h, m = time_part[:2], time_part[2:4]
                        hour = int(h)
                        ampm = "AM" if hour < 12 else "PM"
                        hour = hour % 12 or 12
                        time_str = f"{hour}:{m} {ampm}"
                    except:
                        pass
        
        if time_str:
            time_row = QHBoxLayout()
            time_row.setSpacing(6)
            time_row.setContentsMargins(0, 0, 0, 0)

            # Create A colored Icon
            saved_icon = self._create_colored_icon(
            "save_clock.svg",
            self._vars.qcolor('on_surface_variant')
            )
            
            time_icon = QLabel()
            time_icon.setPixmap(saved_icon.pixmap(24, 24))
            time_icon.setFixedWidth(24)
            time_row.addWidget(time_icon)
            
            time_label = QLabel(time_str)
            time_label.setStyleSheet(f"""
                color: {self._vars['on_surface']};
                font-size: 11px;
                font-weight: 500;
            """)
            time_row.addWidget(time_label)
            time_row.addStretch()
            self._layout.addLayout(time_row)

        # ---- Resolution ----
        width = metadata.get("width")
        height = metadata.get("height")
        if width and height:
            res_row = QHBoxLayout()
            res_row.setSpacing(6)
            res_row.setContentsMargins(0, 0, 0, 0)
            
            aspect_ratio_icon = self._create_colored_icon(
            "aspect_ratio.svg",
            self._vars.qcolor('on_surface_variant')
            )
            
            res_icon = QLabel()
            res_icon.setPixmap(aspect_ratio_icon.pixmap(24, 24))
            res_icon.setFixedWidth(24)
            res_row.addWidget(res_icon)
            
            res_label = QLabel(f"{width} × {height}")
            res_label.setStyleSheet(f"""
                color: {self._vars['on_surface']};
                font-size: 11px;
            """)
            res_row.addWidget(res_label)
            res_row.addStretch()
            self._layout.addLayout(res_row)

        # ---- Horizontal line before Mood section ----
        mood_separator = QFrame()
        mood_separator.setFrameShape(QFrame.HLine)
        mood_separator.setStyleSheet(f"""
            background-color: {self._vars['outline_variant']};
        """)
        mood_separator.setFixedHeight(1)
        self._layout.addWidget(mood_separator)

        # ---- Mood section ----
        mood_section_label = QLabel("Mood selected today")
        mood_section_label.setStyleSheet(f"""
            color: {self._vars['on_surface_variant']};
            font-size: 10px;
            font-weight: 500;
        """)
        self._layout.addWidget(mood_section_label)

        mood_value = metadata.get("mood")
        if mood_value and mood_value in MOOD_GIF_MAP:
            mood_row = QHBoxLayout()
            mood_row.setSpacing(8)
            mood_row.setContentsMargins(0, 4, 0, 0)

            mood_gif_label = QLabel()
            mood_gif_label.setFixedSize(32, 32)
            mood_gif_label.setAlignment(Qt.AlignCenter)
            gif_path = str(MOOD_DIR / MOOD_GIF_MAP[mood_value])
            self._mood_movie = QMovie(gif_path)
            if self._mood_movie.isValid():
                self._mood_movie.setScaledSize(QSize(22, 22))
                mood_gif_label.setMovie(self._mood_movie)
                self._mood_movie.start()
            
            mood_gif_label.setStyleSheet(f"""
                background-color: {self._vars['surface_container_low']};
                border: 2px solid {self._vars['outline_variant']};
                border-radius: 8px;
            """)
            mood_row.addWidget(mood_gif_label)

            mood_text = QLabel(mood_value)
            mood_text.setStyleSheet(f"""
                color: {self._vars['on_surface']};
                font-size: 11px;
                font-weight: 500;
            """)
            mood_row.addWidget(mood_text)
            mood_row.addStretch()
            self._layout.addLayout(mood_row)
        else:
            no_mood = QLabel("No mood")
            no_mood.setStyleSheet(f"""
                color: {self._vars['on_surface_variant']};
                font-size: 10px;
                font-style: italic;
            """)
            self._layout.addWidget(no_mood)

        # ---- Horizontal line before Notes section ----
        notes_separator = QFrame()
        notes_separator.setFrameShape(QFrame.HLine)
        notes_separator.setStyleSheet(f"""
            background-color: {self._vars['outline_variant']};
        """)
        notes_separator.setFixedHeight(1)
        self._layout.addWidget(notes_separator)

        # ---- Note section ----
        notes_section_label = QLabel("Notes")
        notes_section_label.setStyleSheet(f"""
            color: {self._vars['on_surface_variant']};
            font-size: 10px;
            font-weight: 500;
        """)
        self._layout.addWidget(notes_section_label)

        note_value = metadata.get("notes")
        if note_value:
            note_text = note_value[:35] + "..." if len(note_value) > 35 else note_value
            
            note_row = QHBoxLayout()
            note_row.setSpacing(6)
            note_row.setContentsMargins(0, 0, 0, 0)
            
            notes_icon = self._create_colored_icon(
                "notes.svg",
                self._vars.qcolor('on_surface_variant')
            )
            
            note_icon_label = QLabel()
            note_icon_label.setPixmap(notes_icon.pixmap(16, 16))
            note_icon_label.setFixedWidth(16)
            note_row.addWidget(note_icon_label)
            
            note_label = QLabel(note_text)
            note_label.setWordWrap(True)
            note_label.setStyleSheet(f"""
                color: {self._vars['on_surface_variant']};
                font-size: 10px;
            """)
            note_row.addWidget(note_label)
            note_row.addStretch()
            self._layout.addLayout(note_row)
        else:
            no_notes = QLabel("No notes")
            no_notes.setStyleSheet(f"""
                color: {self._vars['on_surface_variant']};
                font-size: 10px;
                font-style: italic;
            """)
            self._layout.addWidget(no_notes)

        self._layout.addStretch()

        # Retake button
        retake_btn = QPushButton("Retake")
        retake_btn.setObjectName("RetakeButton")
        retake_btn.setCursor(Qt.PointingHandCursor)
        retake_btn.setFixedHeight(32)
        
        retake_icon = self._create_colored_icon(
            "retake_image.svg",
            self._vars.qcolor('on_surface_variant')
        )
        retake_btn.setIcon(retake_icon)
        retake_btn.setIconSize(QSize(14, 14))
        
        retake_btn.setStyleSheet(f"""
            QPushButton#RetakeButton {{
                background-color: {self._vars['surface_container_high']};
                color: {self._vars['on_surface_variant']};
                border: 1px solid {self._vars['outline_variant']};
                border-radius: 16px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton#RetakeButton:hover {{
                background-color: {self._vars['surface_container_highest']};
                border: 1px solid {self._vars['outline']};
                color: {self._vars['on_surface']};
            }}
        """)
        self._layout.addWidget(retake_btn)

        # Delete today's photo button
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("DeleteButton")
        self._delete_btn.setCursor(Qt.PointingHandCursor)
        self._delete_btn.setFixedHeight(32)
        
        delete_icon = self._create_colored_icon(
            "delete.svg",
            self._vars.qcolor('error')
        )
        self._delete_btn.setIcon(delete_icon)
        self._delete_btn.setIconSize(QSize(14, 14))
        
        self._delete_btn.setStyleSheet(f"""
            QPushButton#DeleteButton {{
                background-color: {self._vars['surface_container_high']};
                color: {self._vars['error']};
                border: 1px solid {self._vars['error']};
                border-radius: 16px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton#DeleteButton:hover {{
                background-color: {self._vars['error_container']};
                border: 1px solid {self._vars['error']};
                color: {self._vars['on_error_container']};
            }}
        """)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        self._layout.addWidget(self._delete_btn)
    
    def _on_delete_clicked(self):
        """Handle delete button click: delete photo file and update index."""
        image_path = self._selfie_card.get_image_path()
        metadata = self._selfie_card.get_metadata()
        
        if not image_path or not image_path.exists():
            return
        
        selfie_id = metadata.get("id") or image_path.stem
        
        # Delete the photo file
        success, error = delete_path(image_path)
        if not success:
            # TODO: Show error to user
            print(f"Failed to delete photo: {error}")
            return
        
        # Record deletion in the index API
        try:
            app_paths = get_app_paths("DailySelfie", ensure=True)
            api = get_api(app_paths)
            api.record_deletion(selfie_id, reason="user_deleted")
        except Exception as e:
            print(f"Failed to record deletion: {e}")
        
        # Refresh the selfie card to show empty state
        self._selfie_card.set_empty_state()
        
        # Clear our own content and show placeholder
        self._clear_and_show_placeholder()
        
        # Emit signal for any external listeners
        self.delete_requested.emit()
    
    def _clear_and_show_placeholder(self):
        """Clear content and show no selfie placeholder."""
        # Remove all widgets from layout
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                # Clear nested layout
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()
        
        # Add placeholder
        placeholder = QLabel("No selfie yet")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet(f"""
            color: {self._vars['on_surface_variant']};
            font-size: 12px;
            font-style: italic;
        """)
        self._layout.addWidget(placeholder)
        self._layout.addStretch()


class DashboardSurface(QFrame):
    """
    Primary dashboard surface containing today's selfie card and summary widgets.
    """
    def __init__(self):
        super().__init__()
        vars = theme_vars()

        self.setObjectName("DashboardSurface")

        self.setStyleSheet(f"""
            QFrame#DashboardSurface {{
                background-color: {vars['surface_container_highest']};
                border-radius: 12px;
            }}
        """)

        surface_layout = QVBoxLayout(self)
        surface_layout.setContentsMargins(12, 12, 12, 12)
        surface_layout.setSpacing(12)

        # Top Section: TodaySelfieCard + InfoBox + Side Column
        top_section = QHBoxLayout()
        top_section.setSpacing(12)

        # Selfie Card (image only, fills the card)
        today_selfie_card = TodaySelfieCard()

        # Info Box (between selfie and side column)
        info_box = TodaySelfieInfoBox(today_selfie_card)

        # Side Column: Streak + Mood
        side_column = QVBoxLayout()
        side_column.setSpacing(12)

        streak_summary_widget = StreakSummaryWidget()
        mood_summary_widget = MoodSummaryWidget()

        side_column.addWidget(streak_summary_widget)
        side_column.addWidget(mood_summary_widget)

        # Layout: Selfie (stretch=2) | InfoBox (stretch=0) | SideColumn (stretch=0)
        top_section.addWidget(today_selfie_card, stretch=2)
        top_section.addWidget(info_box, stretch=0)
        top_section.addLayout(side_column, stretch=0)

        surface_layout.addLayout(top_section)
        surface_layout.addSpacing(8)
        carousel = RecentSelfieCarouselPlaceholder()
        surface_layout.addWidget(carousel)


class DashboardPage(QWidget):
    def __init__(self):
        super().__init__()
        vars = theme_vars()
        
        
                


        root_layout = QVBoxLayout()
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)
        surface = DashboardSurface()
        root_layout.addWidget(surface)

        self.setLayout(root_layout)


