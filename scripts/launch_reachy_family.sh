#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [ -f "${HOME}/.reachy/gemini.env" ]; then
  # shellcheck disable=SC1090
  source "${HOME}/.reachy/gemini.env"
fi

if [ -f "${HOME}/.reachy/openai.env" ]; then
  # shellcheck disable=SC1090
  source "${HOME}/.reachy/openai.env"
fi

export BACKEND_PROVIDER="${BACKEND_PROVIDER:-gemini}"
export MODEL_NAME="${MODEL_NAME:-gemini-3.1-flash-live-preview}"
export REACHY_MINI_CUSTOM_PROFILE="${REACHY_MINI_CUSTOM_PROFILE:-reachy_family}"
export REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY="${REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY:-${ROOT_DIR}/external_content/external_profiles}"
export REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY="${REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY:-${ROOT_DIR}/external_content/external_tools}"
export REACHY_FAMILY_BRIDGE_URL="${REACHY_FAMILY_BRIDGE_URL:-http://127.0.0.1:8787}"

exec uv run reachy-mini-conversation-app "$@"
