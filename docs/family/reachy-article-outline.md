# Article Outline: Building a Family Robot With Reachy, Jetson, and a Mac Bridge

Date: 2026-04-25

Primary source log:

- [Reachy Project Log](reachy-project-log.md)

Working title:

> Building a Kid-Friendly Family Robot Without Turning It Into a Cloud Money Pit

## Thesis

A useful home robot for kids needs three things at once:

- fast local interaction
- playful screen and creative abilities
- parent-visible safety, memory, and cost controls

The interesting engineering choice is not "local vs cloud." It is routing each
task to the cheapest, fastest, safest place that can do it well.

## Narrative Arc

1. The dream: build Reachy with the kids and make it feel alive quickly.
2. The constraint: low latency matters more than benchmark glory.
3. The split: Jetson for the local body loop, Mac mini for back-office tasks.
4. The model bakeoff: GLM won games, but not every task.
5. The memory problem: kids need personalization, parents need review.
6. The screen problem: games, drawings, YouTube, calendar, and chores.
7. The safety problem: logs, allowlists, cloud toggles, motion gates.
8. The architecture pivot: use Pollen's conversation app fork as the robot
   runtime, not the NVIDIA local-LLM demo as the product spine.
9. The next frontier: vision and duplex/live conversation.

## Sections

### 1. What We Wanted Reachy To Be

Key points:

- Not a novelty chatbot.
- Not a tablet with a face.
- A small embodied family helper and playmate.
- Useful for Brian, fun for Preston and Greyson.

### 2. The Hardware/Software Split

Explain the two-computer architecture:

- Jetson: room appliance, VAD, cached ack, tracking, motion, touchscreen,
  direct Gemini Live/Codex sessions.
- Mac mini: parent dashboard, reports, logs, Linear/GitHub, Hermes, canonical
  repo work, artifact mirror.

Possible diagram: use the Mermaid diagram from `README.md` or
`docs/system-architecture.md`.

### 3. Why Local-Only Was Not Enough

Key points:

- Local Gemma is fast for tiny text but too expensive as an always-hot resident
  beside speech/tracking/motion.
- Small local models are not the right tool for live bilingual voice, building
  games, or doing heavy reasoning yet.
- Local Mac Ollama models froze the Mac mini, so the Mac policy became
  cloud-only.
- Codex/GPT-5.5 and Gemini Live became the primary cloud lanes; Ollama Cloud
  acts as fallback/bakeoff.

### 4. Model Routing By Actual Family Tasks

Current findings:

- GLM 5.1 won the human game test.
- Gemma cloud looked best for calendar/family/kid coaching tasks.
- DeepSeek cloud is good for fast parent summaries.
- Nemotron is fast for plain tasks but not the game default.
- Qwen/Nemotron were weak on generated games in Brian's test.

Supporting file:

```text
docs/reachy-model-routing-feedback.md
docs/ollama-family-task-bakeoff.json
```

### 5. Memory Needs A Parent-In-The-Loop

Explain:

- Kids can show drawings or say preferences.
- The system can propose memories.
- Brian edits/approves/rejects them.
- Approved memories become plain Markdown.
- A future graph/vector layer can improve recall without becoming the source of
  truth.

Article angle:

> Memory is not just a database problem. In a family robot, memory is a trust
> problem.

### 6. The Family Command Center

Current surfaces:

- `/parent`: operator dashboard
- `/logs`: what happened
- `/memory`: memory review
- `/family`: parent schedule/chore editing
- `/kids`: kid-facing chore/calendar board

Talk about the Skylight-inspired direction:

- big touch targets
- visible calendar
- simple chore states
- no admin controls on kid pages

### 7. Safety Gates Before Motion

Explain why physical robot software needs a higher bar:

- hardware enumeration first
- Reachy SDK connect
- tiny neutral pose
- fake motion tests
- clamp/rate-limit gestures
- never let raw model text become motor commands

### 8. Why We Forked The Conversation App

Explain:

- NVIDIA's Jetson assistant is a useful local demo.
- DGX Spark shows a service architecture, but it is not our hardware class.
- Pollen's conversation app already has Gemini Live/OpenAI Realtime, camera
  tools, head tracking, dances, emotions, external tools/profiles, and a single
  movement manager.
- Brian's fork becomes the robot runtime; this repo remains the parent/memory
  and article hub.

Supporting files:

```text
docs/reachy-jetson-existing-setups-research.md
docs/reachy-conversation-app-fork-plan.md
```

### 9. Vision And Live Video

Current stance:

- Start with explicit live sessions and snapshots, not always-on background
  streaming.
- Use vision models when asked or when a mode clearly needs them.
- Use Gemini Live only for explicit premium sessions with visible indicators and
  timers.
- Do not stream continuous child video by default.

### 10. What Is Ready For Build Day

Ready:

- bridge
- dashboards
- logs
- memory review
- kid board
- Jetson reachability
- local LLM health
- audio capture
- model routing
- health reports

Waiting:

- Reachy hardware enumeration
- camera/control devices
- first safe motion
- real child UAT

### 11. Lessons So Far

Potential lessons:

- Optimize for "time to first smile," not theoretical architecture.
- A local-first memory file beats a fancy memory system you cannot inspect.
- Human play testing beats static model scoring for games.
- Parent controls should exist before kid delight features go wide.
- Latency is a product feature.
- The robot feels alive because of local timing and motion, not because an LLM
  thinks every millisecond.

## Screenshots To Capture Later

- Parent dashboard
- Kid board
- Memory proposal review
- Logs page
- GLM-generated game artifact
- Health report snippet
- First Reachy hardware enumeration
- First successful neutral pose

## Source Links

- Reachy Mini SDK: https://github.com/pollen-robotics/reachy_mini
- Reachy Mini overview: https://www.pollen-robotics.com/reachy-mini/
- Jetson AI Lab Gemma 4 tutorial: https://www.jetson-ai-lab.com/tutorials/gemma4-on-jetson/
- NVIDIA Gemma 4 Jetson blog: https://developer.nvidia.com/blog/bringing-ai-closer-to-the-edge-and-on-device-with-gemma-4/
- Ollama Cloud models: https://ollama.com/blog/cloud-models
- Gemini Live API: https://ai.google.dev/api/multimodal-live
- Gemini image generation: https://ai.google.dev/gemini-api/docs/image-generation
- Reachy project log: docs/reachy-project-log.md
