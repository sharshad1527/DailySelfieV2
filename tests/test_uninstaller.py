"""
core/uninstaller.py safety tests.

Uninstall is the one code path in this app that deletes user data, so these
tests concentrate on the dangerous branches rather than the happy path:

* the rescue MOVE happens *before* anything is deleted;
* a failed/incomplete rescue leaves the source in place (never deletes data it
  could not verify as rescued);
* disposable paths (logs) are skipped by the rescue and still removed;
* explicit "delete photos" is the only path that destroys photos;
* every target stays inside the pytest sandbox — nothing touches the real HOME;
* re-running is idempotent and cannot double-delete.

All filesystem roots are created under the per-test DS_* sandbox, and
Path.home() is redirected into it, so ~/Pictures rescue folders and
~/.local/bin wrappers are fake.
"""
from __future__ import annotations

import builtins
import shutil
from pathlib import Path

import pytest

import core.uninstaller as uninstaller
from core.uninstaller import (
    RESCUE_PREFIX,
    RESCUE_README_NAME,
    _confirm,
    _count_files,
    _has_rescuable_content,
    _is_safe_to_delete,
    _is_within,
    _make_rescue_root,
    _move_subtree,
    _prune_delete,
    _rescue_contents,
    run_uninstall,
)

pytestmark = pytest.mark.core_only  # fast/offline core data-layer tests


# -------------------------------------------------------------
# helpers
# -------------------------------------------------------------
@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """Redirect Path.home() into the pytest tmp tree."""
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture()
def stub_hooks(monkeypatch):
    """Record (instead of perform) the autostart / desktop-entry teardown."""
    calls = []
    monkeypatch.setattr(
        uninstaller, "set_autostart", lambda enabled: calls.append(("autostart", enabled))
    )
    monkeypatch.setattr(
        uninstaller,
        "set_desktop_entry",
        lambda enabled: calls.append(("desktop", enabled)),
    )
    return calls


@pytest.fixture()
def answers(monkeypatch):
    """Feed scripted y/n answers to the interactive _confirm() prompts."""
    queue: list[str] = []

    def _fake_input(prompt: str = "") -> str:
        if not queue:
            raise AssertionError(f"unexpected prompt with no scripted answer: {prompt!r}")
        return queue.pop(0)

    monkeypatch.setattr(builtins, "input", _fake_input)

    def _script(*values: str) -> None:
        queue.extend(values)

    return _script


