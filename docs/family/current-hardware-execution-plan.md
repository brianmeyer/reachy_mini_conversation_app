# Current Hardware Execution Plan

Date: 2026-04-25

This is the execution plan for the hardware that exists right now: Mac mini,
Jetson Orin Nano, USB mic, Mac bridge, Codex CLI, Ollama Cloud, Gemini key, and
fake/no-motion Reachy harnesses. It does not assume the physical Reachy robot is
fully built or safely movable.

## Current Locks

- Jetson + Reachy + touchscreen is the in-room target.
- Brian's fork of `pollen-robotics/reachy_mini_conversation_app` is now the
  single active repo and robot-facing runtime path:
  `https://github.com/brianmeyer/reachy_mini_conversation_app`.
- Parent dashboard, memory, planning, Mac bridge, docs, test harnesses,
  external family profile/tools, and runtime helpers live in that same repo.
- `/Users/brianmeyer/reachy` is migration source/archive only; do not continue
  product work there.
- Mac is parent/dev/back-office and Mac-only tooling.
- No local Mac models.
- No Claude API.
- No always-on local Jetson general LLM until it proves it can coexist with
  accepted STT, TTS, VAD, camera/tracking, and motion.
- vLLM is a controlled Gemma audio experiment only, not the default runtime.
- Codex/GPT-5.5 is allowed through Codex CLI/OAuth.
- Jetson/Mac Codex should use `model_reasoning_effort="low"` by default for
  normal in-room tasks. Use `none` only after measuring quality, and use
  `medium/high` only for explicit hard planning/debugging.
- Hermes belongs in future Brian/parent mode, not the kid low-latency path.

## What Is Working Now

- Mac bridge is live at `http://127.0.0.1:8787`.
- Mac bridge now reports Codex CLI as a reasoning backend.
- `POST /reason` defaults to Codex CLI/GPT-5.5 with low reasoning effort, then
  falls back to Ollama Cloud if Codex fails.
- Jetson SSH is reachable at `192.168.55.1`.
- Jetson `assistant-llm` Docker container is running.
- Jetson local Gemma is fast for tiny replies, but it is currently the main RAM
  consumer and should be moved out of the always-on kid voice path.
- Stale `claude login`/Codex MCP processes were found on the Jetson and the
  exact `claude login` process was stopped on 2026-04-25. Claude CLI state was
  quarantined under `~/.reachy_disabled_claude_20260425`, the Jetson project
  `CLAUDE.md` was moved to neutral `AGENTS.md`, and no Claude API is in the
  approved stack.
- Jetson currently enumerates the USB mic adapter, but no Reachy camera,
  `/dev/video*`, `/dev/ttyACM*`, `/dev/ttyUSB*`, or serial-by-id device is
  present yet.
- Current benchmark script exists:

```sh
scripts/jetson_latency_benchmark.py --include-codex
scripts/jetson_voice_path_probe.py
scripts/jetson_resource_probe.py
scripts/jetson_resource_probe.py --include-codex
scripts/jetson_tts_benchmark.py
scripts/jetson_piper_tts_benchmark.py
scripts/jetson_stt_benchmark.py
```

Latest full Codex benchmark report:

```text
docs/health-reports/20260425-204701-current-hardware-benchmark.md
```

Latest direct Codex values from that report:

- Mac `model_reasoning_effort=none`: 7.853 s.
- Jetson `model_reasoning_effort=none`: 5.003 s.
- Mac `model_reasoning_effort=low`: 7.137 s.
- Jetson `model_reasoning_effort=low`: 6.045 s.
- Interpretation: direct Jetson Codex is slightly faster than the Mac path in
  this run, but both are still async lanes. Use cached acknowledgement and local
  motion for first audio.

Latest health-only hardware benchmark report:

```text
docs/health-reports/20260425-153429-current-hardware-benchmark.md
```

Post-restart health-only hardware benchmark report:

```text
docs/health-reports/20260425-153859-current-hardware-benchmark.md
```

Latest Jetson voice-path probe report:

```text
docs/health-reports/20260425-154409-jetson-voice-path-probe.md
docs/health-reports/20260425-154518-jetson-voice-path-probe.md
docs/health-reports/20260425-162711-jetson-voice-path-probe.md
docs/health-reports/20260425-165201-jetson-voice-path-probe.md
```

Latest Jetson resource reports:

```text
docs/health-reports/20260425-155253-jetson-resource-probe.md
docs/health-reports/20260425-155319-jetson-resource-probe.md
docs/health-reports/20260425-155912-jetson-resource-probe.md
docs/health-reports/20260425-160606-jetson-resource-probe.md
docs/health-reports/20260425-160935-jetson-resource-probe.md
docs/health-reports/20260425-161630-jetson-resource-probe.md
docs/health-reports/20260425-165156-jetson-resource-probe.md
```

Latest bilingual speech reports:

```text
docs/health-reports/20260425-164014-jetson-tts-benchmark.md
docs/health-reports/20260425-165926-jetson-piper-tts-benchmark.md
docs/health-reports/20260425-164654-jetson-stt-benchmark.md
```

