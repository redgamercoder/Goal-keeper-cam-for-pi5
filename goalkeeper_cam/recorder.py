"""Thread 3 — State machine + clip recording.

States: IDLE → RECORDING → SAVING → IDLE

Drains the ring buffer as pre-roll when a ball is first detected, continues
writing new frames live, then hands the raw frame dump to FFmpeg for final
H.264 mp4 encoding.
"""
import logging
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from .config import Config
from .detector import DetectionEvent
from .ring_buffer import RingBuffer

logger = logging.getLogger(__name__)


class State(Enum):
    IDLE = auto()
    RECORDING = auto()
    SAVING = auto()


class RecorderThread(threading.Thread):
    def __init__(
        self,
        config: Config,
        ring_buffer: RingBuffer,
        event_queue: "queue.Queue[DetectionEvent]",
        record_queue: "queue.Queue[np.ndarray]",
        stop_event: threading.Event,
        clip_index: list,           # shared list; recorder appends entries
        clip_index_lock: threading.Lock,
    ) -> None:
        super().__init__(name="recorder", daemon=True)
        self.config = config
        self.ring_buffer = ring_buffer
        self.event_queue = event_queue
        self.record_queue = record_queue
        self.stop_event = stop_event
        self.clip_index = clip_index
        self.clip_index_lock = clip_index_lock

        self.state = State.IDLE
        self.last_ball_time: Optional[float] = None
        self._raw_frames: List[np.ndarray] = []
        self._clip_start_ts: Optional[float] = None

    def run(self) -> None:
        clips_dir = self.config.clip_storage_dir()
        os.makedirs(clips_dir, exist_ok=True)
        logger.info("Recorder thread started. Clips → %s", clips_dir)

        while not self.stop_event.is_set():
            self._drain_event_queue()

            if self.state == State.RECORDING:
                self._collect_live_frames()
                if self._should_stop_recording():
                    self.state = State.SAVING
                    self._save_clip(clips_dir)
                    self.state = State.IDLE
                    self._raw_frames = []
                    self._clip_start_ts = None

            time.sleep(0.005)

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _drain_event_queue(self) -> None:
        while True:
            try:
                event: DetectionEvent = self.event_queue.get_nowait()
            except queue.Empty:
                break

            if event.ball_detected:
                self.last_ball_time = event.timestamp
                if self.state == State.IDLE:
                    self._start_recording()

    def _start_recording(self) -> None:
        self.state = State.RECORDING
        self._clip_start_ts = time.time()
        logger.info("Ball detected — started recording (pre-roll flush)")

        # Drain ring buffer → pre-roll frames
        for jpeg_bytes in self.ring_buffer.snapshot():
            frame = self.ring_buffer.decode_frame(jpeg_bytes)
            if frame is not None:
                self._raw_frames.append(frame)

    def _collect_live_frames(self) -> None:
        while True:
            try:
                frame = self.record_queue.get_nowait()
                self._raw_frames.append(frame)
            except queue.Empty:
                break

    def _should_stop_recording(self) -> bool:
        if self.last_ball_time is None:
            return False
        return (time.time() - self.last_ball_time) > self.config.hold_seconds

    # ------------------------------------------------------------------
    # Clip saving
    # ------------------------------------------------------------------

    def _save_clip(self, clips_dir: str) -> None:
        if not self._raw_frames:
            return

        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_path = os.path.join(clips_dir, f"clip_{ts_str}.mp4")
        thumb_path = os.path.join(clips_dir, f"clip_{ts_str}_thumb.jpg")

        logger.info("Saving clip: %s (%d frames)", final_path, len(self._raw_frames))

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = os.path.join(tmpdir, "raw.avi")
            self._write_raw_avi(raw_path)
            self._encode_to_mp4(raw_path, final_path)

        # Save thumbnail from first frame
        if self._raw_frames:
            cv2.imwrite(thumb_path, self._raw_frames[0])

        duration = len(self._raw_frames) / max(self.config.fps, 1)
        entry = {
            "filename": os.path.basename(final_path),
            "thumb": os.path.basename(thumb_path),
            "timestamp": ts_str,
            "duration": round(duration, 1),
            "size_mb": round(os.path.getsize(final_path) / 1e6, 1) if os.path.exists(final_path) else 0,
        }
        with self.clip_index_lock:
            self.clip_index.insert(0, entry)

        logger.info("Clip saved: %s (%.1fs)", final_path, duration)

    def _write_raw_avi(self, path: str) -> None:
        h, w = self._raw_frames[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(path, fourcc, self.config.fps, (w, h))
        for frame in self._raw_frames:
            writer.write(frame)
        writer.release()

    def _encode_to_mp4(self, src: str, dst: str) -> None:
        """Try hardware H.264 encoder first; fall back to libx264."""
        hw_cmd = [
            "ffmpeg", "-y", "-i", src,
            "-c:v", "h264_v4l2m2m",
            "-b:v", "4M",
            "-pix_fmt", "yuv420p",
            dst,
        ]
        sw_cmd = [
            "ffmpeg", "-y", "-i", src,
            "-c:v", "libx264",
            "-crf", "23",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            dst,
        ]
        for cmd in (hw_cmd, sw_cmd):
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            if result.returncode == 0:
                return
            logger.debug("FFmpeg cmd failed: %s", " ".join(cmd))

        logger.error("Both FFmpeg encoders failed for %s", src)
