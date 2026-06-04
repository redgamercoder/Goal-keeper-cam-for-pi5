"""
Configuration for Goalkeeper Cam.

A single dataclass holds every tunable. Defaults live here, can be overridden
by a `config.json` at the project root, and finally overridden by CLI flags
(handled in goalkeeper_cam.py). Precedence, lowest to highest:

    dataclass defaults  <  config.json  <  command-line flags
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, fields

log = logging.getLogger("gkcam.config")


@dataclass
class Config:
    # --- original prototype options (CLI flags must keep working) ---
    output: str = "clips"
    width: int = 1280
    height: int = 720
    fps: int = 30
    sensitivity: int = 25       # motion threshold; LOWER = more sensitive
    min_area: int = 1500        # min changed-pixel area to count as motion
    preroll: float = 2.0        # seconds kept before motion starts
    postroll: float = 3.0       # seconds kept after motion stops
    camera: int = 0             # USB/OpenCV camera index
    show: bool = False          # local GUI preview window (off-Pi testing)

    # --- new in the deployable build ---
    dashboard_enabled: bool = True
    dashboard_port: int = 8080
    max_disk_usage_gb: float = 20.0   # stop recording when clips dir exceeds this

    @classmethod
    def load(cls, path: str = "config.json") -> "Config":
        """Build a Config from defaults, overlaying config.json if present."""
        cfg = cls()
        if not os.path.exists(path):
            return cfg

        try:
            with open(path) as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read %s (%s); using defaults", path, exc)
            return cfg

        known = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key in known:
                setattr(cfg, key, value)
            else:
                log.warning("Ignoring unknown config key: %s", key)
        log.info("Loaded overrides from %s", path)
        return cfg