def _write(path: Path, data: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    return path


def _make_install(tmp_path: Path, *, photos=True, data=True, logs=True):
    """Build a plausible install tree; returns (paths, cfg, dirs)."""
    install = tmp_path / "install"
    photos_root = tmp_path / "photos"
    data_dir = tmp_path / "data"
    logs_dir = data_dir / "logs"

    if photos:
        _write(photos_root / "2026" / "2026-08-24_120000.jpg", "photo-bytes")
        _write(photos_root / "2026" / "2026-08-25_120000.jpg", "photo-bytes")
    if data:
        _write(data_dir / "index.db", "sqlite")
        _write(data_dir / "captures.jsonl", "{}\n")
        _write(data_dir / "metadata" / "2026-08-24_120000.json", "{}")
        _write(data_dir / "thumbs" / "2026-08-24_120000.jpg", "thumb")
    if logs:
        _write(logs_dir / "app.log", "noise")
    # install dir holds the program itself, outside the rescued dirs
    _write(install / "DailySelfie.py", "# app")
    _write(install / "venv" / "bin" / "python", "binary")

    paths = type("P", (), {"app_name": "DailySelfie"})()
    cfg = {
        "installation": {
            "install_dir": str(install),
            "photos_root": str(photos_root),
            "data_dir": str(data_dir),
            "logs_dir": str(logs_dir),
        }
    }
    return paths, cfg, {
        "install": install,
        "photos": photos_root,
        "data": data_dir,
        "logs": logs_dir,
    }


def _rescue_folders(home: Path):
    base = home / "Pictures"
    return sorted(base.glob(f"{RESCUE_PREFIX}-*")) if base.exists() else []


# -------------------------------------------------------------
# _is_safe_to_delete — the guard that must never allow catastrophe
# -------------------------------------------------------------
class TestIsSafeToDelete:
    @pytest.mark.parametrize("dangerous", ["/", "/usr", "/usr/local"])
    def test_system_dirs_are_never_deletable(self, dangerous):
        assert _is_safe_to_delete(Path(dangerous)) is False

    def test_home_directory_is_never_deletable(self, fake_home):
        assert _is_safe_to_delete(fake_home) is False

    def test_project_root_is_protected(self):
        # Running from source means install_dir could be the repo itself.
        assert _is_safe_to_delete(Path(__file__).resolve().parent.parent) is False

    def test_ordinary_subdirectory_is_allowed(self, tmp_path):
        target = tmp_path / "install"
        target.mkdir()
        assert _is_safe_to_delete(target) is True


# -------------------------------------------------------------
# small pure helpers
# -------------------------------------------------------------
class TestConfirm:
    def test_empty_answer_returns_default(self, monkeypatch):
        monkeypatch.setattr(builtins, "input", lambda prompt="": "")
        assert _confirm("go?") is False
        assert _confirm("go?", default=True) is True

    @pytest.mark.parametrize("answer,expected", [
        ("y", True), ("YES", True), ("n", False), ("No", False),
    ])
    def test_affirmative_and_negative_words(self, monkeypatch, answer, expected):
        monkeypatch.setattr(builtins, "input", lambda prompt="": answer)
        assert _confirm("go?") is expected

    def test_prompt_repeats_on_garbage(self, monkeypatch):
        seq = iter(["maybe", "later", "y"])
        monkeypatch.setattr(builtins, "input", lambda prompt="": next(seq))
        assert _confirm("go?") is True


class TestFileCounting:
    def test_counts_nested_files(self, tmp_path):
        _write(tmp_path / "a.jpg")
        _write(tmp_path / "2026" / "b.jpg")
        _write(tmp_path / "2026" / "2027" / "c.jpg")
        assert _count_files(tmp_path) == 3

    def test_missing_path_counts_zero(self, tmp_path):
        assert _count_files(tmp_path / "nope") == 0

    def test_single_file_counts_one(self, tmp_path):
        f = _write(tmp_path / "a.jpg")
        assert _count_files(f) == 1


class TestIsWithin:
    def test_child_and_self_are_within(self, tmp_path):
        assert _is_within(tmp_path, tmp_path) is True
        assert _is_within(tmp_path / "a" / "b", tmp_path) is True

    def test_sibling_outside_is_not_within(self, tmp_path):
        root = tmp_path / "photos"
        other = tmp_path / "data"
        root.mkdir()
        other.mkdir()
        assert _is_within(other, root) is False


class TestHasRescuableContent:
    def test_true_when_a_non_excluded_child_exists(self, tmp_path):
        _write(tmp_path / "index.db")
        assert _has_rescuable_content(tmp_path, [tmp_path / "logs"]) is True

    def test_false_when_only_excluded_children_exist(self, tmp_path):
        _write(tmp_path / "logs" / "app.log")
        assert _has_rescuable_content(tmp_path, [tmp_path / "logs"]) is False

    def test_false_for_missing_dir(self, tmp_path):
        assert _has_rescuable_content(tmp_path / "gone", []) is False


# -------------------------------------------------------------
# rescue mechanics
# -------------------------------------------------------------
class TestMoveSubtree:
    def test_moves_and_reports_file_count(self, tmp_path):
        src = tmp_path / "photos"
        _write(src / "a.jpg")
        _write(src / "2026" / "b.jpg")
        dst = tmp_path / "rescue"
        dst.mkdir()
        rescued: list = []

        assert _move_subtree(src, dst, rescued) is True
        assert not src.exists()
        assert _count_files(dst / "photos") == 2
        assert rescued == [{"src": str(src), "dst": str(dst / "photos"), "files": 2}]

    def test_failed_move_returns_false_and_keeps_source(self, tmp_path, monkeypatch):
        src = tmp_path / "photos"
        _write(src / "a.jpg")
        dst = tmp_path / "rescue"
        dst.mkdir()
        rescued: list = []

        def _boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(shutil, "move", _boom)
        assert _move_subtree(src, dst, rescued) is False
        assert _count_files(src) == 1, "source must survive a failed rescue"
        assert rescued == [], "nothing may be reported as rescued"

    def test_name_collision_gets_suffixed_destination(self, tmp_path):
        src = tmp_path / "photos"
        _write(src / "a.jpg")
        dst = tmp_path / "rescue"
        _write(dst / "photos" / "old.jpg")
        dst.mkdir(exist_ok=True)
        rescued: list = []

        assert _move_subtree(src, dst, rescued) is True
        assert (dst / "photos-1" / "a.jpg").exists()


class TestRescueContents:
    def test_excluded_children_are_left_behind(self, tmp_path):
        src = tmp_path / "data"
        _write(src / "index.db")
        logs = _write(src / "logs" / "app.log")
        dst = tmp_path / "rescue" / "data"
        rescued: list = []

        protected = _rescue_contents(src, dst, [src / "logs"], rescued)

        assert protected == set()
        assert (dst / "index.db").exists()
        assert logs.exists(), "logs are disposable and must not be rescued"
        assert not (src / "index.db").exists()

    def test_unrescuable_child_is_reported_as_protected(self, tmp_path, monkeypatch):
        src = tmp_path / "data"
        _write(src / "index.db")
        dst = tmp_path / "rescue" / "data"
        rescued: list = []

        def _boom(*a, **k):
            raise OSError("nope")

        monkeypatch.setattr(shutil, "move", _boom)
        protected = _rescue_contents(src, dst, [], rescued)

        # The un-rescuable child itself is marked protected, which is what
        # stops _prune_delete from deleting it.
        assert protected == {(src / "index.db").resolve()}
        assert (src / "index.db").exists()

    def test_missing_source_returns_empty_protected_set(self, tmp_path):
        assert _rescue_contents(tmp_path / "gone", tmp_path / "d", [], []) == set()


class TestMakeRescueRoot:
    def test_creates_unique_timestamped_folder(self, fake_home):
        base = fake_home / "Pictures"
        first = _make_rescue_root()
        second = _make_rescue_root()

        assert first is not None and first.parent == base
        assert first.name.startswith(RESCUE_PREFIX)
        assert second is not None
        assert first != second, "two rescues in the same second must not collide"

    def test_returns_none_when_base_cannot_be_created(self, tmp_path, monkeypatch):
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("i am a file", encoding="utf-8")
        assert _make_rescue_root(base=blocker / "Pictures") is None


class TestPruneDelete:
    def test_removes_everything_when_nothing_protected(self, tmp_path):
        _write(tmp_path / "a" / "b.txt")
        assert _prune_delete(tmp_path, set()) is True
        assert not tmp_path.exists()

    def test_protected_subtree_survives_and_others_are_removed(self, tmp_path):
        _write(tmp_path / "doomed" / "x.txt")
        keep = _write(tmp_path / "keep" / "y.txt")
        protected = {keep.parent.resolve()}

        assert _prune_delete(tmp_path, protected) is False
        assert keep.exists(), "protected subtree must be preserved"
        assert not (tmp_path / "doomed").exists(), "unprotected siblings must go"

    def test_exact_protected_target_is_never_deleted(self, tmp_path):
        target = tmp_path / "photos"
        _write(target / "a.jpg")
        assert _prune_delete(target, {target.resolve()}) is False
        assert (target / "a.jpg").exists()

    def test_unremovable_child_reports_incomplete(self, tmp_path, monkeypatch):
        target = tmp_path / "install"
        _write(target / "sub" / "a.txt")

        def _boom(*a, **k):
            raise OSError("locked")

        monkeypatch.setattr(shutil, "rmtree", _boom)
        assert _prune_delete(target, set()) is False
        assert (target / "sub" / "a.txt").exists()


# -------------------------------------------------------------
# end-to-end run_uninstall
# -------------------------------------------------------------
class TestRunUninstall:
    def test_missing_install_dir_is_a_noop(self, tmp_path, fake_home, stub_hooks, answers):
        paths, cfg, dirs = _make_install(tmp_path)
        shutil.rmtree(dirs["install"])

        run_uninstall(paths, cfg)  # must not prompt at all

        assert (dirs["photos"] / "2026").exists()
        assert _rescue_folders(fake_home) == []
        assert stub_hooks == [], "hooks must not be touched for a no-op uninstall"

    def test_cancelling_the_prompt_deletes_nothing(
        self, tmp_path, fake_home, stub_hooks, answers
    ):
        paths, cfg, dirs = _make_install(tmp_path)
        answers("n")

        run_uninstall(paths, cfg)

        assert dirs["install"].exists()
        assert (dirs["photos"] / "2026").exists()
        assert _rescue_folders(fake_home) == []

    def test_unsafe_target_aborts_before_any_deletion(
        self, tmp_path, fake_home, stub_hooks, answers
    ):
        paths, cfg, dirs = _make_install(tmp_path)
        cfg["installation"]["install_dir"] = str(Path.home())
        _write(fake_home / "important.txt", "do not delete me")

        run_uninstall(paths, cfg)

        assert (fake_home / "important.txt").exists()
        assert (dirs["photos"] / "2026").exists()
        assert stub_hooks == []

    def test_default_answer_keeps_photos_and_rescues_them(
        self, tmp_path, fake_home, stub_hooks, answers
    ):
        paths, cfg, dirs = _make_install(tmp_path)
        answers("y", "")  # proceed, then default ("no") to permanent deletion

        run_uninstall(paths, cfg)

        rescue = _rescue_folders(fake_home)
        assert len(rescue) == 1
        rescued_photos = list((rescue[0] / "photos").rglob("*.jpg"))
        assert len(rescued_photos) == 2, "both photos must be MOVED into the rescue folder"
        assert not list(dirs["photos"].rglob("*.jpg")), (
            "no photo may be left behind at the original location"
        )

        readme = (rescue[0] / RESCUE_README_NAME).read_text(encoding="utf-8")
        assert str(rescue[0] / "photos") in readme
        assert "photos_root" in readme, "README must explain how to reconnect a fresh install"

    def test_rescue_happens_before_deletion_and_data_survives_photos_loss(
        self, tmp_path, fake_home, stub_hooks, answers
    ):
        """Data (index.db/captures.jsonl) is rescued even when photos are deleted."""
        paths, cfg, dirs = _make_install(tmp_path)
        answers("y", "y")  # proceed, and DO permanently delete the photos

        run_uninstall(paths, cfg)

        assert not dirs["photos"].exists(), "explicitly requested deletion must happen"
        rescue = _rescue_folders(fake_home)
        assert len(rescue) == 1
        assert not (rescue[0] / "photos").exists(), "deleted photos must not be rescued"
        assert (rescue[0] / "data" / "index.db").exists()
        assert (rescue[0] / "data" / "captures.jsonl").exists()
        assert (rescue[0] / "data" / "metadata").is_dir()

    def test_logs_are_never_rescued(
        self, tmp_path, fake_home, stub_hooks, answers
    ):
        paths, cfg, dirs = _make_install(tmp_path)
        answers("y", "")

        run_uninstall(paths, cfg)

        rescue = _rescue_folders(fake_home)[0]
        assert not (rescue / "data" / "logs").exists(), "logs are disposable"
        assert (rescue / "data" / "index.db").exists(), "real data IS rescued"
        # data_dir lives outside install_dir here, so the skipped logs dir is
        # left where it was (only install_dir is pruned). Under the default
        # layout, where data_dir is inside install_dir, the same skip means the
        # logs are deleted with the rest of the install - see the
        # photos_inside_install_dir test.
        assert (dirs["logs"] / "app.log").exists()

    def test_failed_rescue_preserves_the_original_data(
        self, tmp_path, fake_home, stub_hooks, answers, monkeypatch
    ):
        """If photos cannot be moved, they must survive the uninstall."""
        paths, cfg, dirs = _make_install(tmp_path)
        answers("y", "")

        def _boom(*a, **k):
            raise OSError("cross-device link failure")

        monkeypatch.setattr(shutil, "move", _boom)
        run_uninstall(paths, cfg)

        assert (dirs["photos"] / "2026" / "2026-08-24_120000.jpg").read_text(
            encoding="utf-8"
        ) == "photo-bytes"
        assert (dirs["data"] / "index.db").exists()
        # install_dir is not a parent of photos/data here, so it still goes
        assert not dirs["install"].exists()

    def test_incomplete_rescue_verification_keeps_source(
        self, tmp_path, fake_home, stub_hooks, answers, monkeypatch
    ):
        """A move that silently loses files must not count as rescued.

        Photos live inside install_dir here, so if the verification step is
        bypassed the uninstaller would delete the only surviving copy.
        """
        install = tmp_path / "install"
        _write(install / "photos" / "2026" / "a.jpg")
        _write(install / "photos" / "2026" / "b.jpg")
        _write(install / "data" / "index.db")
        _write(install / "DailySelfie.py")
        paths = type("P", (), {"app_name": "DailySelfie"})()
        cfg = {"installation": {"install_dir": str(install)}}
        answers("y", "")

        def _lossy_move(src, dst):
            # Copy only the first file and leave the source tree in place:
            # the destination file count will not match, which is exactly the
            # condition _move_subtree must refuse to accept.
            src_path, dst_path = Path(src), Path(dst)
            if src_path.is_dir():
                dst_path.mkdir(parents=True, exist_ok=True)
                files = [p for p in sorted(src_path.rglob("*")) if p.is_file()]
                shutil.copy2(files[0], dst_path / files[0].name)
            else:
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, dst_path)

        monkeypatch.setattr(shutil, "move", _lossy_move)
        run_uninstall(paths, cfg)

        # b.jpg never reached the rescue folder, so the source subtree must be
        # preserved rather than deleted.
        rescue = _rescue_folders(fake_home)[0]
        assert not (rescue / "photos" / "2026" / "b.jpg").exists()
        assert (install / "photos" / "2026" / "b.jpg").exists(), (
            "an unverified subtree must be preserved, not deleted"
        )
        assert install.exists(), "install_dir must survive an unverified rescue"
        # The rest of install_dir is still cleaned up.
        assert not (install / "DailySelfie.py").exists()

    def test_hooks_are_torn_down_before_rescue(
        self, tmp_path, fake_home, stub_hooks, answers
    ):
        paths, cfg, dirs = _make_install(tmp_path)
        answers("y", "")

        run_uninstall(paths, cfg)

        assert stub_hooks == [("autostart", False), ("desktop", False)]

    def test_hook_failure_does_not_abort_uninstall(
        self, tmp_path, fake_home, stub_hooks, answers, monkeypatch
    ):
        paths, cfg, dirs = _make_install(tmp_path)
        answers("y", "")

        def _boom(enabled):
            raise RuntimeError("no autostart subsystem")

        monkeypatch.setattr(uninstaller, "set_autostart", _boom)
        run_uninstall(paths, cfg)

        assert not dirs["install"].exists(), "uninstall must continue past a hook error"

    def test_cli_wrapper_is_removed(self, tmp_path, fake_home, stub_hooks, answers,
                                    monkeypatch):
        import platform as _platform

        if _platform.system().lower() == "windows":
            pytest.skip("POSIX wrapper path only")

        paths, cfg, dirs = _make_install(tmp_path)
        wrapper = _write(fake_home / ".local" / "bin" / "dailyselfie", "#!/bin/sh")
        answers("y", "")

        run_uninstall(paths, cfg)

        assert not wrapper.exists()

    def test_photos_inside_install_dir_are_rescued_then_removed(
        self, tmp_path, fake_home, stub_hooks, answers
    ):
        """Default layout: photos live under install_dir and still get rescued."""
        install = tmp_path / "install"
        _write(install / "photos" / "2026" / "a.jpg")
        _write(install / "data" / "index.db")
        _write(install / "data" / "logs" / "app.log")
        _write(install / "DailySelfie.py")
        paths = type("P", (), {"app_name": "DailySelfie"})()
        cfg = {"installation": {"install_dir": str(install)}}
        answers("y", "")

        run_uninstall(paths, cfg)

        rescue = _rescue_folders(fake_home)[0]
        assert (rescue / "photos" / "2026" / "a.jpg").read_text(encoding="utf-8") == "x"
        assert (rescue / "data" / "index.db").exists()
        assert not (rescue / "data" / "logs").exists(), "logs are never rescued"
        assert not install.exists(), "everything under install_dir is now disposable"

    def test_venv_is_removed_but_never_rescued(
        self, tmp_path, fake_home, stub_hooks, answers
    ):
        paths, cfg, dirs = _make_install(tmp_path)
        venv_python = dirs["install"] / "venv" / "bin" / "python"
        answers("y", "")

        run_uninstall(paths, cfg)

        assert not venv_python.exists()
        rescue = _rescue_folders(fake_home)[0]
        assert not (rescue / "venv").exists()

    def test_data_only_install_with_no_photos(
        self, tmp_path, fake_home, stub_hooks, answers
    ):
        """No photos -> no photo question is asked at all."""
        paths, cfg, dirs = _make_install(tmp_path, photos=False)
        answers("y")

        run_uninstall(paths, cfg)

        rescue = _rescue_folders(fake_home)[0]
        assert (rescue / "data" / "index.db").exists()
        assert not (rescue / "photos").exists()
        assert not dirs["install"].exists()

    def test_empty_photos_dir_does_not_trigger_the_delete_question(
        self, tmp_path, fake_home, stub_hooks, answers
    ):
        paths, cfg, dirs = _make_install(tmp_path, photos=False)
        dirs["photos"].mkdir(parents=True, exist_ok=True)  # exists but empty
        answers("y")  # if a second prompt were asked this would AssertionError

        run_uninstall(paths, cfg)

        assert not dirs["install"].exists()

    def test_rerunning_is_idempotent(
        self, tmp_path, fake_home, stub_hooks, answers
    ):
        paths, cfg, dirs = _make_install(tmp_path)
        answers("y", "")
        run_uninstall(paths, cfg)

        rescue_after_first = _rescue_folders(fake_home)
        assert len(rescue_after_first) == 1

        answers()  # second run must be a silent no-op: nothing left to uninstall
        run_uninstall(paths, cfg)

        assert not dirs["install"].exists()
        assert (rescue_after_first[0] / "data" / "index.db").exists()
        assert len(_rescue_folders(fake_home)) == 1, "second run must not add a folder"

    def test_rerun_after_photo_deletion_leaves_rescue_intact(
        self, tmp_path, fake_home, stub_hooks, answers
    ):
        paths, cfg, dirs = _make_install(tmp_path)
        answers("y", "y")
        run_uninstall(paths, cfg)

        answers()
        run_uninstall(paths, cfg)

        rescue = _rescue_folders(fake_home)[0]
        assert (rescue / "data" / "index.db").exists()
        assert len(_rescue_folders(fake_home)) == 1