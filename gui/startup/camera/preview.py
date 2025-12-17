from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QImage
import time
from core.camera import Camera
import cv2
import numpy as np

class CameraPreviewThread(QThread):
    frame_ready = Signal(QImage)
    error_occurred = Signal(str)

    def __init__(self, camera_index=0, width=None, height=None, fps=30, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self._target_interval = 1.0 / fps
        self._running = False

    def run(self):
        self._running = True
        consecutive_errors = 0
        max_retries = 50

        try:
            with Camera(index=self.camera_index, width=self.width, height=self.height) as cam:
                # Camera opened successfully, now enter the read loop
                # Warmup
                time.sleep(0.3)

                while self._running:
                    start_time = time.time()
                    try:
                        frame = cam.read_frame()
                        
                        # Reset error counter
                        consecutive_errors = 0
                        
                        h, w, ch = frame.shape
                        bytes_per_line = ch * w
                        
                        # Convert BGR to RGB efficiently
                        # We create a new array here, but avoiding double copies where possible
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        
                        # Create QImage from data.
                        # QImage(data, w, h, fmt) references data, so we must ensure 'rgb' stays alive
                        # OR we copy it. Since we emit it across threads, .copy() is required eventually.
                        # The most efficient way for thread safety is QImage(rgb.data, ...).copy()
                        qt_img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()

                        self.frame_ready.emit(qt_img)

                        # Calculate sleep to maintain target FPS
                        elapsed = time.time() - start_time
                        sleep_time = max(0.001, self._target_interval - elapsed)
                        time.sleep(sleep_time)

                    except Exception as e:
                        consecutive_errors += 1
                        
                        if consecutive_errors < max_retries:
                            time.sleep(0.1)
                            continue
                        
                        self.error_occurred.emit(f"Stream died: {e}")
                        break

        except Exception as e:
            self.error_occurred.emit(f"Camera open failed: {e}")

    def stop(self):
        self._running = False
        self.wait(1000)
