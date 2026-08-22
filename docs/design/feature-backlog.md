# Feature Backlog (Feature Scout research, Aug 2026)

Ranked by (user value × feasibility). Sequencing applies AFTER
Calendar + Settings pages ship.

## Top 10

| # | Feature | Pitch | Size | Backend |
|---|---|---|---|---|
| 1 | On This Day banner | Throwback photo from same date previous months/years on dashboard | S | ready |
| 2 | System tray icon | Streak tooltip + Capture action; foundation for notifications | S/M | ready (QSystemTrayIcon) |
| 3 | Mood trend mini-chart | Mood line/bar over 7/30 days next to existing distribution widget | S | ready (get_moods_since) |
| 4 | Streak freeze tokens | 1 forgiveness token protects streak for a missed day; retention mechanic proven in habit apps | S | small schema addition |
| 5 | Badges/milestones v1 | 7/30/100-day achievements from streak.py math | S | ready |
| 6 | Grid collage exporter | Month/year collage PNG export | M | new image-exporter module (Pillow/QPainter) |
| 7 | JSON/Markdown journal export | Portable data export | S | ready |
| 8 | "Wrapped" year-in-review | Shareable stat cards: captures, best streak, dominant mood, top month (Spotify Wrapped psychology) | M/L | stats ready; needs exporter (#6) |
| 9 | Slideshow playback mode | Fullscreen auto-play carousel w/ crossfade + shuffle ("movie of your life") | M | ready (reuse carousel widgets) |
| 10 | Reminders / nudges scheduler | Daily capture nudge at chosen time; loss-framed copy converts best | L | needs scheduler daemon + notification channel (depends on #2) |

Honorable mentions: tags/favorites via sidecar JSON extension (M),
Then-&-Now side-by-side compare (M).

## Quick wins (S + ready-now)

On This Day · basic tray · mood trend chart · streak freezes · badges v1 ·
JSON/Markdown export.

## Moonshots

- Face-aligned morph timelapse video (OpenCV landmarks → MP4)
- MP4 mash export, 1SE-style (ffmpeg dep)
- Encrypted zero-knowledge backup (AES-256-GCM passphrase zip)
- Multi-project timelines

## Dependencies

- Reminders ← tray notifications (#2) + scheduler daemon
- Wrapped ← collage exporter (#6); video variant ← ffmpeg
- Badges ← freeze-token schema decision first
- Global hotkey ← desktop-entry registration (exists) + PySide6-GlobalHotkeys (M)

## Recommended sequencing

1. **Wave 1 — Retention core:** On This Day → tray → mood chart → streak freeze
2. **Wave 2 — Output/share:** collage exporter → slideshow → Wrapped (ship before December)
3. **Wave 3 — Trust:** app lock (PIN) → encrypted backup/export (pairs with Settings)
4. **Wave 4 — New backend:** reminders daemon → global hotkey
5. **Moonshots last**
