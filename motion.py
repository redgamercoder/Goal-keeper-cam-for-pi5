"""
Detection.

`Detector` is the interface the capture loop talks to: give it a frame, it tells
you whether something interesting happened. Today the only implementation is
`MotionDetector` (OpenCV frame-differencing, same algorithm as the prototype).

TODO(yolo): add a `YoloDetector(Detector)` here for ball tracking. It must take
a frame and return a bool from `.detect()`, exactly like MotionDetector, so it
drops in via the `--mode ball` flag with no changes to the capture loop.
"""

from __future__ import annotations

from typing import Protocol

import cv2


class Detector(Protocol):
    def detect(self, frame) -> bool:
        """Return True when this frame should trigger/continue a recording."""
        ...


class MotionDetector:
    """Frame-differencing motion detector.

    sensitivity: pixel-delta threshold. LOWER = more sensitive.
    min_area:    smallest changed-region (in pixels) that counts as motion.
                 Raise it outdoors to ignore wind, shadows, and bugs.
    """

    def __init__(self, sensitivity: int, min_area: int) -> None:
        self.sensitivity = sensitivity
        self.min_area = min_area
        self._prev_gray = None

    def detect(self, frame) -> bool:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self._prev_gray is None:
            self._prev_gray = gray
            return False

        delta = cv2.absdiff(self._prev_gray, gray)
        thresh = cv2.threshold(delta, self.sensitivity, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)
        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        self._prev_gray = gray
        return any(cv2.contourArea(c) >= self.min_area for c in contours)


def make_detector(mode: str, cfg) -> Detector:
    """Factory so the capture loop never hard-codes a detector type."""
    if mode == "motion":
        return MotionDetector(cfg.sensitivity, cfg.min_area)
    if mode == "ball":
        # TODO(yolo): return YoloDetector(...) once implemented.
        raise NotImplementedError(
            "--mode ball (YOLO ball tracking) is not implemented yet; "
            "use --mode motion."
        )
    raise ValueError(f"Unknown detection mode: {mode}")
