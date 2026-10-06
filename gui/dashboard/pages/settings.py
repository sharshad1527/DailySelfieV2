# gui/dashboard/pages/settings.py
"""
SettingsPage — grouped, instantly-persisting settings per docs/design/settings-page.md.

Sections: Appearance (theme/mode/contrast), Behavior (camera/quality/resolution/
timer/retake), System (autostart/desktop-entry/folders), About.

All persistence is instant-apply (atomic writes via core.config.write_config);
styles are build-time f-strings over theme tokens rebuilt on themeChanged.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    Qt,
    QThread,
    QTimer,
    Signal,
    QUrl,
)
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from autostart import is_autostart_enabled
from desktop_entry import is_desktop_entry_enabled
from core.app_info import APP_VERSION
from core.autostart_manager import set_autostart
from core.camera import list_cameras
from core.config import DEFAULT_CONFIG, load_config, write_config
from core.desktop_entry_manager import set_desktop_entry
from core.index_api import get_api
from core.logging import get_logger
from core.paths import AppPaths, get_app_paths
from core.recap import recap_eligible_periods
from gui.theme import motion_tokens as mt
from gui.theme.theme_vars import theme_vars
from gui.widgets.error_popup import ErrorToast
from gui.widgets.motion import install_motion_wrapper


logger = get_logger("settings_page")

# Config keys edited by rows -> owning TOML section
_ROW_KEYS: Dict[str, str] = {
    "camera_index": "behavior",
    "width": "behavior",
    "height": "behavior",
    "quality": "behavior",
    "timer_duration": "behavior",
    "allow_retake": "behavior",
    "highlights_enabled": "behavior",
}

TIMER_MIN, TIMER_MAX = 0, 60
# DIM_MIN is 1, not 0: core.config._validate_behavior accepts only a positive
# int (or null) for width/height and rewrites 0 -> None, which write_config then
# strips — so a persisted 0 never survives a round trip and the key silently
# reverts to the DEFAULT_CONFIG resolution on the next load. Stepper bounds must
# therefore match the validator's real minimum. core/config.py is the root
# cause — see _sanitised_dimension and the recommendation in the report.
DIM_MIN, DIM_MAX, DIM_STEP = 1, 4096, 80
_DIM_KEYS = ("width", "height")
QUALITY_MIN, QUALITY_MAX, QUALITY_FALLBACK = 1, 100, 90


def _sanitised_dimension(key: str, raw: Any) -> int:
    """The width/height value core.config will actually hold after a load.

    `_validate_behavior` rewrites 0/None -> None and `write_config` omits None
    keys, so "0 = camera default" cannot survive a round trip: the key is
    dropped and the next load falls back to DEFAULT_CONFIG. Normalising to the
    value that really persists means the stepper can never display a number the
    config layer will silently rewrite (settings-page.md edge case 9).

    Tied to DIM_MIN so flipping the bounds back to 0 (once core.config stops
    rewriting 0) needs no second change here.
    """
    fallback = DEFAULT_CONFIG["behavior"].get(key, 1280)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = int(fallback)
    if value < DIM_MIN:
        value = int(fallback)
    return max(DIM_MIN, min(DIM_MAX, value))

# C4 "invalid input shake": ±4px ×3 @40ms Linear (motion-gated).
_SHAKE_AMPLITUDE_PX = 4
_SHAKE_HALF_CYCLE_MS = 40
_SHAKE_CYCLES = 3
# C4 "value commit label": the committed value rises this far while fading in.
_VALUE_COMMIT_RISE_PX = 8


# -------------------------------------------------------------
# Off-thread workers
# -------------------------------------------------------------
class CameraProbeWorker(QThread):
    """Probes camera indices off-thread; emits sorted usable indices ([] if none/cv2 missing)."""

    probed = Signal(list)

    def run(self):
        try:
            results = list_cameras(max_test=8, only_available=True)
            indices = sorted(results.keys())
        except Exception as e:
            logger.warning("camera_probe_failed", extra={"meta": {"error": str(e)}})
            indices = []
        self.probed.emit(indices)


class ManagerCallThread(QThread):
    """Runs a manager callable (set_autostart/set_desktop_entry) off-thread.

    Emits None on success or the exception instance on failure.
    """

    done = Signal(object)

    def __init__(self, fn: Callable[[], Any], parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self._fn()
            self.done.emit(None)
        except Exception as e:
            self.done.emit(e)


# -------------------------------------------------------------
# Custom switch
# -------------------------------------------------------------
class ToggleSwitch(QAbstractButton):
    """Custom painted switch (track h28 w48 r14, thumb d20).

    C4 (motion-system.md): thumb slides ON 200ms OutCubic / OFF 150ms InCubic,
    gated on behavior.motion_enabled — with reduced motion the thumb jumps
    straight to the target position. Track colour swaps instantly at t=0
    (colour leads motion) because paintEvent reads isChecked() directly while
    only the thumb position animates.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(48, 28)

        self._c_track_off = "#666666"
        self._c_track_on = "#666666"
        self._c_track_disabled = "#333333"
        self._c_thumb = "#FFFFFF"
        self._c_thumb_off_disabled = "#888888"

        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"thumbPos", self)
        self.toggled.connect(self._animate_to)

    # Animated property
    def _get_pos(self) -> float:
        return self._pos

    def _set_pos(self, value: float) -> None:
        self._pos = float(value)
        self.update()

    thumbPos = Property(float, _get_pos, _set_pos)

    def apply_theme(self):
        v = theme_vars()
        self._c_track_on = v["primary"]
        self._c_track_off = v["surface_container_highest"]
        self._c_track_disabled = v["surface_container_lowest"]
        self._c_thumb = v["on_primary"]
        self._c_thumb_off_disabled = v["outline_variant"]
        self.update()

    def _animate_to(self, checked: bool):
        self._anim.stop()
        target = 1.0 if checked else 0.0
        # C4 reduced motion: jump to the end state, never animate. The gate is
        # read from config at trigger time, which is what the spec mandates; the
        # switch that turns motion off therefore still slides (the row persists
        # the new value after this slot runs) — nothing else is in flight then.
        if not mt.is_motion_enabled():
            self._pos = target
            self.update()
            return
        self._anim.setDuration(mt.duration_base if checked else mt.duration_fast)
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(mt.curve_enter if checked else mt.curve_exit)
        self._anim.start()

    def snap(self, checked: bool):
        """Set state without emitting signals or animating (programmatic sync)."""
        blocked = self.blockSignals(True)
        self.setChecked(bool(checked))
        self.blockSignals(blocked)
        self._anim.stop()
        self._pos = 1.0 if checked else 0.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        enabled = self.isEnabled()
        checked = self.isChecked()
        if not enabled:
            track = self._c_track_disabled
            thumb = self._c_thumb_off_disabled if not checked else self._c_thumb
        else:
            track = self._c_track_on if checked else self._c_track_off
            thumb = self._c_thumb

        p.setBrush(QColor(track))
        p.drawRoundedRect(0, 0, 48, 28, 14, 14)

        x = 4 + self._pos * (48 - 20 - 8)
        p.setBrush(QColor(thumb))
        p.drawEllipse(int(round(x)), 4, 20, 20)
        p.end()


