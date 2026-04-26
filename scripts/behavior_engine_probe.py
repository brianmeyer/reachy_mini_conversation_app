#!/usr/bin/env python3
from __future__ import annotations
import sys
import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from reachy_runtime.behavior import SafetyPolicy, BehaviorEngine, FakeReachyAdapter
from reachy_runtime.protocol import validate_mac_action, validate_jetson_event


def main() -> None:
    engine = BehaviorEngine(FakeReachyAdapter(SafetyPolicy(min_interval_ms=0)))
    steps = [
        ("event", {"type": "wake_started", "profile": "greyson", "wake_word": "reachy"}),
        ("event", {"type": "face_seen", "target_id": "greyson", "confidence": 0.88, "center": {"x": 0.48, "y": 0.41}}),
        (
            "event",
            {
                "type": "utterance_final",
                "profile": "greyson",
                "text": "Tell me a story with pictures about a robot castle.",
            },
        ),
        (
            "action",
            {
                "type": "story_beat",
                "profile": "greyson",
                "line": "Deep under the blocky mountain, Reachy found a glowing key.",
                "voice": "narrator",
                "emotion": "wonder",
                "gesture": "story_beat",
                "screen": {
                    "kind": "image_prompt",
                    "title": "Robot Castle",
                    "prompt": "storybook image of a friendly robot finding a glowing key under a blocky mountain",
                },
                "pause_ms": 700,
            },
        ),
        ("event", {"type": "music_beat", "bpm": 112, "beat_index": 1, "confidence": 0.82}),
    ]

    results = []
    for kind, payload in steps:
        if kind == "event":
            results.append(engine.process_event(validate_jetson_event(payload)))
        else:
            results.append(engine.process_action(validate_mac_action(payload)))

    print(
        json.dumps(
            {
                "ok": True,
                "state": engine.state.model_dump(),
                "gesture_names": engine.gesture_names(),
                "results": results,
                "timeline": engine.adapter.export_timeline(),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
