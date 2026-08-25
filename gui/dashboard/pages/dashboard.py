# gui/dashboard/pages/dashboard.py
import calendar as pycal
import time
from datetime import date as date_cls, datetime, timezone
from pathlib import Path
from typing import List, Set, Tuple

from PySide6.QtCore import Qt, QSize, Signal, QTimer, QFileSystemWatcher
from PySide6.QtGui import QPixmap, QIcon, QPainter, QMovie, QColor, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QSizePolicy, QApplication

from gui.theme.theme_vars import theme_vars
from gui.widgets.lift_mixin import LiftMixin
from gui.widgets.motion import install_motion_wrapper
from gui.widgets.pixmap_utils import active_dpr, recolored_icon, rounded_corners, scaled_cover_crop
from gui.dashboard.widgets.highlight_chip import HighlightChip, RecapEntryCard
from gui.dashboard.widgets.mood_trend_chart import MoodTrendChart, play_entrance_fade
from core.capture import check_if_already_captured
from core.storage import delete_path
from core.paths import get_app_paths
from core.config import ensure_config, apply_config_to_paths, load_config, write_config
from core.recap import (
    MILESTONE_RUNGS,
    comeback_signal,
    mood_shift,
    recap_eligible_periods,
    recap_period_id,
    streak_record_active,
)
from core.thumbs import load_display_pixmap
from core.index_api import get_api
from core.streak import calculate_streaks
from core.logging import get_logger

logger = get_logger("dashboard_page")

# Asset paths
_paths = get_app_paths("DailySelfie", ensure=False)

# ICONS_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "icons"
ICONS_DIR = _paths.project_root / "gui" / "assets" / "icons"

# print(ICONS_DIR)

MOOD_DIR = ICONS_DIR / "mood"

# Mood name to GIF mapping
MOOD_GIF_MAP = {
    "Great": "cool.gif",
    "Good": "smile.gif",
    "Neutral": "neutral.gif",
    "Bad": "sad.gif",
    "Awful": "sosad.gif",
}


def _blend_over(top_hex: str, base_hex: str, alpha: float) -> str:
    top = QColor(top_hex)
    base = QColor(base_hex)
    mix = lambda a, b: max(0, min(255, round(a * alpha + b * (1.0 - alpha))))
    return QColor(mix(top.red(), base.red()),
                  mix(top.green(), base.green()),
                  mix(top.blue(), base.blue())).name()


def _resolve_app_paths(app_paths=None):
    """Config-applied AppPaths: explicit argument wins, else bootstrap+config.

    The popup and selfie page save through apply_config_to_paths() (honouring
    [installation] overrides), so the raw get_app_paths() OS defaults
    (e.g. ~/Pictures) diverge from the real photos_root on every installed
    layout. Today-card globbing and the photos watcher must target the SAME
    root captures are written to, or today's capture stays invisible.
    """
    if app_paths is not None:
        return app_paths
    bootstrap = get_app_paths("DailySelfie", ensure=False)
    cfg = ensure_config(bootstrap.config_dir)
    return apply_config_to_paths(bootstrap, cfg)