# -------------------------------------------------------------
# Section container
# -------------------------------------------------------------
class SectionCard(QFrame):
    """Grouped card: title label + QVBoxLayout content (radius 16, matches dashboard cards)."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsSectionCard")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        self.title_lbl = QLabel(title)
        outer.addWidget(self.title_lbl)

        self.content = QVBoxLayout()
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(12)
        outer.addLayout(self.content)

        self.apply_theme()

    def add(self, widget: QWidget):
        self.content.addWidget(widget)
        return widget

    def apply_theme(self):
        v = theme_vars()
        self.setStyleSheet(f"""
            QFrame#SettingsSectionCard {{
                background-color: {v['surface_container_low']};
                border-radius: 16px;
            }}
        """)
        self.title_lbl.setStyleSheet(f"""
            color: {v['on_surface']};
            font-size: 14px;
            font-weight: 600;
        """)


# -------------------------------------------------------------
# Shared row helpers
# -------------------------------------------------------------
def _header(title: str, desc: str) -> tuple:
    """Build the left-side label stack; returns (widget, title_lbl, desc_lbl)."""
    wrap = QWidget()
    lay = QVBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)

    t = QLabel(title)
    d = QLabel(desc)
    d.setWordWrap(True)
    lay.addWidget(t)
    lay.addWidget(d)
    return wrap, t, d


def _secondary_button_style(v) -> str:
    return f"""
        QPushButton#SecondaryButton {{
            background-color: {v['surface_container_high']};
            color: {v['on_surface_variant']};
            border: 1px solid {v['outline_variant']};
            border-radius: 16px;
            padding: 0 12px;
            font-size: 11px;
            font-weight: 500;
        }}
        QPushButton#SecondaryButton:hover {{
            background-color: {v['surface_container_highest']};
            border: 1px solid {v['outline']};
            color: {v['on_surface']};
        }}
    """


def _stepper_button_style(v) -> str:
    return f"""
        QPushButton#SecondaryButton {{
            background-color: {v['surface_container_high']};
            color: {v['on_surface_variant']};
            border: 1px solid {v['outline_variant']};
            border-radius: 16px;
            padding: 0;
            font-size: 15px;
        }}
        QPushButton#SecondaryButton:hover {{
            background-color: {v['surface_container_highest']};
            border: 1px solid {v['outline']};
            color: {v['on_surface']};
        }}
    """


def _combo_style(v) -> str:
    return f"""
        QComboBox#SettingsCombo {{
            background-color: {v['surface_container_high']};
            color: {v['on_surface']};
            border: 1px solid {v['outline_variant']};
            border-radius: 16px;
            padding: 0 12px;
            font-size: 12px;
            font-weight: 500;
        }}
        QComboBox#SettingsCombo:hover {{
            background-color: {v['surface_container_highest']};
            border: 1px solid {v['outline']};
        }}
        QComboBox#SettingsCombo::drop-down {{ border: none; width: 24px; }}
        QComboBox#SettingsCombo QAbstractItemView {{
            background-color: {v['surface_container_high']};
            color: {v['on_surface']};
            border: 1px solid {v['outline_variant']};
            border-radius: 8px;
            selection-background-color: {v['primary']};
            selection-color: {v['on_primary']};
            outline: none;
        }}
    """


# -------------------------------------------------------------
# C4 row motion helpers (motion-system.md)
# -------------------------------------------------------------
def _animate_value_commit(label: QLabel):
    """C4 'value commit label': +8px rise with fade-in, 150ms OutCubic.

    Motion-gated: with reduced motion the committed value just appears. The
    opacity effect is transient — attached for the flight only and detached in
    `finished` so the steady state stays effect-free (performance rule 2), and
    the group is parked on the label as a GC guard (rule 9).
    """
    if not mt.is_motion_enabled():
        return
    running = getattr(label, "_commit_anim", None)
    if running is not None:
        running.stop()

    base = QPoint(label.x(), label.y())
    effect = QGraphicsOpacityEffect(label)
    effect.setOpacity(0.0)
    label.setGraphicsEffect(effect)

    pos_anim = QPropertyAnimation(label, b"pos", label)
    pos_anim.setDuration(mt.duration_fast)
    pos_anim.setEasingCurve(mt.curve_enter)
    pos_anim.setStartValue(QPoint(base.x(), base.y() + _VALUE_COMMIT_RISE_PX))
    pos_anim.setEndValue(base)

    fade_anim = QPropertyAnimation(effect, b"opacity", label)
    fade_anim.setDuration(mt.duration_fast)
    fade_anim.setEasingCurve(mt.curve_enter)
    fade_anim.setStartValue(0.0)
    fade_anim.setEndValue(1.0)

    group = QParallelAnimationGroup(label)
    group.addAnimation(pos_anim)
    group.addAnimation(fade_anim)

    def _detach():
        try:
            if label.graphicsEffect() is effect:
                label.setGraphicsEffect(None)
        except RuntimeError:
            pass  # label torn down mid-flight
        label._commit_anim = None

    group.finished.connect(_detach)
    label._commit_anim = group
    group.start()


def _shake_row(row: QWidget):
    """C4 invalid-input shake: ±4px ×3 @40ms Linear (motion-gated).

    Played when a requested value never committed (write failure), so the
    rejection is felt as well as toasted. Reduced motion skips it entirely —
    the control still snaps back and the ERROR toast still fires. Follows the
    lift-mixin precedent of animating `pos` on a layout-managed child; the last
    keyframe restores the original position.
    """
    if not mt.is_motion_enabled():
        return
    running = getattr(row, "_shake_anim", None)
    if running is not None:
        running.stop()

    base = QPoint(row.x(), row.y())
    anim = QPropertyAnimation(row, b"pos", row)
    anim.setDuration(_SHAKE_HALF_CYCLE_MS * 2 * _SHAKE_CYCLES)
    anim.setEasingCurve(QEasingCurve.Linear)

    steps = _SHAKE_CYCLES * 2
    for i in range(steps):
        offset = _SHAKE_AMPLITUDE_PX if i % 2 == 0 else -_SHAKE_AMPLITUDE_PX
        # setKeyValueAt steps are normalised to 0..1, not percent.
        anim.setKeyValueAt((i + 1) / steps, QPoint(base.x(), base.y() + offset))
    anim.setKeyValueAt(1.0, base)

    def _release():
        row._shake_anim = None

    anim.finished.connect(_release)
    row._shake_anim = anim
    anim.start()


# -------------------------------------------------------------
# Rows
# -------------------------------------------------------------
class ToggleRow(QWidget):
    """label + desc + custom switch. Signals: toggled(bool), settingChanged(key, value)."""

    toggled = Signal(bool)
    settingChanged = Signal(str, object)

    def __init__(self, title: str, desc: str, key: str, checked: bool = False, parent=None):
        super().__init__(parent)
        self.key = key

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        header, self.title_lbl, self.desc_lbl = _header(title, desc)
        row.addWidget(header)
        row.addStretch()

        self.switch_w = ToggleSwitch()
        self.switch_w.setChecked(bool(checked))
        self.switch_w.toggled.connect(self._on_switch_toggled)
        row.addWidget(self.switch_w, 0, Qt.AlignVCenter)

        self.apply_theme()

    def _on_switch_toggled(self, checked: bool):
        self.toggled.emit(checked)
        self.settingChanged.emit(self.key, checked)

    def set_checked_silent(self, checked: bool):
        self.switch_w.snap(bool(checked))

    def set_enabled_state(self, enabled: bool):
        self.switch_w.setEnabled(bool(enabled))

    def apply_theme(self):
        v = theme_vars()
        self.title_lbl.setStyleSheet(f"""
            color: {v['on_surface']};
            font-size: 13px;
            font-weight: 600;
        """)
        self.desc_lbl.setStyleSheet(f"""
            color: {v['on_surface_variant']};
            font-size: 11px;
        """)
        self.switch_w.apply_theme()


class SliderRow(QWidget):
    """label + desc + QSlider + live value label. Signals: valueChanged(int), settingChanged."""

    valueChanged = Signal(int)
    settingChanged = Signal(str, object)

    def __init__(self, title: str, desc: str, key: str, value: int,
                 minimum: int, maximum: int, suffix: str = "", parent=None):
        super().__init__(parent)
        self.key = key
        self._suffix = suffix

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        header, self.title_lbl, self.desc_lbl = _header(title, desc)
        row.addWidget(header)
        row.addStretch()

        self.value_lbl = QLabel()
        self.value_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_lbl.setFixedWidth(44)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(int(minimum))
        self.slider.setMaximum(int(maximum))
        self.slider.setValue(int(value))
        self.slider.setMinimumWidth(200)
        self.slider.setFixedHeight(28)  # >= 20px handle bbox + 4px breathing room
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.valueChanged.connect(self._on_value_changed)

        row.addWidget(self.value_lbl)
        row.addWidget(self.slider)

        self._update_label(int(value))
        self.apply_theme()

    def _update_label(self, value: int):
        self.value_lbl.setText(f"{int(value)}{self._suffix}")

    def value(self) -> int:
        return int(self.slider.value())

    def _on_value_changed(self, value: int):
        self._update_label(value)
        _animate_value_commit(self.value_lbl)
        self.valueChanged.emit(int(value))
        self.settingChanged.emit(self.key, int(value))

    def set_value_silent(self, value: int):
        blocked = self.slider.blockSignals(True)
        self.slider.setValue(int(value))
        self.slider.blockSignals(blocked)
        self._update_label(int(value))

    def apply_theme(self):
        v = theme_vars()
        self.title_lbl.setStyleSheet(f"""
            color: {v['on_surface']};
            font-size: 13px;
            font-weight: 600;
        """)
        self.desc_lbl.setStyleSheet(f"""
            color: {v['on_surface_variant']};
            font-size: 11px;
        """)
        self.value_lbl.setStyleSheet(f"""
            color: {v['on_surface']};
            font-size: 13px;
            font-weight: 600;
        """)
        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                subcontrol-position: center;
                height: 6px;
                border-radius: 3px;
                background-color: {v['surface_container_highest']};
            }}
            QSlider::sub-page:horizontal {{
                subcontrol-position: center;
                height: 6px;
                border-radius: 3px;
                background-color: {v['primary']};
            }}
            QSlider::handle:horizontal {{
                width: 16px;
                height: 16px;
                margin: -7px 0;
                border-radius: 10px;
                background-color: {v['on_primary']};
                border: 2px solid {v['primary']};
            }}
            QSlider::handle:horizontal:disabled {{
                background-color: {v['outline_variant']};
                border: 2px solid {v['outline_variant']};
            }}
        """)


