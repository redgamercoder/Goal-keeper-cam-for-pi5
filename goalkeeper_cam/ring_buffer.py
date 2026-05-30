"""Thread-safe JPEG-compressed ring buffer for pre-roll footage."""
import threading
from collections import deque
from typing import List, Optional, Tuple

import cv2
import numpy as np


class RingBuffer:
    """
    Stores frames as JPEG bytes to keep memory use manageable.
    At 1080p/30fps with quality=85, each frame ≈ 80-150 KB,
    so 15s×30fps = 450 frames ≈ 40-65 MB — well within budget.
    """

    def __init__(self, maxlen: int, jpeg_quality: int = 85) -> None:
        self._buf: deque[bytes] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._jpeg_quality = jpeg_quality
        self._encode_params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]

    def push(self, frame: np.ndarray) -> None:
        ok, buf = cv2.imencode(".jpg", frame, self._encode_params)
        if not ok:
            return
        data = buf.tobytes()
        with self._lock:
            self._buf.append(data)

    def snapshot(self) -> List[bytes]:
        """Return a copy of the current buffer contents (oldest → newest)."""
        with self._lock:
            return list(self._buf)

    def decode_frame(self, data: bytes) -> Optional[np.ndarray]:
        arr = np.frombuffer(data, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)
