# Motion System Spec (Squad D)

House motion language extracted from existing code. New pages MUST reuse
these tokens. Carousel & window animations are reference-only — never modify.

## Tokens (new module `gui/theme/motion_tokens.py`, mirrors theme_vars.py)

| Token | Value | Where used today |
|---|---|---|
| `duration_fast` | 150 ms | hover/leave lifts, close anims |
| `duration_base` | 200 ms | enters, toggles, transitions |
| `curve_enter` | QEasingCurve.OutCubic | all entrances |
| `curve_exit` | QEasingCurve.InCubic | exits |
| `stagger_interval` | 20 ms | month-load tile cascade (cap 160 ms) |
| `slide_distance` | 16 px | page transition offset |
| `press_alpha` | 0.12 | state-layer press fills |

Durations/curves are developer constants — NOT user config. Users get
`behavior.motion_enabled` only.

## Page transitions (nav rail switching)

Technique: **incoming-only child-wrapper transition** (RECOMMENDED after
comparison — safe in frameless translucent shell; never touches top-level
window; obeys all past Windows-bug lessons).

- Per-page one-time refactor: Page(QWidget) → `_motion_wrapper(QWidget)` owns
  real layout.
- On switch: `setCurrentIndex` instant; animate incoming wrapper:
  pos.x from `sign*16 → 0` + opacity effect 0→1, both 200ms OutCubic parallel.
  `sign = +1 if new_index > old_index else -1`.
- QGraphicsOpacityEffect attached to wrapper ONLY during flight, DETACHED in
  `finished` (`setGraphicsEffect(None)`) — steady state must be effect-free.
- Rapid clicks: retarget the single held animation pair, never queue.
- Initial page render unanimated. Gate everything on `is_motion_enabled()`.
- REJECTED: full-page QGraphicsOpacityEffect (kills Selfie camera perf;
  one-effect-per-widget limit), manual two-page pixmap composite (stale grabs,
  input dead, complexity).

## Component specs

### C1 Standardized card hover-lift (`LiftMixin`)
enter: pos.y −2px 150ms OutCubic · leave: back 150ms InCubic · press: snap to
baseline instantly · non-image cards bg swap surface_container_low→surface_
container (NavButton state-layer precedent) · image cards border
outline_variant→outline · custom-painted cards use press_alpha fill.
pos-animation ONLY — no per-frame shadows, no layout invalidation.

### C2 Calendar tiles
Month load per tile: opacity+pos.y (+6px→0) 200ms OutCubic, stagger
min(idx,8)×20ms via singleShot. Hover: paint-scale 1.00→1.02 center-origin
(hoverProgress float prop, NavButton fillProgress mechanism) + standard lift.
Press: snap 1.00 + 0.12 state layer in paintEvent. Today marker: fill
expansion progress 0.5→1.0 200ms OutCubic (clone of nav rail). Repaint scope:
update(tile.rect()) only; scale via painter.translate+scale, NOT QGraphicsScale.

### C3 Day detail overlay
Open: scrim opacity 0→0.5 (scrim token) 200ms OutCubic ∥ card paint-scale
0.92→1.00 + opacity 0→1 200ms OutCubic, both children of page container.
Close: scrim 0.5→0 ∥ card scale→0.96 fade-out 150ms InCubic; deleteLater on
finished. Scrim consumes clicks. Triggers: scrim click / Esc / ✕.

### C4 Settings rows
Toggle thumb pos.x: ON 200ms OutCubic, OFF 150ms InCubic; track color swaps
instantly at t=0 (color leads motion): unchecked surface_container_highest ↔
checked primary. Value commit label: +8px/fade-in 150ms OutCubic. Invalid
input shake ±4px ×3 @40ms Linear (optional). Row hover: 0.08 tint instant,
NO lift (rows ≠ cards).

## Reduced motion

Gate `behavior.motion_enabled` (default true; NEW config key — add to
DEFAULT_CONFIG behavior block + bool coercion in _validate_behavior).
Checked at trigger time; off = jump to end states (hover tints KEPT — state
feedback not motion). NEVER gated: flash hold, countdown ticks, toast lifetime.
Phase-2 separate key `behavior.animated_media` for GIF playback — do NOT ship
together.

## Performance rules (Windows lessons encoded)

1. NO graphics effects on top-level native windows (frameless +
   WA_TranslucentBackground shells stay effect-free); children only
   (ErrorToast shadow precedent error_popup.py:90–97, ghost layer selfie.py:242)
2. Detach transient effects in finished; steady state effect-free
3. Animate child geometry/pos only; never new window-level animation
4. Defer cosmetic swaps to finished, never mid-flight
5. Prefer startSystemMove/startSystemResize before manual fallbacks
6. Dirty-rect repaints: update(rect) with old∪new geometry union
7. Cost ladder: pos on child ≻ painted scalar prop ≻ subtree opacity effect ≻
   anything window-level. Never hold opacity effect across live-camera subtree
   beyond one transition
8. QRectF draw targets (white-line fix selfie_card.py:189–213); cache pixmaps
   per size, never rescale per frame
9. Stop-before-start retargeting; hold animation refs as members (GC guard);
   QTimer.singleShot for delayed steps
10. Never animate layouts (no invalidate()/adjustSize() per frame)

## Backend asks

1. `behavior.motion_enabled` bool default true (+ validation coercion)
2. Phase-2: `behavior.animated_media` bool default true (separate change)
