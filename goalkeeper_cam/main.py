"""Entry point — wires all threads together and handles shutdown."""
import logging
import queue
import signal
import sys
import threading
import time

from .capture import CaptureThread
from .config import Config
from .dashboard import start_dashboard
from .detector import DetectionThread
from .recorder import RecorderThread
from .ring_buffer import RingBuffer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run(config: Config) -> None:
    stop_event = threading.Event()

    ring_buffer = RingBuffer(
        maxlen=config.preroll_frames(),
        jpeg_quality=config.jpeg_quality,
    )

    # Queue sizes: detection gets up to 2 frames buffered; record queue is bigger
    detect_queue: queue.Queue = queue.Queue(maxsize=2)
    event_queue: queue.Queue = queue.Queue(maxsize=60)
    record_queue: queue.Queue = queue.Queue(maxsize=300)

    clip_index: list = []
    clip_index_lock = threading.Lock()

    capture = CaptureThread(config, ring_buffer, detect_queue, stop_event)
    detection = DetectionThread(config, detect_queue, event_queue, stop_event)
    recorder = RecorderThread(
        config, ring_buffer, event_queue, record_queue,
        stop_event, clip_index, clip_index_lock,
    )

    # Capture also feeds the record queue so the recorder gets live frames
    # We monkey-patch the capture thread to push to record_queue too.
    _orig_run = capture.run

    def _patched_run():
        import os
        import time as _time
        import cv2

        _set_aff = lambda cores: (
            os.sched_setaffinity(0, set(cores))
            if hasattr(os, "sched_setaffinity")
            else None
        )
        _set_aff(config.capture_cores)
        cap = capture._open_camera()
        if cap is None:
            logger.error("Could not open camera")
            return
        try:
            while not stop_event.is_set():
                ret, frame = cap.read()
                if not ret:
                    _time.sleep(0.05)
                    continue
                ring_buffer.push(frame)
                try:
                    detect_queue.put_nowait(frame)
                except queue.Full:
                    pass
                try:
                    record_queue.put_nowait(frame)
                except queue.Full:
                    pass
                capture._update_fps()
        finally:
            cap.release()

    capture.run = _patched_run

    start_dashboard(
        config,
        clip_index,
        clip_index_lock,
        get_recorder_state=lambda: recorder.state.name,
        get_fps=lambda: capture.fps_actual,
        get_last_ball_time=lambda: recorder.last_ball_time,
    )

    for t in (capture, detection, recorder):
        t.start()

    def _shutdown(sig, frame):
        logger.info("Shutdown signal received")
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Goalkeeper cam running. Press Ctrl-C to stop.")
    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()

    for t in (capture, detection, recorder):
        t.join(timeout=10)

    logger.info("All threads stopped. Goodbye.")
