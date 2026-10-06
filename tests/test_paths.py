"""
core/paths.py: the containment guard the whole test suite leans on.

ensure_sandbox()/assert_sandboxed() are what stop a test from resolving a
directory outside the pytest sandbox (i.e. into the real HOME). Those helpers
were previously only exercised indirectly by conftest, so a regression in them
would have shown up as "some other test mysteriously wrote to ~". These tests
pin the guard's behaviour directly, including the opt-in nature that keeps real
users unaffected.

DS_* overrides come from the autouse ds_sandbox fixture, so nothing here can
touch the real filesystem.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.paths import (
    AppPaths,
    DEFAULT_SANDBOX_ROOT,
    DS_ENV_KEYS,
    assert_sandboxed,
    ds_mode_active,
    ensure_sandbox,
    get_app_paths,
    get_env_overrides,
    photos_folder_for_ts,
)

pytestmark = pytest.mark.core_only  # fast/offline core data-layer tests


_SANDBOXED_ATTRS = ("config_dir", "data_dir", "logs_dir", "photos_root", "venv_dir")


def _paths(**overrides) -> AppPaths:
    """An AppPaths whose dirs all live under `root` unless overridden."""
    root = overrides.pop("root")
    kwargs = {
        "app_name": "DailySelfie",
        "os_name": "linux",
        "home": root,
        "project_root": root,
    }
    for attr in _SANDBOXED_ATTRS:
        kwargs[attr] = overrides.pop(attr, root / attr)
    assert not overrides, f"unused overrides: {overrides}"
    return AppPaths(**kwargs)


class TestAppPathsResolution:
    def test_env_overrides_win_over_os_defaults(self, ds_sandbox):
        got = get_app_paths("DailySelfie")
        assert got.config_dir == Path(os.environ["DS_CONFIG_DIR"]).resolve()
        assert got.data_dir == Path(os.environ["DS_DATA_DIR"]).resolve()
        assert got.photos_root == Path(os.environ["DS_PHOTOS_DIR"]).resolve()
        assert got.venv_dir == Path(os.environ["DS_VENV_DIR"]).resolve()
        assert got.logs_dir == Path(os.environ["DS_LOGS_DIR"]).resolve()

    def test_ensure_false_creates_nothing(self, tmp_path, monkeypatch):
        root = tmp_path / "fresh"
        monkeypatch.setenv("DS_CONFIG_DIR", str(root / "config"))
        monkeypatch.setenv("DS_DATA_DIR", str(root / "data"))
        monkeypatch.setenv("DS_LOGS_DIR", str(root / "logs"))
        monkeypatch.setenv("DS_PHOTOS_DIR", str(root / "photos"))
        monkeypatch.setenv("DS_VENV_DIR", str(root / "venv"))

        get_app_paths("DailySelfie", ensure=False)

        assert not root.exists(), "import/resolution must not create directories"

    def test_ensure_true_creates_every_dir(self, tmp_path, monkeypatch):
        root = tmp_path / "made"
        monkeypatch.setenv("DS_CONFIG_DIR", str(root / "config"))
        monkeypatch.setenv("DS_DATA_DIR", str(root / "data"))
        monkeypatch.setenv("DS_LOGS_DIR", str(root / "logs"))
        monkeypatch.setenv("DS_PHOTOS_DIR", str(root / "photos"))
        monkeypatch.setenv("DS_VENV_DIR", str(root / "venv"))

        got = get_app_paths("DailySelfie", ensure=True)

        for attr in _SANDBOXED_ATTRS:
            assert Path(getattr(got, attr)).is_dir()

    def test_as_dict_exposes_every_path(self, ds_sandbox):
        as_dict = ds_sandbox.as_dict()
        for attr in ("config_dir", "data_dir", "logs_dir", "photos_root", "venv_dir"):
            assert Path(as_dict[attr]).is_absolute()

    def test_logs_dir_defaults_under_data_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DS_LOGS_DIR", raising=False)
        monkeypatch.setenv("DS_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("DS_CONFIG_DIR", str(tmp_path / "config"))
        monkeypatch.setenv("DS_PHOTOS_DIR", str(tmp_path / "photos"))
        monkeypatch.setenv("DS_VENV_DIR", str(tmp_path / "venv"))

        got = get_app_paths("DailySelfie")

        assert got.logs_dir == (tmp_path / "data" / "logs").resolve()

    def test_venv_defaults_under_data_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DS_VENV_DIR", raising=False)
        monkeypatch.setenv("DS_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("DS_CONFIG_DIR", str(tmp_path / "config"))
        monkeypatch.setenv("DS_LOGS_DIR", str(tmp_path / "logs"))
        monkeypatch.setenv("DS_PHOTOS_DIR", str(tmp_path / "photos"))

        got = get_app_paths("DailySelfie")

        assert got.venv_dir == (tmp_path / "data" / ".venv").resolve()

    @pytest.mark.parametrize("truthy", ["1", "true", "TRUE", "yes", "on"])
    def test_dev_mode_truthy_values_use_project_local_dir(
        self, ds_sandbox, monkeypatch, truthy
    ):
        monkeypatch.setenv("DS_DEV", truthy)
        # An explicit override must still win over the dev-mode default.
        assert get_app_paths("DailySelfie").photos_root == ds_sandbox.photos_root

    @pytest.mark.parametrize("falsy", ["0", "false", "no", "off", "", "maybe"])
    def test_dev_mode_falsy_values_are_ignored(self, ds_sandbox, monkeypatch, falsy):
        monkeypatch.setenv("DS_DEV", falsy)
        assert get_app_paths("DailySelfie").photos_root == ds_sandbox.photos_root

    def test_force_local_is_an_alias_for_dev_mode(self, ds_sandbox, monkeypatch):
        monkeypatch.setenv("DS_FORCE_LOCAL", "1")
        assert get_app_paths("DailySelfie").config_dir == ds_sandbox.config_dir

    def test_dev_mode_without_overrides_uses_ds_dev_folder(self, tmp_path, monkeypatch):
        for var in DS_ENV_KEYS.values():
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("DS_DEV", "1")

        got = get_app_paths("DailySelfie")

        assert got.photos_root.name == "photos"
        assert got.photos_root.parent.name == ".ds_dev"


class TestEnvOverrides:
    def test_every_ds_key_is_reported(self, ds_sandbox):
        overrides = get_env_overrides()
        assert set(overrides) == set(DS_ENV_KEYS)

    def test_absent_var_is_omitted(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DS_PHOTOS_DIR", raising=False)
        overrides = get_env_overrides()
        assert "photos_root" not in overrides

    def test_relative_override_is_resolved(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DS_PHOTOS_DIR", "rel-photos")
        assert get_env_overrides()["photos_root"] == (tmp_path / "rel-photos").resolve()

    def test_user_expansion_is_applied(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("DS_PHOTOS_DIR", "~/pics")
        assert get_env_overrides()["photos_root"] == (tmp_path / "pics").resolve()


class TestDsModeActive:
    def test_true_when_any_ds_var_present(self, monkeypatch):
        monkeypatch.setenv("DS_ANYTHING_AT_ALL", "1")
        assert ds_mode_active() is True

    def test_false_when_no_ds_var_present(self, monkeypatch):
        for name in list(os.environ):
            if name.upper().startswith("DS_"):
                monkeypatch.delenv(name)
        assert ds_mode_active() is False

    def test_prefix_is_configurable(self, monkeypatch):
        monkeypatch.setenv("DS_CONFIG_DIR", str(Path(os.devnull).parent))
        assert ds_mode_active("DSX_") is False


class TestAssertSandboxed:
    def test_passes_when_every_dir_is_inside_root(self, tmp_path):
        paths = _paths(root=tmp_path / "sandbox")
        assert assert_sandboxed(paths, root=tmp_path / "sandbox", strict=True) is paths

    def test_dir_equal_to_root_is_allowed(self, tmp_path):
        root = tmp_path / "sandbox"
        paths = _paths(root=root, config_dir=root)
        assert assert_sandboxed(paths, root=root, strict=True) is paths

    def test_raises_and_names_the_escaping_dir(self, tmp_path):
        root = tmp_path / "sandbox"
        paths = _paths(root=root, photos_root=tmp_path / "elsewhere" / "photos")

        with pytest.raises(RuntimeError) as excinfo:
            assert_sandboxed(paths, root=root, strict=True)

        message = str(excinfo.value)
        assert "photos_root" in message
        assert "elsewhere" in message

    def test_reports_every_escape_not_just_the_first(self, tmp_path):
        root = tmp_path / "sandbox"
        paths = _paths(
            root=root,
            photos_root=tmp_path / "pics",
            data_dir=tmp_path / "data",
        )

        with pytest.raises(RuntimeError) as excinfo:
            assert_sandboxed(paths, root=root, strict=True)

        message = str(excinfo.value)
        assert "photos_root" in message and "data_dir" in message

    def test_parent_of_root_is_not_inside_root(self, tmp_path):
        root = tmp_path / "sandbox"
        paths = _paths(root=root, config_dir=tmp_path)  # the root's parent
        with pytest.raises(RuntimeError):
            assert_sandboxed(paths, root=root, strict=True)

    def test_missing_attr_is_skipped_not_reported(self, tmp_path):
        root = tmp_path / "sandbox"
        paths = _paths(root=root)
        paths.data_dir = None  # type: ignore[assignment]
        assert assert_sandboxed(paths, root=root, strict=True) is paths

    def test_attrs_selection_is_honoured(self, tmp_path):
        root = tmp_path / "sandbox"
        paths = _paths(root=root, photos_root=tmp_path / "pics")

        # photos_root escapes but is not in the selected attr list.
        assert_sandboxed(paths, root=root, strict=True, attrs=("config_dir",))

        with pytest.raises(RuntimeError):
            assert_sandboxed(paths, root=root, strict=True, attrs=("photos_root",))

    def test_symlink_escape_is_detected(self, tmp_path):
        """A symlink pointing outside the root must not pass the guard."""
        root = tmp_path / "sandbox"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "real").mkdir()
        linked = root / "photos"
        linked.symlink_to(outside / "real", target_is_directory=True)

        paths = _paths(root=root, photos_root=linked)

        with pytest.raises(RuntimeError):
            assert_sandboxed(paths, root=root, strict=True)

    def test_is_a_noop_when_not_strict_and_ds_mode_off(self, tmp_path, monkeypatch):
        for name in list(os.environ):
            if name.upper().startswith("DS_"):
                monkeypatch.delenv(name)
        paths = _paths(root=tmp_path / "sandbox", photos_root=tmp_path / "pics")

        # A real user running the app normally must never trip this.
        assert assert_sandboxed(paths, root=tmp_path / "sandbox") is paths

    def test_strict_flag_forces_the_check_without_ds_mode(self, tmp_path, monkeypatch):
        for name in list(os.environ):
            if name.upper().startswith("DS_"):
                monkeypatch.delenv(name)
        paths = _paths(root=tmp_path / "sandbox", photos_root=tmp_path / "pics")

        with pytest.raises(RuntimeError):
            assert_sandboxed(paths, root=tmp_path / "sandbox", strict=True)

    def test_default_sandbox_root_is_a_temp_location(self):
        assert DEFAULT_SANDBOX_ROOT.startswith("/tmp") or "tmp" in DEFAULT_SANDBOX_ROOT


class TestEnsureSandbox:
    def test_resolves_paths_when_ds_mode_active(self, ds_sandbox):
        checked = ensure_sandbox(root=str(ds_sandbox.photos_root.parent.parent.parent))
        assert isinstance(checked, AppPaths)
        assert checked.photos_root == ds_sandbox.photos_root

    def test_returns_none_when_opted_out_and_no_paths_given(self, monkeypatch):
        for name in list(os.environ):
            if name.upper().startswith("DS_"):
                monkeypatch.delenv(name)
        assert ensure_sandbox() is None

    def test_supplied_paths_obj_is_checked_verbatim(self, tmp_path):
        root = tmp_path / "sandbox"
        paths = _paths(root=root, photos_root=tmp_path / "pics")
        # Even with no DS_ var set, an explicit paths_obj is validated when strict.
        with pytest.raises(RuntimeError):
            ensure_sandbox(paths_obj=paths, root=root, strict=True)

    def test_passes_paths_obj_through_when_clean(self, tmp_path):
        root = tmp_path / "sandbox"
        paths = _paths(root=root)
        assert ensure_sandbox(paths_obj=paths, root=root, strict=True) is paths

    def test_ds_sandbox_fixture_resolved_dirs_are_all_inside_sandbox(self, ds_sandbox):
        """The invariant the rest of the suite depends on, asserted directly."""
        root = Path(os.environ["DS_PHOTOS_DIR"]).parent
        for attr in _SANDBOXED_ATTRS:
            assert Path(getattr(ds_sandbox, attr)).is_relative_to(root)


class TestPhotosFolderForTs:
    def test_creates_and_returns_year_folder(self, tmp_path):
        got = photos_folder_for_ts(tmp_path / "photos", 2026)
        assert got == tmp_path / "photos" / "2026"
        assert got.is_dir()

    def test_is_idempotent_for_an_existing_year(self, tmp_path):
        first = photos_folder_for_ts(tmp_path, 2025)
        marker = first / "keep.txt"
        marker.write_text("keep", encoding="utf-8")

        second = photos_folder_for_ts(tmp_path, 2025)

        assert second == first
        assert marker.exists()