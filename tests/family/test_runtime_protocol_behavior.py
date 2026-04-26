from __future__ import annotations
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

import mac_bridge.app as bridge
from reachy_runtime.behavior import SafetyPolicy, BehaviorEngine, FakeReachyAdapter
from reachy_runtime.protocol import validate_mac_action, validate_jetson_event


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "1", "type": "wake_started", "wake_word": "reachy"},
        {"schema_version": "1", "type": "utterance_final", "text": "Tell me a story.", "duration_ms": 900},
        {"schema_version": "1", "type": "face_seen", "confidence": 0.92, "center": {"x": 0.5, "y": 0.4}},
        {"schema_version": "1", "type": "gaze_target", "target": "preston", "center": {"x": 0.5, "y": 0.4}},
        {"schema_version": "1", "type": "motion_blocked", "gesture": "raw_motor", "reason": "unsafe"},
        {"schema_version": "1", "type": "latency_sample", "stage": "stt", "duration_ms": 180},
    ],
)
def test_valid_jetson_events(payload: dict[str, object]) -> None:
    event = validate_jetson_event(payload)

    assert event.schema_version == "1"
    assert event.type == payload["type"]


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "1", "type": "nope"},
        {"schema_version": "2", "type": "wake_started"},
        {"schema_version": "1", "type": "face_seen", "confidence": "0.92", "center": {"x": 0.5, "y": 0.4}},
        {"schema_version": "1", "type": "wake_started", "surprise": True},
        {"schema_version": "1", "type": "latency_sample", "stage": "stt", "duration_ms": "180"},
    ],
)
def test_invalid_jetson_events_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        validate_jetson_event(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "1", "type": "gesture", "gesture": "curious_tilt", "intensity": 0.4, "duration_ms": 900},
        {"schema_version": "1", "type": "look_at", "target": "greyson", "center": {"x": 0.4, "y": 0.5}},
        {"schema_version": "1", "type": "story_beat", "line": "Reachy found a key.", "gesture": "story_beat"},
        {"schema_version": "1", "type": "start_live_mode", "mode": "audio_video", "requested_seconds": 60},
    ],
)
def test_valid_mac_actions(payload: dict[str, object]) -> None:
    action = validate_mac_action(payload)

    assert action.schema_version == "1"
    assert action.type == payload["type"]


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "1", "type": "raw_motor", "angle": 120},
        {"schema_version": "2", "type": "gesture", "gesture": "curious_tilt"},
        {"schema_version": "1", "type": "gesture", "gesture": "curious_tilt", "intensity": "0.4"},
        {"schema_version": "1", "type": "story_beat", "line": "hello", "unknown": True},
    ],
)
def test_invalid_mac_actions_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        validate_mac_action(payload)


def test_protocol_jsonl_round_trip(tmp_path: Path) -> None:
    event = validate_jetson_event(
        {"schema_version": "1", "type": "latency_sample", "stage": "tts", "duration_ms": 220}
    )
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps(event.model_dump(mode="json")) + "\n", encoding="utf-8")

    loaded = validate_jetson_event(json.loads(path.read_text(encoding="utf-8").strip()))

    assert loaded.type == "latency_sample"
    assert loaded.duration_ms == 220


def test_behavior_engine_runs_named_gestures_and_rejects_raw_motion() -> None:
    engine = BehaviorEngine(FakeReachyAdapter(SafetyPolicy(min_interval_ms=0)))
    result = engine.process_event(
        validate_jetson_event(
            {
                "schema_version": "1",
                "type": "face_seen",
                "target_id": "preston",
                "confidence": 0.9,
                "center": {"x": 0.5, "y": 0.4},
            }
        )
    )

    assert result["motions"][0]["gesture"] == "look_at_target"
    assert result["motions"][0]["status"] == "dry_run"

    with pytest.raises(ValueError):
        engine.execute_gesture("set_target_head_yaw_180")


