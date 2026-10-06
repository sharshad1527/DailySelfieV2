# DailySelfie

A desktop app for taking one photo a day and keeping track of the days you
actually took one. Built with PySide6. No network calls anywhere — the only
inter-process communication is a local socket used to enforce a single
running dashboard.

What it does:

- **Daily capture** — a startup popup with a camera preview, optional timer,
  shutter, and a retake of the day's photo.
- **Streaks** — current and best run, plus the "you can still save it" state
  when today's photo is missing.
- **Calendar** — month grid of captures with day detail and charts.
- **Recap ("Wrapped")** — month and year recaps built from your own data:
  best shots, activity heatmaps, mood palette, streaks.
- **Mood and notes** — tag each photo with a mood and a text note.
- **Themes** — Material-3-derived light/dark themes with contrast levels,
  switchable from the CLI or the Settings page.
- **Quality advisory** — blurry/too-dark/too-bright frames are flagged before
  saving; advisory only, you can always save anyway.

## Requirements

- **Python 3.13** (the code targets 3.13; it uses `tomllib` from the stdlib, so
  3.11+ is the hard floor).
- A webcam or any camera OpenCV can open.
- **Windows or Linux.** macOS is not supported: `autostart/__init__.py` and
  `desktop_entry/__init__.py` raise `RuntimeError` for any OS that is not
  Linux or Windows. The capture and dashboard code has no macOS-specific
  paths, so the core may well run, but the lifecycle integration is not
  written for it.

There are no other prerequisites. The install command below runs on bare
system Python with no third-party packages installed — see *Why the installer
needs nothing*.

## Install

From the repository root:

```bash
python DailySelfie.py --install
```

On Windows, use the `py` launcher if `python` is not on your PATH:

```powershell
py DailySelfie.py --install
```

`--install` runs an interactive wizard that:

1. Shows the install plan and lets you edit it (directory, camera index,
   resolution, JPEG quality, desktop entry, autostart, theme mode/contrast).
2. Creates the directories and writes `config.toml`.
3. Creates a virtual environment and `pip install`s `requirements.txt` into it.
4. Creates a `dailyselfie` command-line wrapper.
5. Optionally registers the desktop entry and login autostart.

Afterwards, launch the dashboard with no arguments, or use the wrapper:

```bash
dailyselfie          # dashboard
dailyselfie --start-up   # the daily capture popup
```

### Why the installer needs nothing

`DailySelfie.py` deliberately defers its PySide6 import until after argparse,
and dispatches `--install`/`--uninstall`/autostart/desktop-entry flags before
any third-party module is touched. The config writer used during install
(`write_config_bootstrap`) emits TOML by hand rather than via `tomli-w`. So the
lifecycle commands work on a bare interpreter with an empty `site-packages`,
which is what makes bootstrapping from nothing possible.

## Lifecycle commands

All of these run before the venv exists and therefore work on bare Python.

| Command | Effect |
|---|---|
| `--install` | Interactive installation wizard |
| `--uninstall` | Remove the app; prompts separately for your photos |
| `--enable-autostart` | Launch at login (`~/.config/autostart/DailySelfie.desktop` on Linux, a `.cmd` in the Windows Startup folder) |
| `--disable-autostart` | Remove the autostart entry |
| `--create-desktop-entry` | Create the desktop/app launcher entry |
| `--delete-desktop-entry` | Delete it |

## Runtime and diagnostic commands

| Command | Effect |
|---|---|
| *(no args)* | Open the dashboard |
| `--start-up` | Open the daily capture popup (what autostart uses) |
| `--capture` | Take one photo headlessly and exit |
| `--allow-retake` | Overwrite today's existing photo |
| `--show-paths` | Print every resolved directory |
| `--list-cameras` | Scan for usable cameras and report which open |
| `--backfill-quality` | Score older photos for blur/brightness (headless) |
| `--tail-logs [N]` | Print the last N log entries (default 20) |

Capture overrides, used with `--capture`: `--camera-index N`, `--width PX`,
`--height PX`, `--quality 1-100`. Each falls back to the `config.toml` value.

Theme commands: `--show-themes` lists the available themes;
`--theme NAME`, `--theme-mode {dark,light}`, and
`--theme-contrast {standard,medium,high}` write the choice to `config.toml`.
They exit after applying unless `--start-up` is also given.

```bash
python DailySelfie.py --list-cameras
python DailySelfie.py --capture --camera-index 1 --quality 95
python DailySelfie.py --show-themes
python DailySelfie.py --theme coral --theme-mode dark
```

