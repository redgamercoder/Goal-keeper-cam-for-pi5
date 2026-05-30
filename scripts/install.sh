#!/usr/bin/env bash
# Goalkeeper Cam — one-shot installer for Raspberry Pi 5 (Pi OS Bookworm)
# Run as: sudo bash scripts/install.sh
set -euo pipefail

INSTALL_USER="${SUDO_USER:-pi}"
APP_DIR="/home/${INSTALL_USER}/goalkeeper-cam"
CLIPS_DIR="${APP_DIR}/clips"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Goalkeeper Cam installer"
echo "    App dir  : ${APP_DIR}"
echo "    Repo dir : ${REPO_DIR}"
echo "    User     : ${INSTALL_USER}"

# ── System packages ──────────────────────────────────────────────────────────
apt-get update -qq
apt-get install -y --no-install-recommends \
  python3 python3-pip python3-venv \
  ffmpeg v4l-utils \
  libopencv-dev \
  git curl

# ── NVMe detection ───────────────────────────────────────────────────────────
if lsblk | grep -q nvme0n1; then
  echo "==> NVMe detected — mounting /dev/nvme0n1p1 at /mnt/nvme"
  mkdir -p /mnt/nvme
  if ! grep -q nvme0n1p1 /etc/fstab; then
    echo "/dev/nvme0n1p1  /mnt/nvme  ext4  defaults,noatime  0  2" >> /etc/fstab
  fi
  mount -a || true
  CLIPS_DIR="/mnt/nvme/goalkeeper-cam/clips"
fi

mkdir -p "${CLIPS_DIR}"
chown -R "${INSTALL_USER}:${INSTALL_USER}" "${APP_DIR}" 2>/dev/null || true

# ── CPU governor → performance ───────────────────────────────────────────────
if [ -f /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]; then
  for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > "$gov"
  done
  echo "==> CPU governor set to performance"
else
  echo "    (cpufreq not available — skipping governor change)"
fi

# Persist across reboots
if ! grep -q "scaling_governor" /etc/rc.local 2>/dev/null; then
  sed -i '/^exit 0/i for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo performance > "$gov"; done' /etc/rc.local 2>/dev/null || true
fi

# ── Python venv + dependencies ───────────────────────────────────────────────
VENV="${APP_DIR}/venv"
sudo -u "${INSTALL_USER}" python3 -m venv "${VENV}"
sudo -u "${INSTALL_USER}" "${VENV}/bin/pip" install --upgrade pip

echo "==> Installing Python dependencies…"
sudo -u "${INSTALL_USER}" "${VENV}/bin/pip" install \
  "opencv-python-headless>=4.9" \
  "ultralytics>=8.2" \
  "flask>=3.0" \
  "numpy>=1.26"

# ── Export NCNN model (first-time only) ──────────────────────────────────────
echo "==> Exporting YOLOv8s → NCNN (this may take a few minutes)…"
cd "${REPO_DIR}"
sudo -u "${INSTALL_USER}" "${VENV}/bin/python" scripts/export_model.py

# ── Systemd service ──────────────────────────────────────────────────────────
SERVICE_FILE="/etc/systemd/system/goalkeeper-cam.service"
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Goalkeeper Highlight Auto-Recorder
After=network.target

[Service]
User=${INSTALL_USER}
WorkingDirectory=${REPO_DIR}
ExecStart=${VENV}/bin/python -m goalkeeper_cam \\
  --clips-dir ${CLIPS_DIR} \\
  --port 8080
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable goalkeeper-cam
systemctl start goalkeeper-cam

echo ""
echo "==> Installation complete!"
echo "    Service status : systemctl status goalkeeper-cam"
echo "    Live logs      : journalctl -fu goalkeeper-cam"
echo "    Dashboard      : http://$(hostname -I | awk '{print $1}'):8080"