class ComboRow(QWidget):
    """label + desc + QComboBox. Signals: currentChanged(int), settingChanged(key, itemData)."""

    currentChanged = Signal(int)
    settingChanged = Signal(str, object)

    def __init__(self, title: str, desc: str, key: str, parent=None):
        super().__init__(parent)
        self.key = key

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        header, self.title_lbl, self.desc_lbl = _header(title, desc)
        row.addWidget(header)
        row.addStretch()

        self.combo = QComboBox()
        self.combo.setObjectName("SettingsCombo")
        self.combo.setFixedHeight(32)
        self.combo.setMinimumWidth(210)
        self.combo.setCursor(Qt.PointingHandCursor)
        self.combo.currentIndexChanged.connect(self._on_index_changed)
        row.addWidget(self.combo)

        self.apply_theme()

    def _on_index_changed(self, index: int):
        self.currentChanged.emit(index)
        self.settingChanged.emit(self.key, self.combo.itemData(index))

    def add_item(self, text: str, data: Any = None):
        self.combo.addItem(text, data)

    def select_data_silent(self, data: Any) -> bool:
        index = self.combo.findData(data)
        if index < 0:
            return False
        blocked = self.combo.blockSignals(True)
        self.combo.setCurrentIndex(index)
        self.combo.blockSignals(blocked)
        return True

    def set_error_state(self, error: bool):
        self._error = bool(error)
        self.apply_theme()

    def apply_theme(self):
        v = theme_vars()
        self.title_lbl.setStyleSheet(f"""
            color: {v['on_surface']};
            font-size: 13px;
            font-weight: 600;
        """)
        self.desc_lbl.setStyleSheet(f"""
            color: {v['error'] if getattr(self, '_error', False) else v['on_surface_variant']};
            font-size: 11px;
        """)
        self.combo.setStyleSheet(_combo_style(v))


