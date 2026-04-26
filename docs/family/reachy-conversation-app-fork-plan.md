# Reachy Conversation App Fork Plan

Date: 2026-04-25

Linear: `REC-391`

Fork:

- Upstream: https://github.com/pollen-robotics/reachy_mini_conversation_app
- Brian fork: https://github.com/brianmeyer/reachy_mini_conversation_app
- Local clone: `/Users/brianmeyer/reachy_mini_conversation_app`

## Decision

Yes: use the Pollen Reachy Mini conversation app as the robot-facing runtime
spine, then add our family robot extras to it.

Single-repo lock: Brian's fork of `reachy_mini_conversation_app` is now the
canonical active repo for runtime, parent dashboard, memory, planning, testing,
docs, Linear/GitHub, Mac bridge, and Jetson harnesses. The older
`/Users/brianmeyer/reachy` checkout is migration source/archive only until its
remaining private state is deliberately moved or discarded.

## Why This Is Better Than Continuing The NVIDIA Jetson Demo

The NVIDIA Jetson assistant is a useful fully local reference, but it is shaped
like a demo: local VLM/LLM, STT, TTS, VAD, camera, web UI, and motion all on an
8 GB Jetson. It is valuable for snippets, diagnostics, and local fallback
tests, but it fights our real goal: low-latency, bilingual, expressive family
interaction.

The Pollen conversation app already has the product-like pieces we need:

- `fastrtc` low-latency conversation loop.
- Gemini Live support.
- OpenAI Realtime support, though we are not assuming Codex OAuth gives us this.
- Camera tool.
- Optional head tracking.
- Dance tool.
- Emotion tool using the official recorded emotion dataset.
- Single-owner `MovementManager` that queues primary moves and blends speech
  wobble/head-tracking offsets.
- External profiles and external tools.
- Official `reachy_mini_apps` app packaging.

That means we can add family behavior instead of rebuilding the robot runtime
from scratch.

## Fork Strategy

Use one repo and one branch for active work:

- Repo: `https://github.com/brianmeyer/reachy_mini_conversation_app`
- Branch: `reachy-family-runtime`
- Upstream: `https://github.com/pollen-robotics/reachy_mini_conversation_app`

Use `upstream` to keep pulling Pollen updates. Keep our changes in three lanes:
external family profile/tools, packaged family/runtime helpers under `src/`,
and the local Mac bridge sidecar.

Current local layout:

```text
/Users/brianmeyer/reachy
/Users/brianmeyer/reachy_mini_conversation_app
```

The old `/Users/brianmeyer/reachy` path is a temporary migration source, not a
second product repo.

## First Customization Layer

Start without hard-forking core behavior where possible. Use external profiles
and tools first:

```text
external_content/
├── external_profiles/
│   └── reachy_family/
│       ├── instructions.txt
│       ├── tools.txt
│       └── voice.txt
└── external_tools/
    ├── family_memory.py
    ├── parent_log_event.py
    ├── show_kid_schedule.py
    ├── show_chore_board.py
    ├── open_artifact.py
    ├── story_screen_image.py
    └── request_codex_async.py
```

Environment shape:

```env
BACKEND_PROVIDER=gemini
MODEL_NAME=gemini-3.1-flash-live-preview
GEMINI_API_KEY=...
REACHY_MINI_CUSTOM_PROFILE=reachy_family
REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY=./external_content/external_profiles
REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY=./external_content/external_tools
```

## Our Extras To Add

Family/profile behavior:

- Brian, Preston, and Greyson awareness.
- Age/personality-aware tone: playful for kids, direct assistant mode for
  Brian/adults.
- English/Spanish/code-switch support.
- Parent-only actions gated by explicit Brian mode.

Memory:

- Tool to emit memory proposal events to the Mac bridge.
- Tool to retrieve approved profile snippets from the shared memory service.
- Never let the conversation app write kid memories directly without parent
  review.

Parent dashboard/logs:

- Tool to log watched/opened websites, model route, live session status,
  screen artifacts, and motion/tool calls.
