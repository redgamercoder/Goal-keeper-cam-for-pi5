"""
Detection.

`Detector` is the interface the capture loop talks to: give it a frame, it tells
you whether something interesting happened. Two implementations:

- `MotionDetector` — OpenCV frame-differencing (same algorithm as the prototype).
- `YoloDetector`   — YOLOv8s exported to NCNN, triggers only on a sports ball.

Both expose `.detect(frame) -> bool`, so the capture loop never changes; the
`make_detector()` factory picks one based on `--mode {motion,ball}`.
"""

from __future__ import annotations

import os
from typing import Protocol

import cv2
import numpy as np


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


class YoloDetector:
    """
    Ball detector using YOLOv8s exported to NCNN.
    Drops in via make_detector('ball', cfg) with zero changes to the capture loop.
    Only triggers on class 32 (sports ball) in the COCO dataset.

    No PyTorch at runtime: inference is pure NCNN. The .param/.bin files are
    produced once by the one-time export in install.sh (`sudo ./install.sh --yolo`).
    """

    COCO_SPORTS_BALL = 32          # class id for "sports ball" in COCO
    INPUT_SIZE = 640               # YOLOv8 square input
    NMS_IOU = 0.45                 # IoU threshold for non-max suppression

    def __init__(self, model_param: str, model_bin: str, confidence: float) -> None:
        if not os.path.exists(model_param) or not os.path.exists(model_bin):
            raise FileNotFoundError(
                f"NCNN model files not found:\n  {model_param}\n  {model_bin}\n"
                "Run `sudo ./install.sh --yolo` to download and export the "
                "YOLOv8 model before using --mode ball."
            )
        try:
            import ncnn
        except ImportError as exc:
            raise FileNotFoundError(
                "The 'ncnn' package is not installed. Run "
                "`sudo ./install.sh --yolo` to set up ball detection."
            ) from exc

        self.confidence = confidence
        self._net = ncnn.Net()
        self._net.load_param(model_param)
        self._net.load_model(model_bin)

    def detect(self, frame) -> bool:
        import ncnn

        h0, w0 = frame.shape[:2]

        # Resize to 640x640 (BGR->RGB) and normalize pixels to 0-1 float.
        mat_in = ncnn.Mat.from_pixels_resize(
            frame, ncnn.Mat.PixelType.PIXEL_BGR2RGB,
            w0, h0, self.INPUT_SIZE, self.INPUT_SIZE,
        )
        mat_in.substract_mean_normalize([0.0, 0.0, 0.0],
                                        [1 / 255.0, 1 / 255.0, 1 / 255.0])

        ex = self._net.create_extractor()
        ex.input("in0", mat_in)
        ret, mat_out = ex.extract("out0")
        if ret != 0:
            return False

        # YOLOv8 head: (4 + num_classes, 8400). Normalize to (num_boxes, 4+nc).
        preds = np.array(mat_out)
        if preds.ndim != 2:
            return False
        if preds.shape[0] < preds.shape[1]:
            preds = preds.T
        if preds.shape[1] < 5:
            return False

        class_scores = preds[:, 4:]
        class_ids = class_scores.argmax(axis=1)
        confidences = class_scores.max(axis=1)

        keep = confidences >= self.confidence
        if not keep.any():
            return False

        boxes_xywh = preds[keep, :4]          # center-x, center-y, w, h
        confs = confidences[keep]
        cls = class_ids[keep]

        # cv2.dnn.NMSBoxes wants top-left xywh.
        boxes = [
            [float(cx - bw / 2), float(cy - bh / 2), float(bw), float(bh)]
            for (cx, cy, bw, bh) in boxes_xywh
        ]
        idxs = cv2.dnn.NMSBoxes(boxes, confs.tolist(),
                                self.confidence, self.NMS_IOU)
        if len(idxs) == 0:
            return False

        idxs = np.array(idxs).flatten()
        return any(cls[i] == self.COCO_SPORTS_BALL for i in idxs)


def make_detector(mode: str, cfg) -> Detector:
    """Factory so the capture loop never hard-codes a detector type."""
    if mode == "motion":
        return MotionDetector(cfg.sensitivity, cfg.min_area)
    elif mode == "ball":
        return YoloDetector(
            cfg.ncnn_model_param,
            cfg.ncnn_model_bin,
            cfg.confidence_threshold,
        )
    raise ValueError(
        f"Unknown detection mode: {mode!r}. Valid options are 'motion' or 'ball'."
    )