class StepperRow(QWidget):
    """label + desc + −/+ stepper with clamped integer value."""

    valueChanged = Signal(int)
    settingChanged = Signal(str, object)

    def __init__(self, title: str, desc: str, key: str, value: int,
                 minimum: int, maximum: int, step: int = 1, suffix: str = "", parent=None):
        super().__init__(parent)
        self.key = key
        self.minimum = int(minimum)
        self.maximum = int(maximum)
        self.step = int(step)
        self._suffix = suffix
        self._value = int(value)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        header, self.title_lbl, self.desc_lbl = _header(title, desc)
        row.addWidget(header)
        row.addStretch()

        self.minus_btn = QPushButton("-")
        self.plus_btn = QPushButton("+")
        for b in (self.minus_btn, self.plus_btn):
            b.setObjectName("SecondaryButton")
            b.setFixedSize(32, 32)
            b.setCursor(Qt.PointingHandCursor)
        self.minus_btn.clicked.connect(self._step_down)
        self.plus_btn.clicked.connect(self._step_up)

        self.value_lbl = QLabel()
        self.value_lbl.setAlignment(Qt.AlignCenter)
        self.value_lbl.setFixedWidth(56)

        row.addWidget(self.minus_btn)
        row.addWidget(self.value_lbl)
        row.addWidget(self.plus_btn)

        self.set_value_silent(self._value)
        self.apply_theme()

    def _clamp(self, value: int) -> int:
        return max(self.minimum, min(self.maximum, int(value)))

    def value(self) -> int:
        return int(self._value)

    def _step_down(self):
        self.set_value(self._value - self.step)

    def _step_up(self):
        self.set_value(self._value + self.step)

    def set_value(self, value: int, emit: bool = True):
        self._value = self._clamp(value)
        self.value_lbl.setText(f"{self._value}{self._suffix}")
        self.minus_btn.setEnabled(self._value > self.minimum)
        self.plus_btn.setEnabled(self._value < self.maximum)
        if emit:
            _animate_value_commit(self.value_lbl)
            self.valueChanged.emit(self._value)
            self.settingChanged.emit(self.key, self._value)

    def set_value_silent(self, value: int):
        self.set_value(value, emit=False)

    def apply_theme(self):
        v = theme_vars()
        self.title_lbl.setStyleSheet(f"""
            color: {v['on_surface']};
            font-size: 13px;
            font-weight: 600;
        """)
        self.desc_lbl.setStyleSheet(f"""
            color: {v['on_surface_variant']};
            font-size: 11px;
        """)
        self.value_lbl.setStyleSheet(f"""
            color: {v['on_surface']};
            font-size: 13px;
            font-weight: 600;
        """)
        btn_style = _stepper_button_style(v)
        self.minus_btn.setStyleSheet(btn_style)
        self.plus_btn.setStyleSheet(btn_style)


class ButtonRow(QWidget):
    """label + desc + inline secondary action button(s)."""

    def __init__(self, title: str, desc: str, parent=None):
        super().__init__(parent)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        header, self.title_lbl, self.desc_lbl = _header(title, desc)
        row.addWidget(header)
        row.addStretch()

        self.apply_theme()

    def add_button(self, text: str, callback: Callable[[], None]) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("SecondaryButton")
        btn.setFixedHeight(32)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(callback)
        self.layout().addWidget(btn)
        self.apply_theme()
        return btn

    def apply_theme(self):
        v = theme_vars()
        self.title_lbl.setStyleSheet(f"""
            color: {v['on_surface']};
            font-size: 13px;
            font-weight: 600;
        """)
        self.desc_lbl.setStyleSheet(f"""
            color: {v['on_surface_variant']};
            font-size: 11px;
        """)
        btn_style = _secondary_button_style(v)
        for i in range(self.layout().count()):
            w = self.layout().itemAt(i).widget()
            if isinstance(w, QPushButton):
                w.setStyleSheet(btn_style)


