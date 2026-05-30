# Goalkeeper Highlight Auto-Recorder — Pi 5

Automatically records soccer goalkeeper training clips from a USB webcam using
YOLOv8s ball detection. Clips are saved as H.264 MP4 files and browsable from
any device on the LAN via a built-in web dashboard.

**Target hardware:** Raspberry Pi 5 (16 GB RAM) · USB webcam (V4L2) · Optional NVMe SSD

---

## Quick Start

```bash
# 1. Clone repo and install (run once as root on the Pi)
git clone https://github.com/redgamercoder/goal-keeper-cam-for-pi5.git
cd goal-keeper-cam-for-pi5
sudo bash scripts/install.sh
```

The installer:
- Installs system packages (ffmpeg, v4l-utils, python3-venv)
- Creates a Python venv with all dependencies
- Exports YOLOv8s → NCNN format (one-time, ~2–5 min)
- Detects NVMe SSD and uses it for clip storage if present
- Sets CPU governor to `performance` on all 4 Cortex-A76 cores
- Installs and starts a `goalkeeper-cam` systemd service

Open the dashboard at `http://<pi-ip>:8080` from any browser on your LAN.

---

## Manual Run (without systemd)

```bash
source ~/goalkeeper-cam/venv/bin/activate
python -m goalkeeper_cam
# or
goalkeeper-cam --help
```

### CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `--device` | `/dev/video0` | V4L2 camera device |
| `--resolution` | `1920x1080` | Target capture resolution |
| `--fps` | `30` | Target frame rate |
| `--confidence` | `0.45` | Ball detection confidence threshold |
| `--hold-seconds` | `5` | Seconds after ball disappears before saving |
| `--preroll` | `15` | Pre-roll ring buffer length in seconds |
| `--clips-dir` | `/home/pi/goalkeeper-cam/clips` | Clip output directory |
| `--port` | `8080` | Web dashboard port |
| `--model` | `models/yolov8s_ncnn_model` | Path to NCNN model directory |
| `--finetune` | — | Print Roboflow fine-tuning instructions and exit |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  USB Webcam (1080p/30fps, MJPEG, /dev/video0)        │
└──────────────┬──────────────────────────────────────┘
               │ frames
   ┌───────────▼────────────┐
   │  Thread 1 — Capture    │  cores 0-1
   │  cv2.VideoCapture      │
   └───┬───────────┬────────┘
       │           │ frames
  ring │      detect_queue (max 2)
 buffer│           │
(JPEG) │   ┌───────▼───────────────┐
       │   │  Thread 2 — Detection │  cores 2-3
       │   │  YOLOv8s NCNN         │
       │   └───────────────────────┘
       │           │ DetectionEvents
       │      event_queue
       │           │
   ┌───▼───────────▼────────────┐
   │  Thread 3 — State Machine  │  cores 0-1
   │  IDLE → RECORDING → SAVING │
   │  FFmpeg H.264 (hw/sw)      │
   └────────────────────────────┘
               │ clip_index
   ┌───────────▼────────────────┐
   │  Thread 4 — Flask Dashboard│
   │  http://0.0.0.0:8080       │
   └────────────────────────────┘
```

### States

| State | Description |
|-------|-------------|
| `IDLE` | Watching for ball detections |
| `RECORDING` | Ball detected — draining ring buffer as pre-roll, then writing live frames |
| `SAVING` | Ball gone for `hold_seconds` — FFmpeg encoding to MP4, then back to IDLE |

---

## Web Dashboard

| Route | Description |
|-------|-------------|
| `GET /` | Live status: state, FPS, clip count, disk free, last ball time |
| `GET /clips` | Paginated clip browser with thumbnails |
| `GET /clips/<file>` | Stream or download a clip |
| `GET /api/status` | JSON status (polled every 2s by dashboard) |
| `POST /api/config` | Update `hold_seconds`, `confidence`, `detect_every_n` at runtime |

---

## Pi 5 Optimisations

- **16 GB RAM ring buffer:** 15 s × 30 fps frames stored as JPEG (quality 85) ≈ 40–65 MB
- **4-core affinity:** detection on cores 2-3; capture/recording on cores 0-1
- **Hardware encoder:** FFmpeg uses `h264_v4l2m2m` (Pi 5 V4L2 M2M); falls back to `libx264`
- **NVMe auto-detection:** clips written to `/mnt/nvme` if mounted, else `/home/pi/goalkeeper-cam/clips`
- **CPU performance governor:** set at install time and on every boot

---

## Fine-tuning on Soccer Ball Data

The stock YOLOv8s COCO model detects sports balls reliably in most conditions.
If detection is poor on your specific setup, run:

```bash
goalkeeper-cam --finetune
```

This prints step-by-step instructions for downloading a Roboflow soccer ball
dataset and fine-tuning the model on your Pi or a more powerful machine.

---

## Logs & Service Management

```bash
# View live logs
journalctl -fu goalkeeper-cam

# Restart / stop
sudo systemctl restart goalkeeper-cam
sudo systemctl stop goalkeeper-cam

# Check camera device
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-formats-ext
```