class TodaySelfieCard(LiftMixin, QFrame):
    """
    Primary dashboard card showing today's selfie (image fills the card).
    Emits image_resized signal with the displayed image height.
    """
    image_resized = Signal(int)  # Emits the displayed image height
    takeSelfieRequested = Signal()  # Emitted when "Take selfie" button is clicked
    # C1 image-card variant: no lift movement; hover swaps the stylesheet
    # border outline_variant→outline to match the painted photo border.
    LIFT_IMAGE_CARD = True

    def __init__(self, app_paths=None):
        super().__init__()
        self._vars = theme_vars()
        self._image_path = None
        self._metadata = {}
        self._current_image_height = 0
        self._render_key = None  # (path, w, h, dpr) of the last decoded pixmap
        self._state_is_empty = False  # True once the empty-state UI is built
        self.take_selfie_btn = None  # Initialize to None
        # Config-applied paths: same resolution chain as the capture popup,
        # so the today-glob reads the photos_root captures land in.
        self._app_paths = _resolve_app_paths(app_paths)

        self.setObjectName("TodaySelfieCard")
        self.setMinimumHeight(250)
        self.setMinimumWidth(250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.setStyleSheet(f"""
            QFrame#TodaySelfieCard {{
                background-color: {self._vars['surface_container_low']};
                border: 1px solid {self._vars['outline_variant']};
                border-radius: 16px;
            }}
        """)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(0)

        self._content_widget = None

        self._check_today_selfie()
        self.init_lift()

    def _check_today_selfie(self):
        """Check if today's selfie exists and set the appropriate state.

        Idempotent: skips the UI rebuild when the resolved state matches
        what is already shown, so repeated re-checks (showEvent / watcher)
        are cheap no-ops.
        """
        try:
            app_paths = self._app_paths
            # Photos are saved under app_paths.photos_root by capture
            # (see core/capture.py); never compose data_dir/"photos".
            # Timezone-aware LOCAL-day lookup (UTC-named files).
            exists, today_selfie_path = check_if_already_captured(app_paths)
            
            if exists and today_selfie_path and today_selfie_path.exists():
                # Get metadata from index API
                selfie_id = today_selfie_path.stem  # e.g., "2026-01-02_040733"
                try:
                    api = get_api(app_paths)
                    metadata = api.get_item(selfie_id) or {}
                except Exception:
                    metadata = {}

                # Skip rebuild when already showing this exact capture
                if (not self._state_is_empty
                        and self._image_path is not None
                        and Path(self._image_path) == Path(today_selfie_path)
                        and self._metadata == metadata):
                    return

                self.set_taken_state(today_selfie_path, metadata)
            else:
                if self._state_is_empty:
                    return  # already showing empty state
                self.set_empty_state()
        except Exception:
            # If anything goes wrong, default to empty state
            if not self._state_is_empty:
                self.set_empty_state()

    def _clear_content(self):
        """Remove existing content widget and selfie label if any."""
        if self._content_widget:
            self._layout.removeWidget(self._content_widget)
            self._content_widget.deleteLater()
            self._content_widget = None
        
        # Also remove selfie_label if it exists (added directly in set_taken_state)
        if hasattr(self, 'selfie_label') and self.selfie_label:
            self._layout.removeWidget(self.selfie_label)
            self.selfie_label.deleteLater()
            self.selfie_label = None
        
        # Reset internal state
        self._image_path = None
        self._metadata = {}
        self._current_image_height = 0
        self._render_key = None

    def set_empty_state(self):
        """
        Configure card UI for 'no selfie taken today'.
        Shows primary button and secondary caption.
        """
        self._clear_content()
        self._state_is_empty = True

        # Create container for empty state content
        self._content_widget = QWidget()
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        # Add stretch to center content vertically
        content_layout.addStretch()

        # Primary button: "Take today's selfie"
        self.take_selfie_btn = QPushButton("Take today's selfie")
        self.take_selfie_btn.setObjectName("TakeSelfieButton")
        self.take_selfie_btn.setCursor(Qt.PointingHandCursor)
        self.take_selfie_btn.setFixedHeight(48)
        hover_bg = _blend_over(self._vars['primary'], self._vars['surface_container_low'], 0.85)
        pressed_bg = _blend_over(self._vars['primary'], self._vars['surface_container_low'], 0.75)
        self.take_selfie_btn.setStyleSheet(f"""
            QPushButton#TakeSelfieButton {{
                background-color: {self._vars['primary']};
                color: {self._vars['on_primary']};
                border: none;
                border-radius: 24px;
                padding: 0 24px;
                font-size: 14px;
                font-weight: 500;
            }}
            QPushButton#TakeSelfieButton:hover {{
                background-color: {hover_bg};
            }}
            QPushButton#TakeSelfieButton:pressed {{
                background-color: {pressed_bg};
            }}
        """)
        # Connect button to emit the signal
        self.take_selfie_btn.clicked.connect(self.takeSelfieRequested.emit)
        content_layout.addWidget(self.take_selfie_btn, alignment=Qt.AlignCenter)

        # Secondary text: "Capture your day"
        self.caption_label = QLabel("Capture your day")
        self.caption_label.setObjectName("CaptionLabel")
        self.caption_label.setAlignment(Qt.AlignCenter)
        self.caption_label.setStyleSheet(f"""
            QLabel#CaptionLabel {{
                color: {self._vars['on_surface_variant']};
                font-size: 12px;
            }}
        """)
        content_layout.addWidget(self.caption_label)

        # Add stretch to center content vertically
        content_layout.addStretch()

        self._layout.addWidget(self._content_widget)

    def _create_colored_icon(self, icon_name: str, qcolor):
        """
        Loads an SVG and repaints it with the given QColor (HiDPI-aware).
        """
        return recolored_icon(ICONS_DIR / icon_name, qcolor, active_dpr(self))

    def _create_rounded_pixmap(self, pixmap: QPixmap, radius: int) -> QPixmap:
        """
        Create a pixmap with rounded corners by clipping.
        """
        from PySide6.QtGui import QPainterPath
        
        rounded = QPixmap(pixmap.size())
        rounded.fill(Qt.transparent)
        
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        path = QPainterPath()
        path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), radius, radius)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        
        return rounded

    def set_taken_state(self, image_path: Path, metadata: dict = None):
        """
        Configure card to show just the selfie image, filling the entire card.
        """
        self._clear_content()
        self._state_is_empty = False
        self._metadata = metadata or {}
        self._image_path = image_path

        self.selfie_label = QLabel()
        self.selfie_label.setAlignment(Qt.AlignCenter)
        self.selfie_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.selfie_label.setStyleSheet("background-color: transparent;")
        

        self.layout().addWidget(self.selfie_label)
        
        self._update_selfie_image()
    
    def get_metadata(self):
        """Return the metadata for external widgets."""
        return getattr(self, '_metadata', {})

    def get_image_path(self):
        """Return the image path for external widgets."""
        return getattr(self, '_image_path', None)

    def has_selfie(self):
        """Return True if selfie exists."""
        return getattr(self, '_image_path', None) is not None
    
    def _create_bordered_rounded_pixmap(self, pixmap: QPixmap, radius: int, border_width: int, border_color) -> QPixmap:
        """Create a pixmap with rounded corners and a border (dpr-aware)."""
        from PySide6.QtGui import QPainterPath, QPen

        dpr = float(pixmap.devicePixelRatio()) or 1.0
        bw_dev = round(border_width * dpr)
        total_size = QSize(pixmap.width() + bw_dev * 2, pixmap.height() + bw_dev * 2)
        result = QPixmap(total_size)
        result.setDevicePixelRatio(dpr)
        result.fill(Qt.transparent)

        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw image inside (logical coordinates; pixmap carries its own dpr)
        logical_w = pixmap.width() / dpr
        logical_h = pixmap.height() / dpr
        inner_path = QPainterPath()
        inner_path.addRoundedRect(border_width, border_width, 
                                  logical_w, logical_h, 
                                  radius - border_width/2, radius - border_width/2)
        painter.setClipPath(inner_path)
        painter.drawPixmap(round(border_width), round(border_width), pixmap)
        painter.end()
        
        return result
    
    def _update_selfie_image(self):
        """Update selfie image to fill the card completely (dpr-aware)."""
        if not self._image_path:
            return
            
        BORDER_RADIUS = 16
        BORDER_WIDTH = 3
        PADDING = 12  # 10-20px padding as requested
        
        # Get available space in the card
        card_width = self.width() - (PADDING * 2)
        card_height = self.height() - (PADDING * 2)
        
        if card_width < 100 or card_height < 100:
            return  # Card not properly sized yet

        dpr = self.devicePixelRatioF()

        # Decode once per (path, size, dpr): resizes reuse the last pixmap and
        # oversized sources come from the disk thumbnail cache, so window
        # resizing no longer re-decodes the full-resolution capture.
        render_key = (str(self._image_path), card_width, card_height, dpr)
        if render_key != self._render_key:
            self._render_key = render_key
            self._pixmap_cache = load_display_pixmap(
                Path(self._image_path), max(card_width, card_height), dpr)
        pixmap = getattr(self, "_pixmap_cache", QPixmap())

        if not pixmap.isNull():
            # Scale to fill the available space while keeping aspect ratio,
            # then crop — all in device pixels so HiDPI stays sharp
            scaled = scaled_cover_crop(pixmap, card_width, card_height, dpr)
            
            # Apply rounded corners and border
            bordered_pixmap = self._create_bordered_rounded_pixmap(
                scaled, BORDER_RADIUS, BORDER_WIDTH, 
                self._vars.qcolor('outline_variant')
            )
            self.selfie_label.setPixmap(bordered_pixmap)
            
            # Emit height signal for info box
            image_height = round(bordered_pixmap.height() / dpr) + PADDING * 2
            if image_height != self._current_image_height:
                self._current_image_height = image_height
                self.image_resized.emit(image_height)
    
    def resizeEvent(self, event):
        """Handle resize to update image."""
        super().resizeEvent(event)
        if self._image_path:
            self._update_selfie_image()

class OnThisDayBanner(LiftMixin, QFrame):
    """
    Throwback strip: most recent capture from this calendar day in a previous
    year/month (IndexAPI.get_on_this_day). Hidden entirely when there is no
    match — build via create(), which returns None instead of an empty card.
    """
    openRequested = Signal(object)  # date of the throwback day

    THUMB_SIZE = 40

    def __init__(self, entry: dict):
        super().__init__()
        self._vars = theme_vars()
        self._entry = entry or {}
        self._day = self._parse_day()

        self.setObjectName("OnThisDayBanner")
        self.setFixedHeight(56)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"""
            QFrame#OnThisDayBanner {{
                background-color: {self._vars['surface_container_low']};
                border-radius: 12px;
            }}
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(10)

        thumb_label = QLabel()
        thumb_label.setFixedSize(self.THUMB_SIZE, self.THUMB_SIZE)
        source = Path(str(self._entry.get("path") or ""))
        if source.exists():
            pixmap = load_display_pixmap(source, self.THUMB_SIZE, active_dpr(self))
            if not pixmap.isNull():
                scaled = scaled_cover_crop(pixmap, self.THUMB_SIZE, self.THUMB_SIZE, active_dpr(self))
                thumb_label.setPixmap(rounded_corners(scaled, 10))
                row.addWidget(thumb_label)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        caption = QLabel("On this day")
        caption.setStyleSheet(f"""
            color: {self._vars['primary']};
            font-size: 10px;
            font-weight: 600;
        """)
        text_col.addWidget(caption)

        date_label = QLabel(self._format_day())
        date_label.setStyleSheet(f"""
            color: {self._vars['on_surface']};
            font-size: 13px;
            font-weight: 600;
        """)
        text_col.addWidget(date_label)
        text_col.addStretch()
        row.addLayout(text_col)
        row.addStretch()

        hint = QLabel("View in Calendar")
        hint.setStyleSheet(f"""
            color: {self._vars['on_surface_variant']};
            font-size: 11px;
        """)
        row.addWidget(hint)

        self.init_lift()

    @classmethod
    def create(cls, app_paths=None):
        """Build a banner for today's throwback capture, or None when no match."""
        try:
            app_paths = _resolve_app_paths(app_paths)
            entry = get_api(app_paths).get_on_this_day()
        except Exception:
            return None
        return cls(entry) if entry else None

    def _parse_day(self):
        ts = str(self._entry.get("ts") or "")
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date()
        except ValueError:
            try:
                return datetime.strptime(ts[:10], "%Y-%m-%d").date()
            except ValueError:
                return None

    def _format_day(self) -> str:
        return self._day.strftime("%b %d, %Y") if self._day else ""

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._day is not None:
            self.openRequested.emit(self._day)
        super().mouseReleaseEvent(event)


