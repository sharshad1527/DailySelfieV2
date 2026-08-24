# gui/tray.py
"""
System tray icon for DailySelfie (Wave-1).

Cross-platform (Linux + Windows). Created only for the default dashboard GUI
launch; the --start-up popup mode and headless CLI modes intentionally run
without a tray.

Behavior:
- create_tray_icon() returns None gracefully when no system tray host is
  available (e.g. minimal window managers without a tray, offscreen QPA) or
  when construction fails for any reason. Callers must treat None as
  "no tray today" — this module never raises.
- Tooltip shows the current capture streak, computed from IndexAPI capture
  dates via core.streak.calculate_streaks. It is refreshed ONLY at creation
  time; there are deliberately NO polling loops or timers. Future callers
  (e.g. after a successful capture/deletion lands in the index) may call
  tray.update_tooltip(index_api) to refresh it on demand.
- Left-click / Trigger opens (focuses) the dashboard via the provided
  on_open_dashboard callback.
- "Capture now" spawns the same detached subprocess the desktop entry uses
  (DailySelfie.py --start-up --allow-retake) via QProcess.startDetached;
  no GUI windows are imported into the tray process.
- Teardown: the icon hides itself on QApplication.aboutToQuit.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QProcess
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from core.logging import get_logger
from core.streak import calculate_streaks

logger = get_logger("tray")

_APP_NAME = "DailySelfie"


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def streak_tooltip(dates) -> str:
    """
    Human-readable tooltip for a list of 'YYYY-MM-DD' capture dates.

    Active streak  -> "DailySelfie · 🔥 N-day streak"
    Empty/broken   -> "DailySelfie"
    """
    try:
        current, _best, _has_today = calculate_streaks(list(dates or []))
    except Exception as e:
        logger.warning("streak_calculation_failed", extra={"meta": {"error": str(e)}})
        return _APP_NAME
    if current > 0:
        return f"{_APP_NAME} · 🔥 {current}-day streak"
    return _APP_NAME


def _tooltip_for(index_api) -> str:
    """Tooltip from the live index; any DB error falls back to the base name."""
    try:
        return streak_tooltip(index_api.get_all_capture_dates())
    except Exception as e:
        logger.warning("tooltip_dates_fetch_failed", extra={"meta": {"error": str(e)}})
        return _APP_NAME


def _app_icon(paths) -> QIcon:
    """Per-platform app icon (.ico on Windows, .png elsewhere).

    A missing asset is tolerated: an empty QIcon renders as a blank slot
    instead of crashing.
    """
    ext = "app.ico" if paths.os_name == "windows" else "app.png"
    icon_path = Path(paths.project_root) / "gui" / "assets" / "icons" / ext
    if icon_path.exists():
        return QIcon(str(icon_path))
    logger.warning("tray_icon_asset_missing", extra={"meta": {"path": str(icon_path)}})
    return QIcon()


def _venv_python(paths) -> Path:
    """Interpreter for detached capture; mirrors desktop-entry targets."""
    if paths.os_name == "windows":
        scripts = Path(paths.venv_dir) / "Scripts"
        for name in ("pythonw.exe", "python.exe"):
            if (scripts / name).exists():
                return scripts / name
        return scripts / "python.exe"
    return Path(paths.venv_dir) / "bin" / "python"


def focus_window(widget) -> None:
    """Restore/raise/activate an existing top-level window (tray open action)."""
    if widget is None:
        return
    try:
        if widget.isMinimized():
            widget.showNormal()
        else:
            widget.show()
        widget.raise_()
        widget.activateWindow()
    except RuntimeError:
        # Underlying C++ widget already destroyed (window closed earlier).
        pass


# ---------------------------------------------------------
# Tray icon
# ---------------------------------------------------------
class SelfieTrayIcon(QSystemTrayIcon):
    """System tray icon with streak tooltip and dashboard/capture/quit menu."""

    def __init__(self, app, cfg, paths, index_api, on_open_dashboard):
        super().__init__()
        self._app = app
        self._cfg = cfg  # Reserved for future toggles (e.g. behavior.tray_enabled).
        self._paths = paths
        self._on_open_dashboard = on_open_dashboard

        self.setIcon(_app_icon(paths))

        # Held reference: setContextMenu does NOT take ownership, so the menu
        # must outlive __init__ or Qt would destroy it once Python GC runs.
        menu = QMenu()
        act_open = QAction("Open Dashboard", menu)
        act_open.triggered.connect(self._open_dashboard)
        act_capture = QAction("Capture now", menu)
        act_capture.triggered.connect(self._capture_now)
        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_open)
        menu.addAction(act_capture)
        menu.addSeparator()
        menu.addAction(act_quit)
        self._menu = menu
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)
        self.update_tooltip(index_api)

        # Clean teardown once the event loop winds down.
        app.aboutToQuit.connect(self.hide)

    # ---------------------------------------------------------
    # Public API
    # ---------------------------------------------------------
    def update_tooltip(self, index_api) -> None:
        """Recompute the streak tooltip on demand (no polling by design)."""
        try:
            self.setToolTip(_tooltip_for(index_api))
        except RuntimeError:
            pass

    # ---------------------------------------------------------
    # Slots
    # ---------------------------------------------------------
    def _on_activated(self, reason) -> None:
        """Left-click/Trigger opens the dashboard (platform-consistent)."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._open_dashboard()

    def _open_dashboard(self) -> None:
        cb = self._on_open_dashboard
        if cb is None:
            return
        try:
            cb()
        except Exception:
            logger.exception("open_dashboard_callback_failed")

    def _capture_now(self) -> None:
        """Spawn the startup popup detached, exactly like the desktop entry."""
        program = _venv_python(self._paths)
        if not program.exists():
            logger.warning(
                "venv_python_missing_using_sys_executable",
                extra={"meta": {"expected": str(program)}},
            )
            program = Path(sys.executable)

        app_entry = Path(self._paths.project_root) / "DailySelfie.py"
        ok = False
        try:
            ok = QProcess.startDetached(
                str(program),
                [str(app_entry), "--start-up", "--allow-retake"],
                str(self._paths.project_root),
            )
        except Exception:
            logger.exception("capture_spawn_failed")
        if not ok:
            logger.warning("capture_spawn_failed")

    def _quit(self) -> None:
        try:
            self._app.quit()
        except Exception:
            logger.exception("tray_quit_failed")


# ---------------------------------------------------------
# Factory
# ---------------------------------------------------------
def create_tray_icon(app, cfg, paths, index_api, on_open_dashboard):
    """
    Build and show the DailySelfie system tray icon.

    Args:
        app: QApplication instance (used for quit + teardown hookup).
        cfg: Loaded app config (currently unused; reserved).
        paths: AppPaths from core.paths.
        index_api: IndexAPI used for streak tooltip computation.
        on_open_dashboard: Zero-arg callable invoked on left-click /
            "Open Dashboard".

    Returns:
        SelfieTrayIcon (a QSystemTrayIcon subclass exposing
        update_tooltip(index_api)), or None when no tray host is available
        or anything goes wrong. Never raises.
    """
    try:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.info("system_tray_unavailable_skipping")
            return None
        tray = SelfieTrayIcon(app, cfg, paths, index_api, on_open_dashboard)
        tray.show()
        return tray
    except Exception:
        logger.exception("tray_creation_failed")
        return None
