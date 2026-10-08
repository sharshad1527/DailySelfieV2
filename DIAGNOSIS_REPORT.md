# DIAG-WIN Report — `python DailySelfie.py --install` fails on Windows ("some model error")

Branch `dashboard`, diagnosed 2026-08-26. Source changes made: **only** `DailySelfie.py`,
`core/config.py`, `core/spinner.py` (minimal guards; details in §4). All other dirty files in
the worktree are pre-existing Wave-R2 work, untouched.

---

## (a) Root cause(s), ranked

### RC1 — CONFIRMED ROOT CAUSE: PySide6 imported before `--install` is handled
**Evidence:** `DailySelfie.py:139` (pre-fix): `from PySide6.QtWidgets import QApplication`
executed unconditionally at the top of `main()` — **before** argparse parses anything and
**before** the `--install` branch (old line 200). On a fresh machine with zero third-party
packages this raises immediately:

```
ModuleNotFoundError: No module named 'PySide6'
```

**Reproduced locally** (bare `python3 -m venv --without-pip` interpreter running
`DailySelfie.py --install`):

```
ModuleNotFoundError: No module named 'PySide6'
!!! CRITICAL CRASH LOGGED !!!        <- global_exception_hook (core/logging.py:197) double-prints
```

The user's "**model** error" is almost certainly "**module** error"
(`No module named ...`) heard/paraphrased. Compounding confusion: the custom excepthook
(`core/logging.py:214-215`) prints the traceback **twice** plus a scary banner.

This makes self-install **impossible by construction**: deps live only in the venv, but the
installer demanded PySide6 from the *system* python before it could create that venv.

### RC2 — Same class of bug, latent: unguarded `tomli` fallback
`core/config.py:28-31` (pre-fix): on Python < 3.11 the `except ModuleNotFoundError:
import tomli` itself raises an *uncaught* `ModuleNotFoundError: No module named 'tomli'` at
import time — even earlier than RC1. Most users have 3.11+, so RC1 fires first, but this is
the same fresh-machine killer one version earlier.

