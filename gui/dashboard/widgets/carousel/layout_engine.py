# gui/dashboard/widgets/carousel/layout_engine.py
"""
Carousel Layout Engine

Computes the geometry (position, size) for each item in a horizontal carousel.
Implements a "hero-focus" layout where the currently focused item is larger,
and items further from focus progressively shrink.

The layout uses linear interpolation (lerp) to smoothly transition
item widths as the user scrolls between items.
"""
from dataclasses import dataclass
from typing import List, Tuple


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class ItemGeometry:
    """
    Represents the computed geometry for a single carousel item.
    
    Attributes:
        x: Horizontal position (left edge) of the item in pixels.
        width: Width of the item in pixels.
        height: Height of the item in pixels.
        index: Original index of the item in the carousel.
    """
    x: float
    width: float
    height: float
    index: int


# ============================================================================
# Layout Engine
# ============================================================================

class CarouselLayoutEngine:
    """
    Calculates item positions and sizes for a horizontal carousel layout.
    
    The engine implements a "stacking/accordion" effect where:
    - The focused (center) item displays at full "hero" width
    - Adjacent items shrink proportionally based on distance from focus
    - All items stack horizontally with consistent gaps
    
    Usage:
        engine = CarouselLayoutEngine(item_count=10, available_width=400, available_height=200)
        items, total_width = engine.calculate_layout(scroll_progress=0.5)
    """
    
    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------
    
    def __init__(
        self,
        item_count: int,
        available_width: int,
        available_height: int
    ):
        """
        Initialize the layout engine with carousel constraints.
        
        Args:
            item_count: Total number of items in the carousel.
            available_width: Viewport width in pixels.
            available_height: Viewport height in pixels.
        """
        self.count = item_count
        self.view_width = available_width
        self.view_height = available_height

        # ---------------------------------------------------------------------
        # Layout Configuration
        # ---------------------------------------------------------------------
        
        # Hero (focused) item width - the largest any item can be
        self.large_width = 200.0
        
        # Default width for non-focused items
        self.small_width = 40.0
        
        # Absolute minimum width (prevents items from disappearing)
        self.min_width = 20.0
        
        # Gap between items (kept small to maximize card height)
        self.gap = 4.0

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _lerp(self, start: float, end: float, progress: float) -> float:
        """
        Linear interpolation between two values.
        
        Args:
            start: Value when progress is 0.
            end: Value when progress is 1.
            progress: Interpolation factor, clamped to [0, 1].
            
        Returns:
            Interpolated value between start and end.
        """
        clamped_progress = max(0.0, min(1.0, progress))
        return start + (end - start) * clamped_progress

    # -------------------------------------------------------------------------
    # Layout Calculation
    # -------------------------------------------------------------------------

    def calculate_layout(self, scroll_progress: float) -> Tuple[List[ItemGeometry], float]:
        """
        Compute geometry for all carousel items based on current scroll position.
        
        The scroll_progress value maps to the focused item:
        - 0.0 = first item focused
        - 1.0 = last item focused
        - 0.5 = middle item focused
        
        Items closer to the focus get larger widths, creating a
        smooth "accordion" effect as the user scrolls.
        
        Args:
            scroll_progress: Normalized scroll position in range [0, 1].
            
        Returns:
            Tuple containing:
            - List of ItemGeometry for each carousel item
            - Total width consumed by all items (for scroll bounds)
        """
        # Handle empty carousel
        if self.count == 0:
            return [], 0
        
        layout_items: List[ItemGeometry] = []
        
        # Convert normalized progress [0,1] to floating-point index [0, count-1]
        # Example: progress=0.5 with 5 items → focus_index=2.0 (middle item)
        focus_index = scroll_progress * (self.count - 1)
        
        # Start positioning at the left gap
        current_x = self.gap
        
        # Calculate geometry for each item
        for i in range(self.count):
            # Distance from the current focus (can be fractional during scroll)
            distance_from_focus = abs(i - focus_index)
            
            # Determine width based on proximity to focus
            if distance_from_focus < 1.0:
                # Item is within 1 position of focus - interpolate between hero and small
                # Closer to focus (distance → 0) = larger width
                # Further from focus (distance → 1) = smaller width
                width = self._lerp(self.large_width, self.small_width, distance_from_focus)
            else:
                # Item is more than 1 position away - use small width
                width = self.small_width
            
            # Enforce minimum width constraint
            width = max(width, self.min_width)
            
            # Create geometry for this item
            geometry = ItemGeometry(
                x=current_x,
                width=width,
                height=self.view_height - (self.gap * 2),  # Height with top/bottom margins
                index=i
            )
            layout_items.append(geometry)
            
            # Advance position for next item
            current_x += width + self.gap
        
        # Total width is the final x position (includes trailing gap)
        total_width = current_x
        
        return layout_items, total_width