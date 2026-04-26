#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAC_BRIDGE_URL="${MAC_BRIDGE_URL:-http://127.0.0.1:8787}"
JETSON_HOST="${JETSON_HOST:-192.168.55.1}"
JETSON_USER="${JETSON_USER:-brianmeyer}"
JETSON_SSH_KEY="${JETSON_SSH_KEY:-${HOME}/.ssh/reachy_jetson_ed25519}"
JETSON_PROJECT="${JETSON_PROJECT:-/home/brianmeyer/reachy-mini-jetson-assistant}"

status_line() {
  local status="$1"
  local label="$2"
  local detail="${3:-}"
  printf '%-7s %s' "${status}" "${label}"
  if [ -n "${detail}" ]; then
    printf ' — %s' "${detail}"
  fi
  printf '\n'
}

json_field() {
  local field="$1"
  python3 -c '
import json
import sys

field = sys.argv[1]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)

value = data
for part in field.split("."):
    value = value[part]
print(value)
' "$field"
}

echo "Reachy pre-build readiness"
echo

health="$(curl -fsS "${MAC_BRIDGE_URL}/health" 2>/dev/null || true)"
if [ -n "${health}" ]; then
  cloud="$(printf '%s' "${health}" | json_field cloud_enabled 2>/dev/null || printf unknown)"
  gemini="$(printf '%s' "${health}" | json_field gemini_configured 2>/dev/null || printf unknown)"
  status_line "READY" "Mac bridge" "cloud=${cloud}, gemini=${gemini}"
else
  status_line "FIX" "Mac bridge" "run: launchctl kickstart -k gui/$(id -u)/com.reachy.mac-bridge"
fi

admin="$(curl -fsS "${MAC_BRIDGE_URL}/admin/status" 2>/dev/null || true)"
if [ -n "${admin}" ]; then
  quota="$(printf '%s' "${admin}" | python3 -c 'import json,sys; d=json.load(sys.stdin); q=d.get("gemini_image_quota",{}); print(str(q.get("used", "?")) + "/" + str(q.get("limit", "?")))' 2>/dev/null || printf unknown)"
  model="$(printf '%s' "${admin}" | json_field default_tool_model 2>/dev/null || printf unknown)"
  status_line "READY" "Parent panel" "${MAC_BRIDGE_URL}/parent"
  status_line "READY" "Gemini image quota" "${quota}"
  status_line "READY" "Default tool model" "${model}"
else
  status_line "FIX" "Parent panel" "admin status endpoint unavailable"
fi

if ssh -i "${JETSON_SSH_KEY}" -o BatchMode=yes -o ConnectTimeout=5 "${JETSON_USER}@${JETSON_HOST}" "true" >/dev/null 2>&1; then
  status_line "READY" "Jetson SSH" "${JETSON_USER}@${JETSON_HOST}"
else
  status_line "FIX" "Jetson SSH" "check Jetson power, USB network, and SSH key"
fi

llm="$(ssh -i "${JETSON_SSH_KEY}" -o BatchMode=yes -o ConnectTimeout=5 "${JETSON_USER}@${JETSON_HOST}" "curl -fsS http://127.0.0.1:8080/health" 2>/dev/null || true)"
if [ "${llm}" = '{"status":"ok"}' ]; then
  status_line "READY" "Jetson local LLM" "llama.cpp health ok"
else
  status_line "FIX" "Jetson local LLM" "check assistant-llm container"
fi

imports="$(ssh -i "${JETSON_SSH_KEY}" -o BatchMode=yes -o ConnectTimeout=5 "${JETSON_USER}@${JETSON_HOST}" "cd ${JETSON_PROJECT} && source venv/bin/activate && python - <<'PY'
mods = ['reachy_mini', 'cv2', 'sounddevice', 'httpx', 'fastapi', 'onnxruntime']
failed = []
for name in mods:
    try:
        __import__(name)
    except Exception:
        failed.append(name)
print('ok' if not failed else ','.join(failed))
PY" 2>/dev/null || true)"
if [ "${imports}" = "ok" ]; then
  status_line "READY" "Jetson Python env" "core imports pass"
else
  status_line "FIX" "Jetson Python env" "${imports:-unreachable}"
fi

devices="$(ssh -i "${JETSON_SSH_KEY}" -o BatchMode=yes -o ConnectTimeout=5 "${JETSON_USER}@${JETSON_HOST}" "ls -1 /dev/video* /dev/ttyACM* /dev/ttyUSB* /dev/serial/by-id/* 2>/dev/null || true" 2>/dev/null || true)"
if [ -n "${devices}" ]; then
  status_line "READY" "Reachy device candidates" "$(printf '%s' "${devices}" | tr '\n' ' ')"
else
  status_line "WAIT" "Reachy device candidates" "expected before build; should appear after robot is connected"
fi

echo
echo "Generating full report..."
report="$("${ROOT_DIR}/scripts/health_report.sh")"
echo "Report: ${report}"
echo
echo "Build-day rule: if hardware devices do not appear after plug-in, pause before motion tests."
