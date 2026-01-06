# gui/dashboard/widgets/carousel/motion_carousel.py
"""
Motion Carousel Widget

A Material 3-inspired horizontal carousel for displaying recent selfies.
Supports smooth scrolling via mouse wheel and drag gestures.

The carousel dynamically calculates how many cards can fit in the
available viewport width and arranges them using the CarouselLayoutEngine.

Features:
- Responsive layout adapts to container width
- Wheel scroll and drag-to-scroll input
- Automatic data refresh from database
- Hero focus effect (focused card is larger)
"""
from typing import List
from pathlib import Path

from PySide6.QtWidgets import QFrame
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent, QWheelEvent

from gui.theme.theme_vars import theme_vars
from core.index_api import get_api
from gui.dashboard.widgets.carousel.layout_engine import CarouselLayoutEngine
from gui.dashboard.widgets.carousel.selfie_card import SelfieCard


# ============================================================================
# Constants
# ============================================================================

# Carousel dimensions
CAROUSEL_HEIGHT = 120

# Scroll sensitivity (higher = slower scroll)
WHEEL_SENSITIVITY = 4000.0
DRAG_SENSITIVITY_FACTOR = 2.0  # Multiplied by viewport width

# Data limits
MAX_PHOTOS_TO_LOAD = 50


# ============================================================================
# Motion Carousel Widget
# ============================================================================

