from __future__ import annotations
from typing import Any

from pydantic import Field, BaseModel, ConfigDict

from reachy_runtime.protocol import (
    MacAction,
    JetsonEvent,
    BargeInEvent,
    LookAtAction,
    FaceSeenEvent,
    GestureAction,
    HandSeenEvent,
    MusicBeatEvent,
    GazeTargetEvent,
    ObjectSeenEvent,
    StoryBeatAction,
    SetEmotionAction,
    WakeStartedEvent,
    LatencySampleEvent,
    UtteranceFinalEvent,
)
from reachy_runtime.behavior.fake_reachy import MotionResult, FakeReachyAdapter


class BehaviorState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mood: str = "curious"
    energy: float = Field(default=0.55, ge=0, le=1)
    attention: float = Field(default=0.65, ge=0, le=1)
    confidence: float = Field(default=0.75, ge=0, le=1)
    curiosity: float = Field(default=0.65, ge=0, le=1)
    profile_mode: str = "friendly_limited"
    attention_target: str | None = None


class GestureDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    default_intensity: float = Field(ge=0, le=1)
    default_duration_ms: int = Field(ge=100, le=10_000)
    tags: list[str] = Field(default_factory=list)


class GestureCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gesture: str
    intensity: float = Field(ge=0, le=1)
    duration_ms: int = Field(ge=100, le=10_000)
    reason: str
    target: dict[str, Any] | None = None


GESTURE_LIBRARY: dict[str, GestureDefinition] = {
    "listening_idle": GestureDefinition(
        name="listening_idle", default_intensity=0.25, default_duration_ms=1_200, tags=["idle", "listening"]
    ),
    "curious_tilt": GestureDefinition(
        name="curious_tilt", default_intensity=0.4, default_duration_ms=900, tags=["emotion", "attention"]
    ),
    "happy_bounce": GestureDefinition(
        name="happy_bounce", default_intensity=0.55, default_duration_ms=1_000, tags=["emotion", "celebration"]
    ),
    "thinking_glance": GestureDefinition(
        name="thinking_glance", default_intensity=0.35, default_duration_ms=1_100, tags=["thinking"]
    ),
    "story_beat": GestureDefinition(
        name="story_beat", default_intensity=0.45, default_duration_ms=850, tags=["story", "speech"]
    ),
    "look_at_target": GestureDefinition(
        name="look_at_target", default_intensity=0.35, default_duration_ms=650, tags=["gaze", "tracking"]
    ),
    "confused_tilt": GestureDefinition(
        name="confused_tilt", default_intensity=0.35, default_duration_ms=1_000, tags=["emotion"]
    ),
    "sleepy_rest": GestureDefinition(
        name="sleepy_rest", default_intensity=0.2, default_duration_ms=1_500, tags=["rest"]
    ),
    "dance_pulse": GestureDefinition(
        name="dance_pulse", default_intensity=0.45, default_duration_ms=500, tags=["dance"]
    ),
    "soft_apology": GestureDefinition(
        name="soft_apology", default_intensity=0.25, default_duration_ms=1_200, tags=["emotion"]
    ),
}

RAW_MOTION_MARKERS = ("raw", "motor", "servo", "joint", "set_target", "goto_target", "position", "angle")