## Where your data lives

Defaults, resolved by `core/paths.py` and then adjusted by
`config.toml [installation]`:

| What | Linux | Windows |
|---|---|---|
| Config | `~/.config/DailySelfie/config.toml` | `%APPDATA%\DailySelfie\config.toml` |
| Data (index, audit, metadata, thumbs) | `~/.local/share/DailySelfie/data` | `%LOCALAPPDATA%\DailySelfie\data` |
| Photos | `~/Pictures` | `%USERPROFILE%\DailySelfie\Pictures` |
| Logs | `<data_dir>/logs` | `<data_dir>\logs` |
| venv | `<data_dir>/.venv` | `<data_dir>\.venv` |

Inside those:

- Photos are `photos_root/YYYY/MM/YYYY-MM-DD_HHMMSS.jpg`. Mood and notes live
  in a separate sidecar per capture: `data/metadata/<id>.json`.
- `data/index.db` is the SQLite index; `data/captures.jsonl` is the
  append-only audit log. A corrupt DB is quarantined as
  `index.db.corrupt-<stamp>` and rebuilt from the audit log.
- `data/thumbs/` caches downscaled JPEGs for the UI.
- `logs/dailyselfie.jsonl` and `logs/dailyselfie.error.jsonl` are structured
  JSONL logs.

`python DailySelfie.py --show-paths` prints the resolved values.

### Sandboxing and testing overrides

Every directory can be redirected with an environment variable. Env vars
always win over `config.toml`, which is what lets the test suite run entirely
inside a temp directory:

| Variable | Overrides |
|---|---|
| `DS_CONFIG_DIR` | config dir |
| `DS_DATA_DIR` | data dir |
| `DS_LOGS_DIR` | logs dir |
| `DS_PHOTOS_DIR` | photos root |
| `DS_VENV_DIR` | venv dir |
| `DS_DEV=1` / `DS_FORCE_LOCAL=1` | put everything under `.ds_dev/` in the repo |
| `DS_PHOTOS_FALLBACK` | Linux photos fallback when `DS_PHOTOS_DIR` is unset |

## Development

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install --group dev        # pytest-cov, pytest-qt, ruff (pip >= 25.1)
```

Run the tests from the repository root — `testpaths` is configured in
`pyproject.toml`, so no path argument is needed:

```bash
python -m pytest              # whole suite
python -m pytest tests/test_recap.py -k streak   # one file / one topic
python -m pytest --cov        # with a coverage report (floor: 40%)
ruff check .                  # lint
```

The suite needs neither Qt nor a camera nor network access; `conftest.py`
points every `DS_*` path at a per-test temp sandbox and asserts containment.
`pytest-qt` is available for future GUI tests but nothing requires it today.

### Layout

```
DailySelfie.py      CLI entry point and phase dispatcher (install -> config ->
                   lifecycle toggles -> runtime init -> command dispatch)
core/               Qt-free business logic — importable without PySide6
  paths.py          path resolution + DS_* overrides + sandbox guards
  config.py         config.toml load/write/validate
  index_api.py      public façade over the indexer
  indexer.py        SQLite schema, migrations, queries
  capture.py        capture_once, day-detection, quality gate
  camera.py         OpenCV camera enumeration and frame grabbing
  recap.py          highlights, recaps, quality backfill (Qt-free)
  streak.py         current/best streak maths
  thumbs.py         disk-backed thumbnail cache
  timeutils.py      local-date helpers (all day bucketing goes through here)
  installer.py      the --install wizard
gui/                PySide6 UI
  dashboard/        window, navigation rail, pages (dashboard/selfie/calendar/settings)
  startup/          the daily capture popup and its widgets
  theme/            theme model, controller, tokens, JSON theme files
  widgets/          shared widgets, motion, recap stage and cards
autostart/          login autostart backends (linux.py, windows.py)
desktop_entry/      .desktop / shortcut backends (linux.py, windows.py)
tests/              core-only pytest suite
docs/design/        decision-complete UI/UX specs for Settings, Calendar, motion
```

The split is the main architectural rule: `core/` never imports Qt, so the
data layer is testable headlessly. Qt imports inside `core/` are all lazy and
sit at the point of use.

## Design specs

`docs/design/` holds the UI/UX specs written before implementation — class
names, sizes, states, flows, and edge behaviours are fixed there, so read them
before changing a page. Start at
[docs/design/README.md](docs/design/README.md).
