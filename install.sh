#!/usr/bin/env bash
#
# Goalkeeper Cam installer for Raspberry Pi 5 (Raspberry Pi OS Bookworm 64-bit).
# Idempotent: safe to run again any time. Run with sudo:
#
#     sudo ./install.sh
#
set -euo pipefail

# --- resolve paths / user ---------------------------------------------------
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_USER="williampatrickconnell"
SERVICE="goalkeeper-cam"
UNIT_PATH="/etc/systemd/system/${SERVICE}.service"

if [[ $EUID -ne 0 ]]; then
  echo "Please run with sudo: sudo ./install.sh" >&2
  exit 1
fi

# Fall back to the invoking user if the expected Pi user doesn't exist.
if ! id "$RUN_USER" >/dev/null 2>&1; then
  RUN_USER="${SUDO_USER:-$(logname 2>/dev/null || echo pi)}"
  echo "User williampatrickconnell not found; using '$RUN_USER' instead."
fi

echo "==> Project dir : $PROJECT_DIR"
echo "==> Service user: $RUN_USER"

# --- 1. system packages -----------------------------------------------------
echo "==> Installing system packages..."
apt-get update -y
apt-get install -y python3-picamera2 v4l-utils python3-pip

# --- 2. python dependencies -------------------------------------------------
echo "==> Installing Python dependencies..."
pip install --break-system-packages -r "$PROJECT_DIR/requirements.txt"

# --- 3. camera auto-detect (informational) ----------------------------------
echo "==> Detecting cameras..."
echo "--- rpicam-hello --list-cameras ---"
if command -v rpicam-hello >/dev/null 2>&1; then
  rpicam-hello --list-cameras 2>&1 || echo "(no CSI camera reported)"
else
  echo "(rpicam-hello not installed)"
fi
echo "--- v4l2-ctl --list-devices ---"
v4l2-ctl --list-devices 2>&1 || echo "(no V4L2 devices reported)"
echo "Picamera2 (CSI) is preferred; OpenCV (USB) is the fallback."

# --- 4. CPU governor -> performance -----------------------------------------
echo "==> Setting CPU governor to performance..."
for cpu in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor; do
  [[ -w "$cpu" ]] && echo performance > "$cpu" || true
done
echo "performance" > /etc/default/cpu-governor 2>/dev/null || true

# --- 5. clips dir with correct ownership ------------------------------------
echo "==> Creating clips directory..."
mkdir -p "$PROJECT_DIR/clips"
chown -R "$RUN_USER":"$RUN_USER" "$PROJECT_DIR/clips"

# --- 6. install + enable systemd service ------------------------------------
echo "==> Installing systemd service..."
cat > "$UNIT_PATH" <<EOF
[Unit]
Description=Goalkeeper Cam (motion-triggered camera + dashboard)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=/usr/bin/python3 ${PROJECT_DIR}/goalkeeper_cam.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

# --- 7. final status --------------------------------------------------------
IP="$(hostname -I | awk '{print $1}')"
echo
echo "============================================================"
echo " Goalkeeper Cam installed and running."
echo "   IP address  : ${IP:-unknown}"
echo "   Dashboard   : http://${IP:-10.0.0.245}:8080"
echo "   Service     : systemctl status ${SERVICE}"
echo "   Logs        : journalctl -u ${SERVICE} -f"
echo "============================================================"
systemctl --no-pager --full status "$SERVICE" || true
