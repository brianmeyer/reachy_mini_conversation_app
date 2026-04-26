#!/usr/bin/env python3
from __future__ import annotations
import json
import urllib.request


BRIDGE_URL = "http://127.0.0.1:8787"


def post(path: str, payload: dict[str, object]) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BRIDGE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def get(path: str) -> dict[str, object]:
    with urllib.request.urlopen(f"{BRIDGE_URL}{path}", timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    protocol = get("/protocol")
    event = post(
        "/jetson/events",
        {"schema_version": "1", "type": "latency_sample", "stage": "stt", "duration_ms": 177, "route": "rec370-probe"},
    )
    action = post(
        "/jetson/actions",
        {"schema_version": "1", "type": "gesture", "gesture": "curious_tilt", "intensity": 0.35, "duration_ms": 800},
    )
    action_id = str(action["action"]["id"])
    pending = get("/jetson/actions/pending")
    ack = post(f"/jetson/actions/{action_id}/ack", {"status": "acked", "note": "rec370 probe"})
    behavior = post(
        "/behavior/dry-run",
        {
            "events": [
                {"schema_version": "1", "type": "wake_started", "wake_word": "reachy"},
                {
                    "schema_version": "1",
                    "type": "face_seen",
                    "target_id": "greyson",
                    "confidence": 0.88,
                    "center": {"x": 0.48, "y": 0.42},
                },
            ],
            "actions": [
                {
                    "schema_version": "1",
                    "type": "story_beat",
                    "line": "Reachy found a friendly robot castle.",
                    "gesture": "story_beat",
                    "screen": {"kind": "image_prompt", "prompt": "friendly robot castle storybook scene"},
                }
            ],
        },
    )
    latency = get("/analytics/latency?limit=50")

    result = {
        "ok": True,
        "protocol_types": {
            "events": len(protocol["protocol"]["event_types"]),
            "actions": len(protocol["protocol"]["action_types"]),
        },
        "event_id": event["event"]["id"],
        "action_id": action_id,
        "pending_seen": any(item["id"] == action_id for item in pending["actions"]),
        "ack_status": ack["action"]["status"],
        "behavior_motion_count": len(behavior["timeline"]),
        "stt_p50_ms": latency["latency"]["stages"]["stt"]["p50_ms"],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] and result["pending_seen"] and result["ack_status"] == "acked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
