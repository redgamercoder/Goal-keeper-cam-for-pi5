"""
Camera abstraction.

Prefers Picamera2 (the CSI Camera Module 3 on a Raspberry Pi) and falls back to
OpenCV's VideoCapture (USB webcams, and your Mac for off-Pi testing). The active
backend is exposed as `.backend` so the dashboard can show which one is live.

`reinit()` lets the capture loop recover from a camera that drops out (cable
knock, USB re-enumeration) instead of spinning forever on failed grabs.
"""

from __future__ import annotations

import logging
import time

import cv2

log = logging.getLogger("gkcam.camera")


class Camera:
    def __init__(self, cfg, state=None) -> None:
        self.cfg = cfg
        self.state = state
        self.backend: str | None = None
        self._picam = None
        self._cap = None
        self._open()

    # -- backend setup -------------------------------------------------------
    def _open(self) -> None:
        if self._init_picamera2():
            return
        self._init_opencv()
        if self.state is not None:
            self.state.backend = self.backend or "unknown"

    def _init_picamera2(self) -> bool:
        try:
            from picamera2 import Picamera2
        except ImportError:
            return False
        try:
            self._picam = Picamera2()
            config = self._picam.create_video_configuration(
                main={"size": (self.cfg.width, self.cfg.height), "format": "RGB888"}
            )
            self._picam.configure(config)
            self._picam.start()
            time.sleep(1)  # let auto-exposure settle
            self.backend = "picamera2"
            log.info("Camera backend: Picamera2 (CSI)")
            if self.state is not None:
                self.state.backend = self.backend
            return True
        except Exception as exc:  # no CSI camera attached, etc.
            log.warning("Picamera2 unavailable (%s); trying OpenCV", exc)
            self._picam = None
            return False

    def _init_opencv(self) -> None:
        self._cap = cv2.VideoCapture(self.cfg.camera)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
        self._cap.set(cv2.CAP_PROP_FPS, self.cfg.fps)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open camera index {self.cfg.camera}")
        self.backend = "opencv"
        log.info("Camera backend: OpenCV (USB/webcam index %d)", self.cfg.camera)

    # -- runtime -------------------------------------------------------------
    def read(self):
        """Return (ok, frame_bgr)."""
        try:
            if self.backend == "picamera2":
                frame = self._picam.capture_array()
                return True, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            return self._cap.read()
        except Exception as exc:
            log.warning("Camera read error: %s", exc)
            return False, None

    def reinit(self) -> bool:
        """Tear down and re-open the camera after repeated read failures."""
        log.warning("Reinitializing camera backend...")
        self.release()
        time.sleep(1)
        try:
            self._open()
            log.info("Camera reinitialized on backend: %s", self.backend)
            return True
        except Exception as exc:
            log.error("Camera reinit failed: %s", exc)
            return False

    def release(self) -> None:
        if self._picam is not None:
            try:
                self._picam.stop()
            except Exception:
                pass
            self._picam = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
