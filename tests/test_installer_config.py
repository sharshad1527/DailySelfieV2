"""
Installer / config-writer hardening (DIAG Phase 2 + Phase 3 + Phase 4 + RC3).

Covers the pure helpers and the dependency-free config writer contract:

- write_config_safe() prefers tomli-w and falls back to the dependency-free
  bootstrap writer when tomli-w is absent, without dropping keys.
- The tomllib/tomli guard raises the intended clear RuntimeError.
- venv_python() is the single source of truth for the interpreter layout.
- installer.plan_post_install_steps()/build_post_install_command() decide and
  shape the RC3 venv re-exec; run_post_install_step() is exercised with a
  stubbed subprocess so no real venv or network is touched.
- DailySelfie's Windows Store stub guard fires on Windows only.

No real filesystem writes outside tmp_path, no network, no Qt, no venv builds:
conftest.py's DS_* sandbox applies to every test here.
"""
from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

import core.config as config_mod
from core.config import (
    DEFAULT_CONFIG,
    WRITER_BOOTSTRAP,
    WRITER_TOMLI_W,
    load_config,
    write_config,
    write_config_bootstrap,
    write_config_safe,
)
from core.installer import (
    POST_INSTALL_STEPS,
    build_post_install_command,
    plan_post_install_steps,
    run_post_install_step,
)
from core.venv_helper import venv_python

pytestmark = pytest.mark.core_only


