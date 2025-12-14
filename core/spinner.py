# core/spinner.py
import sys
import threading
import time
import itertools

class Spinner:
    def __init__(self, message: str):
        self.message = message
        self._stop = threading.Event()
        self._thread = None
        self._frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def _run(self):
        for frame in itertools.cycle(self._frames):
            if self._stop.is_set():
                break
            sys.stdout.write(f"\r{self.message} {frame}")
            sys.stdout.flush()
            time.sleep(0.1)

        # Clear line when done
        sys.stdout.write("\r" + " " * (len(self.message) + 2) + "\r")
        sys.stdout.flush()

    def __enter__(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        self._thread.join()