def _remember_behavior_list(config_path, key: str, value: str,
                            cap: int = 64) -> bool:
    """Append `value` to behavior[key] (dedupe, keep newest cap) atomically."""
    try:
        cfg = load_config(Path(config_path))
        beh = cfg.setdefault("behavior", {})
        items = [i for i in beh.get(key, []) if isinstance(i, str)]
        if value in items:
            return True
        items.append(value)
        beh[key] = items[-max(1, int(cap)):]
        write_config(Path(config_path), cfg)
        return True
    except Exception as e:
        logger.warning("behavior_list_persist_failed",
                       extra={"meta": {"key": key, "error": str(e)}})
        return False


class HighlightStrip(QWidget):
    """Highlights arbiter (§3): recap_ready chip > up to 3 chips >
    OnThisDayBanner > collapse to 0. Dismissals persist to
    behavior.dismissed_highlights; recap eligibility is shared with the
    side-column entry card via eligibilityChanged."""

    chipActivated = Signal(str)
    recapLaunchRequested = Signal(tuple)
    dismissedId = Signal(str)
    throwbackOpenRequested = Signal(object)
    eligibilityChanged = Signal(list, set)

    MAX_CHIPS = 3

    def __init__(self, app_paths=None, config_path=None, parent=None):
        super().__init__(parent)
        self._app_paths = _resolve_app_paths(app_paths)
        self._config_path = (Path(config_path) if config_path else
                             Path(self._app_paths.config_dir) / "config.toml")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self.hide()

    # ---- data ---------------------------------------------------------
    def _load_behavior(self) -> dict:
        try:
            return load_config(self._config_path).get("behavior", {})
        except Exception:
            return {}

    def recompute(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        beh = self._load_behavior()
        enabled = bool(beh.get("highlights_enabled", True))
        seen: Set[str] = {i for i in beh.get("recap_seen", [])
                          if isinstance(i, str)}
        dismissed: Set[str] = {i for i in beh.get("dismissed_highlights", [])
                               if isinstance(i, str)}

        periods: List[Tuple] = []
        dates: List[str] = []
        moods: List[dict] = []
        api = None
        try:
            api = get_api(self._app_paths)
            if enabled:
                periods = recap_eligible_periods(api)
            dates = api.get_all_capture_dates()
            moods = api.get_moods_since(60)
        except Exception:
            logger.debug("highlight_inputs_unavailable", exc_info=True)

        self.eligibilityChanged.emit(list(periods), seen)
        today = date_cls.today()
        built = False

        if enabled:
            # 1) recap_ready — newest eligible period not yet seen or dismissed
            ready = next((p for p in periods
                          if recap_period_id(p) not in seen
                          and recap_period_id(p) not in dismissed), None)
            if ready is not None:
                kind, y, m = (list(ready) + [None])[:3]
                label = (f"Your {pycal.month_name[int(m)]} recap is ready"
                         if m else f"Your {int(y)} recap is ready")
                chip = HighlightChip(
                    "recap_ready", label,
                    reason="A finished month is ready to rewatch",
                    dismiss_id=recap_period_id(ready),
                    icon_name="sparkles.svg", emphasis=True, hint="")
                chip.activated.connect(
                    lambda _k, p=tuple(ready): self.recapLaunchRequested.emit(p))
                chip.dismissed.connect(self._on_dismissed)
                policy = chip.sizePolicy()
                policy.setHorizontalPolicy(QSizePolicy.Expanding)
                chip.setSizePolicy(policy)
                self._layout.addWidget(chip)
                built = True
            else:
                # 2) scored chips (cap 3, drop lowest)
                candidates: List[Tuple[int, str, str, str, str, str]] = []
                current, best, has_today = calculate_streaks(dates)
                for rung in sorted(MILESTONE_RUNGS, reverse=True):
                    mid = f"milestone:{rung}"
                    if current >= rung and mid not in dismissed:
                        candidates.append((
                            80, mid, f"{rung}-day streak",
                            f"Your current streak crossed the {rung}-day milestone",
                            "streak.svg", "primary"))
                        break
                rid = "new_record"
                if rid not in dismissed and streak_record_active(dates,
                                                                 today=today):
                    candidates.append((
                        90, rid, "New personal record",
                        f"{current} days — your longest streak yet",
                        "celebration.svg", "tertiary"))
                cb = comeback_signal(dates, today=today)
                if cb is not None and "comeback" not in dismissed:
                    candidates.append((
                        60, "comeback", cb.title, cb.subtitle,
                        "selfie.svg", "secondary"))
                shift = mood_shift(moods, today=today)
                if shift is not None and "mood_shift" not in dismissed:
                    candidates.append((
                        50, "mood_shift", shift.title, shift.subtitle,
                        "light.svg", "secondary"))

                candidates.sort(key=lambda c: -c[0])
                kept = candidates[:self.MAX_CHIPS]
                if kept:
                    row_holder = QWidget()
                    row = QHBoxLayout(row_holder)
                    row.setContentsMargins(0, 0, 0, 0)
                    row.setSpacing(6)
                    row.addStretch()
                    for score, did, label, reason, icon, color_key \
                            in reversed(kept):
                        chip = HighlightChip(
                            did.split(":", 1)[0], label, reason=reason,
                            dismiss_id=did, icon_name=icon,
                            color_key=color_key)
                        chip.activated.connect(self.chipActivated.emit)
                        chip.dismissed.connect(self._on_dismissed)
                        row.insertWidget(0, chip)
                    self._layout.addWidget(row_holder)
                    built = True

        # 3) OnThisDay fallback (kept even with highlights disabled)
        if not built:
            banner = OnThisDayBanner.create(self._app_paths)
            if banner is not None:
                banner.openRequested.connect(self.throwbackOpenRequested.emit)
                self._layout.addWidget(banner)
                built = True

        self.setVisible(built)

    def refresh_highlights(self):
        self.recompute()

    def _on_dismissed(self, dismiss_id: str):
        _remember_behavior_list(self._config_path, "dismissed_highlights",
                                dismiss_id)
        self.dismissedId.emit(dismiss_id)
        self.recompute()


class StreakSummaryWidget(LiftMixin, QFrame):
    """
    Read-only summary showing current and longest streak with status icon.
    """
    def __init__(self, app_paths=None):
        super().__init__()

        self._vars = theme_vars()
        self._app_paths = _resolve_app_paths(app_paths)

        self.setObjectName("StreakSummaryWidget")
        self.setMinimumHeight(90)
        self.setMinimumWidth(200)
        self.setMaximumWidth(280)

        self.setStyleSheet(f"""
            QFrame#StreakSummaryWidget {{
                background-color: {self._vars['surface_container_low']};
                border-radius: 16px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Fetch streak data
        current, best, has_photo_today = self._get_streaks()
        
        # Title row with icon
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        
        # Status icon based on today's photo status
        self._status_icon = QLabel()
        icon_name = "streak.svg" if has_photo_today else "nostreak.svg"
        colored_icon = self._create_colored_icon(
            icon_name,
            self._vars.qcolor('tertiary') if has_photo_today else self._vars.qcolor('on_surface_variant')
        )
        self._status_icon.setPixmap(colored_icon.pixmap(20, 20))
        self._status_icon.setFixedSize(20, 20)
        title_row.addWidget(self._status_icon)
        
        # Title label
        title = QLabel("Streak")
        title.setStyleSheet(f"""
            color: {self._vars['on_surface']};
            font-size: 14px;
            font-weight: 600;
        """)
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)
        
        # Current streak value (large)
        current_text = f"{current} day{'s' if current != 1 else ''}"
        if not has_photo_today and current > 0:
            current_text += " (at risk)"
        
        # Use tertiary color when at risk, primary when safe
        streak_color = self._vars['tertiary'] if (not has_photo_today and current > 0) else self._vars['primary']
        
        current_label = QLabel(current_text)
        current_label.setStyleSheet(f"""
            color: {streak_color};
            font-size: 18px;
            font-weight: 700;
        """)
        layout.addWidget(current_label)
        
        # Horizontal separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet(f"background-color: {self._vars['outline_variant']};")
        separator.setFixedHeight(1)
        layout.addWidget(separator)
        
        # Best streak row
        best_row = QHBoxLayout()
        best_row.setSpacing(6)
        
        best_icon = self._create_colored_icon("timer.svg", self._vars.qcolor('on_surface_variant'))
        best_icon_label = QLabel()
        best_icon_label.setPixmap(best_icon.pixmap(16, 16))
        best_icon_label.setFixedSize(16, 16)
        best_row.addWidget(best_icon_label)
        
        best_label = QLabel(f"Best: {best} days")
        best_label.setStyleSheet(f"""
            color: {self._vars['on_surface_variant']};
            font-size: 13px;
            font-weight: 500;
        """)
        best_row.addWidget(best_label)
        best_row.addStretch()
        layout.addLayout(best_row)
        
        # Days to beat best streak
        days_to_beat = best - current + 1
        if days_to_beat > 0 and current > 0:
            beat_label = QLabel(f"{days_to_beat} more day{'s' if days_to_beat != 1 else ''} to beat record")
            beat_label.setStyleSheet(f"""
                color: {self._vars['on_surface_variant']};
                font-size: 11px;
                font-style: italic;
            """)
            layout.addWidget(beat_label)
        elif current > best:
            # Current streak IS the record
            record_row = QHBoxLayout()
            record_row.setSpacing(6)
            
            celebration_icon = self._create_colored_icon("celebration.svg", self._vars.qcolor('tertiary'))
            celebration_label = QLabel()
            celebration_label.setPixmap(celebration_icon.pixmap(16, 16))
            celebration_label.setFixedSize(16, 16)
            record_row.addWidget(celebration_label)
            
            record_label = QLabel("New record!")
            record_label.setStyleSheet(f"""
                color: {self._vars['tertiary']};
                font-size: 11px;
                font-weight: 600;
            """)
            record_row.addWidget(record_label)
            record_row.addStretch()
            layout.addLayout(record_row)

        self.init_lift()

    def _create_colored_icon(self, icon_name: str, qcolor):
        """Loads an SVG and repaints it with the given QColor (HiDPI-aware)."""
        return recolored_icon(ICONS_DIR / icon_name, qcolor, active_dpr(self))
    
    def _get_streaks(self) -> Tuple[int, int, bool]:
        """Fetch dates from DB and calculate streaks."""
        try:
            api = get_api(self._app_paths)
            dates = api.get_all_capture_dates()
            return calculate_streaks(dates)
        except Exception:
            return (0, 0, False)


class MoodSummaryWidget(LiftMixin, QFrame):
    """
    Widget showing mood summary for last 7 days and 30 days.
    Displays mood distribution with GIF icons and counts.
    """
    # Order of moods for display (positive to negative)
    MOOD_ORDER = ["Great", "Good", "Neutral", "Bad", "Awful"]
    
    def __init__(self, app_paths=None):
        super().__init__()

        self._vars = theme_vars()
        self._movies = []  # Keep references to QMovie objects
        self._app_paths = _resolve_app_paths(app_paths)

        self.setObjectName("MoodSummaryWidget")
        self.setMinimumHeight(90)
        self.setMinimumWidth(200)
        self.setMaximumWidth(280)

        self.setStyleSheet(f"""
            QFrame#MoodSummaryWidget {{
                background-color: {self._vars['surface_container_low']};
                border-radius: 16px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Fetch mood data
        moods_7, moods_30, days_available = self._get_mood_data()

        # Title row with icon
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        
        # Use a mood icon for the title
        self._title_icon = QLabel()
        self._title_icon.setFixedSize(20, 20)
        # Use the first available mood GIF as title icon
        title_gif_path = str(MOOD_DIR / "smile.gif")
        self._title_movie = QMovie(title_gif_path)
        if self._title_movie.isValid():
            self._title_movie.setScaledSize(QSize(20, 20))
            self._title_icon.setMovie(self._title_movie)
            self._title_movie.start()
        title_row.addWidget(self._title_icon)
        
        title = QLabel("Mood Summary")
        title.setStyleSheet(f"""
            color: {self._vars['on_surface']};
            font-size: 14px;
            font-weight: 600;
        """)
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        # 7-day section
        self._build_mood_section(layout, "Last 7 days", moods_7, 7)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet(f"background-color: {self._vars['outline_variant']};")
        separator.setFixedHeight(1)
        layout.addWidget(separator)

        # 30-day section (or available days)
        if days_available < 30:
            section_title = f"Last {days_available} days" if days_available > 0 else "No data"
        else:
            section_title = "Last 30 days"
        self._build_mood_section(layout, section_title, moods_30, days_available)

        self.init_lift()

    def _build_mood_section(self, parent_layout: QVBoxLayout, title: str, mood_counts: dict, total_days: int):
        """Build a section showing mood distribution."""
        # Section title
        section_label = QLabel(title)
        section_label.setStyleSheet(f"""
            color: {self._vars['on_surface_variant']};
            font-size: 11px;
            font-weight: 500;
        """)
        parent_layout.addWidget(section_label)

        if total_days == 0 or not mood_counts:
            no_data = QLabel("No mood data")
            no_data.setStyleSheet(f"""
                color: {self._vars['on_surface_variant']};
                font-size: 10px;
                font-style: italic;
            """)
            parent_layout.addWidget(no_data)
            return

        # Mood icons row
        mood_row = QHBoxLayout()
        mood_row.setSpacing(4)
        mood_row.setContentsMargins(0, 4, 0, 0)

        for mood in self.MOOD_ORDER:
            count = mood_counts.get(mood, 0)
            mood_container = self._create_mood_item(mood, count)
            mood_row.addWidget(mood_container)

        mood_row.addStretch()
        parent_layout.addLayout(mood_row)

        # Most common mood
        if mood_counts:
            most_common = max(mood_counts.items(), key=lambda x: x[1])
            if most_common[1] > 0:
                common_label = QLabel(f"Most common: {most_common[0]} ({most_common[1]} days)")
                common_label.setStyleSheet(f"""
                    color: {self._vars['on_surface_variant']};
                    font-size: 10px;
                    font-style: italic;
                """)
                parent_layout.addWidget(common_label)

    def _create_mood_item(self, mood: str, count: int) -> QWidget:
        """Create a single mood item with GIF and count."""
        container = QWidget()
        container.setFixedWidth(36)
        
        vlayout = QVBoxLayout(container)
        vlayout.setContentsMargins(0, 0, 0, 0)
        vlayout.setSpacing(2)
        vlayout.setAlignment(Qt.AlignCenter)

        # Mood GIF
        gif_label = QLabel()
        gif_label.setFixedSize(24, 24)
        gif_label.setAlignment(Qt.AlignCenter)
        
        gif_filename = MOOD_GIF_MAP.get(mood)
        if gif_filename:
            gif_path = str(MOOD_DIR / gif_filename)
            movie = QMovie(gif_path)
            if movie.isValid():
                movie.setScaledSize(QSize(20, 20))
                gif_label.setMovie(movie)
                movie.start()
                self._movies.append(movie)  # Keep reference
        
        vlayout.addWidget(gif_label, alignment=Qt.AlignCenter)

        # Count label
        count_label = QLabel(str(count))
        count_color = self._vars['primary'] if count > 0 else self._vars['on_surface_variant']
        count_label.setStyleSheet(f"""
            color: {count_color};
            font-size: 11px;
            font-weight: {'600' if count > 0 else '400'};
        """)
        count_label.setAlignment(Qt.AlignCenter)
        vlayout.addWidget(count_label, alignment=Qt.AlignCenter)

        return container

    def _get_mood_data(self) -> tuple:
        """
        Fetch mood data from DB.
        Returns: (7_day_counts: dict, 30_day_counts: dict, days_available: int)
        """
        try:
            api = get_api(self._app_paths)

            # Get moods for last 7 days
            moods_7_raw = api.get_moods_since(7)
            moods_7 = self._count_moods(moods_7_raw)
            
            # Get moods for last 30 days
            moods_30_raw = api.get_moods_since(30)
            moods_30 = self._count_moods(moods_30_raw)
            
            # Count unique days available in 30-day data
            unique_dates = set(m['date'] for m in moods_30_raw)
            days_available = len(unique_dates)
            
            return (moods_7, moods_30, days_available)
        except Exception:
            return ({}, {}, 0)

    def _count_moods(self, mood_data: list) -> dict:
        """
        Count occurrences of each mood.
        Returns dict like {'Great': 2, 'Good': 5, ...}
        """
        counts = {}
        for entry in mood_data:
            mood = entry.get('mood')
            if mood:
                counts[mood] = counts.get(mood, 0) + 1
        return counts


class MoodTrendCard(LiftMixin, QFrame):
    """
    Compact sparkline of the last 14 days of moods (MoodTrendChart).
    Data loads on construction; the page-level themeChanged→refresh rebuild
    recreates the card so theme switches repaint it with fresh data.
    """
    CHART_DAYS = 14

    def __init__(self, app_paths=None):
        super().__init__()
        self._vars = theme_vars()
        self._entered = False
        self._app_paths = _resolve_app_paths(app_paths)

        self.setObjectName("MoodTrendCard")
        self.setMinimumHeight(108)
        self.setMinimumWidth(200)
        self.setMaximumWidth(280)
        self.setStyleSheet(f"""
            QFrame#MoodTrendCard {{
                background-color: {self._vars['surface_container_low']};
                border-radius: 16px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        title = QLabel("Mood Trend")
        title.setStyleSheet(f"""
            color: {self._vars['on_surface']};
            font-size: 14px;
            font-weight: 600;
        """)
        layout.addWidget(title)

        self._chart = MoodTrendChart(self)
        layout.addWidget(self._chart, 1)

        self.init_lift()
        self.refresh_data()

    def refresh_data(self):
        try:
            rows = get_api(self._app_paths).get_moods_since(self.CHART_DAYS)
        except Exception:
            rows = []
        self._chart.set_moods(rows, days=self.CHART_DAYS)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._entered:
            self._entered = True
            play_entrance_fade(self)


class TodaySelfieInfoBox(LiftMixin, QFrame):
    """
    Info box showing mood, note, and retake button for today's selfie.
    Placed between selfie card and side column.
    """
    delete_requested = Signal()  # Emitted when user deletes today's photo
    retakeRequested = Signal()  # Emitted when user clicks retake button
    
    def __init__(self, selfie_card: TodaySelfieCard):
        super().__init__()
        self._vars = theme_vars()
        self._selfie_card = selfie_card
        self._image_path = None
        self._metadata = {}

        self.setObjectName("TodaySelfieInfoBox")
        self.setMinimumWidth(160)
        self.setMaximumWidth(200)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setStyleSheet(f"""
            QFrame#TodaySelfieInfoBox {{
                background-color: {self._vars['surface_container_low']};
                border-radius: 16px;
            }}
        """)

        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(10)
        self._layout.setContentsMargins(12, 12, 12, 12)

        self._build_content()
        
        # Connect to selfie card's height signal to sync heights
        self._selfie_card.image_resized.connect(self._on_image_resized)

        self.init_lift()
    
    def _on_image_resized(self, height: int):
        """Signal received but we now use flexible sizing."""
        pass  # Height is now flexible, managed by layout

    def _create_colored_icon(self, icon_name: str, qcolor):
        """Loads an SVG and repaints it with the given QColor (HiDPI-aware)."""
        return recolored_icon(ICONS_DIR / icon_name, qcolor, active_dpr(self))

    def _build_content(self):
        """Build the info box content based on selfie state."""
        if not self._selfie_card.has_selfie():
            placeholder = QLabel("No selfie yet")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet(f"""
                color: {self._vars['on_surface_variant']};
                font-size: 12px;
                font-style: italic;
            """)
            self._layout.addWidget(placeholder)
            self._layout.addStretch()
            return

        metadata = self._selfie_card.get_metadata()

        # Status text with checkmark
        status_label = QLabel("Today's selfie")
        status_label.setStyleSheet(f"""
            color: {self._vars['primary']};
            font-size: 14px;
            font-weight: 600;
        """)
        self._layout.addWidget(status_label)

        # ---- Time taken (convert UTC to local) ----
        time_str = ""
        ts_value = metadata.get("ts")
        if ts_value:
            try:
                from datetime import datetime, timezone
                # Parse ISO timestamp (it's in UTC)
                dt_utc = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
                # Convert to local timezone
                dt_local = dt_utc.astimezone()
                time_str = dt_local.strftime("%I:%M %p")  # e.g., "09:37 AM"
            except:
                pass
        
        if not time_str:
            # Fallback: extract from id (e.g., "2026-01-02_040733")
            selfie_id = metadata.get("id", "")
            if "_" in selfie_id:
                time_part = selfie_id.split("_")[-1]
                if len(time_part) == 6:
                    try:
                        h, m = time_part[:2], time_part[2:4]
                        hour = int(h)
                        ampm = "AM" if hour < 12 else "PM"
                        hour = hour % 12 or 12
                        time_str = f"{hour}:{m} {ampm}"
                    except:
                        pass
        
        if time_str:
            time_row = QHBoxLayout()
            time_row.setSpacing(6)
            time_row.setContentsMargins(0, 0, 0, 0)

            # Create A colored Icon
            saved_icon = self._create_colored_icon(
            "save_clock.svg",
            self._vars.qcolor('on_surface_variant')
            )
            
            time_icon = QLabel()
            time_icon.setPixmap(saved_icon.pixmap(24, 24))
            time_icon.setFixedWidth(24)
            time_row.addWidget(time_icon)
            
            time_label = QLabel(time_str)
            time_label.setStyleSheet(f"""
                color: {self._vars['on_surface']};
                font-size: 11px;
                font-weight: 500;
            """)
            time_row.addWidget(time_label)
            time_row.addStretch()
            self._layout.addLayout(time_row)

        # ---- Resolution ----
        width = metadata.get("width")
        height = metadata.get("height")
        if width and height:
            res_row = QHBoxLayout()
            res_row.setSpacing(6)
            res_row.setContentsMargins(0, 0, 0, 0)
            
            aspect_ratio_icon = self._create_colored_icon(
            "aspect_ratio.svg",
            self._vars.qcolor('on_surface_variant')
            )
            
            res_icon = QLabel()
            res_icon.setPixmap(aspect_ratio_icon.pixmap(24, 24))
            res_icon.setFixedWidth(24)
            res_row.addWidget(res_icon)
            
            res_label = QLabel(f"{width} × {height}")
            res_label.setStyleSheet(f"""
                color: {self._vars['on_surface']};
                font-size: 11px;
            """)
            res_row.addWidget(res_label)
            res_row.addStretch()
            self._layout.addLayout(res_row)

        # ---- Horizontal line before Mood section ----
        mood_separator = QFrame()
        mood_separator.setFrameShape(QFrame.HLine)
        mood_separator.setStyleSheet(f"""
            background-color: {self._vars['outline_variant']};
        """)
        mood_separator.setFixedHeight(1)
        self._layout.addWidget(mood_separator)

        # ---- Mood section ----
        mood_section_label = QLabel("Mood selected today")
        mood_section_label.setStyleSheet(f"""
            color: {self._vars['on_surface_variant']};
            font-size: 10px;
            font-weight: 500;
        """)
        self._layout.addWidget(mood_section_label)

        mood_value = metadata.get("mood")
        if mood_value and mood_value in MOOD_GIF_MAP:
            mood_row = QHBoxLayout()
            mood_row.setSpacing(8)
            mood_row.setContentsMargins(0, 4, 0, 0)

            mood_gif_label = QLabel()
            mood_gif_label.setFixedSize(32, 32)
            mood_gif_label.setAlignment(Qt.AlignCenter)
            gif_path = str(MOOD_DIR / MOOD_GIF_MAP[mood_value])
            self._mood_movie = QMovie(gif_path)
            if self._mood_movie.isValid():
                self._mood_movie.setScaledSize(QSize(22, 22))
                mood_gif_label.setMovie(self._mood_movie)
                self._mood_movie.start()
            
            mood_gif_label.setStyleSheet(f"""
                background-color: {self._vars['surface_container_low']};
                border: 2px solid {self._vars['outline_variant']};
                border-radius: 8px;
            """)
            mood_row.addWidget(mood_gif_label)

            mood_text = QLabel(mood_value)
            mood_text.setStyleSheet(f"""
                color: {self._vars['on_surface']};
                font-size: 11px;
                font-weight: 500;
            """)
            mood_row.addWidget(mood_text)
            mood_row.addStretch()
            self._layout.addLayout(mood_row)
        else:
            no_mood = QLabel("No mood")
            no_mood.setStyleSheet(f"""
                color: {self._vars['on_surface_variant']};
                font-size: 10px;
                font-style: italic;
            """)
            self._layout.addWidget(no_mood)

        # ---- Horizontal line before Notes section ----
        notes_separator = QFrame()
        notes_separator.setFrameShape(QFrame.HLine)
        notes_separator.setStyleSheet(f"""
            background-color: {self._vars['outline_variant']};
        """)
        notes_separator.setFixedHeight(1)
        self._layout.addWidget(notes_separator)

        # ---- Note section ----
        notes_section_label = QLabel("Notes")
        notes_section_label.setStyleSheet(f"""
            color: {self._vars['on_surface_variant']};
            font-size: 10px;
            font-weight: 500;
        """)
        self._layout.addWidget(notes_section_label)

        note_value = metadata.get("notes")
        if note_value:
            note_text = note_value[:35] + "..." if len(note_value) > 35 else note_value
            
            note_row = QHBoxLayout()
            note_row.setSpacing(6)
            note_row.setContentsMargins(0, 0, 0, 0)
            
            notes_icon = self._create_colored_icon(
                "notes.svg",
                self._vars.qcolor('on_surface_variant')
            )
            
            note_icon_label = QLabel()
            note_icon_label.setPixmap(notes_icon.pixmap(16, 16))
            note_icon_label.setFixedWidth(16)
            note_row.addWidget(note_icon_label)
            
            note_label = QLabel(note_text)
            note_label.setWordWrap(True)
            note_label.setStyleSheet(f"""
                color: {self._vars['on_surface_variant']};
                font-size: 10px;
            """)
            note_row.addWidget(note_label)
            note_row.addStretch()
            self._layout.addLayout(note_row)
        else:
            no_notes = QLabel("No notes")
            no_notes.setStyleSheet(f"""
                color: {self._vars['on_surface_variant']};
                font-size: 10px;
                font-style: italic;
            """)
            self._layout.addWidget(no_notes)

        self._layout.addStretch()

        # Retake button
        retake_btn = QPushButton("Retake")
        retake_btn.setObjectName("RetakeButton")
        retake_btn.setCursor(Qt.PointingHandCursor)
        retake_btn.setFixedHeight(32)
        
        retake_icon = self._create_colored_icon(
            "retake_image.svg",
            self._vars.qcolor('on_surface_variant')
        )
        retake_btn.setIcon(retake_icon)
        retake_btn.setIconSize(QSize(14, 14))
        
        retake_btn.setStyleSheet(f"""
            QPushButton#RetakeButton {{
                background-color: {self._vars['surface_container_high']};
                color: {self._vars['on_surface_variant']};
                border: 1px solid {self._vars['outline_variant']};
                border-radius: 16px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton#RetakeButton:hover {{
                background-color: {self._vars['surface_container_highest']};
                border: 1px solid {self._vars['outline']};
                color: {self._vars['on_surface']};
            }}
        """)
        retake_btn.clicked.connect(self.retakeRequested.emit)
        self._layout.addWidget(retake_btn)

        # Copy today's photo to clipboard (secondary style, Retake/Delete metrics)
        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setObjectName("CopyButton")
        self._copy_btn.setCursor(Qt.PointingHandCursor)
        self._copy_btn.setFixedHeight(32)

        copy_icon = self._create_colored_icon(
            "copy.svg",
            self._vars.qcolor('on_surface_variant')
        )
        self._copy_btn.setIcon(copy_icon)
        self._copy_btn.setIconSize(QSize(14, 14))
        self._copy_btn.setToolTip("Copy photo to clipboard (Ctrl+Shift+C)")

        self._copy_btn.setStyleSheet(f"""
            QPushButton#CopyButton {{
                background-color: {self._vars['surface_container_high']};
                color: {self._vars['on_surface_variant']};
                border: 1px solid {self._vars['outline_variant']};
                border-radius: 16px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton#CopyButton:hover {{
                background-color: {self._vars['surface_container_highest']};
                border: 1px solid {self._vars['outline']};
                color: {self._vars['on_surface']};
            }}
        """)
        self._copy_btn.clicked.connect(self._on_copy_clicked)
        self._layout.addWidget(self._copy_btn)

        # Delete today's photo button
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("DeleteButton")
        self._delete_btn.setCursor(Qt.PointingHandCursor)
        self._delete_btn.setFixedHeight(32)
        
        delete_icon = self._create_colored_icon(
            "delete.svg",
            self._vars.qcolor('error')
        )
        self._delete_btn.setIcon(delete_icon)
        self._delete_btn.setIconSize(QSize(14, 14))
        
        self._delete_btn.setStyleSheet(f"""
            QPushButton#DeleteButton {{
                background-color: {self._vars['surface_container_high']};
                color: {self._vars['error']};
                border: 1px solid {self._vars['error']};
                border-radius: 16px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton#DeleteButton:hover {{
                background-color: {self._vars['error_container']};
                border: 1px solid {self._vars['error']};
                color: {self._vars['on_error_container']};
            }}
        """)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        self._layout.addWidget(self._delete_btn)
    
    def _on_delete_clicked(self):
        """Handle delete button click: delete photo file and update index."""
        image_path = self._selfie_card.get_image_path()
        metadata = self._selfie_card.get_metadata()
        
        if not image_path or not image_path.exists():
            return
        
        selfie_id = metadata.get("id") or image_path.stem
        
        # Delete the photo file
        success, error = delete_path(image_path)
        if not success:
            self._show_delete_error(error)
            return
        
        # Record deletion in the index API
        try:
            app_paths = getattr(self._selfie_card, "_app_paths", None) \
                or _resolve_app_paths()
            api = get_api(app_paths)
            api.record_deletion(selfie_id, reason="user_deleted")
        except Exception as e:
            print(f"Failed to record deletion: {e}")
        
        # Refresh the selfie card to show empty state
        self._selfie_card.set_empty_state()
        
        # Clear our own content and show placeholder
        self._clear_and_show_placeholder()
        
        # Emit signal for any external listeners
        self.delete_requested.emit()

    def _show_delete_error(self, error):
        """Show an ErrorToast when deleting the photo fails."""
        from gui.widgets.error_popup import ErrorToast

        popup = ErrorToast(self, level="ERROR", message=f"Failed to delete photo: {error}")

        geo = self.window().geometry()
        x = geo.x() + (geo.width() - popup.width()) // 2
        y = geo.y() + (geo.height() - popup.height()) // 3
        popup.move(x, y)
        popup.show()

    def _on_copy_clicked(self):
        """Copy today's full-resolution photo file to the system clipboard."""
        image_path = self._selfie_card.get_image_path()
        if not image_path:
            self._show_copy_error("No photo to copy")
            return
        try:
            if not Path(image_path).exists():
                self._show_copy_error("Photo file not found")
                return
            # Full-res original (never the display thumbnail)
            image = QImage(str(image_path))
            if image.isNull():
                self._show_copy_error("Could not read photo file")
                return
            QApplication.clipboard().setImage(image)
            self._show_copied_feedback()
        except Exception as e:
            logger.warning("copy_to_clipboard_failed", extra={"meta": {"error": str(e)}})
            self._show_copy_error(e)

    def _toast(self, level: str, message: str):
        """Show an ErrorToast centered over the window (shared positioning)."""
        from gui.widgets.error_popup import ErrorToast

        popup = ErrorToast(self, level=level, message=message)

        geo = self.window().geometry()
        x = geo.x() + (geo.width() - popup.width()) // 2
        y = geo.y() + (geo.height() - popup.height()) // 3
        popup.move(x, y)
        popup.show()

    def _show_copied_feedback(self):
        """Transient INFO toast confirming the copy (non-animated)."""
        try:
            self._toast("INFO", "Copied to clipboard")
        except Exception:
            pass

    def _show_copy_error(self, error):
        """Show an ErrorToast when copying the photo fails."""
        try:
            self._toast("ERROR", f"Failed to copy photo: {error}")
        except Exception:
            pass

    def has_copy_target(self):
        """True when a today-selfie path is set (shortcut/button gate)."""
        return getattr(self, "_selfie_card", None) is not None and \
            self._selfie_card.get_image_path() is not None

    def _clear_and_show_placeholder(self):
        """Clear content and show no selfie placeholder."""
        # Remove all widgets from layout
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                # Clear nested layout
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()
        
        # Add placeholder
        placeholder = QLabel("No selfie yet")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet(f"""
            color: {self._vars['on_surface_variant']};
            font-size: 12px;
            font-style: italic;
        """)
        self._layout.addWidget(placeholder)
        self._layout.addStretch()