# -------------------------------------------------------------
# Page
# -------------------------------------------------------------
class SettingsPage(QWidget):
    """Scrollable single-column settings surface with instant-apply persistence."""

    recapLaunchRequested = Signal(tuple)

    def __init__(self, theme_controller=None, cfg: Optional[Dict[str, Any]] = None,
                 config_path=None, app_paths: Optional[AppPaths] = None):
        super().__init__()
        self.setObjectName("SettingsPage")

        # Explicit wiring preferred; resolve bootstrap context when constructed bare.
        if app_paths is None:
            app_paths = get_app_paths("DailySelfie", ensure=False)
        if config_path is None:
            config_path = Path(app_paths.config_dir) / "config.toml"
        if cfg is None:
            cfg = load_config(Path(config_path))
        if theme_controller is None:
            try:
                theme_controller = theme_vars()._controller
            except Exception:
                theme_controller = None

        self.app_paths = app_paths
        self.config_path = Path(config_path)
        self.cfg = cfg
        self.theme_controller = theme_controller

        self._themed: List[QWidget] = []
        self._sections: List[SectionCard] = []
        self._captions: List[QLabel] = []
        self._row_by_key: Dict[str, QWidget] = {}
        self._cam_worker: Optional[CameraProbeWorker] = None
        self._shell_workers: Dict[str, ManagerCallThread] = {}
        self._probed_once = False
        self._teardown_generation = 0

        # Incoming-only page transitions animate this wrapper (motion-system.md)
        self._motion_wrapper = install_motion_wrapper(self)
        root = QVBoxLayout(self._motion_wrapper)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        content.setObjectName("SettingsContent")
        column = QVBoxLayout(content)
        column.setContentsMargins(12, 12, 12, 12)
        column.setSpacing(12)

        self._build_appearance(column)
        self._build_behavior(column)
        self._build_system(column)
        self._build_about(column)
        column.addStretch()

        self._scroll.setWidget(content)
        root.addWidget(self._scroll)

        self._apply_theme()
        if self.theme_controller is not None:
            self.theme_controller.themeChanged.connect(self.refresh)

        # Quit-without-close must still tear down workers (bound method kept
        # in a ref so disconnect is unambiguous).
        app = QApplication.instance()
        if app is not None:
            self._on_app_quit = self._teardown_workers
            app.aboutToQuit.connect(self._on_app_quit)

        # Selection sync must run after construction: the ring/segments are
        # seeded from controller state that may have changed during build.
        if getattr(self, "_theme_cards", None):
            self._sync_theme_selection()

    # ---------------------------------------------------------
    # Section builders
    # ---------------------------------------------------------
    def _register_section(self, card: SectionCard) -> SectionCard:
        self._sections.append(card)
        self._themed.append(card)
        return card

    def _section_caption(self, parent_layout, text: str) -> QLabel:
        lbl = QLabel(text)
        parent_layout.addWidget(lbl)
        self._captions.append(lbl)
        return lbl

    def _build_appearance(self, column: QVBoxLayout):
        card = self._register_section(SectionCard("Appearance"))

        self._theme_group = QButtonGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_cards: Dict[str, QPushButton] = {}

        themes = []
        if self.theme_controller is not None:
            try:
                themes = list(self.theme_controller.available_themes())
            except Exception:
                themes = []

        grid_holder = QWidget()
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for i, name in enumerate(themes):
            btn = QPushButton(name)
            btn.setObjectName("ThemeCard")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, n=name: self._on_theme_clicked(n))
            self._theme_group.addButton(btn)
            self._theme_cards[name] = btn
            grid.addWidget(btn, i // 4, i % 4)
        if themes:
            card.add(grid_holder)
            self._section_caption(card.content, "Mode")
            mode_holder = QWidget()
            self._mode_layout = QHBoxLayout(mode_holder)
            self._mode_layout.setContentsMargins(0, 0, 0, 0)
            self._mode_layout.setSpacing(6)
            card.add(mode_holder)
            self._section_caption(card.content, "Contrast")
            contrast_holder = QWidget()
            self._contrast_layout = QHBoxLayout(contrast_holder)
            self._contrast_layout.setContentsMargins(0, 0, 0, 0)
            self._contrast_layout.setSpacing(6)
            card.add(contrast_holder)
            self._fill_segment("mode", self._available_modes(), self._current_mode(),
                               self._on_mode_clicked)
            self._fill_segment("contrast", self._available_contrasts(), self._current_contrast(),
                               self._on_contrast_clicked)
        column.addWidget(card)

    def _build_behavior(self, column: QVBoxLayout):
        card = self._register_section(SectionCard("Behavior"))
        beh = self.cfg.get("behavior", {})

        # --- Camera device row (combo + retry, on ComboRow) ---
        stored_idx = beh.get("camera_index", 0)
        self._camera_row = ComboRow(
            "Camera", "Device used for captures", "camera_index",
        )
        # Seed BEFORE connecting so the empty-combo addItem can't fire a
        # spurious persist; block signals during the seed for good measure.
        self._camera_row.combo.blockSignals(True)
        self._camera_row.add_item(f"Camera {stored_idx}", stored_idx)
        self._camera_row.combo.blockSignals(False)
        self._camera_row.combo.currentIndexChanged.connect(self._on_camera_selected)

        self._camera_retry = QPushButton("Retry")
        self._camera_retry.setObjectName("SecondaryButton")
        self._camera_retry.setFixedHeight(32)
        self._camera_retry.setCursor(Qt.PointingHandCursor)
        self._camera_retry.clicked.connect(self._start_camera_probe)
        self._camera_row.layout().addWidget(self._camera_retry)

        card.add(self._camera_row)

        # --- Quality slider ---
        quality = SliderRow(
            "Image quality", "JPEG compression quality (1–100)", "quality",
            self._clamped_quality(), QUALITY_MIN, QUALITY_MAX, suffix="%",
        )
        quality.settingChanged.connect(self._on_row_setting_changed)
        card.add(quality)

        # --- Resolution steppers ---
        # Values are normalised to what core.config will actually hold after a
        # load (see _sanitised_dimension): 0/None is rewritten by the validator
        # and stripped on write, so showing it here would display a value that
        # silently reverts to the default resolution on the next launch.
        width_row = StepperRow(
            "Capture width", "Camera frame width in pixels", "width",
            _sanitised_dimension("width", beh.get("width")),
            DIM_MIN, DIM_MAX, DIM_STEP,
        )
        height_row = StepperRow(
            "Capture height", "Camera frame height in pixels", "height",
            _sanitised_dimension("height", beh.get("height")),
            DIM_MIN, DIM_MAX, DIM_STEP,
        )
        for r in (width_row, height_row):
            r.settingChanged.connect(self._on_row_setting_changed)
            card.add(r)

        # --- Timer stepper ---
        timer_row = StepperRow(
            "Timer duration", "Countdown before capture (seconds, 0 = off)",
            "timer_duration", beh.get("timer_duration", 0), TIMER_MIN, TIMER_MAX, 1,
            suffix=" s",
        )
        timer_row.settingChanged.connect(self._on_row_setting_changed)
        card.add(timer_row)

        # --- Allow-retake switch ---
        retake_row = ToggleRow(
            "Allow retake", "Overwrite today's photo when capturing again",
            "allow_retake", bool(beh.get("allow_retake", False)),
        )
        retake_row.settingChanged.connect(self._on_row_setting_changed)
        card.add(retake_row)

        # --- Animations (reduced-motion gate) ---
        # behavior.motion_enabled gates every animation site in the app (page
        # transitions, card lifts, carousel, chip/card entrances) but had no
        # control at all, so motion was hard-coded on for everyone. It lives in
        # Behavior, not Highlights & Recaps: the key is a behavior.* preference,
        # the gate is app-wide rather than recap-specific, and the spec pins this
        # page to four sections.
        # `toggled` only — NOT settingChanged — because _on_motion_toggled has to
        # reconcile with disk truth on failure and must write exactly once.
        motion_on = mt.is_motion_enabled(self.cfg)
        self._motion_row = ToggleRow(
            "Animations",
            "Page transitions, card lifts and the recap carousel. When off, "
            "everything jumps straight to its new state.",
            "motion_enabled", motion_on,
        )
        self._motion_row.toggled.connect(self._on_motion_toggled)
        self._motion_row_desc(motion_on)
        card.add(self._motion_row)

        self._behavior_rows = [quality, width_row, height_row, timer_row, retake_row]
        # Rows that need a control-level revert when a write fails.
        self._row_by_key.update({r.key: r for r in self._behavior_rows})
        self._themed.append(self._camera_row)
        self._themed.extend(self._behavior_rows)
        self._themed.append(self._motion_row)
        column.addWidget(card)

        # --- Highlights & Recaps section ---
        hl_card = self._register_section(SectionCard("Highlights & Recaps"))

        self._highlights_row = ToggleRow(
            "Highlights",
            "Show recap and highlight suggestions on the dashboard",
            "highlights_enabled", bool(beh.get("highlights_enabled", True)),
        )
        self._highlights_row.settingChanged.connect(self._on_row_setting_changed)
        hl_card.add(self._highlights_row)
        self._row_by_key[self._highlights_row.key] = self._highlights_row

        self._recap_launch_row = ButtonRow(
            "Monthly recap", "Rewatch a finished month as a story deck",
        )
        self._recap_launch_btn = self._recap_launch_row.add_button(
            "View your recap…", self._launch_recap)
        hl_card.add(self._recap_launch_row)

        self._themed.append(self._highlights_row)
        self._themed.append(self._recap_launch_row)
        column.addWidget(hl_card)
        self._refresh_recap_availability()

    def _build_system(self, column: QVBoxLayout):
        card = self._register_section(SectionCard("System"))

        autostart_on = self._query_shell_truth("autostart")
        if autostart_on is None:
            autostart_on = False
        self._autostart_row = ToggleRow(
            "Launch at login", "Start DailySelfie automatically when you log in",
            "autostart", autostart_on,
        )
        self._autostart_row.toggled.connect(
            lambda checked: self._on_shell_toggle("autostart", checked)
        )
        card.add(self._autostart_row)

        entry_on = self._query_shell_truth("desktop_entry")
        if entry_on is None:
            entry_on = False
        self._desktop_row = ToggleRow(
            "Desktop entry", "Show DailySelfie in your application launcher",
            "desktop_entry", entry_on,
        )
        self._desktop_row.toggled.connect(
            lambda checked: self._on_shell_toggle("desktop_entry", checked)
        )
        card.add(self._desktop_row)

        folders = ButtonRow("Folders", "Open photos, data and log locations")
        folders.add_button("Photos", lambda: self._open_folder(Path(self.app_paths.photos_root)))
        folders.add_button("Data", lambda: self._open_folder(Path(self.app_paths.data_dir)))
        folders.add_button("Logs", lambda: self._open_folder(Path(self.app_paths.logs_dir)))
        card.add(folders)

        self._themed.append(self._autostart_row)
        self._themed.append(self._desktop_row)
        self._themed.append(folders)
        column.addWidget(card)

    def _build_about(self, column: QVBoxLayout):
        card = self._register_section(SectionCard("About"))

        top = QWidget()
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        icon_lbl = QLabel()
        icon_path = Path(self.app_paths.project_root) / "gui" / "assets" / "icons" / "app.png"
        if icon_path.exists():
            dpr = self.devicePixelRatioF()
            pix = QPixmap(str(icon_path)).scaled(
                round(48 * dpr), round(48 * dpr), Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            pix.setDevicePixelRatio(dpr)
            icon_lbl.setPixmap(pix)
        icon_lbl.setFixedSize(48, 48)
        top_row.addWidget(icon_lbl)

        name_box = QWidget()
        name_col = QVBoxLayout(name_box)
        name_col.setContentsMargins(0, 0, 0, 0)
        name_col.setSpacing(2)

        name_lbl = QLabel("DailySelfie")
        self._version_lbl = QLabel(f"Version {APP_VERSION}")
        name_col.addWidget(name_lbl)
        name_col.addWidget(self._version_lbl)
        top_row.addWidget(name_box)
        top_row.addStretch()
        card.add(top)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(1)
        card.add(sep)
        self._about_separator = sep

        self._data_path_lbl = QLabel(f"Data folder   {self.app_paths.data_dir}")
        self._log_path_lbl = QLabel(f"Log folder     {self.app_paths.logs_dir}")
        for lbl in (self._data_path_lbl, self._log_path_lbl):
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            card.add(lbl)

        self._about_name_lbl = name_lbl
        self._about_icon_lbl = icon_lbl
        column.addWidget(card)

    # ---------------------------------------------------------
    # Theme handling
    # ---------------------------------------------------------
    def _available_modes(self) -> List[str]:
        if self.theme_controller is None:
            return []
        try:
            return list(self.theme_controller.available_modes())
        except Exception:
            return []

    def _available_contrasts(self) -> List[str]:
        if self.theme_controller is None:
            return []
        try:
            return list(self.theme_controller.available_contrasts())
        except Exception:
            return []

    def _current_mode(self) -> str:
        return self.theme_controller.mode if self.theme_controller else ""

    def _current_contrast(self) -> str:
        return self.theme_controller.contrast if self.theme_controller else ""

    def _fill_segment(self, which: str, options: List[str], current: str,
                      callback: Callable[[str], None]):
        layout = self._mode_layout if which == "mode" else self._contrast_layout
        old_group = getattr(self, f"_{which}_group", None)
        if old_group is not None:
            old_group.deleteLater()
        group = QButtonGroup(self)
        group.setExclusive(True)
        setattr(self, f"_{which}_group", group)

        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        v = theme_vars()
        for opt in options:
            btn = QPushButton(str(opt).capitalize())
            btn.setObjectName("SegmentButton")
            btn.setCheckable(True)
            btn.setChecked(opt == current)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, o=opt: callback(o))
            btn.setStyleSheet(f"""
                QPushButton#SegmentButton {{
                    background-color: transparent;
                    color: {v['on_surface_variant']};
                    border: none;
                    border-radius: 16px;
                    padding: 0 16px;
                    min-height: 32px;
                    font-size: 12px;
                    font-weight: 600;
                }}
                QPushButton#SegmentButton:hover {{
                    background-color: {v['surface_container_high']};
                }}
                QPushButton#SegmentButton:checked {{
                    background-color: {v['primary']};
                    color: {v['on_primary']};
                }}
            """)
            group.addButton(btn)
            layout.addWidget(btn)
        layout.addStretch()

    def _sync_theme_selection(self):
        tc = self.theme_controller
        if tc is None:
            return
        current = tc.theme_name
        for name, btn in self._theme_cards.items():
            btn.blockSignals(True)
            btn.setChecked(name == current)
            btn.blockSignals(False)

        modes = self._available_modes()
        contrasts = self._available_contrasts()
        if hasattr(self, "_mode_layout"):
            self._fill_segment("mode", modes, self._current_mode(), self._on_mode_clicked)
        if hasattr(self, "_contrast_layout"):
            self._fill_segment(
                "contrast", contrasts, self._current_contrast(), self._on_contrast_clicked
            )

    def _on_theme_clicked(self, name: str):
        tc = self.theme_controller
        if tc is None:
            return
        tc.set_theme(name)
        # WORKAROUND for a silent backend failure — do not "simplify" this away.
        # ThemeController.set_theme() catches ThemeLoaderError with a bare
        # `except ThemeLoaderError: pass` (gui/theme/theme_controller.py), so a
        # bad theme name raises nothing, logs nothing and never emits
        # themeChanged: a failure is indistinguishable from success.
        # docs/design/settings-page.md "Backend asks" #3 asks for that handler to
        # log; until it does, the only observable signal is theme_name, so we
        # compare it against the requested name and surface the failure as an
        # ERROR toast + revert the selection. With logging added in the
        # controller, keep this check anyway — the toast is the user-facing half.
        if tc.theme_name != name:
            logger.warning("theme_apply_failed", extra={"meta": {"theme": name}})
            self._toast("ERROR", f"Couldn't load theme '{name}'")
            self._sync_theme_selection()
            return
        try:
            tc.save(self.config_path)
        except Exception as e:
            logger.error("theme_save_failed", extra={"meta": {"error": str(e)}})
            self._toast("ERROR", f"Failed to save theme selection:\n{e}")

    def _on_mode_clicked(self, mode: str):
        tc = self.theme_controller
        if tc is None or mode == tc.mode:
            return
        tc.set_mode(mode)  # set_mode emits themeChanged -> refresh()
        try:
            tc.save(self.config_path)
        except Exception as e:
            logger.error("theme_save_failed", extra={"meta": {"error": str(e)}})
            self._toast("ERROR", f"Failed to save theme mode:\n{e}")

    def _on_contrast_clicked(self, contrast: str):
        tc = self.theme_controller
        if tc is None or contrast == tc.contrast:
            return
        tc.set_contrast(contrast)  # set_contrast emits themeChanged -> refresh()
        try:
            tc.save(self.config_path)
        except Exception as e:
            logger.error("theme_save_failed", extra={"meta": {"error": str(e)}})
            self._toast("ERROR", f"Failed to save theme contrast:\n{e}")

    def refresh(self):
        """Rebuild all build-time-f-string styles + re-sync selections (themeChanged)."""
        self._apply_theme()
        self._sync_theme_selection()

    def _apply_theme(self):
        v = theme_vars()

        self._scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QWidget#SettingsContent { background: transparent; }
        """)

        caption_style = f"""
            color: {v['on_surface_variant']};
            font-size: 11px;
            font-weight: 500;
        """
        for lbl in getattr(self, "_captions", []):
            lbl.setStyleSheet(caption_style)

        theme_card_style = f"""
            QPushButton#ThemeCard {{
                background-color: {v['surface_container_high']};
                color: {v['on_surface_variant']};
                border: 2px solid transparent;
                border-radius: 12px;
                padding: 14px 8px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton#ThemeCard:hover {{
                background-color: {v['surface_container_highest']};
                border: 2px solid {v['outline']};
                color: {v['on_surface']};
            }}
            QPushButton#ThemeCard:checked {{
                background-color: {v['surface_container_highest']};
                border: 2px solid {v['primary']};
                color: {v['on_surface']};
            }}
        """
        for btn in self._theme_cards.values():
            btn.setStyleSheet(theme_card_style)

        self._camera_retry.setStyleSheet(_secondary_button_style(v))

        self._about_name_lbl.setStyleSheet(f"""
            color: {v['on_surface']};
            font-size: 18px;
            font-weight: 700;
        """)
        self._version_lbl.setStyleSheet(f"""
            color: {v['on_surface_variant']};
            font-size: 12px;
        """)
        self._about_separator.setStyleSheet(
            f"background-color: {v['outline_variant']};"
        )
        path_style = f"""
            color: {v['on_surface_variant']};
            font-size: 11px;
        """
        self._data_path_lbl.setStyleSheet(path_style)
        self._log_path_lbl.setStyleSheet(path_style)

        for w in self._themed:
            try:
                w.apply_theme()
            except RuntimeError:
                pass

    # ---------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------
    def _clamped_quality(self) -> int:
        raw = self.cfg.get("behavior", {}).get("quality", QUALITY_FALLBACK)
        try:
            return max(QUALITY_MIN, min(QUALITY_MAX, int(raw)))
        except (TypeError, ValueError):
            return QUALITY_FALLBACK

    def _clamped_int(self, value: Any, low: int, high: int, fallback: int) -> int:
        try:
            return max(low, min(high, int(value)))
        except (TypeError, ValueError):
            return fallback

    def _on_row_setting_changed(self, key: str, value: Any):
        if key == "quality":
            # clamp pre-persist (validation raises otherwise)
            value = self._clamped_int(value, QUALITY_MIN, QUALITY_MAX,
                                      QUALITY_FALLBACK)
        elif key in _DIM_KEYS:
            # core.config rewrites width/height 0 -> None and write_config drops
            # the key, so an out-of-range value would silently revert at the next
            # boot. Clamp into the range the validator really accepts.
            value = self._clamped_int(value, DIM_MIN, DIM_MAX,
                                      _sanitised_dimension(key, value))
        section = _ROW_KEYS.get(key)
        if not section:
            return
        if self._persist_values({f"{section}.{key}": value}):
            return
        # Write failed and _persist_values already toasted. The control must go
        # back to what disk actually holds (edge case 6), and because the
        # requested value never committed it plays the C4 invalid-input shake.
        if self._revert_row(key):
            _shake_row(self._row_by_key[key])

    def _disk_value(self, section: str, key: str) -> Any:
        """Read one value straight from config.toml (disk wins over request).

        Falls back to DEFAULT_CONFIG when the key is absent or was rewritten to
        None by _validate_behavior, so callers always get a usable value.
        """
        default = DEFAULT_CONFIG.get(section, {}).get(key)
        try:
            data = load_config(self.config_path).get(section, {})
            value = data.get(key, default) if isinstance(data, dict) else default
        except Exception:
            value = default
        return default if value is None else value

    def _revert_row(self, key: str) -> bool:
        """Snap one control back to the value config.toml holds.

        Returns True when the control actually moved (i.e. the shown value was
        rejected), which is what drives the C4 shake.
        """
        row = getattr(self, "_row_by_key", {}).get(key)
        if row is None:
            return False
        stored = self._disk_value("behavior", key)
        if key in _DIM_KEYS:
            stored = _sanitised_dimension(key, stored)
        try:
            if isinstance(row, (StepperRow, SliderRow)):
                before = row.value()
                row.set_value_silent(int(stored))
                return row.value() != before
            if isinstance(row, ToggleRow):
                before = row.switch_w.isChecked()
                row.set_checked_silent(bool(stored))
                return row.switch_w.isChecked() != before
        except (TypeError, ValueError, RuntimeError):
            return False
        return False

    # ---------------------------------------------------------
    # Motion gate (behavior.motion_enabled)
    # ---------------------------------------------------------
    def _on_motion_toggled(self, requested: bool):
        """Persist behavior.motion_enabled; disk wins over the request.

        The switch has already flipped optimistically (Qt flips before
        emitting), which is the optimistic-flip-then-reconcile shape the spec
        asks of the shell toggles: on success nothing else happens, on failure
        the switch snaps back to the value config.toml really holds and the
        ERROR toast has already been raised by _persist_values.
        """
        requested = bool(requested)
        if not self._persist_values({"behavior.motion_enabled": requested}):
            if self._reconcile_motion_row():
                _shake_row(self._motion_row)
            return
        self._motion_row_desc(requested)

    def _reconcile_motion_row(self) -> bool:
        """Snap the motion switch to disk truth. True when it actually moved."""
        stored = self._disk_value("behavior", "motion_enabled")
        row = self._motion_row
        try:
            before = row.switch_w.isChecked()
            row.set_checked_silent(bool(stored))
        except RuntimeError:
            return False  # page torn down
        self._motion_row_desc(bool(stored))
        return row.switch_w.isChecked() != before

    def _motion_row_desc(self, enabled: bool):
        """Keep the subtitle truthful about what the switch currently does."""
        self._motion_row.desc_lbl.setText(
            "Page transitions, card lifts and the recap carousel. When off, "
            "everything jumps straight to its new state."
            if enabled else
            "Animations are off — transitions and lifts jump straight to "
            "their new state."
        )

    def _persist_values(self, updates: Dict[str, Any]) -> bool:
        """Instant-apply: read-modify-write config.toml atomically.

        Re-reads from disk so external changes made since launch (CLI --theme,
        another process toggling autostart) are never silently reverted. On
        write failure the fresh dict is discarded and self.cfg stays untouched;
        the snapshot-revert restores prior values preserving absence vs
        explicit-None semantics. Returns False after raising the ERROR toast —
        callers are responsible for snapping their control back (see
        _revert_row) so the UI never shows an unsaved value.
        """
        try:
            fresh = load_config(self.config_path)
        except Exception as e:
            logger.error("config_read_failed", extra={"meta": {"error": str(e)}})
            self._toast("ERROR", f"Failed to save setting:\n{e}")
            return False

        had_key: Dict[str, bool] = {}
        snapshot: Dict[str, Any] = {}
        for dotted, new_value in updates.items():
            sec, key = dotted.split(".", 1)
            sec_cfg = fresh.setdefault(sec, {})
            had_key[dotted] = key in sec_cfg
            snapshot[dotted] = sec_cfg.get(key)
            sec_cfg[key] = new_value

        try:
            write_config(self.config_path, fresh)
        except Exception as e:
            for dotted in updates:
                sec, key = dotted.split(".", 1)
                sec_cfg = fresh.setdefault(sec, {})
                if had_key[dotted]:
                    sec_cfg[key] = snapshot[dotted]
                else:
                    sec_cfg.pop(key, None)
            logger.error("config_write_failed", extra={"meta": {"error": str(e)}})
            self._toast("ERROR", f"Failed to save setting:\n{e}")
            return False

        self.cfg = fresh
        return True

    # ---------------------------------------------------------
    # Camera probing
    # ---------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_recap_availability()
        if not self._probed_once:
            self._probed_once = True
            # Guarded: the timer must not fire into a torn-down page.
            generation = self._teardown_generation
            QTimer.singleShot(200, lambda: self._deferred_probe(generation))

    # ---------------------------------------------------------
    # Highlights & recaps
    # ---------------------------------------------------------
    def _refresh_recap_availability(self):
        """Enable 'View your recap…' iff any eligible period exists (§4)."""
        try:
            periods = recap_eligible_periods(get_api(self.app_paths))
        except Exception:
            periods = []
        self._eligible_periods = list(periods)
        eligible = bool(periods)
        try:
            self._recap_launch_btn.setEnabled(eligible)
            self._recap_launch_row.desc_lbl.setText(
                "Rewatch a finished month as a story deck" if eligible
                else "Unlocks after your first full month with 5+ capture days")
        except RuntimeError:
            pass  # page torn down

    def _launch_recap(self):
        periods = getattr(self, "_eligible_periods", None)
        if periods:
            self.recapLaunchRequested.emit(tuple(periods[0]))

    def _deferred_probe(self, generation: int):
        # Pure-Python generation check first: safe even post-destruction.
        if generation != self._teardown_generation:
            return
        try:
            if not self.isVisible():
                return
            self._start_camera_probe()
        except RuntimeError:
            pass  # underlying C++ widget already destroyed

    def _set_camera_desc(self, text: str, error: bool):
        self._camera_row.desc_lbl.setText(text)
        self._camera_row.set_error_state(error)

    def _start_camera_probe(self):
        if self._cam_worker is not None and self._cam_worker.isRunning():
            return  # gate: one probe at a time
        self._camera_retry.setEnabled(False)
        self._camera_row.combo.setEnabled(False)
        self._set_camera_desc("Scanning for cameras…", error=False)
        worker = CameraProbeWorker(self)
        self._cam_worker = worker
        worker.probed.connect(self._on_cameras_probed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_cameras_probed(self, indices: List[int]):
        try:
            self._cam_worker = None
            combo = self._camera_row.combo
            stored = self.cfg.get("behavior", {}).get("camera_index", 0)
            if not isinstance(stored, int):
                stored = 0

            combo.blockSignals(True)
            combo.clear()
            if not indices:
                combo.addItem("No camera detected")
                model = combo.model()
                item = model.item(0) if model is not None else None
                if item is not None:
                    item.setEnabled(False)
                combo.setCurrentIndex(0)
                self._set_camera_desc("Plug in a camera and press Retry", error=True)
            else:
                self._set_camera_desc("Device used for captures", error=False)
                for i in indices:
                    combo.addItem(f"Camera {i}", i)
                if stored in indices:
                    combo.setCurrentIndex(indices.index(stored))
                else:
                    new_idx = indices[0]
                    combo.setCurrentIndex(indices.index(new_idx))
                    self._persist_values({"behavior.camera_index": new_idx})
                    self._toast(
                        "WARNING", f"Camera {stored} not found — using Camera {new_idx}"
                    )
            combo.blockSignals(False)
            combo.setEnabled(True)
            self._camera_retry.setEnabled(True)
        except RuntimeError:
            pass  # widgets torn down mid-probe

    def _on_camera_selected(self, index: int):
        data = self._camera_row.combo.itemData(index)
        if isinstance(data, int):
            self._persist_values({"behavior.camera_index": data})

    # ---------------------------------------------------------
    # System shell toggles (optimistic flip + disk-truth re-sync)
    # ---------------------------------------------------------
    def _query_shell_truth(self, kind: str) -> Optional[bool]:
        try:
            if kind == "autostart":
                return bool(is_autostart_enabled(self.app_paths))
            return bool(is_desktop_entry_enabled(self.app_paths))
        except Exception as e:
            logger.warning("shell_state_query_failed",
                           extra={"meta": {"kind": kind, "error": str(e)}})
            return None

    def _on_shell_toggle(self, kind: str, requested: bool):
        if kind in self._shell_workers:
            return
        row = self._autostart_row if kind == "autostart" else self._desktop_row
        row.set_enabled_state(False)  # optimistic flip already shown; lock row

        if kind == "autostart":
            call = lambda: set_autostart(requested)
        else:
            call = lambda: set_desktop_entry(requested)

        worker = ManagerCallThread(call, self)
        self._shell_workers[kind] = worker
        worker.done.connect(
            lambda err, k=kind, req=requested: self._on_shell_done(k, req, err)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_shell_done(self, kind: str, requested: bool, err: Optional[Exception]):
        try:
            self._shell_workers.pop(kind, None)
            row = self._autostart_row if kind == "autostart" else self._desktop_row
            truth = self._query_shell_truth(kind)
            if truth is None:
                truth = requested  # disk unreadable; keep optimistic state
            row.set_checked_silent(truth)  # disk wins over request
            row.set_enabled_state(True)
            if err is not None:
                logger.error("shell_toggle_failed",
                             extra={"meta": {"kind": kind, "error": str(err)}})
                self._toast("ERROR", str(err))
        except RuntimeError:
            pass  # page torn down mid-operation

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------
    def _open_folder(self, path: Path):
        try:
            path.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as e:
            logger.error("open_folder_failed",
                         extra={"meta": {"path": str(path), "error": str(e)}})
            self._toast("ERROR", f"Could not open folder:\n{e}")

    def _toast(self, level: str, message: str):
        popup = ErrorToast(self, level=level, message=message)
        geo = self.window().geometry()
        x = geo.x() + (geo.width() - popup.width()) // 2
        y = geo.y() + (geo.height() - popup.height()) // 3
        popup.move(x, y)
        popup.show()

    def closeEvent(self, event):
        self._teardown_workers()
        super().closeEvent(event)

    def _teardown_workers(self):
        """Stop and disconnect probe/manager threads. Idempotent; invoked from
        closeEvent AND QApplication.aboutToQuit (quit without window close)."""
        # Bump so a pending deferred camera probe becomes a no-op.
        self._teardown_generation += 1

        slot = getattr(self, "_on_app_quit", None)
        app = QApplication.instance()
        if slot is not None and app is not None:
            self._on_app_quit = None  # consume: repeat teardown must not re-disconnect
            try:
                app.aboutToQuit.disconnect(slot)
            except Exception:
                pass

        # Disconnect workers before teardown so no signals land on dead widgets.
        for worker in list(self._shell_workers.values()):
            try:
                worker.done.disconnect()
                worker.finished.disconnect()
            except Exception:
                pass
            worker.wait(2000)
        self._shell_workers.clear()

        cam = self._cam_worker
        if cam is not None:
            try:
                cam.probed.disconnect()
                cam.finished.disconnect()
            except Exception:
                pass
            cam.wait(5000)
            self._cam_worker = None
