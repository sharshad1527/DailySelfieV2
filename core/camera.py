# core/camera.py

"""
camera.py

Camera utilities for DailySelfie.

Provides:
- Camera context manager for opening, configuring, and reading frames from a camera index
- list_cameras() to probe available camera indices
- find_first_camera() convenience to pick the first usable camera

Notes:
- This module depends on OpenCV (cv2). If cv2 is not installed users of this module
  will receive a clear RuntimeError asking them to install dependencies or create the venv.
- On Windows the default backend attempts to use CAP_DSHOW for faster camera access.
"""
from __future__ import annotations
from dataclasses import dataclass
import logging
import platform
import threading
from typing import Optional, Dict
import os
import contextlib

# Silence OpenCV's own logger once at import. This is the *supported* knob for
# the "V4L2: device busy" / DirectShow warnings that dominate camera probing,
# and unlike an fd redirect it is scoped to OpenCV's logging rather than to
# the whole process.
try:
    import cv2

    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:
        # fallback for older OpenCV
        try:
            cv2.setLogLevel(3)
        except Exception:
            pass
except Exception:
    cv2 = None  # type: ignore

logger = logging.getLogger("camera")


# -------------------------------------------------------------
# Helper: quiet the noisy parts of opening/reading a device
# -------------------------------------------------------------
@contextlib.contextmanager
def quiet_opencv_logging(level=None):
    """
    Temporarily drop OpenCV's log level around a noisy native call.

    OpenCV emits its device-probe chatter ("[ WARN:0] global/...", V4L2 and
    DirectShow warnings) through its own logger, so raising the threshold is
    the targeted fix: it silences exactly the messages we do not want, and
    nothing else. The previous level is restored in a finally, and an
    exception raised inside the block propagates untouched.

    The level is a single process-wide OpenCV setting, so a concurrent thread
    could in principle see the lower threshold for the duration. That window
    is a few hundred microseconds of logging noise (never data loss), and it
    is why this is preferable to the fd-2 redirect it replaces: that one
    swallowed *all* stderr, including the GUI thread's and our own log output.
    """
    if cv2 is None:
        yield
        return

    api = getattr(getattr(cv2, "utils", None), "logging", None)
    setter = getattr(api, "setLogLevel", None) or getattr(cv2, "setLogLevel", None)
    getter = getattr(api, "getLogLevel", None) or getattr(cv2, "getLogLevel", None)

    if setter is None or getter is None:
        # Old OpenCV with no logging API: nothing targeted to do.
        yield
        return

    if level is None:
        level = getattr(api, "LOG_LEVEL_SILENT", getattr(api, "LOG_LEVEL_FATAL", 3))

    try:
        previous = getter()
    except Exception:
        previous = None

    try:
        try:
            setter(level)
        except Exception:
            # Never fail a camera call because logging setup went wrong.
            pass
        yield
    finally:
        if previous is not None:
            try:
                setter(previous)
            except Exception:
                pass


# Serialises the fd-level guard below. The fd swap is process-wide by nature,
# so overlapping regions would restore each other's descriptor; one at a time.
_native_guard_lock = threading.RLock()


