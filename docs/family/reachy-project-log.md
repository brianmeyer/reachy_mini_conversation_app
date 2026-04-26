# Reachy Project Log

Date: 2026-04-25

This is the chronological source log for the build and for Brian's future
article. Keep it high signal: decisions, measurements, sources, Linear issues,
and why we changed direction.

## North Star

Build a Reachy Mini family robot that feels alive and useful without becoming a
fragile pile of demos. It should be fun for Preston and Greyson, useful for
Brian, English/Spanish capable, parent-visible, and fast enough that kids do
not feel like they are waiting on a chatbot.

## Current Architecture Decision

The project is now split into two code homes:

- `reachy-family-robot`: parent dashboard, memory, Mac bridge, model routing,
  docs, tests, Linear/GitHub work, benchmarks, and article log.
- `reachy_mini_conversation_app`: Brian's fork of the Pollen conversation app,
  used as the robot-facing runtime.

Local filesystem layout:

- `/Users/brianmeyer/reachy`
- `/Users/brianmeyer/reachy_mini_conversation_app`

The fork is a sibling repo, not vendored into this repo.

Runtime split:

- Jetson: in-room appliance for wake/listen, VAD, barge-in, cached
  acknowledgement, camera sampling, head/hand/pointing tracking, attention,
  safe motion, emotion/dance playback, touchscreen, event spool, and direct
  cloud sessions.
- Gemini Live: explicit live audio/video sessions, drawings, homework,
  show-and-tell, and low-latency visual conversation.
- Codex/GPT-5.5: async higher brain for story plans, games/artifacts,
  diagnostics, parent-approved code/tool tasks, and deeper reasoning.
- Ollama Cloud: fallback/bakeoff pool, not local Mac models.
- Mac mini: parent/dev/back-office, Hermes, dashboards, logs, reports,
  GitHub/Linear, canonical repo work, and artifact mirror.

## Timeline

### Initial Family Robot Scope

Brian wanted Reachy to be more than a chatbot: kid playmate, parent assistant,
Spanish helper, memory-aware family robot, touchscreen command center, game
maker, story performer, and eventually self-editing/code-aware with parent
approval.

Profiles named:

- Brian
- Preston
- Greyson

Key constraints:

- No Claude API.
- No local Mac models because they can freeze the Mac.
- Ollama Cloud is allowed as fallback.
- Latency is a product requirement, especially for kid voice.
- Parent-visible logs, memory approval, and model-routing visibility matter.

### Mac Bridge And Parent Surfaces

Built and tested local Mac bridge surfaces:

- `/parent`
- `/ops`
- `/logs`
- `/memory`
- `/family`
- `/kids`
- `/gallery`
- `/command`

Added:

- Parent dashboard/reporting.
- General logs page.
- Memory proposal review flow.
- Kid chore board and schedule direction.
- Model routing analytics.
- Latency telemetry hooks.
- Artifact gallery.
- Jetson/Mac event-action protocol.

### Ollama Cloud Bakeoff

Brian evaluated generated games by seeing the artifacts, not just reading model
answers.

Observed result:

- GLM 5.1 produced the best playable game.
- DeepSeek, MiniMax, and Kimi were tied for second.
- Qwen and Nemotron were weak for the game task.

Current routing consequence:

- GPT-5.5/Codex is preferred for higher-brain work.
- GLM 5.1 remains the known-good Ollama Cloud fallback for games.
- Ollama Cloud stays fallback/experimentation, not the realtime voice/video
  brain.

Evidence:

- [Model Routing Feedback](reachy-model-routing-feedback.md)
- `docs/ollama-equal-game-rounds.json`
- `docs/ollama-family-task-bakeoff.json`

### Memory Policy

Decision:

- One shared family memory service.
- Parent-approved memory proposals.
- Approved kid/family memories as readable Markdown/local state first.
- Models get task-scoped context packs; they do not own separate memories.
- Images/drawings shown to Reachy should be logged as artifacts and can produce
  memory proposals.

Open direction:

- Add a simple two-layer memory system later: durable approved facts plus
  recall/semantic layer.
- Keep the approved record editable/deletable by Brian.

Evidence:

- [Memory Learning Loop](reachy-memory-learning-loop.md)

### Jetson Live Board Findings

Jetson reachable:

- SSH over USB works at `192.168.55.1`.
- mDNS names like `jetson.local` are not reliable right now.

Measured memory:

- Total RAM: about `7.4 GiB`.
- `assistant-llm`/`llama-server`: about `3.796 GiB`, roughly half the board.
- `MemAvailable` with Gemma hot: about `3.7 GiB`.
- `CmaFree` was previously about `5 MiB`, which is a fragmentation warning.

