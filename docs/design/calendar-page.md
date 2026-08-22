# CalendarPage — Design Spec (Squads A + B)

Decision-complete. Squad A = grid/detail UX. Squad B = data-viz layer.
Coordinate via named hooks: `DayTile.set_mood()`, `.set_in_streak()`,
`.set_today_state()`, `.set_future()`.

## Wiring (dashboard.py)

- `self._selfie_page.photoSaved.connect(self._calendar_page.refresh)`
- `self._calendar_page.takeSelfieRequested.connect(self._switch_to_selfie_tab)`
- Page loads month lazily in `showEvent` (`_load_month(today.y, today.m)`).

## Month view

```
┌─ CalendarSurface (surface_container_highest, radius 12) ───────────────┐
│  ◀   August 2026   ▶                              [ Today ]           │ MonthHeaderBar
│   Mon  Tue  Wed  Thu  Fri  Sat  Sun                                    │ WeekdayRow
│ ┌────┬────┬────┬────┬────┬────┬────┐                                   │
│ │ 27░│ 28░│ 29░│ 30░│ 31░│  1 │ ╔2═╗│  ← DayTile ×42 (6×7 grid)        │
│ ├────┼────┼────┼────┼────┼────┼────┤     ░=other-month dim             │
│ │ ▓▓☺│ ▓▓ │    │ ▓▓☺│    │    │ ▓▓ │  ╚══╝=today ring                  │
│ └────┴────┴────┴────┴────┴────┴────┘  ☺=mood dot [Squad B]            │
│        "No selfies captured this month." (conditional hint)            │
└─────────────────────────────────────────────────────────────────────────┘
```

Tile states: captured (rounded thumb crop-fill r10 + day-number chip),
empty-current-month, other-month (dimmed, non-clickable), today (2px primary
ring painted), hover → `surface_container_high`, BROKEN (missing/corrupt file:
dashed outline_variant border + notes.svg glyph, still clickable for delete).

## Components (all in gui/dashboard/pages/calendar.py unless noted)

