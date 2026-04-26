from __future__ import annotations

from reachy_runtime.resources import ResourceSnapshot, decide_resource_policy


def test_voice_realtime_pauses_gemma_when_cma_is_fragmented() -> None:
    snapshot = ResourceSnapshot(
        mem_available_mib=3_012,
        cma_free_mib=4.2,
        largest_free_block_count=39,
        largest_free_block_mb=4,
        gemma_running=True,
        gemma_memory_gib=2.68,
        gemma_swap_gib=0.82,
    )

    decision = decide_resource_policy(snapshot, "voice_realtime")

    assert decision.severity == "constrained"
    assert decision.allow_local_gemma is False
    assert decision.allow_gpu_stt is False
    assert decision.prefer_cached_ack is True
    assert "pause_or_stop_gemma_before_gpu_stt_vision_or_tracking" in decision.actions
    assert "use_smaller_or_scheduled_stt_until_resource_mode_switch" in decision.actions
    assert any("CmaFree" in warning for warning in decision.warnings)


def test_codex_async_is_allowed_but_never_first_audio() -> None:
    snapshot = ResourceSnapshot(
        mem_available_mib=3_012, cma_free_mib=4.2, largest_free_block_count=39, largest_free_block_mb=4
    )

    decision = decide_resource_policy(snapshot, "jetson_codex_async")

    assert decision.allow_codex_async is True
    assert decision.prefer_cached_ack is False
    assert "run_codex_async_with_low_reasoning_effort" in decision.actions
    assert "do_not_put_codex_on_first_audio_path" in decision.actions


def test_healthy_snapshot_allows_local_gemma_fallback() -> None:
    snapshot = ResourceSnapshot(
        mem_available_mib=4_500,
        cma_free_mib=128,
        largest_free_block_count=400,
        largest_free_block_mb=4,
        gemma_running=True,
        gemma_memory_gib=2.1,
        gemma_swap_gib=0,
    )

    decision = decide_resource_policy(snapshot, "local_gemma_fallback")

    assert decision.severity == "watch"
    assert decision.allow_local_gemma is True
    assert decision.allow_gpu_stt is True
