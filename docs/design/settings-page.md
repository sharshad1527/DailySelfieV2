# SettingsPage — Design Spec (Squad C)

Decision-complete. Follow dashboard.py conventions for anything unspecified.

## Wiring

- `SettingsPage(theme_controller, cfg, config_path, app_paths)` — ctor-injected.
  `DashboardWindow.__init__` forwards from `main()` which already holds all four
  objects (`DailySelfie.py` ~271/294). No core changes required.
- Theme disk persistence: page calls `theme_controller.save(config_path)` after
  each theme mutation (GUI currently never persists; only CLI does).

## Page structure

Scrollable single column of grouped SectionCards (bg `surface_container_low`,
radius 16, matching dashboard cards):

1. **Appearance**
   - Theme picker: grid of the 8 themes (names from
     `theme_controller.available_themes()`), click = instant apply via
     `set_theme()` → `themeChanged` app-wide + `theme_controller.save()`.
     Selected card gets `primary` ring. On failure: revert selection,
     ErrorToast(level="ERROR").
   - Mode selector: segmented control from `available_modes()` (light/dark)
   - Contrast selector: segmented control from `available_contrasts()`
   - After any theme change: rebuild section stylesheets (build-time f-string
     convention) and repopulate mode/contrast from controller self-fallbacks
     (`theme_controller.py` falls back when new theme lacks current mode).
2. **Behavior**
   - Camera device combo: populated off-thread via `list_cameras()`
     (core/camera.py); refresh button; probe spinner state while worker runs.
   - Quality slider 1–100 with live value label (config key `behavior.quality`;
     clamp before persist — validation would raise at next boot otherwise).
   - Resolution controls for `behavior.width` / `behavior.height`.
   - Timer duration stepper for `behavior.timer_duration`.
   - Allow-retake ToggleSwitch → `behavior.allow_retake`.
3. **System**
   - Autostart ToggleSwitch → `set_autostart(bool)`
     (core/autostart_manager.py); initial state via enabled-state query.
   - Desktop-entry ToggleSwitch → `set_desktop_entry(bool)`
     (core/desktop_entry_manager.py).
   - Open-folder buttons: photos / data / logs (core/paths helpers);
     `mkdir(parents=True, exist_ok=True)` then open via QDesktopServices.
4. **About**
   - App icon + name + version (`core/app_info.APP_VERSION`), data path,
     log path line.

## Reusable control components

| Class | Purpose | Notes |
|---|---|---|
| `SectionCard` | Grouped card container | title label + QVBoxLayout content |
| `ToggleRow` | label + desc + custom switch | signal `toggled(bool)` |
| `ToggleSwitch` | Custom PySide6 switch (no native one) | track/thumb geometry: h~28 w~48 r14 thumb d20; unchecked track `surface_container_highest`, checked track `primary`, thumb `on_primary`; disabled track `surface_container_lowest`, unchecked thumb `outline_variant` |
| `SliderRow` | label + desc + QSlider + value label | signal `valueChanged(int)` |
| `ComboRow` | label + desc + QComboBox | signal `currentChanged(int)` |
| `StepperRow` | label + desc + −/+ stepper | min/max clamps per config validation |
| `ButtonRow` | inline action button(s) | secondary style (h32 radius 16) |

Rows emit generic `settingChanged(key, value)` up to page for persistence.

## Save model

**Instant-apply per control** (matches existing instant theme behavior):
each mutation persists to config immediately (atomic write already guaranteed
by config layer). No dirty footer bar.

## Interaction & failure rules

- Shell toggles (autostart/desktop-entry): optimistic flip + disable row +
  run manager off-thread → on completion **re-sync from disk truth**
  (`is_autostart_enabled(paths)` / `is_desktop_entry_enabled(paths)`) — disk
  wins over request. RuntimeError ("not installed") or any failure → revert
  switch + ErrorToast with the manager's message.
- Camera probe finds 0 cameras (or cv2 missing): item 0 = "No camera detected"
  (disabled), desc switches to error-colored "Plug in a camera and press Retry".
  Retry stays enabled.
- Stale `camera_index` after unplug: stored index not in results → fallback to
  first available (else 0), persist immediately, WARNING toast:
  "Camera {old} not found — using Camera {new}".
- Probe races: Retry disabled while worker alive; worker ref held by page;
  disconnect `finished` before teardown (no signals into dead widgets).
- `write_config` failure: revert control to snapshot + ERROR toast.
- External config edit / CLI --theme while app open: file-watcher fires
  `themeChanged` → Appearance rows call `refresh()`. Behavior rows do NOT
  live-reload (accepted v1).

## Edge cases checklist

1. Zero cameras / cv2 missing → unified warning state above
2. Stale camera index → auto-fallback + toast
3. Probe race → Retry gating + worker lifetime management
4. Manager raises "not installed" → revert + toast message passthrough
5. Optimistic-toggle drift → disk-truth re-sync after op
6. Config write fails → revert + toast
7. Watcher-driven theme change while page open → refresh Appearance rows
8. New theme lacks current mode/contrast → repopulate from available_*()
9. Slider out-of-range → clamp pre-persist
10. Missing photos dir on Open → mkdir first
11. Theme switch repaint → rebuild section card stylesheets on themeChanged

## Theme keys used (verified present in all 8 themes × modes)

`surface_container_low`, `surface_container_high`, `surface_container_highest`,
`surface_container_lowest`, `on_surface`, `on_surface_variant`, `outline`,
`outline_variant`, `primary`, `on_primary`, `error`, `error_container`,
`on_error_container`, `tertiary`

## Backend asks

1. `core/app_info.py`: `APP_VERSION = "1.0"`
2. Ctor wiring pass-through in DashboardWindow/main (objects already exist)
3. Optional: make `ThemeController.set_theme` log instead of silent pass;
   until then page compares `theme_name` post-call to detect no-op failures.