| Class | Extends | Purpose | Signals |
|---|---|---|---|
| `CalendarPage` | QWidget | root; state machine view/detail; owns `_current_year/_month`, `_items_by_day`, `_selected_eid` | `takeSelfieRequested()`, `photoDeleted()`, `dataChanged()` |
| `CalendarSurface` | QFrame | card container | — |
| `MonthHeaderBar` | QWidget | prev/next/today + title | `prevClicked() nextClicked() todayClicked()` |
| `WeekdayRow` | QWidget | Mon–Sun labels | — |
| `MonthGrid` | QWidget | QGridLayout 6×7 sp(8); keyboard focus index | `dayClicked(QDate)` |
| `DayTile` | QFrame | day cell; TileState enum {EMPTY_MONTH_DAY, OTHER_MONTH, TODAY, CAPTURED, BROKEN}; holds captures list | `clicked(QDate)` |
| `ThumbLabel` | QLabel | scaled rounded thumb (copy TodaySelfieCard._update_selfie_image pattern) | — |
| `EmptyStateView` | QWidget | zero-photos-ever full-surface state w/ CTA (style = TakeSelfieButton verbatim) | `takeSelfieRequested()` |
| `NoCaptureHint` | QLabel | hint line when month empty | — |
| `DetailScrim` | QWidget | page-child overlay painting scrim @55% alpha; click-outside closes | `closeRequested()` |
| `DetailCard` | QFrame | centered ≤720×560 min420×480; VIEW/EDIT modes | `prevDay() nextDay() editRequested() saved(eid) deleteConfirmed(eid) closeRequested()` |
| `MoodPickerRow` | QWidget | 5 mood GIF toggles (reuse MOOD_GIF_MAP from dashboard.py), selected = primary ring | `moodSelected(str)` |
| `ConfirmDeleteDialog` | QDialog | frameless styled like ErrorToast container (#1A1A1A r14 left-border 4px error #EF4444): "Delete selfie from {date}?" Cancel/Delete | std accepted/rejected |

Nav icon buttons: `NavIconButton` 36×36 r18 transparent→surface_container_high
hover, icons via `_create_colored_icon`. New SVGs needed:
`chevron_left.svg chevron_right.svg close.svg edit.svg` (24×24 flat single-path,
recolorable solid fill). Reuse existing: selfie.svg, notes.svg, save_clock.svg,
aspect_ratio.svg, delete.svg.

## Day detail overlay (scrim + DetailCard child of CalendarPage)

Header: ‹ date-title ✕ · large photo r14 · prev/next **captured-day** arrows
(wrap across months by auto-loading adjacent month; stop at empty boundary)
· separator (outline_variant 1px) · mood row + note (truncate >35 chars with …,
matching TodaySelfieInfoBox) · meta row (time · resolution) · bottom: Edit /
Delete.
Edit sub-state swaps card body in place: MoodPickerRow + QTextEdit
("Add a note…" placeholder) + Cancel/Save → `api.update_meta(eid, {...})`.
Delete: ConfirmDeleteDialog → on accept delete_path + record_deletion
(pattern of TodaySelfieInfoBox._on_delete_clicked); failure → ErrorToast;
success → close detail, reload month, emit photoDeleted.
Close via Esc / ✕ / scrim click. Re-center on page resizeEvent.

## Interaction flows

1. Rail click idx 2 → showEvent lazy load; refresh on photoSaved.
2. ◀▶ = addMonths(±1) + reload; Today jumps to current month. Rapid clicks OK
   (generation counter cancels stale thumb loads).
3. Click tile / Tab+Arrows+Enter keyboard nav → open detail.
4. Edit → save via update_meta → back to VIEW, tile mood hook refreshed,
   dataChanged emitted.
5. Zero-photos CTA → takeSelfieRequested → selfie tab.

## Data-viz layer (Squad B)

Shared types module `gui/dashboard/widgets/calendar_analytics/viz_types.py`:

```python
MOOD_COLORS = {"Great": "#178A38", "Good": "#00848C", "Neutral": "#8A7500",
               "Bad": "#A34F00", "Awful": "#A62D12"}
class StreakState(Enum): NONE, CURRENT, BEST_ONLY, CURRENT_AND_BEST
class TodayState(Enum): NOT_TODAY, IN_STREAK, AT_RISK
@dataclass
class DayDecor: mood; streak: StreakState; today: TodayState; future: bool; capture_count: int
```

- Controller computes decorations ONCE per year from FULL history
  (`calculate_streaks` over global dates — never month slices; Dec→Jan best
  runs ring both grids).
- At-risk today (no photo today, current>0): dashed tertiary ring + hollow
  center + tooltip "Take a photo today to keep your N-day streak"; header chip
  appends "(at risk)" — language parity with dashboard.py streak widget.
- New record live (current > best): celebration icon beside chip; tiles show
  solid tertiary only.
- Mood dots: `paint_mood_dot(painter, rect, hex, outline_color, d=6)` free
  function; mandatory 1px `outline` halo; legend strip (MoodLegend QFrame,
  hollow circle = no-mood).
- Streak rings: `paint_streak_ring(painter, rect, state, tertiary, outline,
  inset=2)` — CURRENT solid tertiary, BEST_ONLY dotted outline, BOTH both.
- YearHeatmapStrip: ONE custom-painted QWidget (~371 rects single paintEvent
  pass <2ms; NO widget-per-tile). set_year_data(year, activity dict, moods
  dict, today). Hover column highlight (setMouseTracking), click emits
  `weekClicked(iso_week, anchor_date)` → jump to month of that ISO week's
  Thursday. Intensity fills = rgba(primary, .35/.60/1.0); empty =
  surface_container_lowest; hovered week border outline_variant.
- Stats chips row: photos this month, moods logged, current/best streak
  ("New record!" accent tertiary, mirrors StreakSummaryWidget).
- Today pulse: QTimer 20fps invalidating ONLY today-tile rect, opacity sine
  0.45→1.0 over 1600ms; stop in hideEvent. Respect motion_enabled gate (see
  motion-system.md).
- Theme switch mid-session: themeChanged → heatmap.update() + push fresh
  decors. Fixed MOOD_COLORS hexes intentionally theme-independent.

## Backend notes

- ✅ Exists: get_api, list_month(y,m) (merged dicts id/ts/path/w/h/resolution/
  mood/notes/action/created_at/edited_at), get_item, update_meta,
  record_deletion, delete_path, last_image_for_date, get_last_photo (zero-user
  detection).
- ts is UTC string → convert local: `datetime.fromisoformat(ts.replace("Z",
  "+00:00")).astimezone()` else late-night captures land in wrong bucket.
- No thumbnail pipeline exists: load scaled QPixmap per tile lazily w/
  generation-counter cancellation (~31 images/month fine).
- Multiple captures/day: use LAST row for tile/detail; keep full list on tile.
- ASKS (implement with this page):
  1. Promote public `IndexAPI.get_all_capture_dates()`; migrate dashboard.py
     `_ensure_indexer()` reach-throughs.
  2. New `IndexAPI.get_capture_counts_by_date(year) -> dict[str,int]`
     (SQL substr(ts,1,10) GROUP BY, action='capture').
  3. Optional `get_moods_between(start,end)` for past-year browsing.
  4. Optional `index_changed` callback from record_capture/record_deletion.

## Edge cases

Multiple captures/day (last wins) · missing file → BROKEN tile · corrupt image
(QPixmap.isNull) → BROKEN · zero-capture month → hint line · brand-new user →
EmptyStateView · today-in-other-month → no marker · future days → dimmed inert
non-focusable · other-month tiles visible dim non-clickable · resize while
detail open → re-center · rapid paging → generation counter · list_month throw
→ empty + ErrorToast · note >35 chars truncate · deletions self-correct
(indexer filters action='capture') · empty DB → guard intensity max(count,1) ·
partial ISO edge weeks render partial columns · malformed dates skipped
(streak.py precedent).

## Theme keys used (all verified in schemes)

background, surface_container_highest, surface_container_low,
surface_container_high, surface_container_lowest, primary, on_surface,
on_surface_variant, outline, outline_variant, scrim (rgba .55 detail overlay /
.40 future dim), error, error_container, on_error_container, on_primary,
tertiary.
