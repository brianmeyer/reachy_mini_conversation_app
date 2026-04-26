# Reachy Mini Mac Bridge

This is a local FastAPI service for the Mac side of a Reachy Mini setup. The
current target is Jetson + Reachy + touchscreen in the family/kids room, with
the Mac as parent/dev/back-office. The Jetson should host the room experience;
the Mac bridge mirrors artifacts, exposes parent/admin controls, and handles
Mac-only tools such as GitHub, Linear, reports, and canonical repo work.

## What it provides

- `GET /health` checks that the bridge is alive.
- `GET /tools` reports the callable bridge tools and the local Jetson tool split.
- `GET /models` reports whether Hermes is on PATH and whether Ollama is reachable.
- `POST /reason` defaults to Codex CLI/GPT-5.5 using ChatGPT/Codex auth and
  low reasoning effort, then falls back to Ollama Cloud. OpenAI API can still
  be requested with `"prefer":"openai"` when `OPENAI_API_KEY` is configured.
  Hermes can still be requested explicitly with `"prefer":"hermes"`.
- `POST /artifact` saves a text artifact under `mac_bridge/artifacts/`.
- Generated artifacts are served from `/artifacts/...` so the Mac browser can
  review/mirror them. The production kid-room target is the Jetson touchscreen.
- `POST /screen/open` opens an allowlisted local URL on the Mac.
- `POST /screen/clear` opens `about:blank`.
- `POST /gemini/image` generates a kid-safe picture with Gemini image models,
  saves it under `mac_bridge/artifacts/`, and optionally opens it on the Mac.
- `GET /parent` opens the parent/operator panel for build-day status, screen
  clearing, cloud enable/disable, image quota, and latest artifacts.
- `GET /admin/status` and `POST /admin/cloud` provide the parent-control API.
- `GET /logs` opens the parent activity log for screen, website, model, tool,
  and image history.
- `GET /ops` opens the parent ops page for latency telemetry, recap summaries,
  media allowlist controls, routing analytics, emotion dry-runs, and Gemini
  Live dry-run caps.
- `GET /analytics/latency`, `GET /analytics/routing`, and `GET /reports/summary`
  provide structured parent-report data over local events.
- `GET /media/policy`, `POST /media/allowlist`, and
  `POST /media/allowlist/remove` provide runtime site approval controls.
- `GET /gallery` opens artifact retention/delete controls, backed by
  `GET /artifacts/list` and `POST /admin/artifacts/{artifact_name}/delete`.
- `GET /command` opens a touchscreen command-center mock for family/kid UAT.
- `GET /emotion/state` and `POST /emotion/simulate` provide a no-motion emotion
  state dry-run before physical Reachy control.
- `GET /gemini/live/status` and `POST /gemini/live/session` track Gemini Live
  dry-run session budget/caps before real duplex streaming is wired.
- `POST /gemini/live/probe` opens a real server-side Gemini Live connection via
  `google-genai` and returns text/audio metadata for setup validation.
- `GET /events`, `POST /events/log`, and `POST /memory/capture-image` provide
  the recall trail API.
- `GET /protocol`, `POST /jetson/events`, `POST /jetson/actions`,
  `GET /jetson/actions/pending`, and `POST /jetson/actions/{id}/ack` provide
  the typed Jetson/Mac event-action contract for the embodied runtime.
- `GET /behavior/gestures` and `POST /behavior/dry-run` provide a fake-Reachy
  motion timeline before physical movement is allowed.
- `GET /memory` opens the parent memory review queue.
- `GET /memory/profiles`, `GET/POST /memory/proposals`,
  `POST /memory/proposals/generate`, and approve/reject endpoints provide the
  parent-approved memory loop.
- `POST /memory/profiles` and `POST /memory/profiles/introduction` provide the
  foundation for adding people through parent UI or Reachy voice introductions.
- `GET /family` opens the parent family board for local schedule and chores.
- `GET /kids` opens the kid-facing chore kanban and clickable calendar.
- `GET /family/board`, `POST /family/events`, and `POST /family/chores`
  provide the local schedule/chore API.

## Safety defaults

- The service binds to `127.0.0.1` by default, so only the Mac can call it.
- To allow your Jetson on the same LAN to call it, set `MAC_BRIDGE_HOST=0.0.0.0`
  only on a trusted local network.
- The service does not run shell strings. The Hermes call uses a fixed executable
  path and sends the prompt through standard input.
- `/screen/open` only opens URLs that start with the configured allowlist.
- All Hermes and Ollama calls have timeouts.
- Direct Ollama calls are cloud-only by default. Local Mac models such as
  `qwen3:4b` are rejected unless `MAC_BRIDGE_REQUIRE_OLLAMA_CLOUD=false`.
- OpenAI `gpt-5.5` is the preferred cloud reasoning route when configured.
  Ollama Cloud is the fallback pool, not a local Mac model path.
- Jetson-direct Codex/GPT-5.5 is preferred for in-room async local artifacts
  when latency is acceptable. Mac Codex/GPT-5.5 remains the canonical route for
  repo, GitHub, Linear, and dashboard/backend edits.
