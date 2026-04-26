# Jetson Ground-Up Stack Reset

Date: 2026-04-25

This is the current decision after re-checking the live Jetson, NVIDIA Jetson
docs/blogs, Hugging Face models, and Reachy/Pollen repositories.

Related current docs:

- [Reachy Jetson Existing Setups Research](reachy-jetson-existing-setups-research.md)
- [Reachy Conversation App Fork Plan](reachy-conversation-app-fork-plan.md)

## Hard Decision

Do not treat the Jetson as an always-on local LLM box.

The Jetson should be the low-latency embodiment computer:

- wake/listen state
- VAD and end-of-utterance detection
- barge-in/interruption
- cached acknowledgement audio
- camera capture and local tracking
- face, hand, object, and pointing-follow loops
- attention state
- emotion state
- micro-motion and dance timing
- safe Reachy SDK motion adapter
- touchscreen kiosk and local artifacts
- JSONL event spool and memory cache

The Jetson should not keep a general local model hot while also trying to run
STT, TTS, camera, tracking, diarization, and motion.

The always-on local model budget should be reserved for tiny sensing models:

- Silero VAD or equivalent ONNX VAD.
- Optional TensorRT nano detector/tracker for continuous gaze/object attention.
- Optional end-of-utterance helper after measured.

Everything generative or speech-heavy should be event-triggered, scheduled, or
cloud-backed until it proves it can live inside the memory and latency budget.

## Live Board Measurement

Measured on the Jetson Orin Nano on 2026-04-25:

- Total RAM: about 7.4 GiB.
- `assistant-llm` Docker container: `3.796GiB / 7.441GiB`, about 51%.
- `llama-server` RSS: about 3.7 GiB, about 47.9% of memory.
- `MemAvailable`: about 3.7 GiB.
- `CmaFree`: about 5 MiB.
- Swap pressure: only about 2 MiB, so this is mostly resident RAM and
  contiguous allocation pressure, not ordinary swap exhaustion.

No other process is close. Desktop services matter, but the main RAM killer is
the local Gemma/llama.cpp service.

## vLLM Decision

Do not switch the default runtime to vLLM right now.

vLLM is real on Jetson and is the documented path for trying Gemma audio, but
it is not the right always-on runtime for this 8 GB robot stack.

Reasons:

- vLLM is a serving engine optimized for throughput and batching, not the
  smallest resident footprint for one child talking to one robot.
- vLLM defaults are aggressive about memory reservation. The vLLM docs and
  NVIDIA release notes call out `gpu_memory_utilization` as a key OOM knob.
- NVIDIA's Jetson memory post warns that heavier inference frameworks can add
  over 2.7 GiB before model weights load.
- The board is already fragmented with local Gemma resident.
- Gemma audio input still only gives text output. It does not replace TTS,
  VAD, barge-in, diarization, or motion timing.

Allowed experiment:

- Test only Gemma 4 E2B audio through vLLM.
- Stop `assistant-llm` first.
- Run one request at a time.
- Use low `--gpu-memory-utilization`.
- Cap `--max-model-len`.
- Log RAM, `CmaFree`, largest free block, time to first token, and whether STT,
  TTS, VAD, and tracking can coexist.

If the fit test fails or leaves the board fragmented, vLLM stays out of the
child path.

## Local Model Decision

Keep local models optional and scheduled, not resident.

Local Gemma can remain useful for:

- offline diagnostic prompts
- very short fallback text when the network is down
- one-shot local VLM/reflex experiments
- controlled Gemma audio/vLLM fit tests

Local Gemma should not be used for:

- first kid UAT voice path
- always-on conversation
- live video reasoning
- long stories
- parent reports
- code generation
- anything that needs STT/TTS/camera/tracking hot at the same time

If we keep a local model hot later, it should be much smaller or more specific
than a general multimodal chat model: intent classification, end-of-utterance,
small VAD helper, small local VLM snapshot, or a tiny speech component.

## Speech Decision

There is no accepted local STT/TTS stack yet.

Current facts:

- `base.en` faster-whisper is English-only and not acceptable for Spanish
  immersion.
- faster-whisper CPU fallback fails on the current Jetson image with
  `No SGEMM backend on CPU`.
- CUDA STT can work or OOM depending on Gemma and fragmentation, so it must be
  scheduled.
- Kokoro Spanish speaks, but first audio is too slow with the current CPU-only,
  non-streaming path.
- Piper was fast, but Brian rejected the code-switch quality.

For first kid UAT, use one of these before pretending local speech works:

1. Gemini Live native audio/video for explicit live sessions and maybe first
   voice UAT, with strict caps and logs.
2. Cloud STT/TTS through the Mac/Jetson bridge if Gemini Live latency is not
   acceptable.
3. A new local speech candidate that passes English, Spanish, and code-switch
   samples under the resource policy.

Promising local speech candidates to benchmark:

- `nvidia/canary-180m-flash`: English, Spanish, German, French ASR/AST.
- `nvidia/parakeet-tdt-0.6b-v3`: multilingual ASR including English and
  Spanish, but heavier.
- `csukuangfj/sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8`: possible
  ONNX/sherpa path for lighter deployment.
- Whisper multilingual through `faster-whisper`, `whisper.cpp`, or
  `sherpa-onnx` with Gemma off.
