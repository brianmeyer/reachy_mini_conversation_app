#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="${ROOT_DIR}/docs/health-reports"
STAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="${REPORT_DIR}/${STAMP}-reachy-health.md"

MAC_BRIDGE_URL="${MAC_BRIDGE_URL:-http://127.0.0.1:8787}"
JETSON_HOST="${JETSON_HOST:-192.168.55.1}"
JETSON_USER="${JETSON_USER:-brianmeyer}"
JETSON_SSH_KEY="${JETSON_SSH_KEY:-${HOME}/.ssh/reachy_jetson_ed25519}"
JETSON_PROJECT="${JETSON_PROJECT:-/home/brianmeyer/reachy-mini-jetson-assistant}"
JETSON_LLM_URL="${JETSON_LLM_URL:-http://127.0.0.1:8080/health}"

mkdir -p "${REPORT_DIR}"

write_section() {
  printf '\n## %s\n\n' "$1" >> "${REPORT}"
}

run_local() {
  local title="$1"
  shift
  printf '### %s\n\n```text\n' "${title}" >> "${REPORT}"
  "$@" >> "${REPORT}" 2>&1 || true
  printf '\n```\n\n' >> "${REPORT}"
}

run_jetson() {
  local title="$1"
  local remote_cmd="$2"
  printf '### %s\n\n```text\n' "${title}" >> "${REPORT}"
  ssh -i "${JETSON_SSH_KEY}" -o BatchMode=yes -o ConnectTimeout=5 "${JETSON_USER}@${JETSON_HOST}" "${remote_cmd}" >> "${REPORT}" 2>&1 || true
  printf '\n```\n\n' >> "${REPORT}"
}

json_or_text() {
  local url="$1"
  curl -fsS "${url}" | python3 -m json.tool
}

cat > "${REPORT}" <<EOF
# Reachy Health Report

Generated: $(date)

This report intentionally avoids printing API keys, env files, or secret values.

## Targets

- Mac bridge: \`${MAC_BRIDGE_URL}\`
- Jetson SSH: \`${JETSON_USER}@${JETSON_HOST}\`
- Jetson SSH key: \`${JETSON_SSH_KEY}\`
- Jetson project: \`${JETSON_PROJECT}\`
- Jetson local LLM health: \`${JETSON_LLM_URL}\`
EOF

write_section "Mac Bridge"
run_local "Mac bridge health" json_or_text "${MAC_BRIDGE_URL}/health"
run_local "Mac bridge tools" json_or_text "${MAC_BRIDGE_URL}/tools"
run_local "Mac bridge models" json_or_text "${MAC_BRIDGE_URL}/models"
run_local "Jetson/Mac protocol inventory" json_or_text "${MAC_BRIDGE_URL}/protocol"
run_local "Pending Jetson actions" json_or_text "${MAC_BRIDGE_URL}/jetson/actions/pending"
run_local "LaunchAgent status" launchctl print "gui/$(id -u)/com.reachy.mac-bridge"

write_section "Jetson Reachability"
run_local "Ping Jetson USB address" ping -c 2 -W 1000 "${JETSON_HOST}"
run_jetson "Jetson basic identity" "hostname; date; uname -a; lsb_release -a 2>/dev/null || true"
run_jetson "Jetson disk and memory" "df -h /; free -h"
run_jetson "Jetson LLM health" "curl -fsS ${JETSON_LLM_URL} || true"

write_section "Jetson Hardware Enumeration"
run_jetson "USB devices" "lsusb"
run_jetson "Video and serial devices" "ls -l /dev/video* /dev/ttyACM* /dev/ttyUSB* /dev/serial/by-id/* 2>/dev/null || true"
run_jetson "Audio capture devices" "arecord -l 2>/dev/null || true"
run_jetson "Audio playback devices" "aplay -l 2>/dev/null || true"

write_section "Jetson Project State"
run_jetson "Project files and local status" "cd ${JETSON_PROJECT} && pwd && git status --short 2>/dev/null || true"
run_jetson "Python imports" "cd ${JETSON_PROJECT} && source venv/bin/activate && python - <<'PY'
mods = ['reachy_mini', 'cv2', 'sounddevice', 'httpx', 'fastapi', 'onnxruntime']
for name in mods:
    try:
        mod = __import__(name)
        print(f'{name}: ok {getattr(mod, \"__version__\", \"\")}')
    except Exception as exc:
        print(f'{name}: fail {type(exc).__name__}: {exc}')
PY"
run_jetson "Mac bridge from Jetson" "cd ${JETSON_PROJECT} && source venv/bin/activate && python - <<'PY'
from app.mac_bridge import MacBridgeClient
client = MacBridgeClient()
print(client.health())
tools = client.tools()
print({'ok': tools.get('ok'), 'default_tool_model': tools.get('default_tool_model'), 'gemini_tool': any(t.get('name') == 'gemini_image' for t in tools.get('tools', []))})
PY"

write_section "Summary"
cat >> "${REPORT}" <<'EOF'
- If Mac bridge health failed: restart `com.reachy.mac-bridge`.
- If Jetson SSH failed: check USB network cable, Jetson power, and IP `192.168.55.1`.
- If no video/control device appears after Reachy is plugged in: stop before motion tests and inspect cable/power/device enumeration.
- If imports fail: activate the Jetson venv and repair the named dependency.
- If local LLM health fails: inspect the `assistant-llm` Docker container.
EOF

printf '%s\n' "${REPORT}"
