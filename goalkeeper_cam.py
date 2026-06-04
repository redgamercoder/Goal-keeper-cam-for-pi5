#!/usr/bin/env python3
"""
Goal Keeper Cam for Raspberry Pi 5
==================================

A simple motion-triggered recording camera intended to capture goalkeeper
action clips. Designed for the Raspberry Pi 5 with the Pi Camera Module
(using Picamera2) but falls back to OpenCV/USB webcams on other hardware
(including your Mac for testing).

Usage:
    python3 goalkeeper_cam.py                 # run with defaults
    python3 goalkeeper_cam.py --output clips  # save clips to ./clips
    python3 goalkeeper_cam.py --sensitivity 30 --preroll 3 --postroll 4

Press Ctrl+C to stop.

Dependencies:
    pip install opencv-python numpy
    # On the Pi (recommended for the CSI camera):
    sudo apt install -y python3-picamera2
"""

import argparse
import collections
import datetime as dt
import os
import sys
import time

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("OpenCV is required. Install with: pip install opencv-python")


def parse_args():
    p = argparse.ArgumentParser(description="Motion-triggered goalkeeper camera")
    p.add_argument("--output", default="clips", help="Directory to save clips")
    p.add_argument("--width", type=int, default=1280, help="Frame width")
    p.add_argument("--height", type=int, default=720, help="Frame height")
    p.add_argument("--fps", type=int, default=30, help="Recording frame rate")
    p.add_argument("--sensitivity", type=int, default=25,
                   help="Motion threshold (lower = more sensitive)")
    p.add_argument("--min-area", type=int, default=1500,
                   help="Minimum changed-pixel area to count as motion")
    p.add_argument("--preroll", type=float, default=2.0,
                   help="Seconds of footage to keep before motion starts")
    p.add_argument("--postroll", type=float, default=3.0,
                   help="Seconds to keep recording after motion stops")
    p.add_argument("--camera", type=int, default=0, help="USB/OpenCV camera index")
    p.add_argument("--show", action="store_true", help="Show a live preview window")
    return p.parse_args()


class Camera:
    """Thin wrapper that prefers Picamera2 on the Pi, OpenCV elsewhere."""

    def __init__(self, width, height, fps, index):
        self.width, self.height, self.fps = width, height, fps
        self.backend = None
        self._init_picamera2() or self._init_opencv(index)

    def _init_picamera2(self):
        try:
            from picamera2 import Picamera2
        except ImportError:
            return False
        self.picam = Picamera2()
        config = self.picam.create_video_configuration(
            main={"size": (self.width, self.height), "format": "RGB888"}
        )
        self.picam.configure(config)
        self.picam.start()
        time.sleep(1)  # let auto-exposure settle
        self.backend = "picamera2"
        print("Using Picamera2 backend (Pi camera)")
        return True

    def _init_opencv(self, index):
        self.cap = cv2.VideoCapture(index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        if not self.cap.isOpened():
            sys.exit(f"Could not open camera index {index}")
        self.backend = "opencv"
        print("Using OpenCV backend (USB/webcam)")
        return True

    def read(self):
        if self.backend == "picamera2":
            frame = self.picam.capture_array()
            return True, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        return self.cap.read()

    def release(self):
        if self.backend == "picamera2":
            self.picam.stop()
        else:
            self.cap.release()


def detect_motion(prev_gray, gray, sensitivity, min_area):
    delta = cv2.absdiff(prev_gray, gray)
    thresh = cv2.threshold(delta, sensitivity, 255, cv2.THRESH_BINARY)[1]
    thresh = cv2.dilate(thresh, None, iterations=2)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    return any(cv2.contourArea(c) >= min_area for c in contours)


def new_writer(output_dir, width, height, fps):
    os.makedirs(output_dir, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"save_{stamp}.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (width, height))
    print(f"Recording -> {path}")
    return writer, path


def main():
    args = parse_args()
    cam = Camera(args.width, args.height, args.fps, args.camera)

    preroll_frames = int(args.preroll * args.fps)
    postroll_frames = int(args.postroll * args.fps)
    buffer = collections.deque(maxlen=preroll_frames)

    prev_gray = None
    writer = None
    idle_count = 0

    print("Watching for motion. Press Ctrl+C to stop.")
    try:
        while True:
            ok, frame = cam.read()
            if not ok:
                print("Frame grab failed, retrying...")
                time.sleep(0.05)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            moved = False
            if prev_gray is not None:
                moved = detect_motion(prev_gray, gray,
                                      args.sensitivity, args.min_area)
            prev_gray = gray

            buffer.append(frame)

            if moved:
                if writer is None:
                    writer, _ = new_writer(args.output, args.width,
                                           args.height, args.fps)
                    for buffered in buffer:  # flush the pre-roll
                        writer.write(buffered)
                idle_count = 0
            elif writer is not None:
                idle_count += 1

            if writer is not None:
                writer.write(frame)
                if idle_count >= postroll_frames:
                    writer.release()
                    writer = None
                    buffer.clear()
                    print("Motion ended, clip saved.")

            if args.show:
                label = "REC" if writer else "idle"
                cv2.putText(frame, label, (12, 32),
                            cv2.FONT_HERSHEY_SIMPLEX, 1,
                            (0, 0, 255) if writer else (0, 255, 0), 2)
                cv2.imshow("Goalkeeper Cam", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        if writer is not None:
            writer.release()
        cam.release()
        if args.show:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