Interpretation:

- Local Gemma/llama.cpp is the main RAM resident.
- Codex is not a RAM problem; it is a latency problem.
- Do not keep a general local LLM hot in the kid voice path.

Evidence:

- [Latency Benchmarks](reachy-latency-benchmarks.md)
- [Current Hardware Execution Plan](current-hardware-execution-plan.md)
- Generated report: `docs/health-reports/20260425-204701-current-hardware-benchmark.md`

### Local Speech Stack Reset

No local STT/TTS path is accepted yet.

Findings:

- Piper Spanish was fast, but Brian rejected code-switch quality.
- Kokoro Spanish works, but current first-audio behavior is too slow/non-streaming.
- `faster-whisper base.en` is English-only and not acceptable for Spanish.
- faster-whisper CPU fallback hit `No SGEMM backend on CPU`.
- CUDA STT can OOM or become unreliable with local Gemma resident.

Decision:

- Do not pretend local STT/TTS is ready.
- Use Gemini Live for first real live voice/video UAT if it passes measured
  latency and cost caps.
- Benchmark bilingual ASR candidates with local Gemma off.

Candidates:

- `nvidia/canary-180m-flash`
- `csukuangfj/sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8`
- multilingual Whisper via faster-whisper/whisper.cpp/sherpa-onnx
- Vosk English/Spanish fallback if quality is enough

Evidence:

- [Jetson Ground-Up Stack Reset](jetson-ground-up-stack-reset.md)
- [Latency Benchmarks](reachy-latency-benchmarks.md)

### Direct Jetson Cloud Path

Codex CLI is installed on the Jetson and logged in with ChatGPT.

Latest tiny-prompt benchmark:

- Mac `model_reasoning_effort=none`: `7.853 s`.
- Jetson `model_reasoning_effort=none`: `5.003 s`.
- Mac `model_reasoning_effort=low`: `7.137 s`.
- Jetson `model_reasoning_effort=low`: `6.045 s`.

Interpretation:

- Jetson-direct Codex can be slightly faster than Mac-hop Codex.
- Both are too slow for first-audio.
- Use Codex/GPT-5.5 for async room tasks, local artifacts, story planning, and
  diagnostics.
- Use cached acknowledgement and local micro-motion while waiting.

Evidence:

- Generated report: `docs/health-reports/20260425-204701-current-hardware-benchmark.md`
- [Current Hardware Execution Plan](current-hardware-execution-plan.md)

### NVIDIA Jetson Assistant Research

NVIDIA's `reachy-mini-jetson-assistant` is a useful local demo:

```text
Reachy mic -> Silero VAD -> faster-whisper STT
Reachy camera -> OpenCV/V4L2 ring buffer
STT + frames -> llama.cpp VLM/LLM
LLM stream -> Kokoro TTS -> Reachy speaker + motion
Web UI -> FastAPI/WebSocket stats and camera
```

Useful parts to copy:

- Reachy daemon cleanup and `media_backend="no_media"` pattern.
- Silero VAD and audio/camera handling ideas.
- Camera ring buffer with lower model FPS than UI FPS.
- TTS subprocess isolation.
- Diagnostics for camera, mic, CUDA, RAM, swap, and model server.

Not the product spine:

- Fully local STT/TTS/VLM/LLM on 8 GB Jetson.
- English-only default STT.
- Keeping the local LLM hot while also expecting speech/tracking/motion to stay
  responsive.

Evidence:

- [Reachy Existing Setups Research](reachy-jetson-existing-setups-research.md)

### DGX Spark Research

NVIDIA's Spark + Reachy demo is a design reference, not our deployment target.

DGX Spark has `128 GB` unified memory and runs a multi-service local stack:

- NeMo Agent Toolkit / ReAct agent.
- `openai/gpt-oss-20b` via TensorRT-LLM.
- Riva/Parakeet STT.
- Kokoro TTS.
- FLUX image generation.
- Detectron2 + ByteTrack user tracking.
- Redpanda, MinIO, UI, metrics, robot controller, animation services.

What to copy:

- Service boundaries.
- Message bus thinking.
- Separate robot controller from model services.
- Animation database/compositor concept.
- Metrics/observability.

What not to copy:

- DGX-scale service count on an 8 GB Jetson.
- Local image generation/LLM/STT/TTS/tracking as the starting point.

Evidence:

- [Reachy Existing Setups Research](reachy-jetson-existing-setups-research.md)

