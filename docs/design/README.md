# DailySelfie Design Specs

Coder-ready UI/UX specifications produced by the design squads (Aug 2026).
All specs are decision-complete: class names, signals, sizes, colors, states,
flows, and edge behaviors are fixed. Implementers should not re-design.

| Doc | Scope |
|---|---|
| [settings-page.md](settings-page.md) | SettingsPage full UX + control components |
| [calendar-page.md](calendar-page.md) | CalendarPage grid, day detail, data-viz layer |
| [motion-system.md](motion-system.md) | Motion tokens, transitions, micro-interactions |
| [feature-backlog.md](feature-backlog.md) | Post-pages roadmap (researched) |

## Shared conventions (from existing code)

- Visual language source of truth: `gui/dashboard/pages/dashboard.py`
  (cards radius 16, surface radius 12, buttons h48 primary / h32 secondary,
  margins & spacing 12, title 18px w700, labels 14px w600, captions 11–13px)
- Theme access via `ThemeVars.qcolor(key)` / `theme_vars.rgba(key, alpha)`;
  stylesheets are build-time f-strings → rebuild widgets on `themeChanged`
- Icons via `_create_colored_icon(name, qcolor)` pattern (SourceIn recolor)
- Errors surfaced via `gui/widgets/error_popup.ErrorToast`
- Pages currently constructed zero-arg in `dashboard.py`; new pages receive
  injected context (see each spec's wiring section)

## Backend asks raised by squads (implement alongside pages)

1. Promote `IndexAPI.get_all_capture_dates()` to public façade method;
   migrate `dashboard.py` `_ensure_indexer()` reach-throughs to it
2. New `IndexAPI.get_capture_counts_by_date(year) -> dict[str, int]`
3. Optional `IndexAPI.get_moods_between(start, end)` (year heatmap browsing)
4. `core/app_info.py` with `APP_VERSION = "1.0"` (.desktop templates hardcode version today)
5. New config keys: `behavior.motion_enabled` (bool, default true),
   ghost-opacity persistence key (future), phase-2 `behavior.animated_media`

## Build order (approved)

1. SettingsPage (mostly wiring; backends ready)
2. CalendarPage (+ backend asks 1–3)
3. Motion polish pass across pages

## Out-of-scope v1 (do not design/build yet)

ghost-opacity persistence, capture-time scheduler, `audit_enabled`,
`one_photo_per_day`, `image_format` honoring, animated_media gating
