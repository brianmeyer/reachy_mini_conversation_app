#!/usr/bin/env bash
set -euo pipefail

BRIDGE_URL="${BRIDGE_URL:-http://127.0.0.1:8787}"

echo "Checking Mac bridge at ${BRIDGE_URL}"
echo

echo "== Health =="
curl -sS "${BRIDGE_URL}/health"
echo
echo

echo "== Models =="
curl -sS "${BRIDGE_URL}/models" | python3 -m json.tool
echo

echo "== Parent/admin status =="
curl -sS "${BRIDGE_URL}/admin/status" | python3 -m json.tool
echo

if [ "${RUN_CLOUD_SMOKE:-0}" = "1" ]; then
  echo "== Reason smoke test =="
  curl -sS -m 90 "${BRIDGE_URL}/reason" \
    -H 'Content-Type: application/json' \
    -d '{"prompt":"Reply with exactly: mac bridge ready","prefer":"hermes"}'
  echo
else
  echo "== Reason smoke test =="
  echo "Skipped. Set RUN_CLOUD_SMOKE=1 to spend a small cloud call."
fi
echo

echo "== REC-370 protocol smoke test =="
curl -sS "${BRIDGE_URL}/protocol" | python3 -m json.tool
echo
curl -sS "${BRIDGE_URL}/jetson/events" \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":"1","type":"latency_sample","stage":"stt","duration_ms":180,"route":"mac-check"}' \
  | python3 -m json.tool
echo

echo "== Artifact smoke test =="
curl -sS "${BRIDGE_URL}/artifact" \
  -H 'Content-Type: application/json' \
  -d '{"name":"hello-reachy","kind":"html","content":"<!doctype html><title>Reachy</title><h1>Hello Reachy</h1>"}' \
  | python3 -m json.tool
