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
import platform
from typing import Optional, Dict, Tuple


# Silence OpenCV V4L2 warnings globally
try:
    import cv2
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:
        cv2.setLogLevel(3)
except Exception:
    pass


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
        try:
            import cv2

        
        except Exception as e:
            raise RuntimeError(f"OpenCV (cv2) is required for camera operations: {e}")

        flags = 0
        if self.backend is not None:
            flags = self.backend
        else:
            if platform.system().lower() == "windows":
                # prefer DirectShow on Windows
                flags = cv2.CAP_DSHOW
            else:
                flags = cv2.CAP_ANY

        # VideoCapture accepts (index, apiPreference) in newer OpenCV
        try:
            self._cap = cv2.VideoCapture(self.index, flags)
        except TypeError:
            # older bindings may not accept two args
            self._cap = cv2.VideoCapture(self.index)

        if not self._cap or not self._cap.isOpened():
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
        ret, frame = self._cap.read()
        if not ret or frame is None:
            raise RuntimeError("Failed to read frame from camera")
        return frame

    def read_jpeg(self, quality: int = 90) -> bytes:
        """Capture one frame and return jpeg bytes encoded with given quality."""
        try:
            import cv2
            import numpy as np
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
    try:
        import cv2
    except Exception:
        return results

    for i in range(max_test):
        opened = False
        read_ok = False
        message = None
        try:
            backend = cv2.CAP_DSHOW if platform.system().lower() == "windows" else cv2.CAP_ANY
            try:
                cap = cv2.VideoCapture(i, backend)
            except TypeError:
                cap = cv2.VideoCapture(i)
            opened = bool(cap and cap.isOpened())
            if opened:
                ret, _ = cap.read()
                read_ok = bool(ret)
            try:
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
