# tests/test_data_loss_regressions.py
"""
Regression tests for silent photo destruction.

Both cases here were found by audit after the merge and each destroyed a real
user photo while reporting success. They are cheap to test, so they are pinned
rather than left to a code comment.

    - test_uninstaller: a hand-edited photos_root could be rmtree'd unguarded.
    - storage: two captures in the same second shared a filename and the second
      atomic_write() replaced the first.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from core import storage, uninstaller

pytestmark = pytest.mark.core_only


class TestUninstallerRefusesDangerousTargets:
    """`_is_safe_to_delete` is the only thing between config.toml and rmtree."""

    @pytest.mark.parametrize("label,make", [
        ("home itself", lambda h: h),
        ("home's parent", lambda h: h.parent),
        ("~/.local/share", lambda h: h / ".local" / "share"),
        ("~/.config", lambda h: h / ".config"),
        ("filesystem root", lambda h: Path("/")),
        ("/etc", lambda h: Path("/etc")),
        ("/usr", lambda h: Path("/usr")),
    ])
    def test_refused(self, tmp_path, label, make):
        home = tmp_path / "home"
        home.mkdir()
        os.environ["HOME"] = str(home)
        os.environ["USERPROFILE"] = str(home)
        try:
            target = make(home)
            assert not uninstaller._is_safe_to_delete(target), (
                f"{label} must never be deletable"
            )
        finally:
            os.environ.pop("HOME", None)
            os.environ.pop("USERPROFILE", None)

    @pytest.mark.parametrize("rel", [
        "Pictures/DailySelfie",
        ".local/share/DailySelfie",
        ".local/share/DailySelfie/photos",
    ])
    def test_legitimate_app_dirs_still_allowed(self, tmp_path, rel):
        """The guard must not make the app uninstallable."""
        home = tmp_path / "home"
        target = home / rel
        target.mkdir(parents=True)
        os.environ["HOME"] = str(home)
        os.environ["USERPROFILE"] = str(home)
        try:
            assert uninstaller._is_safe_to_delete(target)
        finally:
            os.environ.pop("HOME", None)
            os.environ.pop("USERPROFILE", None)


class TestRunUninstallProtectsPhotosRoot:
    """Step 5 must apply the guard before deleting an external photos dir."""

    def test_broad_photos_root_is_refused_and_files_survive(
            self, tmp_path, ds_sandbox, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))

        photos = home / ".local" / "share"   # holds app state -> must be refused
        photos.mkdir(parents=True)
        keep = photos / "not-ours.jpg"
        keep.write_bytes(b"\xff\xd8PRECIOUS")

        install = tmp_path / "install"
        (install / "data").mkdir(parents=True)
        cfg = {"installation": {
            "install_dir": str(install),
            "photos_root": str(photos),
            "data_dir": str(install / "data"),
            "logs_dir": str(install / "data" / "logs"),
        }}
        monkeypatch.setattr(uninstaller, "_confirm",
                            lambda prompt, default=False: True)
        monkeypatch.setattr(uninstaller, "set_autostart", lambda e: None)
        monkeypatch.setattr(uninstaller, "set_desktop_entry", lambda e: None)
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")

        uninstaller.run_uninstall(ds_sandbox, cfg)

        assert keep.exists(), (
            "run_uninstall deleted a photos_root that holds app state"
        )


class TestSameSecondCapturesDoNotCollide:
    """Two captures in the same second must both survive.

    Filenames have one-second resolution and atomic_write() replaces
    unconditionally, so same-second writes used to destroy the earlier photo
    while BOTH callers got success=True.
    """

    def test_unique_save_path_picks_a_free_name(self, tmp_path):
        base = tmp_path / "f.jpg"
        assert not base.exists()
        chosen = storage.unique_save_path(tmp_path, "f.jpg")
        assert chosen == base                      # nothing there yet

        base.write_bytes(b"first")
        second = storage.unique_save_path(tmp_path, "f.jpg")
        assert second != base
        assert not second.exists()

        second.write_bytes(b"second")
        third = storage.unique_save_path(tmp_path, "f.jpg")
        assert third not in (base, second)

    def test_three_same_second_saves_all_retained(self, app_paths):
        ts = datetime(2026, 10, 8, 22, 30, 15)     # one frozen second
        payloads = [b"\xff\xd8AAAA-FIRST", b"\xff\xd8BBBB-SECOND",
                    b"\xff\xd8CCCC-THIRD"]

        results = [storage.save_image_bytes(app_paths.photos_root, ts, p)
                   for p in payloads]

        assert all(r.success for r in results)
        paths = [r.path for r in results]
        assert len(set(paths)) == 3, f"captures collided: {paths}"

        folder = storage.year_month_folder(app_paths.photos_root, ts)
        blob = b"".join(p.read_bytes() for p in folder.iterdir())
        for payload in payloads:
            assert payload in blob, f"lost {payload!r} to a same-second collision"

    def test_a_retake_leaves_exactly_one_file(self, app_paths):
        """Dedup must not make retakes accumulate.

        commit_capture_from_bytes saves the new frame BEFORE retiring the old
        one, so the new file legitimately picks up a -2 suffix and the old file
        is then deleted. The invariant that matters is that exactly one photo
        survives a retake -- not that the surviving name is unsuffixed.
        """
        from core.capture import commit_capture_from_bytes

        first = commit_capture_from_bytes(app_paths, jpeg_bytes=b"\xff\xd8OLD",
                                          width=8, height=8, allow_retake=True,
                                          one_photo_per_day=False)
        assert first["success"]
        second = commit_capture_from_bytes(app_paths, jpeg_bytes=b"\xff\xd8NEW",
                                           width=8, height=8, allow_retake=True,
                                           one_photo_per_day=False)
        assert second["success"]

        photos = sorted(p for p in Path(app_paths.photos_root).rglob("*.jpg"))
        assert len(photos) == 1, f"retake left {len(photos)} files: {photos}"
        assert photos[0].read_bytes() == b"\xff\xd8NEW"
        assert not Path(first["path"]).exists(), "retired photo was not deleted"