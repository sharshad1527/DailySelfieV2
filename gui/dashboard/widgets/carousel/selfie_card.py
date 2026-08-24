# gui/dashboard/widgets/carousel/selfie_card.py
"""
Selfie Card Widget

A custom-painted card that displays a selfie image with date/note overlays.
Used as individual items within the MotionCarousel.

Features:
- Rounded corners with anti-aliased clipping
- Cover-fit image scaling with zoom effect
- Gradient overlay for text readability
- Responsive text display (hero vs compact modes)
"""
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import (
    QPainter, QPainterPath, QPixmap, QColor,
    QLinearGradient, QFont, QFontMetrics
)
from PySide6.QtCore import Qt, QRectF, Signal

from core.thumbs import load_display_pixmap
from gui.theme.theme_vars import theme_vars


# ============================================================================
# Constants
# ============================================================================

# Card styling
CARD_CORNER_RADIUS = 16.0

# Largest card the carousel layout draws (CarouselLayoutEngine.large_width);
# combined with IMAGE_ZOOM_FACTOR this bounds how many device pixels a card
# really needs, deciding when the disk thumbnail cache is used.
HERO_MAX_LONG_PX = 200.0

# Image zoom factor (1.25 = 25% zoom for a closer/bigger feel)
IMAGE_ZOOM_FACTOR = 1.25

# Gradient overlay settings
GRADIENT_HEIGHT_RATIO = 0.6  # Covers bottom 60% of card
GRADIENT_OPACITY = 180       # Alpha value for gradient end (0-255)

# Text layout
TEXT_MARGIN_LEFT = 12
TEXT_MARGIN_BOTTOM = 12

# Width thresholds for display modes
HERO_MODE_MIN_WIDTH = 160    # Show full date + notes
MID_MODE_MIN_WIDTH = 80      # Show date only
GRADIENT_MIN_WIDTH = 60      # Show gradient at all


# ============================================================================
# Selfie Card Widget
# ============================================================================

