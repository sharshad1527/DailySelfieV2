"""
Reduced-motion gate: behavior.motion_enabled resolution, the documented
default when config is absent/corrupt, config round-trip, and the cached
config-path resolver.

`gui.theme.motion_tokens` imports PySide6.QtCore for the QEasingCurve token
constants only — no QApplication, no widget, no display is created here, so
these stay runnable in the sandboxed core suite.
"""
import copy
import os

import pytest

from core.config import DEFAULT_CONFIG, load_config, write_config
from gui.theme import motion_tokens as mt

pytestmark = pytest.mark.core_only  # fast/offline, sandboxed data-layer tests


# -------------------------------------------------------------
# helpers
# -------------------------------------------------------------
def _write_config(config_dir, motion_enabled):
    """Write a valid config.toml into config_dir; return its path."""
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["behavior"]["motion_enabled"] = motion_enabled
    path = config_dir / "config.toml"
    write_config(path, cfg)
    return path


def _touch_newer(path, bump_ns=2_000_000_000):
    """Force a distinguishable mtime (filesystems can be coarse-grained)."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + bump_ns))


@pytest.fixture()
def motion_gate(tmp_path, monkeypatch):
    """Point the gate at a fresh config dir and drop any cached state."""
    config_dir = tmp_path / "gate-config"
    monkeypatch.setenv("DS_CONFIG_DIR", str(config_dir))
    mt.invalidate_gate_cache()
    yield config_dir
    mt.invalidate_gate_cache()


# -------------------------------------------------------------
# explicit-cfg form (no disk, no cache)
# -------------------------------------------------------------
def test_explicit_cfg_returns_config_value():
    assert mt.is_motion_enabled({"behavior": {"motion_enabled": False}}) is False
    assert mt.is_motion_enabled({"behavior": {"motion_enabled": True}}) is True


def test_explicit_cfg_defaults_true_when_key_or_section_missing():
    assert mt.is_motion_enabled({"behavior": {}}) is True
    assert mt.is_motion_enabled({}) is True


@pytest.mark.parametrize("raw,expected", [
    (True, True), (False, False),
    ("true", True), ("on", True), ("1", True), ("yes", True),
    ("false", False), ("off", False), ("0", False), ("no", False),
    ("  FALSE  ", False), (1, True), (0, False),
])
def test_explicit_cfg_coerces_like_the_config_validator(raw, expected):
    assert mt.is_motion_enabled({"behavior": {"motion_enabled": raw}}) is expected


def test_non_dict_cfg_falls_back_to_default():
    assert mt.is_motion_enabled(["not", "a", "dict"]) is True


# -------------------------------------------------------------
# on-disk form
# -------------------------------------------------------------
def test_defaults_true_when_config_absent_and_creates_nothing(motion_gate):
    assert mt.is_motion_enabled() is True
    assert motion_gate.exists() is False  # the gate must never write config
    assert (motion_gate / "config.toml").exists() is False


def test_defaults_true_when_config_corrupt(motion_gate):
    motion_gate.mkdir(parents=True, exist_ok=True)
    (motion_gate / "config.toml").write_text("[behavior\nbroken = ", encoding="utf-8")
    assert mt.is_motion_enabled() is True  # unreadable config -> animations on


def test_reads_value_from_disk(motion_gate):
    _write_config(motion_gate, False)
    assert mt.is_motion_enabled() is False

    _write_config(motion_gate, True)
    _touch_newer(motion_gate / "config.toml")
    assert mt.is_motion_enabled() is True


def test_cache_is_invalidated_when_file_changes(motion_gate):
    path = _write_config(motion_gate, True)
    assert mt.is_motion_enabled() is True

    _write_config(motion_gate, False)
    _touch_newer(path)
    assert mt.is_motion_enabled() is False


def test_absent_file_created_later_is_picked_up(motion_gate):
    # Missing files are deliberately not cached, so a config.toml written after
    # the first call (fresh install / first-run bootstrap) must take effect.
    assert mt.is_motion_enabled() is True
    _write_config(motion_gate, False)
    assert mt.is_motion_enabled() is False


# -------------------------------------------------------------
# config-path resolution (regression: path was pinned for the process)
# -------------------------------------------------------------
def test_config_path_comes_from_the_canonical_accessor(motion_gate):
    from core.paths import get_app_paths

    expected = get_app_paths("DailySelfie", ensure=False).config_dir / "config.toml"
    assert mt._default_config_path() == expected


def test_config_path_is_resolved_again_after_the_location_moves(
    tmp_path, monkeypatch, motion_gate
):
    """The regression this file exists for: the path must never be pinned.

    Moving the config location (Settings' "reconnect to rescued data" flow)
    used to leave the gate reading the abandoned config.toml forever, so the
    motion setting silently kept the OLD value for the rest of the session.
    """
    old_dir = motion_gate
    _write_config(old_dir, False)
    assert mt.is_motion_enabled() is False
    assert mt._default_config_path() == old_dir / "config.toml"

    new_dir = tmp_path / "rescued-config"
    _write_config(new_dir, True)
    monkeypatch.setenv("DS_CONFIG_DIR", str(new_dir))

    assert mt._default_config_path() == new_dir / "config.toml"
    assert mt.is_motion_enabled() is True  # now gates on the NEW config


def test_config_move_is_seen_within_one_call(motion_gate, monkeypatch):
    _write_config(motion_gate, True)
    assert mt.is_motion_enabled() is True

    other = motion_gate.parent / "second-config"
    _write_config(other, False)
    monkeypatch.setenv("DS_CONFIG_DIR", str(other))
    assert mt.is_motion_enabled() is False


def test_unchanged_environment_does_not_reresolve_the_path(
    motion_gate, monkeypatch
):
    """Hot-path guard: hover/callers must not re-run path resolution.

    is_motion_enabled() is called from every hover enter/leave, so the cached
    path may only be recomputed when the environment signature actually moves.
    """
    import core.paths as paths_module

    calls = []
    real = paths_module.get_app_paths

    def counting(*args, **kwargs):
        calls.append(kwargs.get("ensure"))
        return real(*args, **kwargs)

    monkeypatch.setattr(paths_module, "get_app_paths", counting)

    mt._default_config_path()
    mt._default_config_path()
    for _ in range(50):
        mt.is_motion_enabled()
    assert len(calls) == 1

    monkeypatch.setenv("DS_CONFIG_DIR", str(motion_gate.parent / "elsewhere"))
    mt._default_config_path()
    assert len(calls) == 2


def test_invalidate_gate_cache_forces_a_fresh_resolve(motion_gate):
    first = mt._default_config_path()
    mt.invalidate_gate_cache()
    assert mt._default_config_path() == first  # same location, cache dropped
    assert mt._config_path_env is not None


def test_dev_mode_env_var_is_part_of_the_signature(motion_gate, monkeypatch):
    """DS_DEV (project-local .ds_dev/config) must invalidate the cached path."""
    mt._default_config_path()
    before = mt._config_env_signature()
    monkeypatch.setenv("DS_DEV", "1")
    assert mt._config_env_signature() != before

    mt._default_config_path()
    assert mt._config_path_env == mt._config_env_signature()


# -------------------------------------------------------------
# config round-trip (read-only use of core/config.py)
# -------------------------------------------------------------
def test_default_config_declares_motion_enabled():
    assert DEFAULT_CONFIG["behavior"]["motion_enabled"] is True


@pytest.mark.parametrize("value", [True, False])
def test_motion_enabled_survives_a_config_roundtrip(tmp_path, value):
    path = tmp_path / "config.toml"
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["behavior"]["motion_enabled"] = value
    write_config(path, cfg)

    loaded = load_config(path)
    assert loaded["behavior"]["motion_enabled"] is value
    assert mt.is_motion_enabled(loaded) is value


def test_motion_enabled_read_from_a_written_file(motion_gate):
    _write_config(motion_gate, False)
    assert mt.is_motion_enabled() is False
    assert mt.is_motion_enabled(load_config(motion_gate / "config.toml")) is False


def test_validator_coerces_string_motion_flags(tmp_path):
    """_validate_behavior normalises hostile strings; the gate must agree."""
    path = tmp_path / "config.toml"
    write_config(path, {**copy.deepcopy(DEFAULT_CONFIG),
                        "behavior": {"motion_enabled": "off"}})
    assert load_config(path)["behavior"]["motion_enabled"] is False
    assert mt.is_motion_enabled(load_config(path)) is False
