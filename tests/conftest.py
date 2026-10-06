"""
Shared fixtures for the DailySelfie core-only test suite.

Guarantees:
- Zero real-HOME access: every test runs with DS_* env vars pointed at a
  pytest-managed temp sandbox, and core.paths.ensure_sandbox/assert_sandboxed
  is enforced (session start + per-test).
- No network, no Qt, no camera.
"""
from __future__ import annotations

import copy
import datetime as _datetime_module
import os
import sys
import types
from pathlib import Path

import pytest

# Captured at import time, before any shim is installed. Re-reading
# `datetime.datetime` later would resolve to the shim itself.
_DATETIME_CLASS = _datetime_module.datetime

DS_ENV_KEYS = {
    "config_dir": "DS_CONFIG_DIR",
    "data_dir": "DS_DATA_DIR",
    "logs_dir": "DS_LOGS_DIR",
    "photos_root": "DS_PHOTOS_DIR",
    "venv_dir": "DS_VENV_DIR",
}


def _ds_env_for(root: Path) -> dict:
    return {
        "DS_CONFIG_DIR": str(root / "config"),
        "DS_DATA_DIR": str(root / "data"),
        "DS_LOGS_DIR": str(root / "logs"),
        "DS_PHOTOS_DIR": str(root / "photos"),
        "DS_VENV_DIR": str(root / "venv"),
    }


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "core_only: fast, offline, sandboxed unit tests over the core data layer",
    )


@pytest.fixture(scope="session", autouse=True)
def _session_sandbox(tmp_path_factory):
    """Session-start containment guard: DS_* mode on, then assert_sandboxed.

    Fails the whole session immediately if any resolved app dir escapes the
    pytest sandbox root (i.e. would touch the real HOME).
    """
    from core import paths

    root = tmp_path_factory.mktemp("ds-session-sandbox")
    env = _ds_env_for(root)
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        checked = paths.ensure_sandbox(paths_obj=paths.get_app_paths(), root=str(root), strict=True)
        assert checked is not None, "sandbox guard did not run"
        for attr in ("config_dir", "data_dir", "logs_dir", "photos_root", "venv_dir"):
            assert root in Path(getattr(checked, attr)).parents or getattr(checked, attr) == root / attr, (
                f"{attr} escaped session sandbox: {getattr(checked, attr)}"
            )
        yield root
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture(autouse=True)
def ds_sandbox(tmp_path, monkeypatch):
    """Per-test DS_* env override + ensure_sandbox containment check.

    Returns the checked AppPaths (all dirs under tmp_path/sandbox). Also resets
    the index_api singleton so IndexAPI instances never leak across tests.
    """
    from core import paths
    import core.index_api as index_api_module

    root = tmp_path / "ds-sandbox"
    for attr, var in DS_ENV_KEYS.items():
        monkeypatch.setenv(var, str(root / attr))
    monkeypatch.setattr(index_api_module, "_api_singleton", None)

    app_paths = paths.ensure_sandbox(root=str(root))
    assert app_paths is not None, "per-test sandbox guard did not run"
    return app_paths


@pytest.fixture()
def app_paths(ds_sandbox):
    """Plain namespace view of the sandboxed paths for capture/storage calls."""
    return types.SimpleNamespace(
        config_dir=ds_sandbox.config_dir,
        data_dir=ds_sandbox.data_dir,
        logs_dir=ds_sandbox.logs_dir,
        photos_root=ds_sandbox.photos_root,
        venv_dir=ds_sandbox.venv_dir,
    )


def _is_datetime_binding(value) -> bool:
    """True for stdlib `datetime` and for a shim we installed earlier.

    A test may call set_tz() more than once; the previous shim is what the
    modules are holding then, so re-patching has to recognise it too.
    """
    return value is _DATETIME_CLASS or getattr(value, "_ds_tz_shim", False) is True


def _patch_tz_bindings(monkeypatch, shim) -> None:
    """Install `shim` everywhere a stdlib `datetime` reference is visible.

    Both import-time bindings (`from datetime import datetime`) and the
    `datetime` module attribute itself (for a `from datetime import datetime`
    executed inside a function body at call time) need the shim, otherwise a
    stray naive `astimezone()` still reads the machine's zone.
    """
    # `monkeypatch.setattr(datetime, "datetime", shim)` makes every *future*
    # `from datetime import datetime` (including ones executed inside a
    # function body at call time) pick up the shim.
    monkeypatch.setattr(_datetime_module, "datetime", shim)
    for mod in list(sys.modules.values()):
        if mod is None or mod is _datetime_module:
            continue
        if not _is_datetime_binding(getattr(mod, "datetime", None)):
            continue
        try:
            monkeypatch.setattr(mod, "datetime", shim)
        except (AttributeError, TypeError):  # pragma: no cover - exotic modules
            pass


