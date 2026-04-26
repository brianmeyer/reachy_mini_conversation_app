#!/usr/bin/env python3
from __future__ import annotations
import sys
import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from reachy_runtime.protocol import protocol_inventory, validate_mac_action, validate_jetson_event


def main() -> None:
    event_payloads = [
        {"type": "wake_started", "profile": "preston", "wake_word": "reachy"},
        {"type": "face_seen", "target_id": "preston", "confidence": 0.91, "center": {"x": 0.52, "y": 0.44}},
        {"type": "latency_sample", "stage": "stt", "duration_ms": 180, "route": "jetson-local"},
    ]
    action_payloads = [
        {"type": "gesture", "gesture": "curious_tilt", "intensity": 0.4, "duration_ms": 900},
        {"type": "story_beat", "line": "Reachy found a glowing key.", "emotion": "wonder", "gesture": "story_beat"},
    ]

    events = [validate_jetson_event(payload).model_dump() for payload in event_payloads]
    actions = [validate_mac_action(payload).model_dump() for payload in action_payloads]
    print(
        json.dumps(
            {"ok": True, "protocol": protocol_inventory(), "events": events, "actions": actions},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