def test_behavior_engine_clamps_intensity_duration_and_rate() -> None:
    engine = BehaviorEngine(
        FakeReachyAdapter(SafetyPolicy(max_intensity=0.5, max_duration_ms=1_000, min_interval_ms=10_000))
    )

    first = engine.execute_gesture("happy_bounce", intensity=1.0, duration_ms=8_000)
    second = engine.execute_gesture("happy_bounce", intensity=0.4, duration_ms=800)

    assert first.applied_intensity == 0.5
    assert first.applied_duration_ms == 1_000
    assert second.status == "blocked"
    assert second.reason.startswith("rate_limited")


def test_protocol_endpoint_and_jetson_event_ingestion(tmp_path: Path, monkeypatch) -> None:
    events_file = tmp_path / "events.jsonl"
    monkeypatch.setattr(bridge, "_event_log_path", lambda: events_file)
    client = TestClient(bridge.app)

    protocol = client.get("/protocol")
    posted = client.post(
        "/jetson/events",
        json={
            "schema_version": "1",
            "type": "latency_sample",
            "stage": "stt",
            "duration_ms": 180,
            "route": "jetson-local",
        },
    )
    latency = client.get("/analytics/latency").json()["latency"]

    assert protocol.status_code == 200
    assert "latency_sample" in protocol.json()["protocol"]["event_types"]
    assert posted.status_code == 200
    assert posted.json()["event"]["event_type"] == "latency_sample"
    assert latency["stages"]["stt"]["p50_ms"] == 180


def test_jetson_action_queue_ack_and_safety(tmp_path: Path, monkeypatch) -> None:
    actions_file = tmp_path / "jetson-actions.jsonl"
    events_file = tmp_path / "events.jsonl"
    monkeypatch.setattr(bridge, "_jetson_actions_path", lambda: actions_file)
    monkeypatch.setattr(bridge, "_event_log_path", lambda: events_file)
    client = TestClient(bridge.app)

    queued = client.post(
        "/jetson/actions",
        json={
            "schema_version": "1",
            "type": "gesture",
            "gesture": "curious_tilt",
            "intensity": 0.4,
            "duration_ms": 900,
        },
    )
    action_id = queued.json()["action"]["id"]
    pending = client.get("/jetson/actions/pending").json()["actions"]
    acked = client.post(f"/jetson/actions/{action_id}/ack", json={"status": "acked", "note": "dry run consumed"})
    blocked = client.post(
        "/jetson/actions",
        json={
            "schema_version": "1",
            "type": "gesture",
            "gesture": "set_target_head_yaw_180",
            "intensity": 0.4,
            "duration_ms": 900,
        },
    )

    assert queued.status_code == 200
    assert pending[0]["id"] == action_id
    assert acked.status_code == 200
    assert acked.json()["action"]["status"] == "acked"
    assert blocked.status_code == 400
    assert "raw_motor" in blocked.json()["detail"]["error"]


def test_behavior_dry_run_endpoint_returns_motion_timeline(tmp_path: Path, monkeypatch) -> None:
    events_file = tmp_path / "events.jsonl"
    monkeypatch.setattr(bridge, "_event_log_path", lambda: events_file)
    client = TestClient(bridge.app)

    response = client.post(
        "/behavior/dry-run",
        json={
            "events": [
                {"schema_version": "1", "type": "wake_started", "wake_word": "reachy"},
                {"schema_version": "1", "type": "utterance_final", "text": "Tell me a robot castle story."},
            ],
            "actions": [
                {
                    "schema_version": "1",
                    "type": "story_beat",
                    "line": "Reachy opened the glowing door.",
                    "gesture": "story_beat",
                    "screen": {"kind": "image_prompt", "prompt": "storybook robot opening a glowing door"},
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["timeline"]
    assert body["timeline"][-1]["gesture"] == "story_beat"
    assert body["event"]["event_type"] == "behavior_dry_run"
