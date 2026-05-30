"""Runtime configuration — all values are mutable at runtime via POST /api/config."""
import os
from dataclasses import dataclass, field
from typing import Tuple


@dataclass
class Config:
    # Camera
    device: str = "/dev/video0"
    resolution: Tuple[int, int] = (1920, 1080)
    fps: int = 30

    # Ring buffer
    preroll_seconds: int = 15          # generous with 16GB RAM
    jpeg_quality: int = 85             # compress ring buffer frames

    # Detection
    model_path: str = "models/yolov8s_ncnn_model"
    confidence: float = 0.45
    ball_class_id: int = 32            # COCO class: sports ball
    detect_every_n: int = 1            # set to 2 to skip every other frame

    # Recording
    hold_seconds: int = 5              # no-ball grace period before saving
    clips_dir: str = "/home/pi/goalkeeper-cam/clips"
    nvme_mount: str = "/mnt/nvme"

    # Web dashboard
    host: str = "0.0.0.0"
    port: int = 8080

    # Thread → core affinity (Linux only)
    capture_cores: Tuple[int, ...] = (0, 1)
    detect_cores: Tuple[int, ...] = (2, 3)

    def clip_storage_dir(self) -> str:
        """Prefer NVMe SSD if mounted."""
        nvme_clips = os.path.join(self.nvme_mount, "goalkeeper-cam", "clips")
        if os.path.ismount(self.nvme_mount):
            return nvme_clips
        return self.clips_dir

    def preroll_frames(self) -> int:
        return self.preroll_seconds * self.fps