class DashboardSurface(QFrame):
    """
    Primary dashboard surface containing today's selfie card and summary widgets.
    """
    # Signal emitted when "Take today's selfie" button is clicked
    takeSelfieRequested = Signal()
    # Signal emitted when "Retake" button is clicked
    retakeRequested = Signal()
    # Signal emitted when photo is deleted
    photoDeleted = Signal()
    # Signal emitted when the On This Day banner is clicked (carries date)
    throwbackOpenRequested = Signal(object)
    # Highlight strip forwards (§3/§8)
    chipActivated = Signal(str)
    recapLaunchRequested = Signal(tuple)

    def __init__(self, app_paths=None, config_path=None):
        super().__init__()
        vars = theme_vars()
        self._app_paths = _resolve_app_paths(app_paths)
        self._config_path = (Path(config_path) if config_path else
                             Path(self._app_paths.config_dir) / "config.toml")

        self.setObjectName("DashboardSurface")

        self.setStyleSheet(f"""
            QFrame#DashboardSurface {{
                background-color: {vars['surface_container_highest']};
                border-radius: 12px;
            }}
        """)

        surface_layout = QVBoxLayout(self)
        surface_layout.setContentsMargins(12, 12, 12, 12)
        surface_layout.setSpacing(12)

        # Highlights arbiter: recap_ready chip > chips > OnThisDay banner
        self._strip = HighlightStrip(app_paths=self._app_paths,
                                     config_path=self._config_path)
        self._strip.chipActivated.connect(self.chipActivated.emit)
        self._strip.recapLaunchRequested.connect(self.recapLaunchRequested.emit)
        self._strip.throwbackOpenRequested.connect(
            self.throwbackOpenRequested.emit)
        surface_layout.addWidget(self._strip)

        # Top Section Container - expanding to fill available space
        top_section_container = QWidget()
        top_section_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._top_section_container = top_section_container

        top_section = QHBoxLayout(top_section_container)
        top_section.setContentsMargins(0, 0, 0, 0)
        top_section.setSpacing(12)

        # Selfie Card (image only, fills the card)
        today_selfie_card = TodaySelfieCard(app_paths=self._app_paths)
        self._today_card = today_selfie_card

        # Connect the card's signal to our signal (forwards the request)
        today_selfie_card.takeSelfieRequested.connect(self.takeSelfieRequested.emit)

        # Info Box (between selfie and side column)
        info_box = TodaySelfieInfoBox(today_selfie_card)
        self._info_box = info_box
        # Forward retake request
        info_box.retakeRequested.connect(self.retakeRequested.emit)
        # Forward delete request
        info_box.delete_requested.connect(self.photoDeleted.emit)

        # Side Column: Streak + Mood (+ height-gated recap entry)
        side_column = QVBoxLayout()
        side_column.setSpacing(12)

        streak_summary_widget = StreakSummaryWidget(app_paths=self._app_paths)
        mood_summary_widget = MoodSummaryWidget(app_paths=self._app_paths)
        mood_trend_card = MoodTrendCard(app_paths=self._app_paths)

        recap_entry = RecapEntryCard()
        recap_entry.recapLaunchRequested.connect(
            self.recapLaunchRequested.emit)
        self._strip.eligibilityChanged.connect(recap_entry.set_eligible)
        self._recap_entry = recap_entry

        side_column.addWidget(streak_summary_widget)
        side_column.addWidget(mood_summary_widget)
        side_column.addWidget(mood_trend_card)
        side_column.addWidget(recap_entry)
        side_column.addStretch()  # Push widgets up, don't let them expand down

        # Layout: Selfie (stretch=2) | InfoBox (stretch=0) | SideColumn (stretch=0)
        top_section.addWidget(today_selfie_card, stretch=2)
        top_section.addWidget(info_box, stretch=0)
        top_section.addLayout(side_column, stretch=0)

        surface_layout.addWidget(top_section_container, stretch=1)  # Takes remaining space
        surface_layout.addSpacing(8)

        from gui.dashboard.widgets.carousel.motion_carousel import MotionCarousel
        self._carousel = MotionCarousel()
        surface_layout.addWidget(self._carousel, stretch=0)  # Fixed height carousel at bottom

        self._side_fixed_min_height = (
            streak_summary_widget.minimumHeight()
            + mood_summary_widget.minimumHeight()
            + mood_trend_card.minimumHeight() + 3 * 12)
        self._strip.recompute()
        QTimer.singleShot(0, self._apply_recap_height_gate)

    def _apply_recap_height_gate(self):
        try:
            available = (self._top_section_container.height()
                         - self._side_fixed_min_height)
            self._recap_entry.maybe_visible(available)
        except RuntimeError:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_recap_height_gate()

    def refresh_highlights(self):
        if self._strip is not None:
            self._strip.recompute()