- Tool to expose "why did Reachy do that?" event details.

Touchscreen:

- Tool to open the kid chore board.
- Tool to open the kid schedule.
- Tool to show story images.
- Tool to open/play local artifacts and simple games.

Higher brain:

- Tool to request Codex/GPT-5.5 async work for story plans, games, UI/code, and
  diagnostics.
- Tool to request Ollama Cloud fallback only for allowed non-live tasks.
- Keep these async; first audio stays local cached ack plus motion.

Agentic plan:

- Kid live lane: Gemini Live / realtime backend, family profile, named robot
  tools, quick acknowledgements, no long tool chains.
- Embodiment lane: Jetson/local app owns wake, VAD, camera, head tracking,
  dance, emotion, and safe named movement.
- Higher brain lane: Codex/GPT-5.5 through `request_codex_async` for games,
  stories, code, diagnostics, and parent-approved changes.
- Parent Brian mode: future Hermes/Codex tool lane for adult tasks, with
  explicit Brian/profile gating.
- Memory lane: log events, summarize into proposals, then require parent
  approval before profile memories become durable.
- Observability lane: parent logs, latency telemetry, model/tool route records,
  and artifact retention/delete controls.

Every agent/tool lane must write parent-visible logs and avoid raw motor
commands.

Motion/emotion:

- Keep the upstream `MovementManager` as the one movement owner.
- Add our safety policy around allowed tools, intensity, duration, and parent
  settings.
- Use official emotion/dance assets before inventing custom moves.
- Add story beat choreography as named emotions/gestures, not raw motors.

## What Probably Needs Fork Patches

External tools/profiles may not be enough for every requirement. Expect small
fork patches for:

- Better event hooks around tool start/finish/failure.
- Latency telemetry events.
- Parent-mode lockout / profile policy.
- Safer model/backend defaults for our setup.
- A headless Jetson launch profile.
- Better config around Gemini Live caps and reconnects.
- More explicit motion safety clamps and logging.

## First Implementation Order

1. Keep fork synced with upstream and create a `reachy-family-runtime` branch.
2. Add the `reachy_family` external profile and tool list.
3. Add a `parent_log_event` external tool that posts to Mac bridge
   `/jetson/events`.
4. Add `show_kid_schedule`, `show_chore_board`, and `open_artifact` tools that
   call the local touchscreen/browser path.
5. Add `family_memory` read/propose tools wired to Mac bridge memory policy.
6. Add `request_codex_async` tool for slow game/story/code tasks.
7. Run in simulation/no-motion mode first.
8. Run Gemini Live text/audio smoke.
9. Run camera/head-tracking dry run.
10. Only then run safe physical motion.

## Test Plan

Before physical motion:

- `uv sync --group dev`
- Unit tests in the fork.
- Import test for external tools.
- Profile load test for `reachy_family`.
- Mac bridge event ingestion test.
- Gemini Live backend smoke with no camera.
- Gradio/simulation launch smoke.
- Motion manager fake/no-motion test.

On Jetson:

- Confirm no local LLM hot for lean mode.
- Confirm environment variables and API key presence without printing secrets.
- Confirm Gemini/OpenAI/Ollama network reachability.
- Confirm microphone/camera devices.
- Confirm Reachy daemon is reachable.

With Reachy:

- Neutral pose.
- One tiny named emotion.
- Head tracking at low intensity.
- Story beat with one screen image.
- Barge-in/stop.

## Sources

- Reachy Mini conversation app:
  https://github.com/pollen-robotics/reachy_mini_conversation_app
- External profiles/tools docs in upstream README:
  https://github.com/pollen-robotics/reachy_mini_conversation_app#advanced-features
- Reachy Mini emotions dataset:
  https://huggingface.co/datasets/pollen-robotics/reachy-mini-emotions-library
- Reachy Mini dances dataset:
  https://huggingface.co/datasets/pollen-robotics/reachy-mini-dances-library
- Reachy Mini app publishing:
  https://huggingface.co/blog/pollen-robotics/make-and-publish-your-reachy-mini-apps