class SelfieCard(QWidget):
    """
    A clickable card displaying a selfie with overlay text.
    
    The card adapts its display based on available width:
    - Hero mode (>160px): Shows date and elided note text
    - Mid mode (>80px): Shows date only
    - Compact mode (<80px): Image only, no text
    
    Signals:
        clicked(str): Emitted when card is clicked, with image path as argument.
    """
    
    clicked = Signal(str)

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Theme reference
        self._vars = theme_vars()
        
        # Card data
        self._image_path: str = ""
        self._pixmap: QPixmap = QPixmap()
        self._is_placeholder: bool = True
        self._date_text: str = ""
        self._note_text: str = ""
        self._mood_icon: str = None
        
        # Styling
        self._bg_color = self._vars['surface_container_low']
        self._radius = CARD_CORNER_RADIUS
        
        # Enable mouse tracking for hover effects
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    # -------------------------------------------------------------------------
    # Data Management
    # -------------------------------------------------------------------------

    def set_data(
        self,
        image_path: str,
        ts: str,
        notes: str,
        mood_icon_path: str = None
    ):
        """
        Populate the card with selfie data.
        
        Args:
            image_path: Absolute path to the selfie image file.
            ts: ISO-format timestamp string (e.g., "2024-01-15T14:30:00").
            notes: User's note text for this selfie.
            mood_icon_path: Optional path to mood indicator icon.
        """
        self._image_path = image_path
        self._note_text = notes if notes else ""
        self._mood_icon = mood_icon_path
        
        # Parse timestamp into display format (e.g., "Jan 15")
        self._date_text = self._parse_timestamp(ts)
        
        # Load image if path is valid (tagged with the widget's device pixel
        # ratio so painting stays sharp on HiDPI screens). Oversized sources
        # are served from the disk thumbnail cache; geometry is unchanged.
        if image_path and Path(image_path).exists():
            self._pixmap = load_display_pixmap(
                Path(image_path),
                HERO_MAX_LONG_PX * IMAGE_ZOOM_FACTOR,
                self.devicePixelRatioF(),
            )
            if not self._pixmap.isNull():
                self._pixmap.setDevicePixelRatio(self.devicePixelRatioF())
            self._is_placeholder = False
        else:
            self._pixmap = QPixmap()
            self._is_placeholder = True
            
        self.update()

    def _parse_timestamp(self, ts: str) -> str:
        """
        Convert ISO timestamp to display format.
        
        Args:
            ts: ISO-format timestamp string.
            
        Returns:
            Formatted date string (e.g., "Jan 15") or original string on error.
        """
        if not ts:
            return ""
        
        try:
            # Handle optional 'Z' suffix for UTC timestamps
            dt = datetime.fromisoformat(ts.replace("Z", ""))
            return dt.strftime("%b %d")
        except (ValueError, AttributeError):
            return ts

    # -------------------------------------------------------------------------
    # Painting
    # -------------------------------------------------------------------------

    def paintEvent(self, event):
        """Custom paint with rounded corners, image, gradient, and text."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        rect = self.rect()
        width, height = rect.width(), rect.height()
        
        # Step 1: Create rounded clip path
        clip_path = QPainterPath()
        clip_path.addRoundedRect(QRectF(rect), self._radius, self._radius)
        painter.setClipPath(clip_path)
        
        # Step 2: Fill background (visible if image doesn't cover)
        painter.fillPath(clip_path, QColor(self._bg_color))
        
        # Step 3: Draw image with cover-fit and zoom
        if not self._is_placeholder and not self._pixmap.isNull():
            self._draw_image(painter, width, height)
            
            # Step 4: Draw gradient and text overlays (only for wider cards)
            if width > GRADIENT_MIN_WIDTH:
                self._draw_gradient_overlay(painter, width, height)
                self._draw_overlay_text(painter, width, height)

    def _draw_image(self, painter: QPainter, card_width: float, card_height: float):
        """
        Draw the selfie image with cover-fit scaling and zoom.
        
        The image is scaled to cover the entire card (no gaps),
        centered, and zoomed slightly for a more immersive feel.
        
        Note: Uses QRectF for both target and source to avoid
        sub-pixel rounding artifacts (fixes "white line" bug).
        All math is in logical units; the pixmap's devicePixelRatio
        provides the extra pixels on HiDPI screens.
        """
        pixmap_dpr = float(self._pixmap.devicePixelRatio()) or 1.0
        img_width = self._pixmap.width() / pixmap_dpr
        img_height = self._pixmap.height() / pixmap_dpr
        
        # Calculate scale to cover entire card (cover-fit)
        base_scale = max(card_width / img_width, card_height / img_height)
        
        # Apply zoom for a closer, more prominent image
        final_scale = base_scale * IMAGE_ZOOM_FACTOR
        
        # Calculate scaled dimensions
        scaled_width = img_width * final_scale
        scaled_height = img_height * final_scale
        
        # Center the image
        x_offset = (card_width - scaled_width) / 2
        y_offset = (card_height - scaled_height) / 2
        
        # Draw with float precision to avoid rendering artifacts
        target_rect = QRectF(x_offset, y_offset, scaled_width, scaled_height)
        source_rect = QRectF(0, 0, img_width, img_height)
        painter.drawPixmap(target_rect, self._pixmap, source_rect)

    def _draw_gradient_overlay(self, painter: QPainter, width: float, height: float):
        """
        Draw a bottom-to-top gradient for text readability.
        
        The gradient fades from transparent at top to semi-opaque black at bottom.
        """
        gradient_height = height * GRADIENT_HEIGHT_RATIO
        gradient_top = height - gradient_height
        
        gradient = QLinearGradient(0, gradient_top, 0, height)
        gradient.setColorAt(0.0, QColor(0, 0, 0, 0))           # Transparent
        gradient.setColorAt(1.0, QColor(0, 0, 0, GRADIENT_OPACITY))  # Semi-opaque
        
        painter.fillRect(QRectF(0, gradient_top, width, gradient_height), gradient)

    def _draw_overlay_text(self, painter: QPainter, width: float, height: float):
        """
        Draw date and optional note text over the gradient.
        
        Display mode depends on card width:
        - Hero mode (>160px): Date above, elided note below
        - Mid mode (>80px): Date only
        - Compact mode (<80px): No text (handled by caller)
        """
        # Set up default font for date
        date_font = QFont("Segoe UI", 9)
        date_font.setBold(True)
        painter.setFont(date_font)
        painter.setPen(QColor("white"))
        
        if width > HERO_MODE_MIN_WIDTH:
            # HERO MODE: Show date + notes
            self._draw_hero_mode_text(painter, width, height, date_font)
        elif width > MID_MODE_MIN_WIDTH:
            # MID MODE: Show date only
            painter.drawText(TEXT_MARGIN_LEFT, height - TEXT_MARGIN_BOTTOM, self._date_text)

    def _draw_hero_mode_text(
        self,
        painter: QPainter,
        width: float,
        height: float,
        date_font: QFont
    ):
        """Draw full text layout for hero-sized cards."""
        if self._note_text:
            # Draw note text (smaller, lighter)
            note_font = QFont("Segoe UI", 8)
            note_font.setBold(False)
            painter.setFont(note_font)
            painter.setPen(QColor(230, 230, 230))
            
            # Calculate note text area
            note_rect = QRectF(
                TEXT_MARGIN_LEFT,
                height - 35,
                width - (TEXT_MARGIN_LEFT * 2),
                30
            )
            
            # Elide text if too long
            metrics = QFontMetrics(note_font)
            elided_note = metrics.elidedText(
                self._note_text,
                Qt.ElideRight,
                int(note_rect.width())
            )
            painter.drawText(note_rect, Qt.AlignLeft | Qt.AlignTop, elided_note)
            
            # Draw date above note
            painter.setFont(date_font)
            painter.setPen(QColor("white"))
            painter.drawText(TEXT_MARGIN_LEFT, height - 35 - 4, self._date_text)
        else:
            # No note - just draw date
            painter.drawText(TEXT_MARGIN_LEFT, height - TEXT_MARGIN_BOTTOM, self._date_text)

    # -------------------------------------------------------------------------
    # Event Handling
    # -------------------------------------------------------------------------

    def mousePressEvent(self, event):
        """Emit clicked signal with image path when left-clicked."""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._image_path)
        super().mousePressEvent(event)