#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [ -f "${HOME}/.reachy/ollama.env" ]; then
  # shellcheck disable=SC1090
  source "${HOME}/.reachy/ollama.env"
fi

if [ -f "${HOME}/.reachy/gemini.env" ]; then
  # shellcheck disable=SC1090
  source "${HOME}/.reachy/gemini.env"
fi

if [ -f "${HOME}/.reachy/openai.env" ]; then
  # shellcheck disable=SC1090
  source "${HOME}/.reachy/openai.env"
fi

export PATH="/Users/brianmeyer/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

if [ -x ".venv-mac-bridge/bin/uvicorn" ]; then
  UVICORN_CMD=(".venv-mac-bridge/bin/uvicorn")
elif [ -x ".venv/bin/uvicorn" ]; then
  UVICORN_CMD=(".venv/bin/uvicorn")
elif command -v uv >/dev/null 2>&1; then
  UVICORN_CMD=("uv" "run" "--frozen" "uvicorn")
else
  echo "Missing .venv-mac-bridge. Run:"
  echo "  python3 -m venv .venv-mac-bridge"
  echo "  .venv-mac-bridge/bin/pip install -r mac_bridge/requirements.txt"
  echo "Or install the repo environment with:"
  echo "  uv run --frozen python -V"
  exit 1
fi

export MAC_BRIDGE_HOST="${MAC_BRIDGE_HOST:-0.0.0.0}"
export MAC_BRIDGE_PORT="${MAC_BRIDGE_PORT:-8787}"
export MAC_BRIDGE_DEFAULT_MODEL="${MAC_BRIDGE_DEFAULT_MODEL:-deepseek-v4-flash:cloud}"
export MAC_BRIDGE_OPENAI_DEFAULT_MODEL="${MAC_BRIDGE_OPENAI_DEFAULT_MODEL:-gpt-5.5}"
export MAC_BRIDGE_ALLOWED_OLLAMA_MODELS="${MAC_BRIDGE_ALLOWED_OLLAMA_MODELS:-kimi-k2.6:cloud,glm-5.1:cloud,deepseek-v4-flash:cloud,nemotron-3-super:cloud,qwen3.5:cloud,minimax-m2.7:cloud,gemma4:31b-cloud}"
export MAC_BRIDGE_REQUIRE_OLLAMA_CLOUD="${MAC_BRIDGE_REQUIRE_OLLAMA_CLOUD:-true}"
export MAC_BRIDGE_HERMES_BIN="${MAC_BRIDGE_HERMES_BIN:-/Users/brianmeyer/.local/bin/hermes}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
export MAC_BRIDGE_GEMINI_TIMEOUT="${MAC_BRIDGE_GEMINI_TIMEOUT:-90}"
export MAC_BRIDGE_GEMINI_IMAGE_MODEL="${MAC_BRIDGE_GEMINI_IMAGE_MODEL:-gemini-3.1-flash-image-preview}"
export MAC_BRIDGE_GEMINI_ALLOWED_IMAGE_MODELS="${MAC_BRIDGE_GEMINI_ALLOWED_IMAGE_MODELS:-gemini-3.1-flash-image-preview,gemini-2.5-flash-image,gemini-3-pro-image-preview}"
export MAC_BRIDGE_GEMINI_DAILY_IMAGE_LIMIT="${MAC_BRIDGE_GEMINI_DAILY_IMAGE_LIMIT:-5}"
export MAC_BRIDGE_ALLOWED_URLS="${MAC_BRIDGE_ALLOWED_URLS:-http://127.0.0.1:${MAC_BRIDGE_PORT},http://localhost:${MAC_BRIDGE_PORT},http://127.0.0.1:3000,http://localhost:3000,https://www.youtube.com,https://youtube.com,https://classic.minecraft.net,https://www.minecraft.net,https://www.roblox.com}"

exec "${UVICORN_CMD[@]}" mac_bridge.app:app \
  --host "${MAC_BRIDGE_HOST}" \
  --port "${MAC_BRIDGE_PORT}"
