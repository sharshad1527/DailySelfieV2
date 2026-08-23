# gui/dashboard/dashboard.py
import sys
from PySide6.QtWidgets import (
    QStackedWidget, QApplication, QHBoxLayout
)
from PySide6.QtCore import QEvent
from gui.theme.theme_vars import theme_vars 

try:
    from gui.dashboard.window_con import DashboardShell
except:
    from window_con import DashboardShell

from gui.dashboard.pages.selfie import SelfiePage
from gui.dashboard.pages.dashboard import DashboardPage
from gui.dashboard.pages.calendar import CalendarPage
from gui.dashboard.pages.settings import SettingsPage
from gui.dashboard.navigation_rail import NavigationRail

class DashboardWindow(DashboardShell):
    def __init__(self, theme_controller=None, cfg=None, config_path=None, app_paths=None):
        super().__init__()
        vars = theme_vars()
        self._pages = QStackedWidget()
        self._app_focused = True  # Track app focus state

        self._toggle_maximize()

        layout = QHBoxLayout()
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(0)

        self._content.setLayout(layout)

        self._navigation_rail = NavigationRail()
        layout.addWidget(self._navigation_rail)
        
        # Store page references for signal connections
        self._selfie_page = SelfiePage()
        self._dashboard_page = DashboardPage()
        self._calendar_page = CalendarPage(
            theme_controller=theme_controller,
            cfg=cfg,
            config_path=config_path,
            app_paths=app_paths,
        )
        self._settings_page = SettingsPage(
            theme_controller=theme_controller,
            cfg=cfg,
            config_path=config_path,
            app_paths=app_paths,
        )
        
        # Use indices matching navigation rail page_ids: 0=selfie, 1=dashboard, 2=calendar, 3=settings
        self._pages.addWidget(self._selfie_page)      # index 0
        self._pages.addWidget(self._dashboard_page)   # index 1
        self._pages.addWidget(self._calendar_page)    # index 2
        self._pages.addWidget(self._settings_page)    # index 3

        layout.addWidget(self._pages, 1)
        # Start on dashboard (index 1, matching navigation rail's default)
        self._pages.setCurrentIndex(1)
        self._navigation_rail.pageSelected.connect(self._onPageSelected)
        layout.addStretch()
        
        # Cross-page communication
        # When selfie is saved, refresh dashboard to show new photo
        self._selfie_page.photoSaved.connect(self._dashboard_page.refresh)
        # When selfie is saved, refresh the calendar month + year viz
        self._selfie_page.photoSaved.connect(self._calendar_page.refresh)

        # When dashboard's "take selfie" button is clicked, switch to selfie tab
        self._dashboard_page.takeSelfieRequested.connect(self._switch_to_selfie_tab)

        # When calendar's zero-photos CTA / detail CTA is clicked, switch to selfie tab
        self._calendar_page.takeSelfieRequested.connect(self._switch_to_selfie_tab)
        
        # When dashboard's "retake" button is clicked, switch to selfie tab and trigger retake
        self._dashboard_page.retakeRequested.connect(self._handle_retake_from_dashboard)
        
        # When photo is deleted from dashboard, refresh the dashboard
        self._dashboard_page.photoDeleted.connect(self._dashboard_page.refresh)

    def _onPageSelected(self, page_id: int):
        """Handle page selection from navigation rail."""
        self._pages.setCurrentIndex(page_id)
    
    def _select_nav_button_by_page_id(self, page_id: int):
        """Select navigation rail button by page_id."""
        for btn in self._navigation_rail._buttons:
            if hasattr(btn, 'page_id') and btn.page_id == page_id:
                self._navigation_rail.toggleCheckedState(btn)
                return
    
    def _switch_to_selfie_tab(self):
        """Switch to selfie tab and update navigation rail."""
        self._pages.setCurrentIndex(0)  # Selfie is at index 0
        # Update navigation rail to select selfie button (page_id=0)
        self._select_nav_button_by_page_id(0)
        # Explicitly activate the selfie page (showEvent may not fire for stacked widgets)
        self._selfie_page.activate()
    
    def _handle_retake_from_dashboard(self):
        """Handle retake request from dashboard - switch to selfie tab and trigger retake."""
        # Switch to selfie tab (but don't activate - we'll call retake instead)
        self._pages.setCurrentIndex(0)  # Selfie is at index 0
        self._select_nav_button_by_page_id(0)
        # Trigger retake on the selfie page (this starts camera)
        self._selfie_page._on_retake()
    
    def changeEvent(self, event):
        """Handle window state changes - stop camera when app loses focus."""
        if event.type() == QEvent.ActivationChange:
            if self.isActiveWindow():
                # App regained focus
                if not self._app_focused:
                    self._app_focused = True
                    # If on selfie page, restart camera
                    if self._pages.currentIndex() == 0:
                        self._selfie_page.activate()
            else:
                # App lost focus
                if self._app_focused:
                    self._app_focused = False
                    # Stop camera if running
                    self._selfie_page._stop_preview()
        super().changeEvent(event)



# --- Smoke Test ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = DashboardWindow()
    win.show()
    app.exec()