### RC3 — Post-install steps run under the WRONG interpreter (Windows-specific fallout)
After `ensure_venv()` succeeds, `core/installer.py:321` (`set_desktop_entry(True)`) and
`:333` (`set_autostart(True)`) execute **in-process**, i.e. under the *system* python where:
- `desktop_entry/windows.py:59 import pylnk3` → ImportError → RuntimeError → caught → prints
  `"Failed To Create Entry: ..."` → **desktop shortcut silently never created on Windows**
  (pylnk3 was installed into the *venv* by pip, but the code needing it doesn't run there).
- `autostart_manager.py:60` / `desktop_entry_manager.py:59` call `write_config`, which hard-
  raises when `tomli_w` is absent (`core/config.py:278-279`) → `"Autostart failed:
  tomli-w is required to write config.toml"` → flag never persisted.

So even post-RC1-fix, Windows install "completes" with broken shortcut + broken autostart.

### RC4 — cp1252 encoding crash mid-install (redirected output only)
`core/spinner.py:15` wrote braille frames (`⠋⠙⠹…`) to stdout. Real Windows consoles are
UTF-8 (PEP 528), but **piped/redirected** output uses the ANSI codepage →
`UnicodeEncodeError: 'charmap' codec can't encode character '\u280b'` during
"Setting up virtual environment". Also `core/venv_helper.py:70,95` use
`subprocess.run(text=True)` without `encoding=` → pip's UTF-8 stderr decoded as cp1252 can
raise `UnicodeDecodeError` on failure reporting.

### Ruled out (checked, not the cause)
- **Windows Store Python stub**: prints "Python was not found…" / opens Store; different
  symptom than reported. Not detected/handled anywhere in the repo (worth documenting).
- **pylnk3 at module level**: it isn't — lazily imported inside
  `desktop_entry/windows.py:59`. Safe pre-venv.
- **cv2 at module level**: all deferred (`core/capture.py:231`, `core/camera.py:28`;
  only `gui/startup/camera/preview.py:5` imports eagerly but is GUI-only).
- **Qt platform-plugin error** ("no Qt platform plugin could be initialized"): requires
  PySide6 present; contradicts fresh-machine scenario.
- **Pre-venv module-level chain is otherwise stdlib-only** (verified by reading every file):
  `core.paths`, `core.config`, `core.logging`, `core.index_api`(+indexer/metadata/locks/
  storage), `autostart/__init__`, `desktop_entry/__init__`, `core.capture` — all pure
  stdlib; OS backends lazily dispatched via `platform.system()`.
- Path handling: all subprocesses use list args (spaces-safe); `.bat` quoting OK; default
  `%LOCALAPPDATA%\DailySelfie` is short (long-path N/A); venv uses `Scripts/python.exe`
  correctly (`core/venv_helper.py:37-39`); `EnvBuilder(with_pip=True)` semantics fine
  (symlinks irrelevant on Windows).

## Pre-fix import map on a fresh machine (`python DailySelfie.py --install`)

```
DailySelfie.py (module level)
├── os, argparse, sys, pathlib, traceback            [stdlib ✓]
├── core.paths                                        [stdlib ✓]
├── core.config      → tomllib/tomli ⚠ RC2 (py<3.11) [tomli_w guarded → None ✓]
├── core.logging                                      [stdlib ✓]
├── core.index_api → indexer/metadata/locks/storage   [stdlib ✓]
├── core.autostart_manager → autostart/__init__       [lazy OS backend ✓]
├── core.desktop_entry_manager → desktop_entry/__init__[lazy OS backend ✓]
└── core.capture                                      [cv2 deferred ✓]
main():
├── sys.excepthook = global_exception_hook            [✓]
└── from PySide6.QtWidgets import QApplication        ← 💥 RC1 dies HERE (line 139)
    (argparse + --install branch at line 200 never reached)
```

## (b) Fix plan for a TRUE one-command Windows install

Order of operations (target architecture):

1. **Phase 0 — stdlib-only bootstrap (DONE in this diff):** defer
   `QApplication` creation until after argparse and skip it for the six lifecycle flags
   (`--install/--uninstall/--enable-autostart/--disable-autostart/
   --create-desktop-entry/--delete-desktop-entry`). Verified: bare-interpreter
   `--install` now boots the full wizard, creates dirs, writes config (dep-free
   `write_config_bootstrap`), builds venv, pip-installs requirements, writes wrapper,
   exits 0 — reproduced end-to-end on Linux incl. opencv+PySide6+pytest install.
2. **Phase 1 — re-exec post-install steps through the VENV python (recommended next PR):**
   replace in-process `set_desktop_entry(True)` / `set_autostart(True)`
   (`core/installer.py:318-337`) with subprocesses using the freshly built interpreter:
   ```python
   subprocess.run([str(py), str(project_root / "DailySelfie.py"),
                   "--create-desktop-entry"], check=False)
   ```
   so `pylnk3` and `tomli-w` resolve from the venv. Kills RC3 entirely.
3. **Phase 2 — make config persistence dep-free everywhere:** switch
   `autostart_manager/desktop_entry_manager/theme_controller` from `write_config`
   (requires `tomli-w`) to the existing dependency-free `write_config_bootstrap`
   writer. Removes the last "needs third-party pkg outside venv" trap.
4. **Phase 3 — Windows entry-point hygiene:** document/recommend the `py` launcher
   (`py DailySelfie.py --install`) and add a friendly check when `sys.executable` is
   under `WindowsApps` (Store stub alias) telling the user to install real Python.
5. **Phase 4 — hardening:** pass `encoding="utf-8", errors="replace"` to the two
   `subprocess.run(..., text=True)` calls in `core/venv_helper.py`; consider
   `errors="replace"` printing in `global_exception_hook`.

Remaining known cosmetic gaps (non-blocking): `create_cli_wrapper` writes the `.bat` with
leading indentation (cmd tolerates it); `.cmd`/`.bat` files written as UTF-8 will mojibake
if the user profile path contains non-ANSI characters (write with locale encoding or ASCII-
safe fallback); duplicate `import platform` at `core/installer.py:21,24`.

## (c) Quick wins IMPLEMENTED now (cross-platform, minimal)

| File | Change |
|---|---|
| `DailySelfie.py` | QApplication creation moved below argparse, skipped for lifecycle-only flags → `--install` (and friends) run on bare Python. **RC1 fixed.** |
| `core/config.py` | `tomllib`/`tomli` double-guard; clear `RuntimeError("Python 3.11+ … pip install tomli")` instead of cryptic crash. **RC2 fixed.** |
| `core/spinner.py` | ASCII frames (`\|/-\`) when stdout encoding is non-UTF → no `UnicodeEncodeError` under cp1252 redirect. **RC4 fixed.** |

Not implemented (per mandate, described above): RC3 re-exec, RC4 subprocess encodings.

## Verification log

```
BEFORE  bare-python --install  -> ModuleNotFoundError: No module named 'PySide6'
AFTER   bare-python --install  -> full wizard; answers scripted ->
                                  venv created @ <install>/venv, pip upgrade +
                                  opencv/numpy/tomli-w/PySide6/pytest installed,
                                  wrapper created, EXIT=0
AFTER   venv python -c "import cv2, PySide6, numpy"  -> deps-OK
AFTER   pytest -q -> 99 passed (baseline was also 99 passed)
cp1252  PYTHONIOENCODING=cp1252 Spinner._frames -> '|/-\\' (fallback OK)
```
