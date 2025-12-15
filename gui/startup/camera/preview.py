from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage
import time
from core.camera import Camera

class CameraPreviewThread(QThread):
    frame_ready = Signal(QImage)
    error_occurred = Signal(str)

    def __init__(self, camera_index=0, width=None, height=None, fps=30, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self._running = False

    def run(self):
        self._running = True
        consecutive_errors = 0
        max_retries = 20  # Allow 20 failed frames (approx 2-3 seconds of warm-up)

        try:
            with Camera(index=self.camera_index, width=self.width, height=self.height) as cam:
                # Camera opened successfully, now enter the read loop
                while self._running:
                    try:
                        frame = cam.read_frame()
                        
                        # [FIX] Success! Reset error counter
                        consecutive_errors = 0
                        
                        h, w, ch = frame.shape
                        rgb = frame[:, :, ::-1].copy()
                        
                        qt_img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
                        self.frame_ready.emit(qt_img.copy())
                        
                        time.sleep(0.03)

                    except Exception as e:
                        # [FIX] Don't crash immediately. Count errors.
                        consecutive_errors += 1
                        
                        # If we just started or it's a hiccup, wait a bit and retry
                        if consecutive_errors < max_retries:
                            time.sleep(0.1)  # Give the camera 100ms to wake up
                            continue
                        
                        # Only give up if it fails consistently
                        self.error_occurred.emit(f"Stream died: {e}")
                        break

        except Exception as e:
            # This handles if the camera device itself cannot be opened (e.g. index not found)
            self.error_occurred.emit(f"Camera open failed: {e}")

    def stop(self):
        self._running = False
        self.wait(1000)