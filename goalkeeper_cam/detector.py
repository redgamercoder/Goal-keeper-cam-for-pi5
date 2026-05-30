"""Thread 2 — Ball detection via YOLOv8s NCNN.

Reads frames from detect_queue, runs inference, and posts DetectionEvent
objects to event_queue. Runs on cores 2-3.
"""
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from .config import Config

logger = logging.getLogger(__name__)


@dataclass
class DetectionEvent:
    ball_detected: bool
    confidence: float
    bbox: Optional[Tuple[int, int, int, int]]  # x1,y1,x2,y2
    timestamp: float


def _set_affinity(cores: tuple) -> None:
    try:
        os.sched_setaffinity(0, set(cores))
    except (AttributeError, OSError):
        pass


class NCNNDetector:
    """Wraps the NCNN YOLOv8 model."""

    def __init__(self, model_dir: str, confidence: float, ball_class_id: int) -> None:
        from ultralytics import YOLO

        param = os.path.join(model_dir, "model.ncnn.param")
        bin_path = os.path.join(model_dir, "model.ncnn.bin")
        if not (os.path.exists(param) and os.path.exists(bin_path)):
            raise FileNotFoundError(
                f"NCNN model files not found in {model_dir}. "
                "Run `python scripts/export_model.py` first."
            )

        # Load via Ultralytics NCNN backend
        self._model = YOLO(model_dir)
        self._conf = confidence
        self._ball_cls = ball_class_id

    def detect(self, frame: np.ndarray) -> DetectionEvent:
        results = self._model.predict(
            frame,
            conf=self._conf,
            classes=[self._ball_cls],
            verbose=False,
            imgsz=640,
        )
        ts = time.time()
        for r in results:
            boxes = r.boxes
            if boxes is not None and len(boxes):
                # Take the highest-confidence detection
                best_idx = int(boxes.conf.argmax())
                conf = float(boxes.conf[best_idx])
                x1, y1, x2, y2 = boxes.xyxy[best_idx].tolist()
                return DetectionEvent(
                    ball_detected=True,
                    confidence=conf,
                    bbox=(int(x1), int(y1), int(x2), int(y2)),
                    timestamp=ts,
                )
        return DetectionEvent(ball_detected=False, confidence=0.0, bbox=None, timestamp=ts)


class DetectionThread(threading.Thread):
    def __init__(
        self,
        config: Config,
        detect_queue: "queue.Queue[np.ndarray]",
        event_queue: "queue.Queue[DetectionEvent]",
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name="detection", daemon=True)
        self.config = config
        self.detect_queue = detect_queue
        self.event_queue = event_queue
        self.stop_event = stop_event
        self._frame_skip = 0

    def run(self) -> None:
        _set_affinity(self.config.detect_cores)
        try:
            detector = NCNNDetector(
                self.config.model_path,
                self.config.confidence,
                self.config.ball_class_id,
            )
        except FileNotFoundError as e:
            logger.error("%s", e)
            return

        logger.info("Detection thread started (YOLOv8s NCNN)")

        while not self.stop_event.is_set():
            try:
                frame = self.detect_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            self._frame_skip += 1
            if self._frame_skip < self.config.detect_every_n:
                continue
            self._frame_skip = 0

            event = detector.detect(frame)
            try:
                self.event_queue.put_nowait(event)
            except queue.Full:
                pass

        logger.info("Detection thread stopped")
