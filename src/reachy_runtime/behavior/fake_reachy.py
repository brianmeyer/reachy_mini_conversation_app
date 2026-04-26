from __future__ import annotations
import time
import uuid
from typing import Any

from pydantic import Field, BaseModel, ConfigDict


class SafetyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_intensity: float = Field(default=0.75, ge=0, le=1)
    min_duration_ms: int = Field(default=150, ge=0, le=5_000)
    max_duration_ms: int = Field(default=2_500, ge=100, le=30_000)
    min_interval_ms: int = Field(default=250, ge=0, le=10_000)
    allow_motion: bool = False


class MotionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    gesture: str
    requested_intensity: float
    requested_duration_ms: int
    applied_intensity: float
    applied_duration_ms: int
    status: str
    reason: str
    target: dict[str, Any] | None = None
    timestamp_ms: int = Field(default_factory=lambda: int(time.time() * 1000))


class FakeReachyAdapter:
    """A no-hardware adapter that records exactly what would be sent to Reachy."""

    def __init__(self, safety: SafetyPolicy | None = None) -> None:
        self.safety = safety or SafetyPolicy()
        self.timeline: list[MotionResult] = []
        self._last_motion_ms = 0

    def apply_gesture(
        self,
        *,
        gesture: str,
        intensity: float,
        duration_ms: int,
        reason: str,
        target: dict[str, Any] | None = None,
    ) -> MotionResult:
        now = int(time.time() * 1000)
        applied_intensity = min(max(intensity, 0.0), self.safety.max_intensity)
        applied_duration = min(max(duration_ms, self.safety.min_duration_ms), self.safety.max_duration_ms)

        if self._last_motion_ms and now - self._last_motion_ms < self.safety.min_interval_ms:
            result = MotionResult(
                gesture=gesture,
                requested_intensity=intensity,
                requested_duration_ms=duration_ms,
                applied_intensity=0,
                applied_duration_ms=0,
                status="blocked",
                reason=f"rate_limited:{self.safety.min_interval_ms}ms",
                target=target,
            )
            self.timeline.append(result)
            return result

        self._last_motion_ms = now
        result = MotionResult(
            gesture=gesture,
            requested_intensity=intensity,
            requested_duration_ms=duration_ms,
            applied_intensity=applied_intensity,
            applied_duration_ms=applied_duration,
            status="dry_run" if not self.safety.allow_motion else "would_send",
            reason=reason,
            target=target,
        )
        self.timeline.append(result)
        return result

    def export_timeline(self) -> list[dict[str, Any]]:
        return [item.model_dump() for item in self.timeline]