class DashboardPage(QWidget):
    # Signal emitted when "Take today's selfie" button is clicked
    takeSelfieRequested = Signal()
    # Signal emitted when "Retake" button is clicked
    retakeRequested = Signal()
    # Signal emitted when photo is deleted
    photoDeleted = Signal()
    # Signal emitted when the On This Day banner is clicked (carries date).
    throwbackOpenRequested = Signal(object)
    # Highlight strip forwards (§8 wiring)
    chipActivated = Signal(str)
    recapLaunchRequested = Signal(tuple)

    def __init__(self, app_paths=None, cfg=None, config_path=None):
        super().__init__()
        vars = theme_vars()

        # Incoming-only page transitions animate this wrapper (motion-system.md)
        self._motion_wrapper = install_motion_wrapper(self)

        self._root_layout = QVBoxLayout(self._motion_wrapper)
        self._root_layout.setContentsMargins(12, 12, 12, 12)
        self._root_layout.setSpacing(12)

        # Config-applied paths (window passes the live object; standalone
        # construction falls back to the bootstrap+config.toml chain) so the
        # today-card and photos watcher target the real capture root.
        self._app_paths = _resolve_app_paths(app_paths)
        self._config_path = (Path(config_path) if config_path else
                             Path(self._app_paths.config_dir) / "config.toml")
        self._surface = None
        self._refreshing = False
        self._build_surface()

        # Cross-process staleness guard: the startup popup captures in its
        # own process (QProcess-launched), so its save can never emit
        # photoSaved into this window. The card's construction-time check is
        # therefore stale until we re-check. Two triggers:
        #   1) page visibility (showEvent / tab-switch refresh_if_stale)
        #   2) best-effort QFileSystemWatcher on photos_root (fail-open)
        self._last_external_check = 0.0
        self._external_check_timer = QTimer(self)
        self._external_check_timer.setSingleShot(True)
        self._external_check_timer.setInterval(400)
        self._external_check_timer.timeout.connect(self._on_watcher_debounce)
        self._photos_watcher = None
        try:
            self._photos_watcher = QFileSystemWatcher(self)
            self._photos_watcher.directoryChanged.connect(self._on_photos_dir_changed)
            self._repoint_photos_watcher()
        except Exception as e:
            logger.warning("photos_watcher_unavailable", extra={"meta": {"error": str(e)}})
            self._photos_watcher = None

        # Ctrl+Shift+C: copy today's photo — scoped to this page only so it
        # never fires while other pages are focused. No selfie → no-op.
        self._copy_shortcut = QShortcut(QKeySequence("Ctrl+Shift+C"), self)
        self._copy_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._copy_shortcut.activated.connect(self._trigger_copy_to_clipboard)

        controller = getattr(theme_vars(), "_controller", None)
        if controller is not None:
            controller.themeChanged.connect(self.refresh)

    def _trigger_copy_to_clipboard(self):
        """Shortcut handler: resolve the live info box (surface rebuilds on
        refresh/theme change) and copy; silently no-op without a target."""
        surface = self._surface
        if surface is None:
            return
        info_box = getattr(surface, "_info_box", None)
        if info_box is not None and info_box.has_copy_target():
            info_box._on_copy_clicked()
    
    def _build_surface(self):
        """Build or rebuild the dashboard surface."""
        # Remove old surface if exists
        if self._surface:
            self._root_layout.removeWidget(self._surface)
            self._surface.deleteLater()
        
        # Create new surface
        self._surface = DashboardSurface(self._app_paths,
                                         config_path=self._config_path)
        # Forward the takeSelfieRequested signal
        self._surface.takeSelfieRequested.connect(self.takeSelfieRequested.emit)
        # Forward the retakeRequested signal
        self._surface.retakeRequested.connect(self.retakeRequested.emit)
        # Forward the photoDeleted signal
        self._surface.photoDeleted.connect(self.photoDeleted.emit)
        # Forward the throwback banner click
        self._surface.throwbackOpenRequested.connect(self.throwbackOpenRequested.emit)
        # Forward highlight chip / recap entry activation
        self._surface.chipActivated.connect(self.chipActivated.emit)
        self._surface.recapLaunchRequested.connect(self.recapLaunchRequested.emit)
        self._root_layout.addWidget(self._surface)

    def refresh_highlights(self):
        """Recompute the highlight strip + recap entry (recap_seen changed)."""
        surface = self._surface
        if surface is not None:
            try:
                surface.refresh_highlights()
            except RuntimeError:
                pass
    
    def refresh(self):
        """Refresh the dashboard to show updated data (e.g., after a new photo is saved)."""
        logger.info("Refreshing dashboard...")
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self._build_surface()
        finally:
            self._refreshing = False

    # --- External-capture staleness handling ----------------------------

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_if_stale()

    def refresh_if_stale(self):
        """Public hook: re-check today's state when the page becomes visible."""
        self._check_external_updates("page_visible")
        self._repoint_photos_watcher()

    def _photos_watch_targets(self):
        """photos_root + current UTC year/month dirs (files are UTC-named)."""
        try:
            root = Path(self._app_paths.photos_root)
            now_utc = datetime.now(timezone.utc)
            year_dir = root / now_utc.strftime("%Y")
            month_dir = year_dir / now_utc.strftime("%m")
            return [root, year_dir, month_dir]
        except Exception:
            return []

    def _repoint_photos_watcher(self):
        """Sync watcher paths with current dirs; picks up month rollovers and
        newly created YYYY/MM directories. No-op when watcher unavailable."""
        watcher = self._photos_watcher
        if watcher is None:
            return
        try:
            desired = {str(p) for p in self._photos_watch_targets() if p.is_dir()}
            current = set(watcher.directories())
            removed = current - desired
            added = desired - current
            if removed:
                watcher.removePaths(sorted(removed))
            if added:
                watcher.addPaths(sorted(added))
        except Exception as e:
            logger.warning("photos_watcher_repoint_failed", extra={"meta": {"error": str(e)}})

    def _on_photos_dir_changed(self, path: str):
        # Coalesce bursts (atomic save = temp file + rename); never re-check
        # inline — the capture may still be mid-write.
        self._external_check_timer.start()

    def _on_watcher_debounce(self):
        # A new year/month dir may have appeared: repoint before checking.
        self._repoint_photos_watcher()
        self._check_external_updates("photos_dir_changed", force=True)

    def _check_external_updates(self, reason: str, force: bool = False):
        """Re-sync when disk/index state diverged from what the card shows.

        Cheap glob + index lookup; full surface rebuild only on actual drift,
        which keeps streak/mood cards and the info box consistent too.
        Loop-safe: refresh writes nothing under photos_root (thumbnails live
        under data_dir/thumbs), so it cannot re-trigger the watcher.
        """
        if self._refreshing:
            return
        now = time.monotonic()
        if not force and (now - self._last_external_check) < 0.25:
            return
        self._last_external_check = now

        try:
            exists, disk_path = check_if_already_captured(self._app_paths)
        except Exception:
            return

        surface = self._surface
        card = getattr(surface, "_today_card", None) if surface is not None else None
        if card is None:
            return

        shown = card.get_image_path()
        shown_path = Path(shown) if shown else None
        disk_norm = Path(disk_path) if (exists and disk_path) else None
        if shown_path == disk_norm:
            return  # already in sync

        logger.info("dashboard_state_stale", extra={"meta": {
            "reason": reason,
            "shown": str(shown_path) if shown_path else None,
            "disk": str(disk_norm) if disk_norm else None,
        }})
        self.refresh()