# ---------------------------------------------------------------
# Phase 2: write_config_safe fallback behaviour
# ---------------------------------------------------------------
def _full_config() -> dict:
    """DEFAULT_CONFIG, validated + path-normalized like load_config returns."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    config_mod._validate_behavior(cfg)
    return cfg


def test_write_config_safe_prefers_tomli_w_when_available(tmp_path):
    path = tmp_path / "config.toml"
    used = write_config_safe(path, _full_config())

    assert used == WRITER_TOMLI_W
    assert path.exists()
    # tomli-w emits quoted/table headers; the bootstrap writer does not emit
    # a "[behavior]" line differently enough to matter, so assert on content.
    assert "dailyselfie" in path.read_text(encoding="utf-8").lower()


def test_write_config_safe_falls_back_when_tomli_w_absent(tmp_path, monkeypatch):
    """Simulate a bare system Python: tomli-w not installed."""
    monkeypatch.setattr(config_mod, "tomli_w", None)

    path = tmp_path / "config.toml"
    cfg = _full_config()
    used = write_config_safe(path, cfg)

    assert used == WRITER_BOOTSTRAP
    assert path.exists()
    # And the fallback output must still be loadable.
    reloaded = load_config(path)
    assert reloaded["theme"] == cfg["theme"]
    assert reloaded["behavior"]["quality"] == cfg["behavior"]["quality"]


def test_write_config_raises_clear_error_without_tomli_w(tmp_path, monkeypatch):
    """The hard-require path must stay loud when called directly."""
    monkeypatch.setattr(config_mod, "tomli_w", None)
    path = tmp_path / "never.toml"

    with pytest.raises(RuntimeError, match="tomli-w is required"):
        write_config(path, _full_config())

    assert not path.exists()


def test_load_config_raises_clear_error_without_toml_reader(tmp_path, monkeypatch):
    """RC2 guard: a clear RuntimeError, not ModuleNotFoundError from load."""
    monkeypatch.setattr(config_mod, "tomllib", None)
    path = tmp_path / "config.toml"
    path.write_text("[behavior]\nquality = 80\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="3.11"):
        load_config(path)


def test_missing_file_load_does_not_need_a_toml_reader(tmp_path, monkeypatch):
    """A missing config.toml must still yield defaults with no toml reader."""
    monkeypatch.setattr(config_mod, "tomllib", None)
    path = tmp_path / "absent.toml"

    loaded = load_config(path)

    assert path.exists() is False
    assert loaded["behavior"]["quality"] == DEFAULT_CONFIG["behavior"]["quality"]


def test_bootstrap_fallback_does_not_drop_asserted_keys(tmp_path, monkeypatch):
    """
    The fallback must not silently drop keys tests (and real users) rely on.

    Runs the exact key set asserted by tests/test_config_roundtrip.py through
    the no-tomli-w path and reads it back.
    """
    monkeypatch.setattr(config_mod, "tomli_w", None)

    cfg = {
        "installation": {
            "install_dir": str(tmp_path / "inst"),
            "venv_dir": str(tmp_path / "inst" / "venv"),
            "data_dir": str(tmp_path / "data"),
            "logs_dir": str(tmp_path / "logs"),
            "photos_root": str(tmp_path / "photos"),
            "create_desktop_entry": True,
            "autostart": False,
        },
        "behavior": {
            "camera_index": 5,
            "width": 640,
            "height": 480,
            "quality": 77,
            "one_photo_per_day": True,
            "allow_retake": True,
            "timer_duration": 300,
            "motion_enabled": False,
            "highlights_enabled": True,
            "dismissed_highlights": [],
            "recap_seen": [],
            "quality_gate_enabled": True,
        },
        "theme": {"name": "material-theme", "mode": "light", "contrast": "high"},
    }

    path = tmp_path / "config.toml"
    assert write_config_safe(path, cfg) == WRITER_BOOTSTRAP

    b = load_config(path)["behavior"]
    assert b["camera_index"] == 5
    assert b["quality"] == 77
    assert b["timer_duration"] == 300
    assert b["one_photo_per_day"] is True
    assert b["allow_retake"] is True
    assert b["motion_enabled"] is False
    assert b["dismissed_highlights"] == []
    assert b["recap_seen"] == []
    assert load_config(path)["theme"]["contrast"] == "high"


def test_fallback_preserves_full_default_config(tmp_path, monkeypatch):
    """The whole DEFAULT_CONFIG must survive a bootstrap-only write/read."""
    monkeypatch.setattr(config_mod, "tomli_w", None)
    path = tmp_path / "config.toml"
    cfg = _full_config()

    write_config_safe(path, cfg)
    loaded = load_config(path)

    assert loaded["theme"] == cfg["theme"]
    assert loaded["behavior"]["quality"] == cfg["behavior"]["quality"]
    assert loaded["behavior"]["timer_duration"] == cfg["behavior"]["timer_duration"]
    # Dead keys resolved in DIAG task 5 must be gone from the defaults.
    assert "image_format" not in loaded["behavior"]
    assert "audit_enabled" not in loaded["behavior"]


def test_stale_image_format_in_existing_config_no_longer_raises(tmp_path):
    """
    An old config.toml carrying image_format must still load.

    Before the dead-key cleanup, `image_format = "png"` raised ValueError out
    of load_config and stopped the app from starting.
    """
    path = tmp_path / "config.toml"
    path.write_text(
        "[behavior]\nimage_format = \"png\"\nquality = 80\n", encoding="utf-8"
    )

    loaded = load_config(path)

    assert loaded["behavior"]["quality"] == 80
    # The stale key is preserved (so we don't destroy unknown user data) but
    # no longer validated.
    assert loaded["behavior"]["image_format"] == "png"


def test_bootstrap_writer_output_parses_as_toml(tmp_path):
    """The manual writer must emit syntactically valid TOML for real defaults."""
    import tomllib

    path = tmp_path / "bootstrap.toml"
    write_config_bootstrap(path, _full_config())

    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["behavior"]["quality"] == DEFAULT_CONFIG["behavior"]["quality"]


# ---------------------------------------------------------------
# Phase 4 / venv helper
# ---------------------------------------------------------------
def test_venv_python_layout_per_os(tmp_path, monkeypatch):
    import core.venv_helper as vh

    monkeypatch.setattr(vh.platform, "system", lambda: "Windows")
    assert venv_python(tmp_path) == tmp_path / "Scripts" / "python.exe"

    monkeypatch.setattr(vh.platform, "system", lambda: "Linux")
    assert venv_python(tmp_path) == tmp_path / "bin" / "python"


def test_stderr_text_decodes_bytes_without_raising():
    from core.venv_helper import _stderr_text

    class Fake:
        stderr = b"pip failed: \xff\xfe invalid\n"

    assert "pip failed" in _stderr_text(Fake())
    assert _stderr_text(type("E", (), {"stderr": None})()) == ""
    assert _stderr_text(type("E", (), {"stderr": "  "})()) == ""


# ---------------------------------------------------------------
# RC3: post-install steps run through the venv interpreter
# ---------------------------------------------------------------
def test_plan_post_install_steps_respects_user_choices():
    both_on = {"installation": {"create_desktop_entry": True, "autostart": True}}
    assert plan_post_install_steps(both_on) == ["desktop_entry", "autostart"]

    entry_only = {"installation": {"create_desktop_entry": True, "autostart": False}}
    assert plan_post_install_steps(entry_only) == ["desktop_entry"]

    autostart_only = {
        "installation": {"create_desktop_entry": False, "autostart": True}
    }
    assert plan_post_install_steps(autostart_only) == ["autostart"]

    # Missing section must not explode (installer deep-copies defaults, but
    # the helper stays total).
    assert plan_post_install_steps({}) == []
    assert plan_post_install_steps({"installation": {}}) == []


def test_post_install_command_uses_venv_interpreter_and_lifecycle_flag():
    venv_py = Path("/opt/ds/venv") / "bin" / "python"
    root = Path("/opt/ds")

    cmd = build_post_install_command(venv_py, root, "desktop_entry")

    assert cmd == [
        str(venv_py),
        str(root / "DailySelfie.py"),
        POST_INSTALL_STEPS["desktop_entry"],
    ]
    assert cmd[0] == str(venv_py), "must NOT re-use the system interpreter"
    assert cmd[2] == "--create-desktop-entry"

    cmd2 = build_post_install_command(venv_py, root, "autostart")
    assert cmd2[2] == "--enable-autostart"


def test_build_post_install_command_keeps_spaces_in_paths():
    """Spaces in the install path must survive (list-args, no shell)."""
    cmd = build_post_install_command(
        Path("/home/a b/venv/bin/python"),
        Path("/home/a b/Project"),
        "desktop_entry",
    )
    assert cmd[1] == str(Path("/home/a b/Project/DailySelfie.py"))


def _fake_venv_layout(tmp_path):
    """Materialise a fake <venv>/bin/python plus a project entry script."""
    venv_py = tmp_path / "venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.touch()
    root = tmp_path / "project"
    root.mkdir()
    (root / "DailySelfie.py").write_text("# fake\n", encoding="utf-8")
    return venv_py, root


def test_run_post_install_step_invokes_venv_python(monkeypatch, tmp_path):
    """RC3 regression guard: the step must be spawned with the venv python."""
    venv_py, root = _fake_venv_layout(tmp_path)

    calls: list[dict] = []

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": list(cmd), "kwargs": kwargs})
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    ok, msg = run_post_install_step(venv_py, root, "desktop_entry")

    assert ok is True
    assert "done" in msg
    assert len(calls) == 1
    assert calls[0]["cmd"] == [
        str(venv_py),
        str(root / "DailySelfie.py"),
        "--create-desktop-entry",
    ]
    # Output decoding must be cp1252-proof (RC4).
    assert calls[0]["kwargs"]["encoding"] == "utf-8"
    assert calls[0]["kwargs"]["errors"] == "replace"
    assert calls[0]["kwargs"]["capture_output"] is True


def test_run_post_install_step_reports_failure_without_raising(monkeypatch, tmp_path):
    venv_py, root = _fake_venv_layout(tmp_path)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="!!! CRITICAL CRASH LOGGED !!!\n"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    ok, msg = run_post_install_step(venv_py, root, "autostart")

    assert ok is False
    assert "autostart failed" in msg
    assert "CRITICAL CRASH" in msg


def test_run_post_install_step_survives_missing_interpreter(monkeypatch, tmp_path):
    """A missing venv python is a warning, never an installer abort."""
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("must not spawn")
    )

    ok, msg = run_post_install_step(
        tmp_path / "nope" / "python", tmp_path, "autostart"
    )

    assert ok is False
    assert "autostart failed" in msg
    assert "venv interpreter missing" in msg


def test_run_post_install_step_handles_timeout(monkeypatch, tmp_path):
    venv_py, root = _fake_venv_layout(tmp_path)

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    monkeypatch.setattr(subprocess, "run", fake_run)

    ok, msg = run_post_install_step(venv_py, root, "desktop_entry")

    assert ok is False
    assert "timed out" in msg


def test_run_post_install_step_handles_os_error(monkeypatch, tmp_path):
    venv_py, root = _fake_venv_layout(tmp_path)

    def fake_run(cmd, **kwargs):
        raise OSError("Exec format error")

    monkeypatch.setattr(subprocess, "run", fake_run)

    ok, msg = run_post_install_step(venv_py, root, "desktop_entry")

    assert ok is False
    assert "Exec format error" in msg


def test_run_post_install_step_reports_missing_entry_script(monkeypatch, tmp_path):
    """A missing DailySelfie.py is a warning, not a spawn attempt."""
    venv_py = tmp_path / "venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.touch()
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("must not spawn")
    )

    ok, msg = run_post_install_step(venv_py, root, "desktop_entry")

    assert ok is False
    assert "entry script missing" in msg


def test_unknown_step_is_rejected():
    with pytest.raises(KeyError):
        build_post_install_command(Path("py"), Path("."), "not_a_step")


# ---------------------------------------------------------------
# Phase 3: Windows Store python stub detection
# ---------------------------------------------------------------
def _load_entry_module():
    """Import DailySelfie.py as a module without triggering Qt or a GUI."""
    import importlib.util

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "dailyselfie_entry", root / "DailySelfie.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_store_stub_detected_on_windows(monkeypatch):
    entry = _load_entry_module()
    monkeypatch.setattr(entry.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        entry.sys,
        "executable",
        r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\python.exe",
    )

    assert entry._is_windows_store_stub() is True


def test_real_windows_python_not_flagged(monkeypatch):
    entry = _load_entry_module()
    monkeypatch.setattr(entry.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        entry.sys,
        "executable",
        r"C:\Users\me\AppData\Local\Programs\Python\Python312\python.exe",
    )

    assert entry._is_windows_store_stub() is False


def test_windows_apps_lookalike_directory_not_flagged(monkeypatch):
    """Only the real ...\\Microsoft\\WindowsApps\\ path counts."""
    entry = _load_entry_module()
    monkeypatch.setattr(entry.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        entry.sys, "executable", r"C:\Users\me\WindowsAppsBackup\python.exe"
    )

    assert entry._is_windows_store_stub() is False


def test_stub_check_is_noop_on_linux(monkeypatch):
    entry = _load_entry_module()
    monkeypatch.setattr(entry.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        entry.sys,
        "executable",
        r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\python.exe",
    )

    assert entry._is_windows_store_stub() is False


def test_guard_is_noop_for_real_interpreters(monkeypatch, capsys):
    entry = _load_entry_module()
    monkeypatch.setattr(entry.platform, "system", lambda: "Linux")

    entry._guard_against_windows_store_stub()  # must not raise/exit

    assert capsys.readouterr().out == ""


def test_guard_exits_nonzero_with_instructions(monkeypatch, capsys):
    entry = _load_entry_module()
    monkeypatch.setattr(entry.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        entry.sys,
        "executable",
        r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\python.exe",
    )

    with pytest.raises(SystemExit) as excinfo:
        entry._guard_against_windows_store_stub()

    assert excinfo.value.code == entry.WINDOWS_STORE_STUB_EXIT_CODE
    assert excinfo.value.code != 0
    out = capsys.readouterr().out
    assert "python.org" in out
    assert "WindowsApps" in out


def test_guard_handles_unresolvable_executable(monkeypatch):
    """A missing sys.executable must not raise, just report 'not a stub'."""
    entry = _load_entry_module()
    monkeypatch.setattr(entry.platform, "system", lambda: "Windows")
    monkeypatch.setattr(entry.sys, "executable", None)

    assert entry._is_windows_store_stub() is False


# ---------------------------------------------------------------
# Bare-Python import hygiene (regression guard for RC1/RC2)
# ---------------------------------------------------------------
def test_entry_and_installer_have_no_third_party_module_level_imports():
    """
    `python DailySelfie.py --install` must boot on a bare interpreter, so no
    third-party module may appear in a *module-level* import in the pre-venv
    chain. (RC1/RC2 regression guard.)
    """
    import ast

    root = Path(__file__).resolve().parent.parent
    allowed_first_party = {"core", "gui", "autostart", "desktop_entry", "DailySelfie"}

    offenders: list[str] = []
    for rel in ("DailySelfie.py", "core/installer.py"):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"), filename=rel)
        for node in tree.body:  # module level only, not inside functions
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top in sys.stdlib_module_names or top in allowed_first_party:
                    continue
                offenders.append(f"{rel}:{node.lineno} -> {name}")

    assert offenders == [], f"third-party module-level imports: {offenders}"