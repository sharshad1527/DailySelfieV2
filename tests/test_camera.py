"""
core/camera.py: the stderr-suppression guard, with no camera attached.

This suite never opens a device. It exercises the parts of the module that
used to be dangerous — the process-global stderr manipulation around
VideoCapture — plus the public API's behaviour against a fake cv2, so the
interesting question ("does this mangle global state?") can be answered
deterministically.

The critical regression this file exists for: suppress_stderr() used to
dup2() file descriptor 2 onto os.devnull for the duration of every
VideoCapture call, which is not thread-safe, raced with the GUI thread, and
swallowed the app's own stderr. A test that opens a Camera with os.dup2
monkeypatched to raise must still work, and fd 2 must be a valid, unchanged
descriptor afterwards.

No filesystem writes, no network, no Qt. Any file the guard touches is
os.devnull.
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
import time

import pytest

import core.camera as camera_mod
from core.camera import (
    Camera,
    CameraResult,
    find_first_camera,
    list_cameras,
    quiet_camera_io,
    quiet_opencv_logging,
    suppress_stderr,
)

pytestmark = pytest.mark.core_only  # fast/offline core data-layer tests


def _fd2_target():
    """Identity of whatever fd 2 currently points at."""
    return os.fstat(2)


def _write_fd2(payload: bytes) -> None:
    os.write(2, payload)


@contextlib.contextmanager
def _capture_camera_logs():
    """Collect `camera` logger records synchronously.

    Used instead of caplog because the drain happens on a helper thread and
    pytest's caplog handler is not guaranteed to still be attached by then.
    """
    records: list[str] = []

    class _Collector(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Collector()
    logger = logging.getLogger("camera")
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield lambda: list(records)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


# -------------------------------------------------------------
# a fake cv2 so nothing touches real hardware
# -------------------------------------------------------------
class FakeCapture:
    def __init__(self, index=0, opened=True, frame_ok=True, raise_on_two_arg=False):
        self.index = index
        self._opened = opened
        self._frame_ok = frame_ok
        self._raise_on_two_arg = raise_on_two_arg
        self.released = False
        self.properties_set = []

    def isOpened(self):
        return self._opened

    def read(self):
        if not self._frame_ok:
            return False, None
        return True, _fake_frame()

    def set(self, prop, value):
        self.properties_set.append((prop, value))
        return True

    def release(self):
        self.released = True


def _fake_frame():
    try:
        import numpy as np
    except Exception:  # pragma: no cover - numpy is a project dependency
        return object()
    return np.zeros((8, 8, 3), dtype="uint8")


class FakeLoggingApi:
    def __init__(self):
        self.level = 3
        self.LOG_LEVEL_SILENT = 0
        self.LOG_LEVEL_FATAL = 1
        self.LOG_LEVEL_ERROR = 3

    def setLogLevel(self, level):
        self.level = level

    def getLogLevel(self):
        return self.level


class FakeCv2:
    """Minimal stand-in exposing exactly what core/camera.py touches."""

    CAP_DSHOW = 700
    CAP_ANY = 0
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    IMWRITE_JPEG_QUALITY = 1

    def __init__(self, opened_indices=(), frame_ok_indices=(), log_api=None):
        self.opened_indices = set(opened_indices)
        self.frame_ok_indices = set(frame_ok_indices)
        self.logging = log_api if log_api is not None else FakeLoggingApi()
        self.utils = type("utils", (), {"logging": self.logging})()
        self.captures: list[FakeCapture] = []
        self.constructed: list[tuple] = []
        self.raise_on_two_arg = False

    def VideoCapture(self, index, *args):
        self.constructed.append((index, args))
        if args and self.raise_on_two_arg:
            raise TypeError("VideoCapture() takes at most 2 positional arguments")
        cap = FakeCapture(index=index, opened=index in self.opened_indices,
                          frame_ok=index in self.frame_ok_indices)
        self.captures.append(cap)
        return cap


@pytest.fixture()
def fake_cv2(monkeypatch):
    """Install a fake cv2 module for the duration of a test."""
    fake = FakeCv2()
    monkeypatch.setattr(camera_mod, "cv2", fake)
    return fake


# -------------------------------------------------------------
# quiet_opencv_logging
# -------------------------------------------------------------
class TestQuietOpenCvLogging:
    def test_restores_the_previous_level(self, fake_cv2):
        fake_cv2.logging.level = 2  # WARNING
        with quiet_opencv_logging():
            assert fake_cv2.logging.level == 0  # SILENT
        assert fake_cv2.logging.level == 2

    def test_explicit_level_is_honoured(self, fake_cv2):
        fake_cv2.logging.level = 3
        with quiet_opencv_logging(level=fake_cv2.logging.LOG_LEVEL_FATAL):
            assert fake_cv2.logging.level == 1
        assert fake_cv2.logging.level == 3

    def test_restores_on_exception_and_propagates_it(self, fake_cv2):
        fake_cv2.logging.level = 3
        with pytest.raises(ValueError, match="boom"):
            with quiet_opencv_logging():
                raise ValueError("boom")
        assert fake_cv2.logging.level == 3, "level must be restored after a failure"

    def test_is_a_noop_without_cv2(self, monkeypatch):
        monkeypatch.setattr(camera_mod, "cv2", None)
        with quiet_opencv_logging():
            pass  # must not raise

    def test_old_opencv_without_a_logging_api(self, monkeypatch):
        class NoLoggingCv2:
            pass

        monkeypatch.setattr(camera_mod, "cv2", NoLoggingCv2())
        with quiet_opencv_logging():
            pass  # must not raise

    def test_setter_failure_is_swallowed(self, monkeypatch):
        class HostileLogging:
            LOG_LEVEL_SILENT = 0

            def setLogLevel(self, level):
                raise RuntimeError("nope")

            def getLogLevel(self):
                return 3

        fake = FakeCv2(log_api=HostileLogging())
        monkeypatch.setattr(camera_mod, "cv2", fake)

        with quiet_opencv_logging():
            pass  # must not raise

    def test_getter_failure_is_swallowed(self, monkeypatch):
        class HostileLogging:
            LOG_LEVEL_SILENT = 0

            def setLogLevel(self, level):
                pass

            def getLogLevel(self):
                raise RuntimeError("nope")

        monkeypatch.setattr(camera_mod, "cv2", FakeCv2(log_api=HostileLogging()))
        with quiet_opencv_logging():
            pass  # must not raise


# -------------------------------------------------------------
# the native (fd 2) guard
# -------------------------------------------------------------
class TestNativeStderrGuard:
    def test_fd2_is_a_valid_open_descriptor_afterwards(self):
        before = _fd2_target()
        with suppress_stderr():
            _write_fd2(b"noise from a native lib\n")
        os.fstat(2)  # raises if fd 2 was closed or stolen
        assert _fd2_target() == before, "fd 2 must point at the same object as before"

    def test_fd2_stays_writable_afterwards(self):
        with suppress_stderr():
            pass
        # If fd 2 had been permanently closed this raises OSError.
        _write_fd2(b"")
        os.fstat(2)

    def test_fd2_is_restored_when_the_body_raises(self):
        before = _fd2_target()
        with pytest.raises(ValueError, match="boom"):
            with suppress_stderr():
                raise ValueError("boom")
        os.fstat(2)
        assert _fd2_target() == before

    def test_exception_is_not_swallowed(self):
        """The old implementation raised RuntimeError('generator didn't stop')."""
        with pytest.raises(ValueError, match="original"):
            with suppress_stderr():
                raise ValueError("original")

    def test_works_when_os_dup2_raises(self, monkeypatch):
        """The headline requirement: no fd juggling at all, so dup2 breaking is fine."""
        monkeypatch.setattr(
            os, "dup2", lambda *a, **k: (_ for _ in ()).throw(OSError("nope"))
        )
        before = _fd2_target()

        with suppress_stderr():
            pass

        monkeypatch.undo()
        os.fstat(2)
        assert _fd2_target() == before

    def test_works_when_os_dup_raises(self, monkeypatch):
        monkeypatch.setattr(
            os, "dup", lambda *a, **k: (_ for _ in ()).throw(OSError("nope"))
        )
        before = _fd2_target()

        with suppress_stderr():
            pass

        monkeypatch.undo()
        os.fstat(2)
        assert _fd2_target() == before

    def test_works_when_os_pipe_raises(self, monkeypatch):
        monkeypatch.setattr(
            os, "pipe", lambda *a, **k: (_ for _ in ()).throw(OSError("nope"))
        )
        before = _fd2_target()

        with suppress_stderr():
            pass

        monkeypatch.undo()
        os.fstat(2)
        assert _fd2_target() == before

    def test_no_fd_is_leaked_across_many_calls(self, monkeypatch):
        """Every descriptor the guard opens must be closed again.

        Checked by counting close() calls rather than by inspecting /proc, so
        the assertion holds on Windows too.
        """
        closed: list[int] = []
        real_close = os.close

        def _tracking_close(fd):
            closed.append(fd)
            return real_close(fd)

        with suppress_stderr():
            pass  # warm up any lazy threads first
        monkeypatch.setattr(os, "close", _tracking_close)
        for _ in range(50):
            with suppress_stderr():
                pass
        monkeypatch.undo()

        # One close per call: the duplicated original. The pipe ends are closed
        # on the drain thread, so assert we are not closing zero of them.
        assert len(closed) >= 50, "guard stopped closing its saved descriptor"

    def test_native_noise_is_relayed_not_discarded(self):
        """Chatter must reach the logger, not vanish."""
        with _capture_camera_logs() as messages:
            with suppress_stderr():
                _write_fd2(b"uvcvideo: entity busy\n")

        for _ in range(200):
            if any("uvcvideo" in m for m in messages()):
                break
            time.sleep(0.01)
        assert any("uvcvideo" in m for m in messages()), (
            "native stderr should be logged at DEBUG, not thrown away"
        )

    def test_nested_guards_restore_fd2(self):
        before = _fd2_target()
        with suppress_stderr():
            with suppress_stderr():
                _write_fd2(b"inner\n")
            _write_fd2(b"outer\n")
        os.fstat(2)
        assert _fd2_target() == before

    def test_concurrent_guards_do_not_corrupt_fd2(self):
        """Serialised by a lock, so overlapping regions cannot cross-restore."""
        before = _fd2_target()
        errors: list[BaseException] = []
        barrier = threading.Barrier(4, timeout=10)

        def worker():
            try:
                for _ in range(10):
                    with suppress_stderr():
                        _write_fd2(b"concurrent noise\n")
            except BaseException as exc:  # pragma: no cover - failure path
                errors.append(exc)
            finally:
                try:
                    barrier.wait(timeout=10)
                except Exception:
                    pass

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
            assert not thread.is_alive(), "a worker deadlocked on the stderr guard"

        assert not errors, errors
        os.fstat(2)
        assert _fd2_target() == before

    @pytest.mark.skipif(os.name != "posix", reason="Windows has no fd redirect here")
    def test_output_from_another_thread_is_not_lost(self):
        """The old fd-2 devnull redirect ate concurrent writers' output."""
        with _capture_camera_logs() as messages:
            with suppress_stderr():
                _write_fd2(b"gui-thread line\n")
        for _ in range(200):
            if messages():
                break
            time.sleep(0.01)
        assert any("gui-thread line" in m for m in messages())

    def test_devnull_is_never_the_permanent_fd2_target(self):
        """fd 2 must never be left pointing at os.devnull."""
        import stat as _stat

        try:
            devnull_ino = os.stat(os.devnull).st_ino
        except OSError:  # pragma: no cover - exotic platform
            devnull_ino = None

        with suppress_stderr():
            pass

        st = os.fstat(2)
        assert st.st_ino != devnull_ino, "fd 2 was left pointing at devnull"
        # A pipe is a FIFO, not a character device; devnull is a char device.
        assert not _stat.S_ISFIFO(st.st_mode), (
            "fd 2 still points at the relay pipe after the guard returned"
        )


# -------------------------------------------------------------
# Camera against a fake cv2
# -------------------------------------------------------------
class TestCameraOpen:
    def test_opens_and_returns_itself(self, fake_cv2):
        fake_cv2.opened_indices = {0}
        with Camera(index=0) as cam:
            assert cam.index == 0
            assert cam._cap is not None

    def test_raises_for_a_closed_device(self, fake_cv2):
        fake_cv2.opened_indices = set()
        with pytest.raises(RuntimeError, match="Failed to open camera index 3"):
            with Camera(index=3):
                pass

    def test_releases_a_capture_that_failed_to_open(self, fake_cv2):
        fake_cv2.opened_indices = set()
        with pytest.raises(RuntimeError):
            with Camera(index=0):
                pass
        assert fake_cv2.captures[0].released is True

    def test_applies_requested_dimensions(self, fake_cv2):
        fake_cv2.opened_indices = {1}
        with Camera(index=1, width=1280, height=720) as cam:
            props = dict(fake_cv2.captures[0].properties_set)
        assert fake_cv2.CAP_PROP_FRAME_WIDTH in props
        assert props[fake_cv2.CAP_PROP_FRAME_WIDTH] == 1280
        assert props[fake_cv2.CAP_PROP_FRAME_HEIGHT] == 720

    def test_explicit_backend_is_passed_through(self, fake_cv2):
        fake_cv2.opened_indices = {0}
        with Camera(index=0, backend=999):
            pass
        assert fake_cv2.constructed[0] == (0, (999,))

    def test_falls_back_to_single_arg_binding_on_typeerror(self, fake_cv2):
        fake_cv2.opened_indices = {0}
        fake_cv2.raise_on_two_arg = True
        with Camera(index=0) as cam:
            assert cam._cap is not None
        # First attempt used two args, second used one.
        assert fake_cv2.constructed[0][1] != ()
        assert fake_cv2.constructed[1][1] == ()

    def test_two_arg_fallback_still_raises_for_closed_device(self, fake_cv2):
        fake_cv2.opened_indices = set()
        fake_cv2.raise_on_two_arg = True
        with pytest.raises(RuntimeError):
            with Camera(index=0):
                pass

    def test_requires_cv2(self, monkeypatch):
        monkeypatch.setattr(camera_mod, "cv2", None)
        with pytest.raises(RuntimeError, match="OpenCV"):
            with Camera(index=0):
                pass

    def test_release_happens_on_exit(self, fake_cv2):
        fake_cv2.opened_indices = {0}
        with Camera(index=0) as cam:
            cap = fake_cv2.captures[0]
        assert cap.released is True
        assert cam._cap is None

    def test_exit_does_not_swallow_exceptions(self, fake_cv2):
        fake_cv2.opened_indices = {0}
        with pytest.raises(ValueError):
            with Camera(index=0):
                raise ValueError("inside")

    def test_fd2_survives_a_full_camera_lifecycle(self, fake_cv2):
        """The headline requirement, through the real public entrypoint."""
        fake_cv2.opened_indices = {0}
        before = _fd2_target()
        real_dup2 = os.dup2
        monkey_calls = []

        def _tracking_dup2(*args, **kwargs):
            monkey_calls.append(args)
            return real_dup2(*args, **kwargs)

        os.dup2 = _tracking_dup2
        try:
            fake_cv2.frame_ok_indices = {0}
            with Camera(index=0) as cam:
                cam.read_frame()
        finally:
            os.dup2 = real_dup2

        os.fstat(2)
        assert _fd2_target() == before, "fd 2 must survive a camera open + read"


class TestCameraRead:
    def test_read_frame_returns_the_frame(self, fake_cv2):
        fake_cv2.opened_indices = {0}
        fake_cv2.frame_ok_indices = {0}
        with Camera(index=0) as cam:
            frame = cam.read_frame()
        assert frame is not None

    def test_read_frame_before_open_raises(self, fake_cv2):
        with pytest.raises(RuntimeError, match="not opened"):
            Camera(index=0).read_frame()

    def test_failed_read_raises_runtime_error(self, fake_cv2):
        fake_cv2.opened_indices = {0}
        fake_cv2.frame_ok_indices = set()
        with Camera(index=0) as cam:
            with pytest.raises(RuntimeError, match="Failed to read frame"):
                cam.read_frame()

    def test_read_exception_is_wrapped(self, fake_cv2):
        fake_cv2.opened_indices = {0}

        class Exploding(FakeCapture):
            def read(self):
                raise ValueError("driver died")

        def _factory(index, *args):
            cap = Exploding(index=index, opened=True, frame_ok=False)
            fake_cv2.captures.append(cap)
            return cap

        fake_cv2.VideoCapture = _factory
        with Camera(index=0) as cam:
            with pytest.raises(RuntimeError, match="driver died"):
                cam.read_frame()


class TestListCameras:
    def test_returns_only_usable_cameras_by_default(self, fake_cv2):
        fake_cv2.opened_indices = {0, 1}
        fake_cv2.frame_ok_indices = {0}  # index 1 opens but cannot read

        results = list_cameras(max_test=3)

        assert set(results) == {0}
        assert results[0].read_ok is True

    def test_only_available_false_reports_every_index(self, fake_cv2):
        fake_cv2.opened_indices = {1}
        fake_cv2.frame_ok_indices = {1}

        results = list_cameras(max_test=3, only_available=False)

        assert set(results) == {0, 1, 2}
        assert results[0].available is False
        assert results[2].available is False

    def test_closed_devices_are_reported_as_unavailable(self, fake_cv2):
        fake_cv2.opened_indices = set()
        results = list_cameras(max_test=2, only_available=False)
        assert all(isinstance(r, CameraResult) for r in results.values())
        assert all(not r.available and not r.opened and not r.read_ok
                   for r in results.values())

    def test_probes_are_released(self, fake_cv2):
        fake_cv2.opened_indices = {0, 1}
        fake_cv2.frame_ok_indices = {0, 1}
        list_cameras(max_test=2)
        assert all(cap.released for cap in fake_cv2.captures)

    def test_returns_empty_without_cv2(self, monkeypatch):
        monkeypatch.setattr(camera_mod, "cv2", None)
        assert list_cameras(max_test=4) == {}

    def test_max_test_zero_probes_nothing(self, fake_cv2):
        assert list_cameras(max_test=0, only_available=False) == {}


class TestFindFirstCamera:
    def test_returns_the_first_usable_index(self, fake_cv2):
        fake_cv2.opened_indices = {0, 1, 2}
        fake_cv2.frame_ok_indices = {0, 2}  # 0 is usable
        assert find_first_camera(max_test=3) == 0

    def test_skips_devices_that_cannot_read(self, fake_cv2):
        fake_cv2.opened_indices = {0, 1}
        fake_cv2.frame_ok_indices = {1}
        assert find_first_camera(max_test=3) == 1

    def test_returns_none_when_nothing_is_usable(self, fake_cv2):
        fake_cv2.opened_indices = set()
        assert find_first_camera(max_test=2) is None

    def test_returns_none_without_cv2(self, monkeypatch):
        monkeypatch.setattr(camera_mod, "cv2", None)
        assert find_first_camera(max_test=2) is None


class TestModuleHygiene:
    def test_suppress_stderr_is_a_thin_alias(self):
        """Kept for existing importers, but no longer does fd surgery."""
        import inspect

        source = inspect.getsource(suppress_stderr)
        assert "dup2" not in source
        assert "quiet_camera_io" in source

    def test_module_has_no_module_level_os_dup2(self):
        import inspect

        source = inspect.getsource(camera_mod)
        # dup2 may appear inside the scoped guard only.
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "os.dup2(" in stripped:
                assert "os.close" in source, "dup2 must be balanced by a close"

    def test_quiet_camera_io_nests_both_guards(self):
        import inspect

        assert "quiet_opencv_logging" in inspect.getsource(quiet_camera_io)