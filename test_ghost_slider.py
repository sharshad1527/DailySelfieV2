import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor

os.environ["QT_QPA_PLATFORM"] = "offscreen"
app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

from gui.startup.widgets.ghost_slider import GhostOpacitySlider

class TestGhostOpacitySlider(unittest.TestCase):
    @patch('gui.startup.widgets.ghost_slider.theme_vars')
    def test_slider_bottom_and_clipping(self, mock_theme_vars):
        mock_theme = MagicMock()
        mock_theme.qcolor.return_value = QColor(255, 0, 0)
        mock_theme_vars.return_value = mock_theme

        slider = GhostOpacitySlider(minimum=0, maximum=60, value=30)

        # Test max value mapping
        slider.setValue(60)
        track = slider._track_rect()
        self.assertEqual(slider._value_to_y(), track.y())

        # Test min value mapping
        slider.setValue(0)
        self.assertEqual(slider._value_to_y(), track.y() + track.height())

if __name__ == '__main__':
    unittest.main()
