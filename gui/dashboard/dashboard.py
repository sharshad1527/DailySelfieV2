# gui/dashboard/dashboard.py
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QApplication, QVBoxLayout, QGraphicsOpacityEffect, QWidget
)
from PySide6.QtCore import (
    QEvent, QPropertyAnimation, QParallelAnimationGroup, QRectF, QSize,
    QStandardPaths, Qt,
)
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap
from gui.theme.theme_vars import theme_vars
from gui.theme import motion_tokens as mt

try:
    from gui.dashboard.window_con import DashboardShell
except:
    from window_con import DashboardShell

from core.index_api import get_api
from core.logging import get_logger
from core.recap import build_recap_stats, recap_period_id
from core.thumbs import load_display_pixmap
from gui.dashboard.pages.selfie import SelfiePage
from gui.dashboard.pages.dashboard import DashboardPage, _remember_behavior_list
from gui.dashboard.pages.calendar import CalendarPage
from gui.dashboard.pages.settings import SettingsPage
from gui.dashboard.navigation_rail import NavigationRail
from gui.widgets.error_popup import ErrorToast
from gui.widgets.pixmap_utils import active_dpr
from gui.widgets.recap import RecapStage, render_card_png, render_deck_pngs

logger = get_logger("dashboard_window")

# Export canvas for recap PNGs (4:5, render_card_png's own default).
RECAP_EXPORT_SIZE = (1080, 1350)

# Fraction of the screen the photo viewer may occupy (min/max px clamps).
VIEWER_SCREEN_FRACTION = 0.82
VIEWER_MIN_SIZE = (320, 240)
VIEWER_MAX_SIZE = (1200, 1000)