- Vosk English/Spanish as a low-memory fallback if accuracy is acceptable.
- Faster, better Spanish/code-switch TTS candidates still need a real bakeoff.

Do not add diarization to the first kid path until STT/TTS works. For now,
identify Brian/Preston/Greyson through face/profile context, explicit
introductions, and parent-approved memories.

## Vision And Embodiment Decision

The "alive" feeling should come from deterministic local behavior, not from a
local chat model.

Run locally:

- Silero VAD or equivalent always-on audio gate.
- Optional YOLO/SCRFD-style TensorRT tracker for continuous attention.
- face tracking
- hand/pointing tracking
- object/screen attention
- gaze/head following
- idle listening posture
- micro-emotions
- story/dance gesture timing
- beat detection
- safety clamping

Use cloud models for:

- scene understanding
- drawings/homework explanation
- story planning
- Spanish tutoring content
- generated pictures
- code/artifact creation

Request-triggered local VLM candidates, only after the lean loop is stable:

- `HuggingFaceTB/SmolVLM2-500M-Video-Instruct`
- `HuggingFaceTB/SmolVLM2-256M-Video-Instruct`
- `vikhyatk/moondream2`
- `Qwen/Qwen2.5-VL-3B-Instruct-AWQ` only if memory is healthy and Gemma is off

Reachy/Pollen research supports this split: the official conversation app uses
real-time voice services with choreographed motion tools, head tracking, dance,
and emotion libraries. The Hugging Face datasets include a Reachy Mini emotions
library and dances library that should be reused as local motion assets.

The preferred implementation path is now Brian's fork of the Pollen
conversation app for the robot-facing runtime, plus external family
profiles/tools for memory, parent logs, touchscreen actions, and Codex async
tasks. Keep the NVIDIA Jetson assistant as a reference/demo, not the product
spine.

## VLA Decision

Do not use a VLA as the live controller now.

SmolVLA is worth tracking because it is compact and LeRobot-native, but it
needs a Reachy-specific action space and demonstrations before it can help. A
VLA should eventually choose among named skills, not output raw motor commands.

Better first target:

- build named Reachy actions
- record safe demos
- log perception and outcome
- later train/evaluate a constrained selector over actions like
  `look_at_target`, `curious_tilt`, `dance_pulse`, `story_surprise`, and
  `calm_listen`

## Locked Runtime Split

| Layer | Use | Default State |
| --- | --- | --- |
| Jetson local loop | wake, VAD/EOU, barge-in, cached audio, tracking, attention, motion, touchscreen | always on |
| Silero VAD / tracker | tiny sensing models for audio gate and gaze attention | always on if measured |
| Local Gemma/llama.cpp | offline/fallback/reflex experiments | off or scheduled |
| vLLM/Gemma audio | controlled fit test only | off |
| Gemini Live | low-latency live audio/video sessions, drawings, homework, show-and-tell | explicit, capped |
| GPT-5.5/Codex | stories, planning, code/artifacts, parent tasks | async |
| Ollama Cloud | fallback and bakeoff pool; GLM 5.1 for games | explicit fallback |
| Hermes | future Brian/parent mode tooling | not kid path |

## Next Tests

1. Stop local Gemma and measure recovered RAM, `CmaFree`, and largest free
   block.
2. Reboot if fragmentation remains too low.
3. Add a "lean room mode" test with no local LLM: VAD, mic capture, cached
   acknowledgement, fake motion, and dashboard logging.
4. Benchmark Gemini Live real mic audio from the Jetson or Mac gateway.
5. Benchmark Canary 180M / sherpa-onnx ASR on English, Spanish, and code-switch
   samples with Gemma off.
6. Run a controlled vLLM/Gemma audio fit test only after the lean baseline is
   healthy.
7. Keep `assistant-llm` disabled by default until a local model earns its RAM.

## Sources

- NVIDIA Jetson memory efficiency blog:
  https://developer.nvidia.com/blog/maximizing-memory-efficiency-to-run-bigger-models-on-nvidia-jetson/
- Jetson AI Lab Gemma 4 tutorial:
  https://www.jetson-ai-lab.com/tutorials/gemma4-on-jetson/
- NVIDIA Jetson LLM/VLM robotics blog:
  https://developer.nvidia.com/blog/getting-started-with-edge-ai-on-nvidia-jetson-llms-vlms-and-foundation-models-for-robotics/
- NVIDIA vLLM release notes:
  https://docs.nvidia.com/deeplearning/frameworks/vllm-release-notes/rel-26-02.html
- Gemini Live API:
  https://ai.google.dev/gemini-api/docs/live-api/capabilities
- Reachy Mini SDK:
  https://github.com/pollen-robotics/reachy_mini
- Reachy Mini conversation app:
  https://github.com/pollen-robotics/reachy_mini_conversation_app
- Reachy Mini emotions dataset:
  https://huggingface.co/datasets/pollen-robotics/reachy-mini-emotions-library
- Reachy Mini dances dataset:
  https://huggingface.co/datasets/pollen-robotics/reachy-mini-dances-library
- SmolVLA:
  https://huggingface.co/blog/smolvla
- NVIDIA Canary 180M Flash:
  https://huggingface.co/nvidia/canary-180m-flash
- NVIDIA Parakeet TDT 0.6B v3:
  https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