## Latest Measured Snapshot

- Ground-up reset measurement on 2026-04-25:
  `assistant-llm` Docker uses `3.796GiB / 7.441GiB`; `llama-server` RSS is
  about 3.7 GiB; `MemAvailable` is about 3.7 GiB; `CmaFree` is about 5 MiB.
  This confirms local Gemma is the RAM killer, not Codex, Hermes, the desktop,
  or the Mac hop.
- Jetson was rebooted on 2026-04-25 after a scheduled STT/Gemma experiment left
  Gemma unable to reacquire its CUDA buffer. Gemma was manually restarted and
  `http://127.0.0.1:8080/health` returned ok.
- Post-reboot Gemma state: no swap pressure, but Gemma is larger than the
  earlier steady state. Latest resource probe showed about 4.2 GiB available,
  Docker stats `3.519 GiB / 7.441 GiB`, cgroup memory `5.73 GiB`, cgroup swap
  `0.00 GiB`, `CmaFree=20.6 MiB`, and lfb `6x4MB`.
- Fragmentation remains the sharp edge: the resource probe briefly allowed GPU
  STT, but the later voice probe saw `CmaFree=8.6 MiB` with Gemma/TTS resident
  and blocked GPU STT again. Treat any Gemma/STT switch as unsafe until the
  scheduler can prove start/stop/restart recovery.
- First resource-manager policy slice is implemented in
  `reachy_runtime/resources.py` and wired into `scripts/jetson_resource_probe.py`.
  Current `voice_realtime` decision is `constrained`: pause/stop Gemma before
  GPU STT/vision/tracking, avoid new CUDA allocations, and keep first audio on a
  cached acknowledgement or warm local path.
- Mac bridge exposes `POST /resource/policy` so the parent/operator side can
  log and display the same decision. Live smoke passed on `127.0.0.1:8787`.
- `http://127.0.0.1:8787/ops` includes a Jetson Resource panel showing the
  latest resource decision, warnings, actions, and timestamp.
- `http://127.0.0.1:8787/parent` includes a compact Jetson resource row linking
  to filtered resource logs.
- `http://127.0.0.1:8787/logs?event_type=resource_decision` opens directly to
  resource decisions and summarizes mode, severity, Gemma/GPU STT status,
  warning, and action.
- `scripts/jetson_resource_probe.py` posts resource decisions to the bridge by
  default; latest live report posted in 1 ms.
- Jetson-side runtime guard is now installed in the Jetson assistant project:
  `app/resource_policy.py`, `app/mac_bridge.py`, and
  `scripts/voice_latency_probe.py` check the same resource policy before
  loading heavy STT/LLM paths. Backups were kept on the Jetson under
  `.codex-backups/20260425-resource-policy/`.
- `run_voice_chat.py` now also performs the policy preflight before loading
  CUDA STT or local Gemma. A bounded live-loop start test found the USB mic,
  asked the Mac bridge for policy, then exited cleanly because CPU fallback is
  disabled and CUDA STT was blocked under `voice_realtime=constrained`.
- Latest Jetson voice-path probe honored that guard: `voice_realtime` was
  `constrained`, GPU STT was skipped intentionally with
  `resource_policy_blocked_gpu_stt`, and the probe avoided another CUDA OOM.
- Jetson Gemma TTFT: about 0.53 s after the reboot/start recovery in the latest
  local tiny reply probe; earlier warmed probes were about 0.166 s.
- Jetson Kokoro TTS cold load+synth: about 4.23 s combined in the latest
  post-reboot voice probe.
- `scripts/jetson_tts_benchmark.py` live-tested English and Spanish Kokoro
  voices. Spanish `ef_dora` and `em_alex` work with `lang=es`, but the current
  backend is CPU-only and non-streaming, so first audio equals full synthesis:
  about 1.45-1.70 s warm for the tested Spanish phrases after a 1.97 s load.
- Piper was installed in an isolated Jetson benchmark venv at
  `/home/brianmeyer/.reachy-bench/piper-venv`, not in the main Reachy assistant
  venv. `es_ES-mls_9972-low` was downloaded under
  `/home/brianmeyer/.reachy-bench/piper-voices`.
- `scripts/jetson_piper_tts_benchmark.py` shows Piper Spanish is fast on the
  latency meter, but Brian rejected the code-switch sample by ear. Treat Piper
  as a benchmark artifact only, not a working kid-facing TTS path.
- `scripts/jetson_stt_benchmark.py` live-tested multilingual faster-whisper
  `tiny`. CPU `float32` loads but transcription fails with
  `No SGEMM backend on CPU`; CUDA `int8` is correctly skipped under constrained
  policy. CPU fallback is not currently viable on this Jetson image.
- Current voice truth: there is no working product-ready local STT/TTS path
  yet. The next voice path must either use a cloud/live speech lane for UAT or
  find a different local ASR/TTS stack that passes English, Spanish, and
  code-switch listening tests.
