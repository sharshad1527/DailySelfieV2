# gui/dashboard/dashboard.py
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QStackedWidget, QApplication, QHBoxLayout, QGraphicsOpacityEffect, QWidget
)
from PySide6.QtCore import QEvent, QPoint, QPropertyAnimation, QParallelAnimationGroup
from gui.theme.theme_vars import theme_vars
from gui.theme import motion_tokens as mt

try:
    from gui.dashboard.window_con import DashboardShell
except:
    from window_con import DashboardShell

from core.index_api import get_api
from core.logging import get_logger
from core.recap import build_recap_stats, recap_period_id
from gui.dashboard.pages.selfie import SelfiePage
from gui.dashboard.pages.dashboard import DashboardPage, _remember_behavior_list
from gui.dashboard.pages.calendar import CalendarPage
from gui.dashboard.pages.settings import SettingsPage
from gui.dashboard.navigation_rail import NavigationRail
from gui.widgets.recap import RecapStage

logger = get_logger("dashboard_window")


class DashboardWindow(DashboardShell):
    def __init__(self, theme_controller=None, cfg=None, config_path=None, app_paths=None):
        super().__init__()
        vars = theme_vars()
        self._pages = QStackedWidget()
        # Held refs for the incoming-only page transition (retarget-not-queue)
        self._page_switch_anim = None
        self._page_switch_effect = None
        self._page_switch_target = None
        self._page_switch_endpos = None
        self._app_focused = True  # Track app focus state

        self._app_paths = app_paths
        self._config_path = (Path(config_path) if config_path else
                             Path(getattr(self._app_paths, "config_dir", Path.cwd())) / "config.toml")

        self._toggle_maximize()

        layout = QHBoxLayout()
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(0)

        self._content.setLayout(layout)

        self._navigation_rail = NavigationRail()
        layout.addWidget(self._navigation_rail)

        # Store page references for signal connections
        self._selfie_page = SelfiePage()
        # Pass the config-applied paths so the today-card glob + photos
        # watcher target the same photos_root the popup captures into.
        self._dashboard_page = DashboardPage(
            app_paths=app_paths, cfg=cfg, config_path=self._config_path)
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

        # ---- Highlights & recaps wiring (§8) ----
        self._dashboard_page.recapLaunchRequested.connect(self._open_recap)
        self._calendar_page.recapRequested.connect(
            lambda y, m: self._open_recap(("month", int(y), int(m))))
        self._settings_page.recapLaunchRequested.connect(self._open_recap)
        self._dashboard_page.throwbackOpenRequested.connect(
            self._open_throwback_in_calendar)

    # ---------------------------------------------------------
    # Recap stage (§8)
    # ---------------------------------------------------------
    def _open_recap(self, period):
        period = tuple(period or ())
        if len(period) < 2:
            return
        scope, year = str(period[0]), int(period[1])
        month = int(period[2]) if len(period) > 2 and period[2] is not None else None
        try:
            api = get_api(self._app_paths)
            data = build_recap_stats(api, year, month)
        except Exception as e:
            logger.warning("recap_open_failed",
                           extra={"meta": {"error": str(e)}})
            return
        stage = RecapStage(self._content)
        stage.closed.connect(lambda p=(scope, year, month): self._on_recap_closed(p))
        invoker = self.sender() if isinstance(self.sender(), QWidget) else None
        stage.open(data, "month" if month else "year", invoker)

    def _on_recap_closed(self, period):
        _remember_behavior_list(self._config_path, "recap_seen",
                                recap_period_id(period))
        self._dashboard_page.refresh_highlights()

    def _open_throwback_in_calendar(self, day):
        """On This Day banner click -> calendar on that capture's month."""
        try:
            target_year, target_month = int(day.year), int(day.month)
        except (AttributeError, TypeError):
            return
        self._switch_page(2)
        self._select_nav_button_by_page_id(2)
        self._calendar_page._jump_to_month(target_year, target_month)

    def _onPageSelected(self, page_id: int):
        """Handle page selection from navigation rail."""
        self._switch_page(page_id)

    def _switch_page(self, new_index: int):
        """Instant index switch + direction-aware incoming-wrapper transition
        (motion-system.md): wrapper pos.x sign*16→0 ∥ opacity 0→1, 200ms
        OutCubic; effect detached in finished; retargets on rapid clicks;
        gated on behavior.motion_enabled (off = instant)."""
        old_index = self._pages.currentIndex()
        if new_index == old_index or not (0 <= new_index < self._pages.count()):
            return
        self._pages.setCurrentIndex(new_index)
        if new_index == 1:
            # Dashboard visible again: a capture made by the startup popup's
            # separate process can't reach us via photoSaved — re-check.
            self._dashboard_page.refresh_if_stale()
        if not mt.is_motion_enabled():
            return
        wrap = getattr(self._pages.widget(new_index), "_motion_wrapper", None)
        if wrap is None:
            return
        # Retarget: stop the held pair and settle its wrapper explicitly —
        # Qt only emits finished() at natural end, never on mid-flight stop().
        prev = self._page_switch_anim
        if prev is not None:
            try:
                prev.stop()
                if self._page_switch_target is not None:
                    self._page_switch_target.move(self._page_switch_endpos)
                    self._page_switch_target.setGraphicsEffect(None)
            except RuntimeError:
                pass
            self._page_switch_anim = None
            self._page_switch_effect = None
            self._page_switch_target = None
            self._page_switch_endpos = None
        sign = 1 if new_index > old_index else -1
        effect = QGraphicsOpacityEffect(wrap)
        wrap.setGraphicsEffect(effect)
        end_pos = wrap.pos()
        wrap.move(end_pos.x() + sign * mt.slide_distance, end_pos.y())

        pos_anim = QPropertyAnimation(wrap, b"pos", wrap)
        pos_anim.setDuration(mt.duration_base)
        pos_anim.setEasingCurve(mt.curve_enter)
        pos_anim.setStartValue(wrap.pos())
        pos_anim.setEndValue(end_pos)
        opa_anim = QPropertyAnimation(effect, b"opacity", wrap)
        opa_anim.setDuration(mt.duration_base)
        opa_anim.setEasingCurve(mt.curve_enter)
        opa_anim.setStartValue(0.0)
        opa_anim.setEndValue(1.0)
        group = QParallelAnimationGroup(wrap)
        group.addAnimation(pos_anim)
        group.addAnimation(opa_anim)

        def _detach_effect():
            try:
                wrap.move(end_pos)
                wrap.setGraphicsEffect(None)
            except RuntimeError:
                pass
            self._page_switch_effect = None
            if self._page_switch_anim is group:
                self._page_switch_anim = None
                self._page_switch_target = None
                self._page_switch_endpos = None

        group.finished.connect(_detach_effect)
        self._page_switch_anim = group
        self._page_switch_effect = effect
        self._page_switch_target = wrap
        self._page_switch_endpos = end_pos
        group.start()
    
    def _select_nav_button_by_page_id(self, page_id: int):
        """Select navigation rail button by page_id."""
        for btn in self._navigation_rail._buttons:
            if hasattr(btn, 'page_id') and btn.page_id == page_id:
                self._navigation_rail.toggleCheckedState(btn)
                return
    
    def _switch_to_selfie_tab(self):
        """Switch to selfie tab and update navigation rail."""
        self._switch_page(0)  # Selfie is at index 0
        # Update navigation rail to select selfie button (page_id=0)
        self._select_nav_button_by_page_id(0)
        # Explicitly activate the selfie page (showEvent may not fire for stacked widgets)
        self._selfie_page.activate()
    
    def _handle_retake_from_dashboard(self):
        """Handle retake request from dashboard - switch to selfie tab and trigger retake."""
        # Switch to selfie tab (but don't activate - we'll call retake instead)
        self._switch_page(0)  # Selfie is at index 0
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