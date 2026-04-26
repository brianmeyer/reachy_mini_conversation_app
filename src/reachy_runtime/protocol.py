from __future__ import annotations
import time
import uuid
from typing import Any, Literal, Annotated

from pydantic import Field, BaseModel, ConfigDict, TypeAdapter


PROTOCOL_VERSION = "1"


def _message_id() -> str:
    return uuid.uuid4().hex[:16]


def _timestamp_ms() -> int:
    return int(time.time() * 1000)


class StrictMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class NormalizedPoint(StrictMessage):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class NormalizedBox(StrictMessage):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class ProtocolEnvelope(StrictMessage):
    schema_version: Literal["1"] = PROTOCOL_VERSION
    message_id: str = Field(default_factory=_message_id, min_length=6, max_length=80)
    timestamp_ms: int = Field(default_factory=_timestamp_ms, ge=0)
    source: str = Field(default="jetson", min_length=1, max_length=80)
    session_id: str | None = Field(default=None, max_length=120)
    profile: str | None = Field(default=None, max_length=80)


class WakeStartedEvent(ProtocolEnvelope):
    type: Literal["wake_started"] = "wake_started"
    wake_word: str | None = Field(default=None, max_length=80)


class WakeTimeoutEvent(ProtocolEnvelope):
    type: Literal["wake_timeout"] = "wake_timeout"
    reason: str | None = Field(default=None, max_length=160)


class UtterancePartialEvent(ProtocolEnvelope):
    type: Literal["utterance_partial"] = "utterance_partial"
    text: str = Field(min_length=1, max_length=1_000)
    confidence: float | None = Field(default=None, ge=0, le=1)


class UtteranceFinalEvent(ProtocolEnvelope):
    type: Literal["utterance_final"] = "utterance_final"
    text: str = Field(min_length=1, max_length=4_000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    language: str | None = Field(default=None, max_length=20)
    duration_ms: int | None = Field(default=None, ge=0, le=120_000)


class BargeInEvent(ProtocolEnvelope):
    type: Literal["barge_in"] = "barge_in"
    reason: str | None = Field(default=None, max_length=160)


class TargetSeenEvent(ProtocolEnvelope):
    target_id: str | None = Field(default=None, max_length=120)
    confidence: float = Field(ge=0, le=1)
    center: NormalizedPoint
    bbox: NormalizedBox | None = None


class FaceSeenEvent(TargetSeenEvent):
    type: Literal["face_seen"] = "face_seen"


class HandSeenEvent(TargetSeenEvent):
    type: Literal["hand_seen"] = "hand_seen"


class ObjectSeenEvent(TargetSeenEvent):
    type: Literal["object_seen"] = "object_seen"
    label: str = Field(min_length=1, max_length=120)


class GazeTargetEvent(ProtocolEnvelope):
    type: Literal["gaze_target"] = "gaze_target"
    target: str = Field(min_length=1, max_length=120)
    center: NormalizedPoint | None = None
    confidence: float = Field(default=1, ge=0, le=1)


class ShownImageEvent(ProtocolEnvelope):
    type: Literal["shown_image"] = "shown_image"
    artifact_url: str | None = Field(default=None, max_length=2_000)
    caption: str | None = Field(default=None, max_length=500)


class MusicBeatEvent(ProtocolEnvelope):
    type: Literal["music_beat"] = "music_beat"
    bpm: float = Field(gt=40, le=220)
    beat_index: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.5, ge=0, le=1)


class MotionStartedEvent(ProtocolEnvelope):
    type: Literal["motion_started"] = "motion_started"
    gesture: str = Field(min_length=1, max_length=120)
    intensity: float = Field(default=0.5, ge=0, le=1)


class MotionDoneEvent(ProtocolEnvelope):
    type: Literal["motion_done"] = "motion_done"
    gesture: str = Field(min_length=1, max_length=120)
    duration_ms: int = Field(ge=0, le=120_000)
    status: Literal["completed", "interrupted", "failed"] = "completed"


class MotionBlockedEvent(ProtocolEnvelope):
    type: Literal["motion_blocked"] = "motion_blocked"
    gesture: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=300)


class LatencySampleEvent(ProtocolEnvelope):
    type: Literal["latency_sample"] = "latency_sample"
    stage: Literal[
        "vad",
        "stt",
        "local_model",
        "mac_route",
        "cloud_model",
        "codex",
        "tts",
        "screen",
        "motion",
        "gemini_live",
        "resource",
    ]
    duration_ms: int = Field(ge=0, le=300_000)
    route: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=160)


JetsonEvent = Annotated[
    WakeStartedEvent
    | WakeTimeoutEvent
    | UtterancePartialEvent
    | UtteranceFinalEvent
    | BargeInEvent
    | FaceSeenEvent
    | HandSeenEvent
    | ObjectSeenEvent
    | GazeTargetEvent
    | ShownImageEvent
    | MusicBeatEvent
    | MotionStartedEvent
    | MotionDoneEvent
    | MotionBlockedEvent
    | LatencySampleEvent,
    Field(discriminator="type"),
]


