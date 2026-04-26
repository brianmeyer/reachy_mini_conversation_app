#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

export REACHY_MINI_SKIP_DOTENV="${REACHY_MINI_SKIP_DOTENV:-1}"
export REACHY_MINI_CUSTOM_PROFILE="${REACHY_MINI_CUSTOM_PROFILE:-reachy_family}"
export REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY="${REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY:-${ROOT_DIR}/external_content/external_profiles}"
export REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY="${REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY:-${ROOT_DIR}/external_content/external_tools}"
export REACHY_FAMILY_BRIDGE_URL="${REACHY_FAMILY_BRIDGE_URL:-http://127.0.0.1:8787}"

uv run python - <<'PY'
from reachy_mini_conversation_app.tools.core_tools import ALL_TOOLS

required = {
    "parent_log_event",
    "family_memory",
    "show_kid_schedule",
    "show_chore_board",
    "open_artifact",
    "story_screen_image",
    "request_codex_async",
}
missing = sorted(required - set(ALL_TOOLS))
if missing:
    raise SystemExit(f"Missing family tools: {missing}")
print("Family profile/tools load ok")
print("Loaded family tools:", ", ".join(sorted(required)))
PY