def _datetime_shim(tz):
    """A datetime subclass whose *implicit* local time is `tz`.

    core.timeutils takes an explicit tz, which is the real fix and covers
    every day-bucketing read. A handful of call sites outside that contract
    still resolve "local" implicitly via `datetime.astimezone()` /
    `datetime.now()` — core/index_api.py's `_local_hour` and
    `get_capture_times_between` window bounds, plus the `naive.astimezone()`
    helpers inside the test modules themselves. Those cannot see an explicit
    tz and cannot be retargeted by changing the process TZ on Windows.

    So while a `set_tz` test runs, `datetime` is temporarily swapped for a
    subclass whose no-argument conversions resolve to the requested zone.
    Anything that passes an explicit tz behaves exactly like stdlib
    datetime, and monkeypatch restores every binding at teardown.
    """
    from datetime import datetime as _dt

    def _rebuild(cls, value):
        """Copy a datetime into the shim class (datetime is immutable)."""
        return cls(
            value.year, value.month, value.day,
            value.hour, value.minute, value.second, value.microsecond,
            tzinfo=value.tzinfo, fold=value.fold,
        )

    class _TzLocalDatetime(_dt):
        def astimezone(self, t=None):
            if t is None and self.tzinfo is None:
                # stdlib reads a naive value as machine-local; here the test
                # zone *is* the local zone, so pin it instead of converting.
                return _rebuild(type(self), self.replace(tzinfo=tz))
            return _rebuild(
                type(self), _dt.astimezone(self, t if t is not None else tz)
            )

        @classmethod
        def now(cls, t=None):
            return _rebuild(cls, _dt.now(t if t is not None else tz))

        @classmethod
        def fromisoformat(cls, s):
            return _rebuild(cls, _dt.fromisoformat(s))

        @classmethod
        def strptime(cls, s, fmt):
            return _rebuild(cls, _dt.strptime(s, fmt))

    # Marker so _patch_tz_bindings can re-patch over an earlier shim.
    _TzLocalDatetime._ds_tz_shim = True
    return _TzLocalDatetime


@pytest.fixture()
def set_tz(monkeypatch):
    """Factory fixture: set_tz('Asia/Kolkata') pins the core layer's tz.

    The old implementation flipped the process-global TZ (os.environ['TZ'] +
    time.tzset), which is POSIX-only — every test using this fixture silently
    skipped on windows-latest, so ~25 tests never ran there. core.timeutils
    now takes an explicit zoneinfo tz, so we point its module-level default
    override at the requested zone, and retarget the remaining implicit-local
    `datetime` call sites via a temporary class shim (see _datetime_shim).

    os.environ['TZ'] and time.tzset() are deliberately never touched: TZ
    tests must mean the same thing on Windows and Linux, and the process-wide
    switch leaked state across tests. monkeypatch undoes everything at
    teardown, so tests stay order-independent.
    """
    from core import timeutils

    def _set(zone):
        # Resolve eagerly so an unknown zone fails the test loudly rather than
        # silently leaving the previous zone in place.
        resolved = timeutils.get_tz(zone)
        monkeypatch.setattr(timeutils, "_local_tz_override", resolved, raising=True)
        _patch_tz_bindings(monkeypatch, _datetime_shim(resolved))
        return resolved

    _set("UTC")  # deterministic baseline before the test picks its own zone

    yield _set

    timeutils.clear_local_tz()


@pytest.fixture()
def make_config(tmp_path):
    """Factory writing a valid config.toml into the tmp sandbox.

    Returns a callable (overrides=None, name="config.toml") -> Path.
    `overrides` is deep-merged onto DEFAULT_CONFIG before writing.
    """
    from core.config import DEFAULT_CONFIG, write_config

    def _make(overrides=None, name="config.toml"):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        if overrides:

            def merge(base, over):
                for k, v in over.items():
                    if isinstance(v, dict) and isinstance(base.get(k), dict):
                        merge(base[k], v)
                    else:
                        base[k] = v

            merge(cfg, overrides)
        path = tmp_path / name
        write_config(path, cfg)
        return path

    return _make
