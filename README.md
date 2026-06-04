# Goalkeeper Cam — Raspberry Pi 5

A simple, robust, motion-triggered camera that records goalkeeper training clips
and serves a bright, phone-friendly web dashboard for live preview and playback.

Pure OpenCV motion detection (frame-differencing) — no ML, no model downloads.
There's a clean seam for adding YOLO ball-tracking later (`--mode ball`), but it
is intentionally **not** implemented yet.

---

## Hardware

| Part        | Notes                                                        |
|-------------|-------------------------------------------------------------|
| Raspberry Pi 5, 16GB | Raspberry Pi OS **Bookworm 64-bit**                |
| Camera      | CSI **Camera Module 3** *or* a USB webcam (auto-detected)   |
| Storage     | microSD or USB SSD (SSD recommended for lots of clips)      |
| Network     | Wired or Wi-Fi; field deployment is headless (SSH only)     |

The app prefers the CSI camera via **Picamera2** and falls back to **OpenCV**
for USB webcams. The same OpenCV path runs on a Mac, so you can test off-Pi.

---

## Headless Bookworm flashing notes

1. Use **Raspberry Pi Imager** → choose *Raspberry Pi OS (64-bit)*.
2. Click the gear / *Edit Settings* before writing and set:
   - Hostname (e.g. `goalkeeper`)
   - **Enable SSH** (password or key)
   - Username `williampatrickconnell` + password
   - Wi-Fi SSID/password (if not wired)
   - Locale / timezone
3. Flash, boot the Pi, then SSH in:
   ```bash
   ssh williampatrickconnell@10.0.0.245
   ```
   (A fixed IP of `10.0.0.245` is assumed throughout; set it via your router's
   DHCP reservation or `nmcli`.)

---

## Install

```bash
git clone https://github.com/redgamercoder/Goal-keeper-cam-for-pi5.git
cd Goal-keeper-cam-for-pi5
sudo ./install.sh
```

`install.sh` is idempotent (safe to re-run). It:

1. Installs `python3-picamera2 v4l-utils python3-pip`
2. `pip install --break-system-packages -r requirements.txt` (opencv, numpy, flask)
3. Auto-detects cameras (`rpicam-hello --list-cameras`, `v4l2-ctl --list-devices`)
   and prints what it found
4. Sets the CPU governor to `performance`
5. Installs + enables the systemd service
6. Creates `clips/` owned by `williampatrickconnell`
7. Prints the IP, dashboard URL, and service status

When it finishes the service is already running and will auto-start on boot.

---

## Dashboard

Open it from any device on the LAN (great on an iPhone from the sideline):

```
http://10.0.0.245:8080
```

- **Status page** — live IDLE/RECORDING badge, FPS, clip count, free disk,
  uptime, active camera backend, and a live MJPEG preview (`/stream`).
- **Clips page** — newest-first card grid, each with an inline player, filename,
  duration, size, timestamp, and a download button.

LAN only, no authentication.

---

## Running manually (testing / off-Pi)

```bash
pip install -r requirements.txt          # on a Mac, drop --break-system-packages
python3 goalkeeper_cam.py                 # defaults + dashboard on :8080
python3 goalkeeper_cam.py --no-dashboard  # capture only
python3 goalkeeper_cam.py --show          # local GUI window (needs a display)
python3 goalkeeper_cam.py --help          # all flags
```

---

## Service control

```bash
sudo systemctl start   goalkeeper-cam
sudo systemctl stop    goalkeeper-cam
sudo systemctl restart goalkeeper-cam
sudo systemctl status  goalkeeper-cam
```

## Logs

```bash
journalctl -u goalkeeper-cam -f        # live service logs
```
A rotating copy is also written to `goalkeeper-cam.log` in the project dir.

---

## Configuration

Defaults live in `config.py`. Override them with a `config.json` at the project
root (copy `config.json.example`), and override *that* per-run with CLI flags:

> precedence: **dataclass defaults  <  config.json  <  command-line flags**

| Option              | Flag                | Default | Meaning                                              |
|---------------------|---------------------|---------|------------------------------------------------------|
| `output`            | `--output`          | `clips` | Directory for saved clips                             |
| `width`             | `--width`           | `1280`  | Frame width (px)                                      |
| `height`            | `--height`          | `720`   | Frame height (px)                                     |
| `fps`               | `--fps`             | `30`    | Recording frame rate                                 |
| `sensitivity`       | `--sensitivity`     | `25`    | Motion threshold — **lower = more sensitive**        |
| `min_area`          | `--min-area`        | `1500`  | Min changed-pixel area to count as motion            |
| `preroll`           | `--preroll`         | `2.0`   | Seconds kept *before* motion starts                  |
| `postroll`          | `--postroll`        | `3.0`   | Seconds kept *after* motion stops                    |
| `camera`            | `--camera`          | `0`     | USB/OpenCV camera index                              |
| `show`              | `--show`            | `false` | Local GUI preview window                             |
| `dashboard_enabled` | `--dashboard` / `--no-dashboard` | `true` | Run the web dashboard               |
| `dashboard_port`    | `--dashboard-port`  | `8080`  | Dashboard port                                       |
| `max_disk_usage_gb` | *(config only)*     | `20.0`  | Pause new recordings when clips dir exceeds this     |
| *(mode)*            | `--mode {motion,ball}` | `motion` | Detector; `ball`/YOLO not implemented yet         |

---

## Motion-tuning cheatsheet

- **`sensitivity` is inverted**: *lower* numbers detect *smaller* changes
  (more sensitive). Raise it if it triggers on nothing/noise.
- **Raise `min_area` outdoors** to ignore wind, swaying nets, shadows, and bugs —
  it's the minimum size of a moving region that counts.
- Missing the start of the action? Increase `--preroll`.
- Clips cut off too early? Increase `--postroll`.
- Too many tiny clips? Raise `min_area` and/or `sensitivity`.

---

## Robustness

- **Disk guard** — when the clips dir exceeds `max_disk_usage_gb`, new recordings
  pause (logged + shown on the dashboard); the app never crashes or fills the card.
- **Camera reconnect** — repeated failed frame grabs trigger a backend re-init
  instead of an infinite spin.
- **Graceful shutdown** — SIGTERM (`systemctl stop`) and Ctrl+C release the
  writer and camera cleanly.
- **Auto-restart** — `Restart=on-failure` plus `enable` means it survives crashes
  and reboots.

---

## Future: YOLO ball tracking

`motion.py` defines a `Detector` protocol (`.detect(frame) -> bool`). A future
`YoloDetector` drops in alongside `MotionDetector` and is selected with
`--mode ball`. No model dependencies are bundled today.

---

## Project layout

```
goalkeeper_cam.py   entry point: CLI, logging, capture loop, shutdown
config.py           Config dataclass + config.json loader
camera.py           Picamera2/OpenCV auto-detect + reconnect
motion.py           Detector protocol + MotionDetector (YOLO seam)
recorder.py         pre-roll ring buffer, clip writing, disk guard
state.py            shared thread-safe state + MJPEG preview buffer
dashboard.py        Flask dashboard (status, clips, /stream)
install.sh          idempotent Pi installer
goalkeeper-cam.service   systemd unit (reference copy)
requirements.txt    opencv-python, numpy, flask
config.json.example sample config
```
