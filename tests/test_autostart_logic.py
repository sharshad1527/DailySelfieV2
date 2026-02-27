
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

# We will import the module under test
import core.autostart_manager

class TestAutostartManagerLogic(unittest.TestCase):

    @patch("core.autostart_manager.write_config_bootstrap")
    @patch("core.autostart_manager.write_config")
    @patch("core.autostart_manager.disable_autostart")
    @patch("core.autostart_manager.enable_autostart")
    @patch("core.autostart_manager.load_config")
    @patch("core.autostart_manager.get_app_paths")
    def test_write_config_success_prevents_bootstrap(self, mock_paths, mock_load, mock_enable, mock_disable, mock_write, mock_bootstrap):
        """
        Scenario: write_config succeeds.
        Expected: write_config_bootstrap is NOT called.
        """
        with patch("pathlib.Path.exists", return_value=True):
            mock_load.return_value = {"installation": {"autostart": False}}

            # Run function
            core.autostart_manager.set_autostart(True)

            # Verify write_config was called
            mock_write.assert_called_once()

            # Verify bootstrap was NOT called
            mock_bootstrap.assert_not_called()

    @patch("core.autostart_manager.write_config_bootstrap")
    @patch("core.autostart_manager.write_config")
    @patch("core.autostart_manager.disable_autostart")
    @patch("core.autostart_manager.enable_autostart")
    @patch("core.autostart_manager.load_config")
    @patch("core.autostart_manager.get_app_paths")
    def test_write_config_failure_calls_bootstrap(self, mock_paths, mock_load, mock_enable, mock_disable, mock_write, mock_bootstrap):
        """
        Scenario: write_config fails (raises Exception).
        Expected: write_config_bootstrap IS called.
        """
        with patch("pathlib.Path.exists", return_value=True):
            mock_load.return_value = {"installation": {"autostart": False}}

            # Make write_config raise exception
            mock_write.side_effect = RuntimeError("tomli-w missing")

            # Run function
            core.autostart_manager.set_autostart(True)

            # Verify write_config was called
            mock_write.assert_called_once()

            # Verify bootstrap was called
            mock_bootstrap.assert_called_once()

if __name__ == "__main__":
    unittest.main()