class MotionCarousel(QFrame):
    """
    A horizontal scrolling carousel displaying recent selfie cards.
    
    The carousel manages a collection of SelfieCard widgets, positioning
    them according to the current scroll progress. The layout uses an
    "accordion" effect where the focused card is larger.
    
    Signals:
        item_clicked(str): Emitted when a card is clicked, with image path.
    """
    
    item_clicked = Signal(str)

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Theme reference
        self._vars = theme_vars()
        
        # Card storage
        self._cards: List[SelfieCard] = []
        
        # Widget setup
        self.setObjectName("MotionCarousel")
        self.setFixedHeight(CAROUSEL_HEIGHT)
        self._apply_styles()
        
        # Scroll state
        self._scroll_progress = 0.0  # Normalized [0, 1]
        self._last_drag_pos = None   # For drag-to-scroll
        
        # Layout engine (initialized with placeholder values)
        self._engine = CarouselLayoutEngine(
            item_count=0,
            available_width=100,
            available_height=CAROUSEL_HEIGHT
        )
        
        # Load initial data
        self.refresh_data()

    def _apply_styles(self):
        """Apply rounded container styling."""
        self.setStyleSheet(f"""
            QFrame#MotionCarousel {{
                background-color: {self._vars['surface_container_low']};
                border-radius: 12px;
                border: none;
            }}
        """)

    # -------------------------------------------------------------------------
    # Data Management
    # -------------------------------------------------------------------------

    def refresh_data(self):
        """
        Reload selfie data from database and recreate cards.
        
        Clears existing cards, fetches recent photos, creates new
        SelfieCard widgets, and updates the layout.
        """
        # Clean up existing cards
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()
        
        # Fetch recent photos from API
        api = get_api()
        photos = api.get_recent_photos(limit=MAX_PHOTOS_TO_LOAD)
        
        # Filter to only photos with valid file paths
        valid_photos = [
            photo for photo in photos
            if photo.get('path') and Path(photo['path']).exists()
        ]

        # Create card widgets for each valid photo
        for photo in valid_photos:
            card = self._create_card(photo)
            self._cards.append(card)
        
        # Reset scroll and update layout
        self._scroll_progress = 0.0
        self._update_layout()

    def _create_card(self, photo: dict) -> SelfieCard:
        """
        Create and configure a SelfieCard for the given photo data.
        
        Args:
            photo: Dictionary with 'path', 'ts', 'notes', and 'mood' keys.
            
        Returns:
            Configured SelfieCard widget (initially hidden).
        """
        card = SelfieCard(self)
        
        card.set_data(
            image_path=photo.get('path'),
            ts=photo.get('ts', ''),
            notes=photo.get('notes', ''),
            mood_icon_path=photo.get('mood')
        )
        
        card.clicked.connect(self.item_clicked)
        card.hide()  # Start hidden; layout will show visible cards
        
        return card

    # -------------------------------------------------------------------------
    # Layout Management
    # -------------------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent):
        """Recalculate layout when container is resized."""
        super().resizeEvent(event)
        self._update_layout()

    def _update_layout(self):
        """
        Position all cards according to current scroll progress.
        
        Determines how many cards can fit in the viewport, calculates
        their geometry using the layout engine, and applies positions.
        """
        if not self._cards:
            return
        
        # Calculate visible capacity based on viewport width
        visible_count = self._calculate_visible_capacity()
        
        # Update engine parameters
        self._engine.count = visible_count
        self._engine.view_width = self.width()
        self._engine.view_height = self.height()
        
        # Get geometries from layout engine
        geometries, _ = self._engine.calculate_layout(self._scroll_progress)
        
        # Apply geometries to cards
        self._apply_card_geometries(geometries)
        
        # Hide cards beyond visible range
        self._hide_overflow_cards(len(geometries))

    def _calculate_visible_capacity(self) -> int:
        """
        Calculate how many cards can fit in the current viewport.
        
        Returns:
            Number of cards that can be displayed simultaneously.
        """
        available_width = self.width()
        hero_width = self._engine.large_width
        small_width = self._engine.small_width
        gap = self._engine.gap
        
        # Space remaining after hero card
        remaining_space = available_width - hero_width - gap
        
        # Space needed per non-hero card
        item_space = small_width + gap
        
        if remaining_space > 0:
            # How many small cards fit in remaining space, plus the hero
            capacity = int(remaining_space / item_space) + 1
        else:
            # Not enough room for anything beyond hero
            capacity = 1
        
        # Don't show more than we have
        return min(capacity, len(self._cards))

    def _apply_card_geometries(self, geometries):
        """
        Apply calculated geometries to card widgets.
        
        Args:
            geometries: List of ItemGeometry from layout engine.
        """
        for geom in geometries:
            if geom.index >= len(self._cards):
                continue
                
            card = self._cards[geom.index]
            
            # Hide if card extends beyond viewport
            if (geom.x + geom.width) > self.width():
                card.hide()
            else:
                if not card.isVisible():
                    card.show()
                    
                card.setGeometry(
                    int(geom.x),
                    int(self._engine.gap),
                    int(geom.width),
                    int(geom.height)
                )

    def _hide_overflow_cards(self, visible_count: int):
        """Hide cards that are beyond the visible geometry range."""
        for i, card in enumerate(self._cards):
            if i >= visible_count:
                card.hide()

    # -------------------------------------------------------------------------
    # Scroll Handling
    # -------------------------------------------------------------------------

    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel scrolling."""
        # Get scroll delta (prefer vertical, fall back to horizontal)
        delta = event.angleDelta().y() or event.angleDelta().x()
        
        # Convert to scroll progress change (negative for natural scrolling)
        change = -delta / WHEEL_SENSITIVITY
        
        self._apply_scroll_change(change)
        event.accept()

    def mousePressEvent(self, event):
        """Start drag-to-scroll on left mouse button."""
        if event.button() == Qt.LeftButton:
            self._last_drag_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Update scroll position during drag."""
        if self._last_drag_pos and event.buttons() == Qt.LeftButton:
            # Calculate horizontal drag distance
            delta_x = event.pos().x() - self._last_drag_pos.x()
            
            # Convert to scroll progress (scaled by viewport width)
            drag_sensitivity = self.width() * DRAG_SENSITIVITY_FACTOR
            change = -delta_x / drag_sensitivity
            
            self._apply_scroll_change(change)
            self._last_drag_pos = event.pos()
            
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """End drag-to-scroll."""
        self._last_drag_pos = None
        self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def _apply_scroll_change(self, delta: float):
        """
        Apply a scroll delta and update the layout.
        
        Args:
            delta: Change in scroll progress (can be positive or negative).
        """
        new_progress = self._scroll_progress + delta
        
        # Clamp to valid range [0, 1]
        self._scroll_progress = max(0.0, min(1.0, new_progress))
        
        self._update_layout()