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
import os
import types
from pathlib import Path

import pytest

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


# NOTE: this suite used to install a `datetime` subclass shim so call sites
# resolving "local" implicitly (bare `.astimezone()` / `.now()`) could be
# retargeted on Windows. Every such site now goes through core.timeutils'
# explicit-tz helpers, so the shim is gone and set_tz() only pins the
# module-level override. If a future change reintroduces an implicit-local call
# site, fix the call site rather than restoring the shim -- patching datetime
# across every loaded module is a blunt instrument that silently affected
# unrelated code.



@pytest.fixture()
def set_tz(monkeypatch):
    """Factory fixture: set_tz('Asia/Kolkata') pins the core layer's tz.

    The old implementation flipped the process-global TZ (os.environ['TZ'] +
    time.tzset), which is POSIX-only — every test using this fixture silently
    skipped on windows-latest, so ~25 tests never ran there. core.timeutils
    now takes an explicit zoneinfo tz, so we point its module-level default
    override at the requested zone. Every call site that needs "local" resolves
    it through timeutils, so nothing else has to be patched.

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
