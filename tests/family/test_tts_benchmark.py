from __future__ import annotations

from reachy_runtime.tts_benchmark import (
    DEFAULT_PHRASES,
    DEFAULT_KOKORO_ENGINES,
    percentile,
    summarize_records,
    make_markdown_report,
)


def test_percentile_interpolates_values() -> None:
    assert percentile([10, 20, 30, 40], 0.50) == 25
    assert percentile([10, 20, 30, 40], 0.95) == 38.5
    assert percentile([], 0.50) is None


def test_default_matrix_includes_spanish_and_code_switch() -> None:
    phrase_languages = {phrase["language"] for phrase in DEFAULT_PHRASES}
    spanish_engines = [engine for engine in DEFAULT_KOKORO_ENGINES if engine["lang"] == "es"]

    assert {"en", "es", "mixed"} <= phrase_languages
    assert spanish_engines
    assert all("mixed" in engine["phrase_languages"] for engine in DEFAULT_KOKORO_ENGINES)


def test_summary_groups_non_streaming_tts_records() -> None:
    summary = summarize_records(
        [
            {
                "engine": "kokoro_spanish_dora",
                "voice": "ef_dora",
                "lang": "es",
                "phrase_id": "spanish_adult",
                "ok": True,
                "cold_load_ms": 2000,
                "synth_ms": 1000,
                "first_audio_ms": 1000,
            },
            {
                "engine": "kokoro_spanish_dora",
                "voice": "ef_dora",
                "lang": "es",
                "phrase_id": "spanish_adult",
                "ok": True,
                "cold_load_ms": 2000,
                "synth_ms": 1200,
                "first_audio_ms": 1200,
            },
        ]
    )

    assert summary[0]["success"] == 2
    assert summary[0]["synth_p50_ms"] == 1100
    assert summary[0]["first_audio_p50_ms"] == 1100


def test_report_calls_out_non_streaming_first_audio() -> None:
    report = make_markdown_report(
        {
            "generated_at": "2026-04-25 16:40:00 -0400",
            "records": [
                {
                    "engine": "kokoro_current",
                    "voice": "af_sarah",
                    "lang": "en-us",
                    "phrase_id": "english_adult",
                    "ok": True,
                    "cold_load_ms": 1900,
                    "synth_ms": 1500,
                    "first_audio_ms": 1500,
                }
            ],
        }
    )

    assert "kokoro_current" in report
    assert "first-audio p50/p95=1500.0/1500.0ms" in report
    assert "Non-streaming engines report first-audio as full synthesis" in report
