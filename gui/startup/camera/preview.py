from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage
import time

from core.camera import Camera


class CameraPreviewThread(QThread):
    """
    Background camera preview thread.

    - Opens camera once
    - Continuously reads frames
    - Emits QImage for GUI
    """

    frame_ready = Signal(QImage)
    error = Signal(str)

    def __init__(self, *, camera_index=0, width=None, height=None, fps=30, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps
        self._running = False

    def run(self):
        self._running = True
        delay = 1.0 / max(1, self.fps)

        try:
            with Camera(
                index=self.camera_index,
                width=self.width,
                height=self.height,
            ) as cam:
                while self._running:
                    try:
                        frame = cam.read_frame()
                    except Exception as e:
                        self.error.emit(str(e))
                        break

                    # OpenCV gives BGR; Qt wants RGB
                    h, w, ch = frame.shape
                    bytes_per_line = ch * w

                    rgb_frame = frame[:, :, ::-1].copy()  # ensures C-contiguous memory

                    h, w, ch = rgb_frame.shape
                    bytes_per_line = ch * w

                    image = QImage(
                        rgb_frame.data,
                        w,
                        h,
                        bytes_per_line,
                        QImage.Format_RGB888,
                    )

                    # Emit a COPY so data is safe across threads
                    self.frame_ready.emit(image.copy())

                    time.sleep(delay)

        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        self._running = False
        self.wait(1000)