- Do not assume Codex OAuth grants this local app OpenAI Realtime API access.
  Until that is proven, Gemini Live remains the realtime prototype path.
- Gemini image generation is capped by `MAC_BRIDGE_GEMINI_DAILY_IMAGE_LIMIT`
  so child prompts cannot silently run up image charges.
- Cloud reasoning/tool/image calls can be disabled at runtime from the parent
  panel without stopping local status/screen controls.
- Child profile memories are not written automatically. Reachy can propose
  memories from logs and images, but a parent must approve them before the Mac
  bridge appends to the Jetson Markdown profile file.
- Voice-introduced people start as pending profiles. Parent review should decide
  role, age group, persona mode, and whether any memory/cloud permissions apply.
- The Jetson/Mac protocol rejects unknown message types and extra fields.
- Jetson actions are queued as named actions only. Gesture actions must use the
  safe gesture allowlist; raw motor, servo, joint, angle, `set_target`, or
  `goto_target` style commands are rejected before reaching a real adapter.

## Install

From `/Users/brianmeyer/reachy_mini_conversation_app`:

```bash
python3 -m venv .venv-mac-bridge
source .venv-mac-bridge/bin/activate
pip install -r mac_bridge/requirements.txt
```

## Run on the Mac only

```bash
source .venv-mac-bridge/bin/activate
uvicorn mac_bridge.app:app --host 127.0.0.1 --port 8787
```

Open the built-in API page:

```text
http://127.0.0.1:8787/docs
```

## Run for a trusted LAN

Only do this on a trusted home/lab network:

```bash
source .venv-mac-bridge/bin/activate
MAC_BRIDGE_HOST=0.0.0.0 MAC_BRIDGE_PORT=8787 uvicorn mac_bridge.app:app --host 0.0.0.0 --port 8787
```

Then the Jetson can call:

```text
http://<your-mac-lan-ip>:8787/health
```

## Useful settings

```bash
export MAC_BRIDGE_DEFAULT_MODEL=qwen3-coder-next:cloud
export MAC_BRIDGE_OPENAI_DEFAULT_MODEL=gpt-5.5
export MAC_BRIDGE_CODEX_DEFAULT_MODEL=gpt-5.5
export MAC_BRIDGE_CODEX_REASONING_EFFORT=low
export MAC_BRIDGE_CODEX_TIMEOUT=45
export MAC_BRIDGE_REQUIRE_OLLAMA_CLOUD=true
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export MAC_BRIDGE_HERMES_BIN=hermes
export MAC_BRIDGE_HERMES_TIMEOUT=45
export MAC_BRIDGE_OLLAMA_TIMEOUT=60
export MAC_BRIDGE_GEMINI_IMAGE_MODEL=gemini-3.1-flash-image-preview
export MAC_BRIDGE_GEMINI_DAILY_IMAGE_LIMIT=5
export MAC_BRIDGE_ALLOWED_URLS=http://127.0.0.1:8787,http://localhost:8787,http://127.0.0.1:3000,http://localhost:3000
```

Add your own screen host URLs to `MAC_BRIDGE_ALLOWED_URLS`, separated by commas.
Keep this list curated instead of allowing arbitrary websites.

## Quick checks

```bash
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/tools
curl http://127.0.0.1:8787/models
curl -X POST http://127.0.0.1:8787/reason \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Say hello from the Mac bridge.","reasoning_effort":"low"}'
curl -X POST http://127.0.0.1:8787/artifact \
  -H 'Content-Type: application/json' \
  -d '{"name":"hello","kind":"html","content":"<h1>Hello Reachy</h1>"}'
curl -X POST http://127.0.0.1:8787/gemini/image \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"A cheerful watercolor sticker of a friendly home robot, no text","open_image":false}'
open http://127.0.0.1:8787/parent
open http://127.0.0.1:8787/ops
open http://127.0.0.1:8787/logs
open http://127.0.0.1:8787/memory
open http://127.0.0.1:8787/gallery
open http://127.0.0.1:8787/command
curl -X POST http://127.0.0.1:8787/admin/cloud \
  -H 'Content-Type: application/json' \
  -d '{"enabled":false}'
curl -X POST http://127.0.0.1:8787/memory/proposals/generate \
  -H 'Content-Type: application/json' \
  -d '{"limit":200}'
curl -X POST http://127.0.0.1:8787/memory/profiles/introduction \
  -H 'Content-Type: application/json' \
  -d '{"utterance":"Hi Reachy, this is Danielle","introduced_by":"brian"}'
open http://127.0.0.1:8787/family
open http://127.0.0.1:8787/kids
curl -X POST http://127.0.0.1:8787/family/events \
  -H 'Content-Type: application/json' \
  -d '{"title":"Build day","date":"2026-04-25","category":"family","profiles":["preston","greyson"]}'
curl -X POST http://127.0.0.1:8787/gemini/live/session \
  -H 'Content-Type: application/json' \
  -d '{"mode":"audio","requested_seconds":60,"dry_run":true}'
curl -X POST http://127.0.0.1:8787/gemini/live/probe \
  -H 'Content-Type: application/json' \
  -d '{"response_modality":"TEXT"}'
python scripts/ollama_family_task_bakeoff.py
```