class ActionEnvelope(StrictMessage):
    schema_version: Literal["1"] = PROTOCOL_VERSION
    message_id: str = Field(default_factory=_message_id, min_length=6, max_length=80)
    timestamp_ms: int = Field(default_factory=_timestamp_ms, ge=0)
    source: str = Field(default="mac", min_length=1, max_length=80)
    session_id: str | None = Field(default=None, max_length=120)
    profile: str | None = Field(default=None, max_length=80)
    priority: Literal["low", "normal", "high"] = "normal"


class SayAction(ActionEnvelope):
    type: Literal["say"] = "say"
    text: str = Field(min_length=1, max_length=4_000)
    voice: str | None = Field(default=None, max_length=80)
    interruptible: bool = True


class PlayAudioAction(ActionEnvelope):
    type: Literal["play_audio"] = "play_audio"
    source_url: str = Field(min_length=1, max_length=2_000)
    volume: float = Field(default=0.8, ge=0, le=1)


class GestureAction(ActionEnvelope):
    type: Literal["gesture"] = "gesture"
    gesture: str = Field(min_length=1, max_length=120)
    intensity: float = Field(default=0.5, ge=0, le=1)
    duration_ms: int = Field(default=900, ge=100, le=10_000)
    reason: str | None = Field(default=None, max_length=300)


class SetEmotionAction(ActionEnvelope):
    type: Literal["set_emotion"] = "set_emotion"
    mood: str = Field(min_length=1, max_length=80)
    energy: float = Field(default=0.5, ge=0, le=1)
    attention: float = Field(default=0.6, ge=0, le=1)
    confidence: float = Field(default=0.7, ge=0, le=1)
    curiosity: float = Field(default=0.6, ge=0, le=1)


class LookAtAction(ActionEnvelope):
    type: Literal["look_at"] = "look_at"
    target: str = Field(default="target", min_length=1, max_length=120)
    center: NormalizedPoint | None = None
    duration_ms: int = Field(default=600, ge=100, le=5_000)


class ScreenPayload(StrictMessage):
    kind: Literal["none", "url", "image_prompt", "artifact", "text"] = "none"
    title: str | None = Field(default=None, max_length=160)
    url: str | None = Field(default=None, max_length=2_000)
    prompt: str | None = Field(default=None, max_length=1_500)
    text: str | None = Field(default=None, max_length=1_500)


class StoryBeatAction(ActionEnvelope):
    type: Literal["story_beat"] = "story_beat"
    line: str = Field(min_length=1, max_length=2_000)
    voice: str = Field(default="narrator", max_length=80)
    emotion: str = Field(default="wonder", max_length=80)
    gesture: str = Field(default="story_beat", max_length=120)
    screen: ScreenPayload = Field(default_factory=ScreenPayload)
    pause_ms: int = Field(default=500, ge=0, le=10_000)


class ScreenShowAction(ActionEnvelope):
    type: Literal["screen_show"] = "screen_show"
    screen: ScreenPayload


class ImageReadyAction(ActionEnvelope):
    type: Literal["image_ready"] = "image_ready"
    artifact_url: str = Field(min_length=1, max_length=2_000)
    caption: str | None = Field(default=None, max_length=500)


class StartLiveModeAction(ActionEnvelope):
    type: Literal["start_live_mode"] = "start_live_mode"
    mode: Literal["audio", "audio_video"] = "audio_video"
    requested_seconds: int = Field(default=120, ge=5, le=300)
    visible_indicator_required: bool = True


class StopLiveModeAction(ActionEnvelope):
    type: Literal["stop_live_mode"] = "stop_live_mode"
    reason: str | None = Field(default=None, max_length=300)


MacAction = Annotated[
    SayAction
    | PlayAudioAction
    | GestureAction
    | SetEmotionAction
    | LookAtAction
    | StoryBeatAction
    | ScreenShowAction
    | ImageReadyAction
    | StartLiveModeAction
    | StopLiveModeAction,
    Field(discriminator="type"),
]


JETSON_EVENT_ADAPTER = TypeAdapter(JetsonEvent)
MAC_ACTION_ADAPTER = TypeAdapter(MacAction)

EVENT_TYPES = [
    "wake_started",
    "wake_timeout",
    "utterance_partial",
    "utterance_final",
    "barge_in",
    "face_seen",
    "hand_seen",
    "object_seen",
    "gaze_target",
    "shown_image",
    "music_beat",
    "motion_started",
    "motion_done",
    "motion_blocked",
    "latency_sample",
]

ACTION_TYPES = [
    "say",
    "play_audio",
    "gesture",
    "set_emotion",
    "look_at",
    "story_beat",
    "screen_show",
    "image_ready",
    "start_live_mode",
    "stop_live_mode",
]


def validate_jetson_event(payload: dict[str, Any]) -> JetsonEvent:
    return JETSON_EVENT_ADAPTER.validate_python(payload)


def validate_mac_action(payload: dict[str, Any]) -> MacAction:
    return MAC_ACTION_ADAPTER.validate_python(payload)


def protocol_inventory() -> dict[str, Any]:
    return {
        "schema_version": PROTOCOL_VERSION,
        "event_types": EVENT_TYPES,
        "action_types": ACTION_TYPES,
        "required_policy": [
            "extra fields are rejected",
            "unknown message types are rejected",
            "motion is named-gesture-only",
            "physical adapters must clamp range, speed, and repeat rate",
        ],
    }