class BehaviorEngine:
    def __init__(self, adapter: FakeReachyAdapter | None = None, state: BehaviorState | None = None) -> None:
        self.adapter = adapter or FakeReachyAdapter()
        self.state = state or BehaviorState()

    def gesture_names(self) -> list[str]:
        return sorted(GESTURE_LIBRARY)

    def command_for_gesture(
        self,
        gesture: str,
        *,
        intensity: float | None = None,
        duration_ms: int | None = None,
        reason: str = "behavior_engine",
        target: dict[str, Any] | None = None,
    ) -> GestureCommand:
        if self._looks_like_raw_motion(gesture):
            raise ValueError("raw_motor_commands_are_not_allowed")
        definition = GESTURE_LIBRARY.get(gesture)
        if not definition:
            raise ValueError(f"unknown_gesture:{gesture}")
        return GestureCommand(
            gesture=definition.name,
            intensity=definition.default_intensity if intensity is None else intensity,
            duration_ms=definition.default_duration_ms if duration_ms is None else duration_ms,
            reason=reason,
            target=target,
        )

    def execute_gesture(
        self,
        gesture: str,
        *,
        intensity: float | None = None,
        duration_ms: int | None = None,
        reason: str = "behavior_engine",
        target: dict[str, Any] | None = None,
    ) -> MotionResult:
        command = self.command_for_gesture(
            gesture,
            intensity=intensity,
            duration_ms=duration_ms,
            reason=reason,
            target=target,
        )
        return self.adapter.apply_gesture(
            gesture=command.gesture,
            intensity=command.intensity,
            duration_ms=command.duration_ms,
            reason=command.reason,
            target=command.target,
        )

    def process_event(self, event: JetsonEvent) -> dict[str, Any]:
        motions: list[MotionResult] = []

        if isinstance(event, WakeStartedEvent):
            self.state.attention = max(self.state.attention, 0.75)
            motions.append(self.execute_gesture("listening_idle", reason="wake_started"))
        elif isinstance(event, BargeInEvent):
            self.state.attention = 0.95
            motions.append(self.execute_gesture("listening_idle", reason="barge_in"))
        elif isinstance(event, (FaceSeenEvent, HandSeenEvent, ObjectSeenEvent)):
            label = getattr(event, "label", None) or event.target_id or event.type.replace("_seen", "")
            self.state.attention_target = label
            self.state.attention = max(self.state.attention, event.confidence)
            motions.append(
                self.execute_gesture(
                    "look_at_target",
                    intensity=min(0.55, 0.2 + event.confidence * 0.4),
                    duration_ms=650,
                    reason=event.type,
                    target={"label": label, "center": event.center.model_dump(), "confidence": event.confidence},
                )
            )
        elif isinstance(event, GazeTargetEvent):
            self.state.attention_target = event.target
            motions.append(
                self.execute_gesture(
                    "look_at_target",
                    intensity=min(0.55, 0.25 + event.confidence * 0.35),
                    duration_ms=event.timestamp_ms % 350 + 500,
                    reason="gaze_target",
                    target={"label": event.target, "center": event.center.model_dump() if event.center else None},
                )
            )
        elif isinstance(event, MusicBeatEvent):
            self.state.energy = min(1.0, max(self.state.energy, event.confidence))
            motions.append(
                self.execute_gesture(
                    "dance_pulse", intensity=0.35 + event.confidence * 0.25, duration_ms=420, reason="music_beat"
                )
            )
        elif isinstance(event, UtteranceFinalEvent):
            lowered = event.text.lower()
            if any(word in lowered for word in ("story", "dragon", "castle", "minecraft", "adventure")):
                self.state.mood = "excited"
                motions.append(self.execute_gesture("happy_bounce", intensity=0.5, reason="story_request_detected"))
            elif any(word in lowered for word in ("look", "show", "drawing", "homework")):
                self.state.mood = "curious"
                motions.append(self.execute_gesture("curious_tilt", reason="look_request_detected"))
        elif isinstance(event, LatencySampleEvent):
            if event.duration_ms > 1_000 and event.stage in {"cloud_model", "gemini_live", "mac_route"}:
                self.state.confidence = max(0.35, self.state.confidence - 0.08)
                motions.append(self.execute_gesture("thinking_glance", reason=f"slow_{event.stage}"))

        return self._result("event", event.model_dump(), motions)

    def process_action(self, action: MacAction) -> dict[str, Any]:
        motions: list[MotionResult] = []
        speech: dict[str, Any] | None = None
        screen: dict[str, Any] | None = None

        if isinstance(action, GestureAction):
            motions.append(
                self.execute_gesture(
                    action.gesture,
                    intensity=action.intensity,
                    duration_ms=action.duration_ms,
                    reason=action.reason or "mac_gesture_action",
                )
            )
        elif isinstance(action, SetEmotionAction):
            self.state.mood = action.mood
            self.state.energy = action.energy
            self.state.attention = action.attention
            self.state.confidence = action.confidence
            self.state.curiosity = action.curiosity
            motions.append(self.execute_gesture(self._gesture_for_emotion(), reason="set_emotion"))
        elif isinstance(action, LookAtAction):
            self.state.attention_target = action.target
            motions.append(
                self.execute_gesture(
                    "look_at_target",
                    duration_ms=action.duration_ms,
                    reason="look_at_action",
                    target={"label": action.target, "center": action.center.model_dump() if action.center else None},
                )
            )
        elif isinstance(action, StoryBeatAction):
            self.state.mood = action.emotion
            speech = {"text": action.line, "voice": action.voice, "pause_ms": action.pause_ms}
            screen = action.screen.model_dump()
            motions.append(self.execute_gesture(action.gesture, reason=f"story_beat:{action.emotion}"))

        return self._result("action", action.model_dump(), motions, speech=speech, screen=screen)

    def _gesture_for_emotion(self) -> str:
        mood = self.state.mood.lower()
        if "happy" in mood or "excited" in mood or self.state.energy > 0.82:
            return "happy_bounce"
        if "confused" in mood or self.state.confidence < 0.35:
            return "confused_tilt"
        if "sleep" in mood or self.state.energy < 0.25:
            return "sleepy_rest"
        if "sorry" in mood or "sad" in mood:
            return "soft_apology"
        return "listening_idle"

    def _result(
        self,
        kind: str,
        message: dict[str, Any],
        motions: list[MotionResult],
        *,
        speech: dict[str, Any] | None = None,
        screen: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "kind": kind,
            "message": message,
            "state": self.state.model_dump(),
            "motions": [motion.model_dump() for motion in motions],
            "timeline": self.adapter.export_timeline(),
            "speech": speech,
            "screen": screen,
            "movement_allowed": self.adapter.safety.allow_motion,
        }

    @staticmethod
    def _looks_like_raw_motion(gesture: str) -> bool:
        lowered = gesture.lower()
        return any(marker in lowered for marker in RAW_MOTION_MARKERS)
