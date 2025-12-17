from PySide6.QtWidgets import QPushButton
from PySide6.QtGui import QMovie, QIcon, QPixmap
from PySide6.QtCore import Qt, QSize

class GifButton(QPushButton):
    """
    A QPushButton that plays a GIF when hovered or checked.
    """
    def __init__(self, gif_path, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)

        # Load the GIF
        self.movie = QMovie(gif_path)
        # Verify the GIF is valid
        if not self.movie.isValid():
            print(f"Warning: Could not load GIF at {gif_path}")

        # Connect frame changes to the button icon
        self.movie.frameChanged.connect(self._update_icon)

        # Start in 'stopped' state (Frame 0)
        self.movie.jumpToFrame(0)
        self._update_icon()

        # Connect internal toggle signal
        self.toggled.connect(self._check_playback_state)

    def _update_icon(self):
        # Updates the button icon with the current GIF frame.
        pix = self.movie.currentPixmap()
        self.setIcon(QIcon(pix))

    def _check_playback_state(self):
        # Decides whether to play or stop based on Hover & Check state.
        should_play = self.underMouse() or self.isChecked()

        if should_play:
            if self.movie.state() != QMovie.Running:
                self.movie.start()
        else:
            self.movie.stop()
            self.movie.jumpToFrame(0) # Reset to start
            self._update_icon()

    # --- Event Overrides for Hover Effects ---
    def enterEvent(self, event):
        self._check_playback_state()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._check_playback_state()
        super().leaveEvent(event)
