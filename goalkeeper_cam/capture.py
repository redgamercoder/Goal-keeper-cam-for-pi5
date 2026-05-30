"""Thread 1 — Webcam capture.

Reads frames from the USB webcam, pushes them into the ring buffer and the
detection queue. Runs on cores 0-1 via CPU affinity.
"""
import logging
import os
import queue
import threading
import time
from typing import Optional

import cv2
import numpy as np

from .config import Config
from .ring_buffer import RingBuffer

logger = logging.getLogger(__name__)


def _set_affinity(cores: tuple) -> None:
    try:
        os.sched_setaffinity(0, set(cores))
    except (AttributeError, OSError):
        pass  # not Linux or no permission — ignore


class CaptureThread(threading.Thread):
    def __init__(
        self,
        config: Config,
        ring_buffer: RingBuffer,
        detect_queue: "queue.Queue[np.ndarray]",
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name="capture", daemon=True)
        self.config = config
        self.ring_buffer = ring_buffer
        self.detect_queue = detect_queue
        self.stop_event = stop_event
        self.fps_actual: float = 0.0
        self._frame_count = 0
        self._fps_ts = time.monotonic()

    def run(self) -> None:
        _set_affinity(self.config.capture_cores)
        cap = self._open_camera()
        if cap is None:
            logger.error("Could not open camera — capture thread exiting")
            return

        logger.info(
            "Capture started: %dx%d @ %dfps on %s",
            *self.config.resolution,
            self.config.fps,
            self.config.device,
        )

        try:
            while not self.stop_event.is_set():
                ret, frame = cap.read()
                if not ret:
                    logger.warning("Frame read failed — retrying")
                    time.sleep(0.05)
                    continue

                self.ring_buffer.push(frame)

                # Non-blocking push to detection queue; drop if full
                try:
                    self.detect_queue.put_nowait(frame)
                except queue.Full:
                    pass

                self._update_fps()
        finally:
            cap.release()
            logger.info("Capture thread stopped")

    def _open_camera(self) -> Optional[cv2.VideoCapture]:
        cap = cv2.VideoCapture(self.config.device, cv2.CAP_V4L2)
        if not cap.isOpened():
            # Fallback: let OpenCV pick the backend
            cap = cv2.VideoCapture(self.config.device)
        if not cap.isOpened():
            return None

        w, h = self.config.resolution
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        cap.set(cv2.CAP_PROP_FPS, self.config.fps)
        # Use MJPEG to reduce USB bandwidth
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (actual_w, actual_h) != (w, h):
            logger.warning(
                "Camera fell back to %dx%d (requested %dx%d)",
                actual_w, actual_h, w, h,
            )
            self.config.resolution = (actual_w, actual_h)

        return cap

    def _update_fps(self) -> None:
        self._frame_count += 1
        now = time.monotonic()
        elapsed = now - self._fps_ts
        if elapsed >= 2.0:
            self.fps_actual = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_ts = now
