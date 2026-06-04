#!/usr/bin/env python3
"""
Goalkeeper Cam for Raspberry Pi 5
=================================

Motion-triggered camera that records goalkeeper training clips, with a bright
phone-friendly web dashboard for live preview and clip playback.

    python3 goalkeeper_cam.py                 # run with defaults (+dashboard)
    python3 goalkeeper_cam.py --no-dashboard  # headless capture only
    python3 goalkeeper_cam.py --help          # all options

Backends auto-detect: Picamera2 (CSI Camera Module 3) is preferred, OpenCV
(USB webcam, or your Mac for testing) is the fallback. See README.md.
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import signal
import sys
import time

from config import Config
from state import AppState
from camera import Camera
from motion import make_detector
from recorder import Recorder
from dashboard import start_dashboard

log = logging.getLogger("gkcam")


# ---------------------------------------------------------------------------
# CLI  (config.json defaults < command-line flags)
# ---------------------------------------------------------------------------
def build_config() -> tuple[Config, str]:
    cfg = Config.load()   # defaults overlaid with config.json
    p = argparse.ArgumentParser(
        description="Motion-triggered goalkeeper camera for the Raspberry Pi 5",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # --- original prototype flags (kept identical) ---
    p.add_argument("--output", default=cfg.output, help="Directory to save clips")
    p.add_argument("--width", type=int, default=cfg.width, help="Frame width")
    p.add_argument("--height", type=int, default=cfg.height, help="Frame height")
    p.add_argument("--fps", type=int, default=cfg.fps, help="Recording frame rate")
    p.add_argument("--sensitivity", type=int, default=cfg.sensitivity,
                   help="Motion threshold (lower = more sensitive)")
    p.add_argument("--min-area", type=int, default=cfg.min_area,
                   help="Minimum changed-pixel area to count as motion")
    p.add_argument("--preroll", type=float, default=cfg.preroll,
                   help="Seconds of footage kept before motion starts")
    p.add_argument("--postroll", type=float, default=cfg.postroll,
                   help="Seconds to keep recording after motion stops")
    p.add_argument("--camera", type=int, default=cfg.camera,
                   help="USB/OpenCV camera index")
    p.add_argument("--show", action="store_true", default=cfg.show,
                   help="Show a local GUI preview window (off-Pi testing)")
    # --- new flags ---
    p.add_argument("--dashboard", action=argparse.BooleanOptionalAction,
                   default=cfg.dashboard_enabled,
                   help="Run the web dashboard (--no-dashboard to disable)")
    p.add_argument("--dashboard-port", type=int, default=cfg.dashboard_port,
                   help="Dashboard port")
    p.add_argument("--mode", choices=["motion", "ball"], default="motion",
                   help="Detection mode (ball/YOLO not implemented yet)")
    args = p.parse_args()

    cfg.output = args.output
    cfg.width = args.width
    cfg.height = args.height
    cfg.fps = args.fps
    cfg.sensitivity = args.sensitivity
    cfg.min_area = args.min_area
    cfg.preroll = args.preroll
    cfg.postroll = args.postroll
    cfg.camera = args.camera
    cfg.show = args.show
    cfg.dashboard_enabled = args.dashboard
    cfg.dashboard_port = args.dashboard_port
    return cfg, args.mode


# ---------------------------------------------------------------------------
# Logging: stdout (journalctl) + rotating file in the project dir
# ---------------------------------------------------------------------------
def setup_logging() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    root.addHandler(stream)

    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(here, "goalkeeper-cam.log"),
        maxBytes=2_000_000, backupCount=3,
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


# ---------------------------------------------------------------------------
# Main capture loop
# ---------------------------------------------------------------------------
def main() -> None:
    cfg, mode = build_config()
    setup_logging()
    log.info("Goalkeeper Cam starting (mode=%s, dashboard=%s)",
             mode, cfg.dashboard_enabled)

    state = AppState()
    detector = make_detector(mode, cfg)
    camera = Camera(cfg, state)
    recorder = Recorder(cfg, state)

    # graceful shutdown for `systemctl stop` (SIGTERM) and Ctrl+C (SIGINT)
    stop = {"flag": False}

    def handle_signal(signum, _frame):
        log.info("Signal %s received; shutting down...", signum)
        stop["flag"] = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    if cfg.dashboard_enabled:
        start_dashboard(cfg, state)

    fail_count = 0
    last = time.time()
    fps_ema: float | None = None

    try:
        while not stop["flag"]:
            ok, frame = camera.read()
            if not ok or frame is None:
                fail_count += 1
                log.warning("Frame grab failed (%d in a row)", fail_count)
                if fail_count >= 30:        # ~a few seconds of failures
                    camera.reinit()
                    state.backend = camera.backend or "unknown"
                    fail_count = 0
                time.sleep(0.1)
                continue
            fail_count = 0

            # rolling FPS estimate
            now = time.time()
            dt_ = now - last
            last = now
            if dt_ > 0:
                inst = 1.0 / dt_
                fps_ema = inst if fps_ema is None else 0.9 * fps_ema + 0.1 * inst
                state.fps = fps_ema

            moved = detector.detect(frame)
            recorder.update(frame, moved)

            if cfg.dashboard_enabled:
                state.update_preview(frame)

            if cfg.show:
                import cv2
                label = "REC" if state.status == "RECORDING" else "idle"
                color = (0, 0, 255) if state.status == "RECORDING" else (0, 255, 0)
                cv2.putText(frame, label, (12, 32),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
                cv2.imshow("Goalkeeper Cam", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        recorder.close()
        camera.release()
        if cfg.show:
            import cv2
            cv2.destroyAllWindows()
        log.info("Stopped cleanly.")


if __name__ == "__main__":
    main()
