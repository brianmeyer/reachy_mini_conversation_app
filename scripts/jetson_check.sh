#!/usr/bin/env bash
set -euo pipefail

JETSON_HOST="${JETSON_HOST:-192.168.55.1}"
JETSON_USER="${JETSON_USER:-brianmeyer}"
MAC_BRIDGE_URL="${MAC_BRIDGE_URL:-http://192.168.55.100:8787}"

echo "Checking Jetson at ${JETSON_USER}@${JETSON_HOST}"
echo

echo "== Local USB/network =="
ifconfig en9 2>/dev/null | sed -n '1,12p' || true
ls /dev/cu.usbmodem* 2>/dev/null || true
echo

echo "== Reachability =="
ping -c 2 "${JETSON_HOST}"
nc -vz -G 3 "${JETSON_HOST}" 22
nc -vz -G 3 "${JETSON_HOST}" 8080 || true
nc -vz -G 3 "${JETSON_HOST}" 8090 || true
curl -sS -m 3 "${MAC_BRIDGE_URL}/health" || true
echo

echo "== Jetson inventory =="
ssh -o StrictHostKeyChecking=no "${JETSON_USER}@${JETSON_HOST}" <<'REMOTE'
set -euo pipefail
echo "--- identity ---"
hostname
whoami
uname -a
echo
echo "--- os/l4t ---"
cat /etc/os-release | sed -n '1,8p'
cat /etc/nv_tegra_release 2>/dev/null || true
echo
echo "--- hardware/resources ---"
tr -d '\0' </proc/device-tree/model || true
echo
free -h
df -h /
echo
echo "--- network ---"
ip -brief addr
echo
echo "--- usb/media/control ---"
lsusb 2>/dev/null || true
ls -l /dev/video* /dev/ttyACM* /dev/ttyUSB* /dev/serial/by-id/* 2>/dev/null || true
arecord -l 2>/dev/null || true
amixer -c 0 scontrols 2>/dev/null || true
amixer -c 0 sget Mic 2>/dev/null || true
echo
echo "--- assistant/docker ---"
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true
curl -sS -m 3 http://127.0.0.1:8080/health 2>/dev/null || true
echo
if [ -d /home/brianmeyer/reachy-mini-jetson-assistant ]; then
  cd /home/brianmeyer/reachy-mini-jetson-assistant
  git status --short --branch || true
  if [ -f venv/bin/activate ]; then
    . venv/bin/activate
    python -m app.cli info || true
    python - <<'PY' || true
import importlib.util
mods = ["sounddevice", "faster_whisper", "cv2", "onnxruntime", "chromadb", "reachy_mini"]
for mod in mods:
    print(f"{mod}: {'ok' if importlib.util.find_spec(mod) else 'missing'}")
PY
  fi
fi
REMOTE
