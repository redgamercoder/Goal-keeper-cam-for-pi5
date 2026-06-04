"""
Recording.

Holds a ring buffer of recent frames (the pre-roll), opens an mp4 writer when
motion starts, keeps writing for `postroll` seconds after motion stops, and
enforces a disk-usage cap so a Pi left running for a week never fills its card
or crashes. All disk problems degrade gracefully: recording pauses, a warning is
logged, and the dashboard shows it — the loop keeps running.
"""

from __future__ import annotations

import collections
import datetime as dt
import logging
import os
import time

import cv2

log = logging.getLogger("gkcam.recorder")


def count_clips(output: str) -> int:
    if not os.path.isdir(output):
        return 0
    return sum(1 for n in os.listdir(output) if n.endswith(".mp4"))


class Recorder:
    def __init__(self, cfg, state) -> None:
        self.cfg = cfg
        self.state = state

        self._preroll = collections.deque(maxlen=max(1, int(cfg.preroll * cfg.fps)))
        self._postroll_frames = max(1, int(cfg.postroll * cfg.fps))
        self._writer = None
        self._path = None
        self._idle = 0

        self._last_disk_check = 0.0
        self._disk_blocked = False

        os.makedirs(cfg.output, exist_ok=True)
        self.state.clip_count = count_clips(cfg.output)

    # -- disk guard ----------------------------------------------------------
    def _dir_size_gb(self) -> float:
        total = 0
        with os.scandir(self.cfg.output) as it:
            for entry in it:
                if entry.is_file():
                    total += entry.stat().st_size
        return total / (1024 ** 3)

    def _check_disk(self) -> None:
        now = time.time()
        if now - self._last_disk_check < 5:   # only check every 5s, it's I/O
            return
        self._last_disk_check = now

        used = self._dir_size_gb()
        self.state.clips_size_gb = round(used, 2)
        stat = os.statvfs(self.cfg.output)
        self.state.disk_free_gb = round(stat.f_bavail * stat.f_frsize / (1024 ** 3), 2)

        blocked = used >= self.cfg.max_disk_usage_gb
        if blocked and not self._disk_blocked:
            log.warning(
                "Clips dir at %.1f GB exceeds limit %.1f GB - pausing new recordings",
                used, self.cfg.max_disk_usage_gb,
            )
        elif not blocked and self._disk_blocked:
            log.info("Disk back under limit - recording re-enabled")
        self._disk_blocked = blocked
        self.state.disk_warning = blocked

    # -- main entry ----------------------------------------------------------
    def update(self, frame, moved: bool) -> None:
        """Feed one frame plus its motion verdict."""
        self._check_disk()

        if moved and self._writer is None and not self._disk_blocked:
            self._open()

        if moved:
            self._idle = 0
        elif self._writer is not None:
            self._idle += 1

        if self._writer is not None:
            self._writer.write(frame)
            if self._idle >= self._postroll_frames:
                self._close()

        # keep current frame as pure pre-roll for the *next* clip
        self._preroll.append(frame)

    def _open(self) -> None:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._path = os.path.join(self.cfg.output, f"save_{stamp}.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = cv2.VideoWriter(
            self._path, fourcc, self.cfg.fps, (self.cfg.width, self.cfg.height)
        )
        for buffered in self._preroll:   # flush pre-roll first
            self._writer.write(buffered)
        self.state.status = "RECORDING"
        log.info("Recording -> %s", self._path)

    def _close(self) -> None:
        if self._writer is not None:
            self._writer.release()
            log.info("Clip saved: %s", self._path)
        self._writer = None
        self._idle = 0
        self._preroll.clear()
        self.state.status = "IDLE"
        self.state.clip_count = count_clips(self.cfg.output)

    def close(self) -> None:
        """Called on shutdown - finish any clip in progress cleanly."""
        self._close()
