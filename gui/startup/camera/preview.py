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
        try:
            with Camera(index=self.camera_index, width=self.width, height=self.height) as cam:
                while self._running:
                    try:
                        frame = cam.read_frame()
                        h, w, ch = frame.shape
                        rgb = frame[:, :, ::-1].copy()
                        
                        qt_img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
                        self.frame_ready.emit(qt_img.copy())
                        time.sleep(0.03)
                    except Exception as e:
                        self.error_occurred.emit(str(e))
                        break
        except Exception as e:
            self.error_occurred.emit(f"Camera open failed: {e}")

    def stop(self):
        self._running = False
        self.wait(1000)