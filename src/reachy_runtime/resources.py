from __future__ import annotations
from typing import Literal

from pydantic import Field, BaseModel, ConfigDict


ResourceMode = Literal[
    "voice_realtime",
    "local_gemma_fallback",
    "jetson_codex_async",
    "gemini_live_visual",
    "dance_tracking",
    "maintenance",
]


class ResourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mem_available_mib: float = Field(ge=0)
    cma_free_mib: float | None = Field(default=None, ge=0)
    largest_free_block_mb: float | None = Field(default=None, ge=0)
    largest_free_block_count: int | None = Field(default=None, ge=0)
    gemma_running: bool = False
    gemma_memory_gib: float | None = Field(default=None, ge=0)
    gemma_swap_gib: float | None = Field(default=None, ge=0)
    codex_active: bool = False
    camera_active: bool = False
    stt_active: bool = False
    tts_active: bool = False


class ResourceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_mode: ResourceMode
    severity: Literal["ok", "watch", "constrained", "critical"]
    allow_local_gemma: bool
    allow_gpu_stt: bool
    allow_gemini_live: bool
    allow_codex_async: bool
    prefer_cached_ack: bool
    warnings: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)


LOW_MEM_MIB = 2_500
CRITICAL_MEM_MIB = 1_500
LOW_CMA_MIB = 16
FRAGMENTED_LFB_MB = 4


def decide_resource_policy(snapshot: ResourceSnapshot, requested_mode: ResourceMode) -> ResourceDecision:
    warnings: list[str] = []
    actions: list[str] = []

    severity = "ok"
    allow_local_gemma = True
    allow_gpu_stt = True
    allow_gemini_live = True
    allow_codex_async = True
    prefer_cached_ack = requested_mode in {"voice_realtime", "dance_tracking"}

    if snapshot.mem_available_mib < CRITICAL_MEM_MIB:
        severity = "critical"
        warnings.append(f"MemAvailable is critically low: {snapshot.mem_available_mib:.0f} MiB.")
        actions.append("stop_local_gemma_and_nonessential_desktop_services")
    elif snapshot.mem_available_mib < LOW_MEM_MIB:
        severity = _max_severity(severity, "constrained")
        warnings.append(f"MemAvailable is low for mixed voice/vision work: {snapshot.mem_available_mib:.0f} MiB.")
        actions.append("avoid_starting_new_heavy_local_services")

    if snapshot.cma_free_mib is not None and snapshot.cma_free_mib < LOW_CMA_MIB:
        severity = _max_severity(severity, "constrained")
        allow_gpu_stt = False
        warnings.append(f"CmaFree is low: {snapshot.cma_free_mib:.1f} MiB.")
        actions.append("avoid_new_cuda_allocations_until_gemma_or_desktop_load_is_reduced")

    if snapshot.largest_free_block_mb is not None and snapshot.largest_free_block_mb <= FRAGMENTED_LFB_MB:
        severity = _max_severity(severity, "watch")
        warnings.append(
            "largest_free_block_is_fragmented:"
            f"{snapshot.largest_free_block_count or 0}x{snapshot.largest_free_block_mb:.0f}MB"
        )

    if snapshot.gemma_running and requested_mode in {"voice_realtime", "gemini_live_visual", "dance_tracking"}:
        allow_local_gemma = False
        actions.append("pause_or_stop_gemma_before_gpu_stt_vision_or_tracking")

    if snapshot.gemma_running and snapshot.gemma_swap_gib is not None and snapshot.gemma_swap_gib > 0.25:
        severity = _max_severity(severity, "watch")
        warnings.append(f"Gemma container is using swap: {snapshot.gemma_swap_gib:.2f} GiB.")

    if requested_mode == "voice_realtime":
        actions.append("keep_first_audio_on_cached_ack_or_warm_local_path")
        if not allow_gpu_stt:
            actions.append("use_smaller_or_scheduled_stt_until_resource_mode_switch")
    elif requested_mode == "local_gemma_fallback":
        prefer_cached_ack = False
        allow_local_gemma = snapshot.gemma_running and snapshot.mem_available_mib >= CRITICAL_MEM_MIB
        if not allow_local_gemma:
            actions.append("start_gemma_only_after_resource_probe_passes")
    elif requested_mode == "jetson_codex_async":
        prefer_cached_ack = False
        actions.append("run_codex_async_with_low_reasoning_effort")
        actions.append("do_not_put_codex_on_first_audio_path")
    elif requested_mode == "gemini_live_visual":
        actions.append("cap_live_session_and_show_visible_indicator")
        if snapshot.gemma_running:
            actions.append("prefer_gemini_live_over_local_vlm_while_gemma_is_resident")
    elif requested_mode == "dance_tracking":
        actions.append("keep_beat_tracking_and_motion_local")
        if not allow_gpu_stt:
            actions.append("avoid_concurrent_gpu_stt_during_dance_mode")
    elif requested_mode == "maintenance":
        prefer_cached_ack = False
        actions.append("safe_to_run_inventory_and_cleanup_tasks")

    return ResourceDecision(
        requested_mode=requested_mode,
        severity=severity,
        allow_local_gemma=allow_local_gemma,
        allow_gpu_stt=allow_gpu_stt,
        allow_gemini_live=allow_gemini_live,
        allow_codex_async=allow_codex_async,
        prefer_cached_ack=prefer_cached_ack,
        warnings=_dedupe(warnings),
        actions=_dedupe(actions),
    )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _max_severity(current: str, candidate: str) -> str:
    rank = {"ok": 0, "watch": 1, "constrained": 2, "critical": 3}
    return candidate if rank[candidate] > rank[current] else current
