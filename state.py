"""
Shared application state.

The capture loop (producer) and the Flask dashboard (consumer, on its own
thread) both touch this object. Scalars are written by one thread and read by
the other; under CPython's GIL those reads/writes are atomic enough for a
status display. The only thing that needs a real lock is the JPEG preview
buffer, because it is a multi-byte object swapped under the reader's feet.
"""

from __future__ import annotations

import threading
import time

import cv2


class AppState:
    def __init__(self) -> None:
        self.start_time = time.time()

        # status surfaced on the dashboard
        self.status = "IDLE"          # "IDLE" or "RECORDING"
        self.fps = 0.0
        self.clip_count = 0
        self.backend = "unknown"      # "picamera2" or "opencv"
        self.disk_free_gb = 0.0
        self.clips_size_gb = 0.0
        self.disk_warning = False     # True when recording is paused for disk

        # latest preview frame, JPEG-encoded for the MJPEG stream
        self._frame_lock = threading.Lock()
        self._latest_jpeg: bytes | None = None

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.start_time

    def update_preview(self, frame, max_width: int = 640) -> None:
        """Downscale + JPEG-encode a frame for the /stream endpoint."""
        h, w = frame.shape[:2]
        if w > max_width:
            scale = max_width / float(w)
            frame = cv2.resize(frame, (max_width, int(h * scale)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return
        with self._frame_lock:
            self._latest_jpeg = buf.tobytes()

    def get_preview(self) -> bytes | None:
        with self._frame_lock:
            return self._latest_jpeg
