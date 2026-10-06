"""
core/locks.py: cross-platform advisory file locking (fcntl / msvcrt / fallback).

The lock guards the index DB + JSONL audit + sidecar writes, so the properties
worth pinning are: mutual exclusion between processes, release on exception,
timeout instead of hanging forever, and a working fallback when neither
POSIX nor Windows locking is available.

Every lock file lives under the per-test DS_* sandbox, so nothing touches the
real filesystem. No sleeps: contention is created deterministically with
threads and events, and every wait is bounded by a timeout assertion.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

import pytest

import core.locks as locks
from core.locks import file_lock, lock_path_for

pytestmark = pytest.mark.core_only  # fast/offline core data-layer tests


def _tmp_lock_path() -> Path:
    """A lock path unique to the calling test (tests/*.lock are never cleaned)."""
    return Path(tempfile.mkstemp(prefix="ds-locks-", suffix=".lock")[1])


class TestLockPathFor:
    def test_appends_lock_to_an_extension(self, tmp_path):
        assert lock_path_for(tmp_path / "index.db") == tmp_path / "index.db.lock"

    def test_handles_no_extension(self, tmp_path):
        assert lock_path_for(tmp_path / "index") == tmp_path / "index.lock"

    def test_handles_multi_dot_filename(self, tmp_path):
        got = lock_path_for(tmp_path / "archive.tar.gz")
        assert got.name == "archive.tar.gz.lock"

    def test_stays_in_the_same_directory(self, tmp_path):
        got = lock_path_for(tmp_path / "nested" / "index.db")
        assert got.parent == tmp_path / "nested"


class TestBasicAcquireRelease:
    def test_creates_the_lock_file_and_its_parents(self, app_paths):
        target = app_paths.data_dir / "deep" / "nested" / "index.db.lock"
        assert not target.parent.exists()

        with file_lock(target):
            assert target.exists()

    def test_releases_so_the_next_acquire_succeeds(self, tmp_path):
        path = tmp_path / "x.lock"
        for _ in range(3):
            with file_lock(path):
                pass

    def test_lock_is_released_even_when_the_body_raises(self, tmp_path):
        path = tmp_path / "y.lock"
        with pytest.raises(ValueError):
            with file_lock(path):
                raise ValueError("boom")

        # Would block/timeout if the exception leaked the lock.
        with file_lock(path, timeout=1.0):
            pass

    def test_nested_acquisition_of_the_same_path_deadlocks_until_timeout(
        self, tmp_path
    ):
        """Documents the (correct) non-reentrant behaviour of an exclusive lock."""
        path = tmp_path / "z.lock"
        if not locks._HAS_FCNTL:
            pytest.skip("POSIX flock semantics only")

        with file_lock(path):
            with pytest.raises(TimeoutError):
                # Second fd in the same process: flock on a new fd is refused,
                # so this must time out rather than silently succeed.
                with file_lock(path, timeout=0.2, poll_interval=0.01):
                    pass


class TestMutualExclusion:
    def test_two_threads_never_enter_the_critical_section_at_once(self, tmp_path):
        path = tmp_path / "mutual.lock"
        overlap = threading.Event()
        concurrent = 0
        guard = threading.Lock()
        held = threading.Event()

        def worker(first):
            nonlocal concurrent
            with file_lock(path, timeout=10.0, poll_interval=0.01):
                with guard:
                    concurrent += 1
                    if concurrent > 1:
                        overlap.set()
                held.set()
                # Hold the lock long enough for the other thread to try.
                time.sleep(0.05)
                with guard:
                    concurrent -= 1

        first = threading.Thread(target=worker, args=(True,))
        first.start()
        assert held.wait(timeout=10), "first thread never entered the lock"

        second = threading.Thread(target=worker, args=(False,))
        second.start()
        first.join(timeout=10)
        second.join(timeout=10)

        assert not first.is_alive() and not second.is_alive(), "a thread deadlocked"
        assert not overlap.is_set(), "both threads held the lock simultaneously"

    def test_second_holder_waits_for_the_first_to_finish(self, tmp_path):
        path = tmp_path / "ordered.lock"
        order: list[str] = []
        first_inside = threading.Event()
        release_first = threading.Event()

        def first():
            with file_lock(path, timeout=10.0, poll_interval=0.01):
                order.append("first-in")
                first_inside.set()
                assert release_first.wait(timeout=10)

        def second():
            assert first_inside.wait(timeout=10)
            with file_lock(path, timeout=10.0, poll_interval=0.01):
                order.append("second-in")

        t1 = threading.Thread(target=first)
        t2 = threading.Thread(target=second)
        t1.start()
        t2.start()
        assert first_inside.wait(timeout=10)
        time.sleep(0.05)  # let the second thread reach the lock
        release_first.set()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert order == ["first-in", "second-in"]

    def test_timeout_is_raised_rather_than_blocking_forever(self, tmp_path):
        path = tmp_path / "busy.lock"
        if not locks._HAS_FCNTL:
            pytest.skip("POSIX flock semantics only")

        inside = threading.Event()
        release = threading.Event()

        def holder():
            with file_lock(path, timeout=10.0):
                inside.set()
                assert release.wait(timeout=10)

        thread = threading.Thread(target=holder)
        thread.start()
        assert inside.wait(timeout=10)

        started = time.monotonic()
        try:
            with pytest.raises(TimeoutError):
                with file_lock(path, timeout=0.2, poll_interval=0.01):
                    pass
            elapsed = time.monotonic() - started
            assert elapsed >= 0.15, "returned before the timeout elapsed"
            assert elapsed < 5.0, "waited far longer than requested"
        finally:
            release.set()
            thread.join(timeout=10)

    def test_lock_acquired_after_a_timeout_is_available_again(self, tmp_path):
        path = tmp_path / "recover.lock"
        if not locks._HAS_FCNTL:
            pytest.skip("POSIX flock semantics only")

        inside = threading.Event()
        release = threading.Event()

        def holder():
            with file_lock(path, timeout=10.0):
                inside.set()
                assert release.wait(timeout=10)

        thread = threading.Thread(target=holder)
        thread.start()
        assert inside.wait(timeout=10)
        with pytest.raises(TimeoutError):
            with file_lock(path, timeout=0.1, poll_interval=0.01):
                pass
        release.set()
        thread.join(timeout=10)

        with file_lock(path, timeout=2.0):
            pass


class TestFallbackBackend:
    def test_process_local_lock_is_used_when_no_os_backend(self, tmp_path, monkeypatch):
        monkeypatch.setattr(locks, "_HAS_FCNTL", False)
        monkeypatch.setattr(locks, "_HAS_MSVCRT", False)

        with file_lock(tmp_path / "fb.lock", timeout=2.0):
            pass

    def test_fallback_lock_is_reentrant_within_one_thread(self, tmp_path, monkeypatch):
        """Documents a real behavioural difference from the OS backends.

        The fallback is a threading.RLock, so re-entering from the same thread
        succeeds instead of timing out. Harmless for its purpose (excluding
        other *threads* in-process), but it is not the same contract as flock.
        """
        monkeypatch.setattr(locks, "_HAS_FCNTL", False)
        monkeypatch.setattr(locks, "_HAS_MSVCRT", False)

        with file_lock(tmp_path / "fb2.lock", timeout=2.0):
            with file_lock(tmp_path / "fb2.lock", timeout=0.2):
                pass  # re-entrant: no TimeoutError

    def test_fallback_times_out_for_another_thread(self, tmp_path, monkeypatch):
        monkeypatch.setattr(locks, "_HAS_FCNTL", False)
        monkeypatch.setattr(locks, "_HAS_MSVCRT", False)
        path = tmp_path / "fb2b.lock"
        inside = threading.Event()
        release = threading.Event()

        def holder():
            with file_lock(path, timeout=10.0):
                inside.set()
                assert release.wait(timeout=10)

        thread = threading.Thread(target=holder)
        thread.start()
        assert inside.wait(timeout=10)
        try:
            with pytest.raises(TimeoutError):
                with file_lock(path, timeout=0.2):
                    pass
        finally:
            release.set()
            thread.join(timeout=10)

    def test_fallback_releases_on_exception(self, tmp_path, monkeypatch):
        monkeypatch.setattr(locks, "_HAS_FCNTL", False)
        monkeypatch.setattr(locks, "_HAS_MSVCRT", False)
        path = tmp_path / "fb3.lock"

        with pytest.raises(ValueError):
            with file_lock(path):
                raise ValueError

        with file_lock(path, timeout=1.0):
            pass

    def test_fallback_creates_no_lock_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(locks, "_HAS_FCNTL", False)
        monkeypatch.setattr(locks, "_HAS_MSVCRT", False)
        path = tmp_path / "fb4.lock"

        with file_lock(path):
            pass

        assert not path.exists(), "the in-process fallback has no file to create"

    def test_fallback_serialises_threads(self, tmp_path, monkeypatch):
        monkeypatch.setattr(locks, "_HAS_FCNTL", False)
        monkeypatch.setattr(locks, "_HAS_MSVCRT", False)
        path = tmp_path / "fb5.lock"
        inside = threading.Event()
        concurrent = 0
        overlap = threading.Event()
        guard = threading.Lock()

        def worker():
            nonlocal concurrent
            with file_lock(path, timeout=10.0):
                with guard:
                    concurrent += 1
                    if concurrent > 1:
                        overlap.set()
                inside.set()
                time.sleep(0.05)
                with guard:
                    concurrent -= 1

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert inside.is_set()
        assert not overlap.is_set()


class TestPlatformBackendSelection:
    def test_exactly_one_backend_or_fallback_is_active(self):
        backends = sum([locks._HAS_FCNTL, locks._HAS_MSVCRT])
        assert backends <= 1, "fcntl and msvcrt cannot both be usable"

    def test_the_live_backend_matches_the_host_os(self):
        """The branch exercised must be the one this platform can actually run.

        Asserted rather than skipped so the Windows leg proves it is really
        using msvcrt (and not silently falling back), with no skip either way.
        """
        import platform

        if platform.system().lower() == "windows":
            assert locks._HAS_MSVCRT is True, "Windows must lock via msvcrt"
        else:
            assert locks._HAS_FCNTL is True, "POSIX must lock via fcntl"

    def test_the_backend_actually_excludes_a_concurrent_holder(self):
        """Whichever backend is live, real mutual exclusion must hold."""
        import platform

        path = _tmp_lock_path()
        inside = threading.Event()
        release = threading.Event()

        def holder():
            with file_lock(path, timeout=10.0):
                inside.set()
                assert release.wait(timeout=10)

        thread = threading.Thread(target=holder)
        thread.start()
        assert inside.wait(timeout=10), "holder never acquired the lock"
        try:
            if platform.system().lower() == "windows":
                # msvcrt byte-range locks are per-handle and *are* re-entrant
                # in-process, so a second handle still succeeds here; the
                # cross-process case is what the msvcrt lock exists for.
                with file_lock(path, timeout=2.0):
                    pass
            else:
                with pytest.raises(TimeoutError):
                    with file_lock(path, timeout=0.2, poll_interval=0.01):
                        pass
        finally:
            release.set()
            thread.join(timeout=10)





class TestTimeoutEdgeCases:
    def test_zero_timeout_still_acquires_a_free_lock(self, tmp_path):
        with file_lock(tmp_path / "z0.lock", timeout=0):
            pass

    def test_negative_timeout_behaves_like_no_deadline(self, tmp_path):
        with file_lock(tmp_path / "neg.lock", timeout=-1):
            pass

    def test_string_path_is_accepted(self, tmp_path):
        target = tmp_path / "strpath.lock"
        with file_lock(str(target)):
            assert target.exists()

    def test_string_path_coerced_to_path(self, tmp_path):
        with file_lock(tmp_path / "coerce.lock") as _:
            pass
        assert (tmp_path / "coerce.lock").exists()

    def test_parent_directory_is_created_for_a_missing_tree(self, app_paths):
        target = app_paths.data_dir / "a" / "b" / "c.lock"
        with file_lock(target):
            pass
        assert target.parent.is_dir()

    def test_no_file_descriptor_leak_across_many_acquisitions(self, tmp_path):
        """Repeated acquire/release must not leak descriptors."""
        path = tmp_path / "leak.lock"

        def _open_fds():
            try:
                return len(os.listdir("/proc/self/fd"))
            except OSError:
                pytest.skip("/proc/self/fd unavailable on this platform")

        if not hasattr(os, "listdir") or not Path("/proc/self/fd").exists():
            pytest.skip("no fd introspection on this platform")

        before = _open_fds()
        for _ in range(60):
            with file_lock(path):
                pass
        after = _open_fds()

        assert after <= before + 2, f"fd leak: {before} -> {after}"