@contextlib.contextmanager
def _capture_native_stderr():
    """
    POSIX-only, scoped, non-destructive guard for output that bypasses Python.

    The V4L2/uvcvideo drivers print straight to file descriptor 2 from C
    (``ioctl(VIDIOC_QBUF): Bad file descriptor``), so OpenCV's logging API
    cannot suppress it. The old implementation solved that by dup2-ing fd 2
    onto os.devnull, which threw away *all* stderr for the duration: not
    thread-safe, racy against the GUI thread, and it silently ate the app's own
    log output.

    Instead this redirects fd 2 into an OS pipe and drains it on a helper
    thread into the module logger at DEBUG. Properties that matter:

    * Scoped: fd 2 is restored in a ``finally``, so an exception inside the
      block still restores it and still propagates.
      (The previous contextmanager swallowed the exception entirely and
      surfaced ``RuntimeError: generator didn't stop after throw()``.)
    * Non-destructive: nothing is lost; device chatter is logged instead of
      discarded, so it is still diagnosable.
    * Non-blocking: the pipe's write end is non-blocking, so a stalled drain
      thread degrades into dropped driver chatter rather than a hung GUI.
    * Serialised: a re-entrant lock keeps two overlapping regions from
      restoring each other's descriptor.
    * Best-effort: any failure to arrange the redirection just yields, leaving
      fd 2 completely untouched.

    On Windows, and whenever ``os.pipe``/``dup2`` are unavailable or fail,
    this is a no-op: there is no portable per-stream redirect, and mangling a
    shared descriptor to chase cosmetic noise is not worth it.
    """
    if os.name != "posix" or not hasattr(os, "pipe"):
        yield
        return

    with _native_guard_lock:
        try:
            saved_fd = os.dup(2)
        except OSError:
            yield
            return

        read_fd = write_fd = None
        drained = threading.Event()
        try:
            try:
                read_fd, write_fd = os.pipe()
                os.set_blocking(write_fd, False)
                os.dup2(write_fd, 2)
            except (OSError, ValueError, AttributeError):
                # Could not redirect: leave fd 2 exactly as we found it.
                yield
                return

            def _drain():
                try:
                    while True:
                        try:
                            chunk = os.read(read_fd, 4096)
                        except (OSError, BlockingIOError):
                            break
                        if not chunk:
                            break
                        logger.debug("camera native stderr: %s",
                                     chunk.decode("utf-8", "replace").rstrip())
                finally:
                    drained.set()

            reader = threading.Thread(target=_drain, name="ds-camera-stderr",
                                      daemon=True)
            reader.start()
            try:
                yield
            finally:
                # Restore first so the driver writes to the real stderr again,
                # then let the drain thread finish the tail of the pipe.
                os.dup2(saved_fd, 2)
                try:
                    os.close(write_fd)
                except OSError:
                    pass
                write_fd = None
                drained.wait(timeout=1.0)
        finally:
            try:
                os.dup2(saved_fd, 2)
            except (OSError, ValueError):
                pass
            for fd in (saved_fd, write_fd, read_fd):
                if fd is None:
                    continue
                try:
                    os.close(fd)
                except OSError:
                    pass


@contextlib.contextmanager
def quiet_camera_io():
    """
    Silence the noisy parts of a VideoCapture open/read without destroying stderr.

    Combines the two mechanisms that actually address the two different sources
    of chatter: OpenCV's own logger (:func:`quiet_opencv_logging`) and C-level
    driver writes to fd 2 (:func:`_capture_native_stderr`).
    """
    with quiet_opencv_logging():
        with _capture_native_stderr():
            yield


@contextlib.contextmanager
def suppress_stderr():
    """
    Backwards-compatible alias for :func:`quiet_camera_io`.

    Kept because the name was imported by name in a few places; the fd-2
    destruction it used to do is gone. This now routes driver noise to the
    logger at DEBUG instead of discarding it.
    """
    with quiet_camera_io():
        yield


@dataclass
class CameraResult:
    index: int
    available: bool
    opened: bool
    read_ok: bool
    message: Optional[str] = None