- Jetson faster-whisper CUDA STT: currently blocked by resource policy while
  Gemma is resident and CMA is fragmented. Earlier same-day probes both
  succeeded and OOMed depending on pressure, so treat CUDA STT as explicitly
  scheduled rather than always hot.
- Mac bridge `/health`: 13 ms in the post-restart health-only script run.
- Mac bridge `/models`: 743 ms in the post-restart health-only script run.
- Codex Mac low effort: 6.477 s in the latest script run.
- Codex Jetson low effort: 5.829 s in the latest script run.
- Codex Mac no reasoning: 9.271 s in the latest script run.
- Codex Jetson no reasoning: 4.361 s in the latest script run.
- Jetson Codex memory test: exact-response smoke passed in 5.873 s, peak
  RSS+children about 56.1 MiB. Codex is a latency concern, not a meaningful RAM
  consumer.
- Mac bridge `/reason` Codex low effort smoke: 6.521-9.885 s across two live
  smoke tests, both returning the exact requested text.

Interpretation:

- The current board cannot honestly run Gemma 4, STT, TTS, VAD, diarization,
  camera/tracking, and motion as an always-hot stack.
- The next baseline should be lean room mode: no local LLM, VAD/mic/cached
  acknowledgement/fake motion/logging first.
- vLLM/Gemma audio can be tested only after stopping `assistant-llm` and
  measuring memory/fragmentation before and after.
- Low effort is the safer default because it is supported, measured, and stable.
- `none` can be faster on Jetson for tiny prompts, but the difference is noisy
  and quality risk is higher. Treat it as an experiment for trivial
  acknowledgements or tiny formatting tasks only.
- Codex/GPT-5.5 is still multi-second. It should drive async creation and
  parent tasks, not the first spoken response.

## Execution Order

1. Keep tests green after every bridge/runtime change.
2. Use `scripts/jetson_latency_benchmark.py` as the current-hardware baseline.
3. Add a lean room-mode benchmark with no local LLM: mic, VAD/EOU, cached ack,
   fake motion, tracking stub, and resource/log reporting.
4. Move `assistant-llm` out of the default kid voice path unless a test
   explicitly enables it.
5. Benchmark always-on Silero VAD and optional TensorRT tracker as the only
   hot local model components.
6. Replace English-only STT with bilingual English/Spanish benchmarks:
   Canary 180M, Parakeet 0.6B v3, sherpa-onnx Canary, multilingual Whisper,
   and Vosk fallback.
7. Run controlled vLLM/Gemma audio fit test only after lean mode is healthy.
8. Build Jetson artifact host/kiosk path for the future touchscreen.
9. Add Parent Brian Mode as a Mac-side agent lane:
   - Brian intent/profile only.
   - Hermes and Mac Codex can be tools.
   - Never route kids into Hermes by default.
   - Never let parent-mode tools bypass review for code, memory, or motion.
10. Keep all physical movement behind fake/no-motion harnesses until hardware
   enumeration, neutral pose, and tiny safe motion pass.

## Current Tests To Run

```sh
.venv-mac-bridge/bin/python -m pytest -q
scripts/jetson_latency_benchmark.py
scripts/jetson_latency_benchmark.py --include-codex
scripts/jetson_voice_path_probe.py
scripts/jetson_resource_probe.py
scripts/jetson_resource_probe.py --include-codex
scripts/jetson_tts_benchmark.py
scripts/jetson_piper_tts_benchmark.py
scripts/jetson_stt_benchmark.py --models tiny
curl http://127.0.0.1:8787/models | python3 -m json.tool
curl http://127.0.0.1:8787/analytics/latency | python3 -m json.tool
curl http://127.0.0.1:8787/resource/policy \
  -H 'Content-Type: application/json' \
  -d '{"requested_mode":"voice_realtime","snapshot":{"mem_available_mib":3023.2,"cma_free_mib":4.2,"largest_free_block_count":39,"largest_free_block_mb":4,"gemma_running":true,"gemma_memory_gib":2.68,"gemma_swap_gib":0.82}}' \
  | python3 -m json.tool
```

Optional cloud spend tests:

```sh
curl -m 60 http://127.0.0.1:8787/reason \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Reply with exactly: bridge-codex-ready","reasoning_effort":"low"}'
```

## Linear Focus

- `REC-378`: Jetson brain router and touchscreen artifact host.
- `REC-379`: Jetson model/resource manager and latency benchmarks.
- `REC-380`: shared family memory service/context packs.
- `REC-381`: bilingual English/Spanish speech path.
- `REC-382`: Parent Brian Mode with Hermes/Mac tool integration.
- `REC-383`: Jetson Codex low-effort task wrapper and benchmark policy.
- `REC-384`: remove/disable lingering Claude process/config from the Jetson
  stack. Done on 2026-04-25; files quarantined, not deleted.
- `REC-387`: lean Jetson room mode with no local LLM hot.
- `REC-388`: controlled vLLM/Gemma audio fit test, blocked on lean mode.
- `REC-389`: benchmark tiny always-on VAD and visual tracking models.
- `REC-390`: benchmark bilingual ASR candidates with Gemma off.