# ---------------------------------------------------------------
# Full-size photo viewer (lightbox)
# ---------------------------------------------------------------
class _PhotoSurface(QWidget):
    """Paints the decoded photo, centered and aspect-fit inside its rect."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # The decoded original is kept untouched; only `scaled` (a dpr-tagged,
        # aspect-fit derivative) is rebuilt, so repeated resizes never
        # compound resampling and the fit size stays derivable from `source`.
        self.source = QPixmap()
        self._scaled = QPixmap()
        self._cached = QSize()

    def set_photo(self, pixmap: QPixmap) -> None:
        self.source = pixmap if pixmap is not None else QPixmap()
        self._scaled = QPixmap()
        self._cached = QSize()
        self._rescale()
        self.update()

    def source_size(self) -> QSize:
        return self.source.size()

    def _rescale(self) -> None:
        """Scale in DEVICE pixels and tag the result, so HiDPI stays sharp."""
        if self.source.isNull() or self.width() <= 0 or self.height() <= 0:
            return
        dpr = active_dpr(self)
        target = QSize(max(1, round(self.width() * dpr)),
                       max(1, round(self.height() * dpr)))
        if target == self._cached and not self._scaled.isNull():
            return
        self._cached = target
        self._scaled = self.source.scaled(target, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation)
        self._scaled.setDevicePixelRatio(dpr)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()
        self.update()

    def paintEvent(self, event):
        if self._scaled.isNull():
            self._rescale()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self._scaled.isNull():
            dpr = float(self._scaled.devicePixelRatio()) or 1.0
            target = QRectF(self.rect())
            # The scaled pixmap is already dpr-tagged, so the source rect is
            # in LOGICAL units (device px / dpr) - the target stays QRectF
            # because PySide6 won't take a QRect here.
            p.drawPixmap(
                target, self._scaled,
                QRectF(0, 0, self._scaled.width() / dpr,
                       self._scaled.height() / dpr))
        p.end()


class PhotoViewer(QDialog):
    """Frameless full-size photo lightbox (dismiss: click / Esc / Close).

    Deliberately minimal: no zoom/pan state, just the photo at as much
    screen real estate as it can get, plus the filename. Sized shrink-to-fit
    so a portrait selfie never lands in a letterboxed landscape box.
    """

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self._path = Path(image_path)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("PhotoViewer")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)

        card = QFrame()
        card.setObjectName("ViewerCard")
        outer.addWidget(card)

        col = QVBoxLayout(card)
        col.setContentsMargins(12, 12, 12, 10)
        col.setSpacing(8)

        self.surface = _PhotoSurface(card)
        self.surface.setMinimumSize(*VIEWER_MIN_SIZE)
        col.addWidget(self.surface, 1)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.caption = QLabel(self._path.name)
        self.caption.setObjectName("ViewerCaption")
        row.addWidget(self.caption)
        row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setObjectName("ViewerClose")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        row.addWidget(close_btn)
        col.addLayout(row)

        # One decode up front, served through the thumbnail cache like every
        # other photo surface in the app; the dialog then shrinks to fit it.
        max_w, max_h = self._screen_box()
        self.surface.set_photo(load_display_pixmap(
            self._path, float(max_w), active_dpr(self)))
        self._fit_to_photo(max_w, max_h)

        # Click anywhere on the photo dismisses (scrim-style), like the recap.
        self.surface.mousePressEvent = self.close

        self._apply_theme()
        try:
            theme_vars()._controller.themeChanged.connect(self._apply_theme)
        except (RuntimeError, AttributeError, TypeError):
            pass

    # ---------------------------------------------------------------
    def _screen_box(self) -> tuple:
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        if avail is None or avail.width() <= 0 or avail.height() <= 0:
            return VIEWER_MAX_SIZE
        return (
            max(VIEWER_MIN_SIZE[0], min(VIEWER_MAX_SIZE[0],
                                        int(avail.width() * VIEWER_SCREEN_FRACTION))),
            max(VIEWER_MIN_SIZE[1], min(VIEWER_MAX_SIZE[1],
                                        int(avail.height() * VIEWER_SCREEN_FRACTION))),
        )

    def _fit_to_photo(self, max_w: int, max_h: int) -> None:
        """Resize the whole dialog to the photo (plus the caption row)."""
        chrome_w = 14 * 2 + 12 * 2          # outer margin + card padding
        chrome_h = 14 * 2 + 12 * 2 + 34     # + the caption/close row
        src = self.surface.source_size()
        iw, ih = src.width(), src.height()
        if iw <= 0 or ih <= 0:
            self.resize(min(max_w + chrome_w, 900), min(max_h + chrome_h, 700))
            return
        fit_w, fit_h = iw, ih
        if iw > max_w or ih > max_h:
            scale = min(max_w / iw, max_h / ih)
            fit_w, fit_h = max(1, int(iw * scale)), max(1, int(ih * scale))
        # Never shrink below the minimum the surface was given, even if that
        # makes the dialog slightly larger than the strict fit.
        fit_w = max(fit_w, VIEWER_MIN_SIZE[0])
        fit_h = max(fit_h, VIEWER_MIN_SIZE[1])
        self.surface.setFixedSize(fit_w, fit_h)
        self.resize(fit_w + chrome_w, fit_h + chrome_h)

    def _apply_theme(self) -> None:
        v = theme_vars()
        try:
            card = self.findChild(QFrame, "ViewerCard")
            card.setStyleSheet(f"""
                QFrame#ViewerCard {{
                    background-color: {v['surface_container_high']};
                    border: 1px solid {v['outline_variant']};
                    border-radius: 18px;
                }}
                QLabel#ViewerCaption {{
                    color: {v['on_surface_variant']};
                    font-size: 12px;
                }}
                QPushButton#ViewerClose {{
                    background-color: {v['surface_container_highest']};
                    color: {v['on_surface']};
                    border: none;
                    border-radius: 15px;
                    padding: 5px 14px;
                    font-size: 12px;
                    font-weight: 600;
                }}
                QPushButton#ViewerClose:hover {{
                    background-color: {v['surface_container_highest']};
                    color: {v['primary']};
                }}
            """)
            self.caption.setStyleSheet(f"color: {v['on_surface_variant']};")
        except RuntimeError:
            pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        try:
            theme_vars()._controller.themeChanged.disconnect(self._apply_theme)
        except (RuntimeError, AttributeError, TypeError):
            pass
        super().closeEvent(event)


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

        # Recap stage currently on screen (set by _open_recap) + its period,
        # so the deck's save/click requests resolve without the deck having to
        # know about dialogs.
        self._recap_stage: Optional[RecapStage] = None
        self._recap_period = ("month", 0, None)
        # Live photo viewer (lightbox); re-opened, never stacked.
        self._photo_viewer: Optional[PhotoViewer] = None

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

        # Deleting from the CALENDAR's day detail must refresh the dashboard
        # too - otherwise its today-card keeps showing the deleted photo
        # (calendar already reloads its own month before emitting).
        self._calendar_page.photoDeleted.connect(self._dashboard_page.refresh)

        # Metadata edited in the calendar's day detail (note/mood) is
        # rendered by the dashboard's carousel cards + today-card, so both
        # surfaces need the rebuild. Distinct from photoSaved/photoDeleted:
        # neither of those fires for an edit-in-place.
        self._calendar_page.dataChanged.connect(self._dashboard_page.refresh)

        # Carousel photo click -> full-size viewer (no consumer until now).
        # The carousel is rebuilt with the whole surface on every refresh, so
        # a one-shot connect in __init__ would die on the first rebuild;
        # _bind_carousel re-attaches after each one (see _install_carousel_hook).
        self._carousel_bound = None
        self._install_carousel_hook()
        self._bind_carousel()

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
        self._recap_stage = stage
        self._recap_period = (scope, year, month)
        # Card actions ("Save PNG" / "Save this card" / "Save all as PNG") and
        # the best-shot tiles. Connected before open() so a card rebuilt while
        # the deck builds itself can't miss them.
        stage.savePngRequested.connect(self._on_recap_save_png)
        stage.saveAllRequested.connect(self._on_recap_save_all)
        stage.shotClicked.connect(self._on_recap_shot_clicked)
        stage.open(data, "month" if month else "year", invoker)

    def _on_recap_closed(self, period):
        self._recap_stage = None
        _remember_behavior_list(self._config_path, "recap_seen",
                                recap_period_id(period))
        self._dashboard_page.refresh_highlights()

    # ---------------------------------------------------------
    # Recap PNG export (§8 backlog #6/#8)
    # ---------------------------------------------------------
    def _recap_slug(self) -> str:
        """Filename-safe period slug; mirrors recap_period_id's shape."""
        _, year, month = self._recap_period
        try:
            if month is not None:
                return f"recap-{int(year):04d}-{int(month):02d}"
            return f"recap-{int(year):04d}"
        except (TypeError, ValueError):
            return "recap"

    def _export_dir(self) -> str:
        """Start directory for the pickers: Pictures if it exists, else home."""
        for loc in (QStandardPaths.PicturesLocation, QStandardPaths.HomeLocation):
            path = QStandardPaths.writableLocation(loc)
            if path and Path(path).is_dir():
                return path
        return str(Path.home())

    def _on_recap_save_png(self, card) -> None:
        """One card -> getSaveFileName -> render_card_png -> report outcome."""
        kind = str(getattr(card, "CARD_KIND", "") or "card")
        suggested = str(Path(self._export_dir()) / f"{self._recap_slug()}-{kind}.png")
        path, _filter = QFileDialog.getSaveFileName(
            self, "Save recap card as PNG", suggested, "PNG image (*.png)")
        if not path:
            return  # user cancelled
        target = Path(path)
        if target.suffix.lower() != ".png":
            target = target.with_name(target.name + ".png")
        saved = render_card_png(card, target, RECAP_EXPORT_SIZE)
        if saved is None:
            self._toast("ERROR",
                        f"Couldn't save the recap card:\n{target.name}")
        else:
            self._toast("INFO", f"Saved {saved.name}")

    def _on_recap_save_all(self) -> None:
        """Whole deck -> getExistingDirectory -> numbered PNGs."""
        stage = self._recap_stage
        try:
            cards = list(stage.cards) if stage is not None else []
        except RuntimeError:
            cards = []
        if not cards:
            self._toast("WARNING", "This recap has no cards to export.")
            return
        directory = QFileDialog.getExistingDirectory(
            self, "Choose a folder for the recap cards", self._export_dir())
        if not directory:
            return
        try:
            written = render_deck_pngs(cards, directory, RECAP_EXPORT_SIZE,
                                       self._recap_slug())
        except Exception as e:
            logger.warning("recap_save_all_failed",
                           extra={"meta": {"error": str(e)}})
            self._toast("ERROR", f"Couldn't export the recap:\n{e}")
            return
        if not written:
            self._toast("ERROR", "Couldn't export the recap cards.")
        elif len(written) < len(cards):
            self._toast("WARNING",
                        f"Saved {len(written)} of {len(cards)} cards to "
                        f"{Path(directory).name}")
        else:
            self._toast("INFO",
                        f"Saved {len(written)} cards to {Path(directory).name}")

    # ---------------------------------------------------------
    # Carousel / recap tile -> full-size viewer
    # ---------------------------------------------------------
    def _install_carousel_hook(self) -> None:
        """Keep the carousel's item_clicked connected across surface rebuilds.

        DashboardPage._build_surface() throws away the whole DashboardSurface
        (carousel included) on every refresh, so the connection is re-made
        after each rebuild rather than once in __init__. Wrapping the single
        choke point every rebuild goes through covers refresh(),
        refresh_if_stale() and the theme-change refresh alike.
        """
        page = self._dashboard_page
        original = page._build_surface

        def _build_and_bind(*args, **kwargs):
            original(*args, **kwargs)
            self._bind_carousel()

        page._build_surface = _build_and_bind

    def _bind_carousel(self) -> None:
        """Connect the current surface's carousel click, at most once."""
        try:
            surface = self._dashboard_page._surface
            carousel = getattr(surface, "_carousel", None)
        except RuntimeError:
            return
        if carousel is None or carousel is self._carousel_bound:
            return
        try:
            carousel.item_clicked.connect(self._open_photo_viewer)
        except RuntimeError:
            return
        self._carousel_bound = carousel

    def _toast(self, level: str, message: str) -> None:
        """ErrorToast centred over the window (same placement as the pages)."""
        try:
            popup = ErrorToast(self, level=level, message=message)
            geo = self.window().geometry()
            popup.move(geo.x() + (geo.width() - popup.width()) // 2,
                       geo.y() + (geo.height() - popup.height()) // 3)
            popup.show()
        except Exception:
            pass

    def _open_photo_viewer(self, image_path) -> None:
        """Open `image_path` in the frameless lightbox (carousel + recap tiles)."""
        try:
            path = Path(str(image_path))
        except (TypeError, ValueError):
            return
        if not path.is_file():
            self._toast("WARNING", "That photo is no longer on disk.")
            return
        if self._photo_viewer is not None:
            # One viewer at a time; the recap deck stays up underneath.
            try:
                self._photo_viewer.close()
            except RuntimeError:
                pass
        viewer = PhotoViewer(path, self)
        geo = self.window().geometry()
        viewer.move(geo.x() + (geo.width() - viewer.width()) // 2,
                    geo.y() + (geo.height() - viewer.height()) // 2)
        self._photo_viewer = viewer
        viewer.show()

    def _on_recap_shot_clicked(self, date_text: str) -> None:
        """Best-shots tile clicked -> resolve its capture -> open the viewer."""
        path = self._shot_path_for(date_text)
        if path is None:
            self._toast("WARNING", "That shot isn't in the library anymore.")
            return
        self._open_photo_viewer(path)

    def _shot_path_for(self, date_text: str) -> Optional[Path]:
        """Map a best-shots tile key (a date/row id) back to its photo file.

        BestShotsCard emits whatever it labelled the tile with, which is the
        recap row's date-or-id - the authoritative mapping is the stage's own
        recap data, so read it from there before falling back to the library.
        """
        key = str(date_text or "").strip()
        if not key:
            return None
        try:
            data = getattr(self._recap_stage, "_recap_data", None) or {}
        except RuntimeError:
            data = {}
        rows = data.get("shot_rows") if isinstance(data, dict) else None
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("date") or row.get("id") or "") == key:
                path = row.get("path")
                if isinstance(path, str) and path and Path(path).is_file():
                    return Path(path)
        try:
            api = get_api(self._app_paths)
            hit = api.get_item(key)
        except Exception as e:
            logger.warning("recap_shot_lookup_failed",
                           extra={"meta": {"key": key, "error": str(e)}})
            return None
        path = (hit or {}).get("path")
        if isinstance(path, str) and path and Path(path).is_file():
            return Path(path)
        return None

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