### Pollen / Hugging Face Conversation App Pivot

Decision:

Use Pollen's `reachy_mini_conversation_app` as the robot-facing runtime spine.

Why:

- It already has `fastrtc`, Gemini Live, OpenAI Realtime, camera tool, head
  tracking, dance/emotion tools, external profiles/tools, and a single-owner
  movement manager.
- Apache-2.0 license is compatible.
- It aligns better with our family robot than the NVIDIA local-LLM demo.

Fork state:

- Brian fork: https://github.com/brianmeyer/reachy_mini_conversation_app
- Local clone: `/Users/brianmeyer/reachy_mini_conversation_app`
- Branch: `reachy-family-runtime`
- Linear: `REC-391`

First fork target:

- `reachy_family` external profile.
- `parent_log_event` external tool.
- Memory proposal/retrieval tools.
- Kid schedule/chore/artifact/story-screen tools.
- Codex async request tool.
- Gemini Live/no-motion smoke test.

Evidence:

- [Reachy Conversation App Fork Plan](reachy-conversation-app-fork-plan.md)
- [Reachy Existing Setups Research](reachy-jetson-existing-setups-research.md)

## Linear Tickets Mentioned In This Phase

- `REC-357`: voice latency telemetry dashboard.
- `REC-378`: Jetson brain router and touchscreen artifact host.
- `REC-379`: Jetson model/resource manager and latency benchmarks.
- `REC-380`: shared family memory service/context packs.
- `REC-381`: bilingual English/Spanish speech path.
- `REC-382`: Brian/parent mode with Hermes/Mac tool integration.
- `REC-383`: Jetson Codex low-effort task wrapper.
- `REC-384`: remove/disable lingering Claude process/config from Jetson.
- `REC-387`: lean Jetson room mode with no local LLM hot.
- `REC-388`: controlled vLLM/Gemma audio fit test.
- `REC-389`: benchmark tiny always-on VAD/tracking models.
- `REC-390`: benchmark bilingual ASR candidates with Gemma off.
- `REC-391`: adopt Reachy Mini conversation app fork as robot runtime.

## Article Hooks

Potential article framing:

- "The hard part was not choosing local or cloud. It was choosing which layer
  needed to be fast, private, cheap, or smart."
- "A family robot's memory is not just a database problem. It is a trust
  problem."
- "The robot feels alive because of timing and motion, not because an LLM is
  thinking every millisecond."
- "Local models are useful, but on an 8 GB Jetson every resident model has to
  earn its RAM."

## Source Links

- Reachy Mini SDK: https://github.com/pollen-robotics/reachy_mini
- Reachy Mini media architecture:
  https://huggingface.co/docs/reachy_mini/en/SDK/media-architecture
- Reachy Mini conversation app:
  https://github.com/pollen-robotics/reachy_mini_conversation_app
- Brian's conversation app fork:
  https://github.com/brianmeyer/reachy_mini_conversation_app
- Reachy Mini app publishing:
  https://huggingface.co/blog/pollen-robotics/make-and-publish-your-reachy-mini-apps
- Reachy Mini emotions dataset:
  https://huggingface.co/datasets/pollen-robotics/reachy-mini-emotions-library
- Reachy Mini dances dataset:
  https://huggingface.co/datasets/pollen-robotics/reachy-mini-dances-library
- NVIDIA Reachy Mini Jetson Assistant:
  https://github.com/NVIDIA-AI-IOT/reachy-mini-jetson-assistant
- NVIDIA Jetson memory efficiency:
  https://developer.nvidia.com/blog/maximizing-memory-efficiency-to-run-bigger-models-on-nvidia-jetson/
- Spark & Reachy Photo Booth:
  https://build.nvidia.com/spark/spark-reachy-photo-booth
- NVIDIA Spark Reachy Photo Booth repo:
  https://github.com/NVIDIA/spark-reachy-photo-booth
- NVIDIA DGX Spark overview:
  https://nvidianews.nvidia.com/news/nvidia-dgx-spark-arrives-for-worlds-ai-developers/
- Gemini Live API:
  https://ai.google.dev/gemini-api/docs/live-api
- Gemini Live session management:
  https://ai.google.dev/gemini-api/docs/live-session
- NVIDIA Canary 180M Flash:
  https://huggingface.co/nvidia/canary-180m-flash
- Sherpa ONNX Canary int8:
  https://huggingface.co/csukuangfj/sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8
- SmolVLM2 500M:
  https://huggingface.co/HuggingFaceTB/SmolVLM2-500M-Video-Instruct