class Camera:
    """Context manager that wraps cv2.VideoCapture with safe open/close semantics.

    Usage:
        with Camera(index=0, width=1280, height=720) as cam:
            frame = cam.read_frame()  # numpy array
            jpeg = cam.read_jpeg()
    """

    def __init__(self, index: int = 0, width: Optional[int] = None, height: Optional[int] = None, backend: Optional[int] = None):
        self.index = int(index)
        self.width = width
        self.height = height
        self.backend = backend
        self._cap = None

    def __enter__(self):
        if cv2 is None:
            raise RuntimeError("OpenCV (cv2) is required for camera operations")

        flags = 0
        if self.backend is not None:
            flags = self.backend
        else:
            if platform.system().lower() == "windows":
                # prefer DirectShow on Windows
                flags = cv2.CAP_DSHOW
            else:
                flags = cv2.CAP_ANY

        # VideoCapture accepts (index, apiPreference) in newer OpenCV.
        # quiet_camera_io only redirects output, never state the capture needs,
        # so a failure there must not cost us the handle.
        with quiet_camera_io():
            try:
                self._cap = cv2.VideoCapture(self.index, flags)
            except TypeError:
                # older bindings may not accept two args
                try:
                    self._cap = cv2.VideoCapture(self.index)
                except Exception:
                    self._cap = None
            except Exception:
                # last resort: no backend hint at all
                try:
                    self._cap = cv2.VideoCapture(self.index)
                except Exception:
                    self._cap = None

        if not self._cap or not self._cap.isOpened():
            # Ensure we release if it was somehow created but not opened properly
            if self._cap:
                try:
                    self._cap.release()
                except Exception:
                    pass
            self._cap = None
            raise RuntimeError(f"Failed to open camera index {self.index}")

        if self.width:
            try:
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(self.width))
            except Exception:
                pass
        if self.height:
            try:
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(self.height))
            except Exception:
                pass

        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
        finally:
            return False  # do not suppress exceptions

    def read_frame(self):
        """Return the next camera frame as a numpy array. Raises RuntimeError on failure."""
        if self._cap is None:
            raise RuntimeError("Camera not opened")
        # reading can also emit native warnings — quiet them
        try:
            with quiet_camera_io():
                ret, frame = self._cap.read()
        except Exception as e:
            raise RuntimeError(f"Failed to read frame from camera: {e}")
        if not ret or frame is None:
            raise RuntimeError("Failed to read frame from camera")
        return frame

    def read_jpeg(self, quality: int = 90) -> bytes:
        """Capture one frame and return jpeg bytes encoded with given quality."""
        try:
            import numpy as np  # noqa: F401
        except Exception as e:
            raise RuntimeError(f"Dependencies missing for jpeg encoding: {e}")

        frame = self.read_frame()
        ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        if not ok:
            raise RuntimeError("JPEG encode failed")
        return buf.tobytes()


def list_cameras(max_test: int = 8, only_available: bool = True) -> Dict[int, CameraResult]:
    """
    Probe camera indices 0..max_test-1 and return index->CameraResult.
    If only_available is True, callers should filter and display only those with available & read_ok.
    """
    results: Dict[int, CameraResult] = {}
    if cv2 is None:
        return results

    for i in range(max_test):
        opened = False
        read_ok = False
        message = None
        try:
            backend = cv2.CAP_DSHOW if platform.system().lower() == "windows" else cv2.CAP_ANY
            with quiet_camera_io():
                try:
                    cap = cv2.VideoCapture(i, backend)
                except TypeError:
                    try:
                        cap = cv2.VideoCapture(i)
                    except Exception as e:
                        cap = None
                        message = str(e)
                except Exception as e:
                    cap = None
                    message = str(e)

            opened = bool(cap and cap.isOpened())
            if opened:
                try:
                    with quiet_camera_io():
                        ret, _ = cap.read()
                except Exception:
                    ret = False
                read_ok = bool(ret)
            try:
                if cap:
                    cap.release()
            except Exception:
                pass
        except Exception as e:
            message = str(e)
        results[i] = CameraResult(index=i, available=opened, opened=opened, read_ok=read_ok, message=message)

    if only_available:
        # shrink to only usable cameras
        return {i: r for i, r in results.items() if r.available and r.read_ok}
    return results


def find_first_camera(max_test: int = 8) -> Optional[int]:
    """Return the index of the first camera that can be opened and read, or None."""
    cams = list_cameras(max_test=max_test)
    for idx, r in cams.items():
        if r.available and r.read_ok:
            return idx
    return None


if __name__ == "__main__":
    # quick smoke test
    cams = list_cameras(6)
    if not cams:
        print("OpenCV not installed or no cameras detected")
    else:
        for i, res in cams.items():
            print(f"{i}: available={res.available} read_ok={res.read_ok} msg={res.message}")
        first = find_first_camera(6)
        print("first usable camera:", first)
