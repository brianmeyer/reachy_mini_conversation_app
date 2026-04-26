from __future__ import annotations

from reachy_runtime.stt_benchmark import (
    DEFAULT_STT_CONFIGS,
    DEFAULT_STT_PHRASES,
    summarize_records,
    make_markdown_report,
)


def test_stt_defaults_include_multilingual_models_only() -> None:
    models = {config["model"] for config in DEFAULT_STT_CONFIGS}
    phrase_languages = {phrase["expected_language"] for phrase in DEFAULT_STT_PHRASES}

    assert models == {"tiny", "base"}
    assert "tiny.en" not in models
    assert "base.en" not in models
    assert {"en", "es", "mixed"} <= phrase_languages


def test_stt_summary_groups_latency_and_text() -> None:
    summary = summarize_records(
        [
            {
                "model": "tiny",
                "device": "cpu",
                "compute_type": "float32",
                "phrase_id": "spanish_adult",
                "ok": True,
                "load_ms": 500,
                "transcribe_ms": 300,
                "detected_language": "es",
                "text": "Hola Reachy.",
            },
            {
                "model": "tiny",
                "device": "cpu",
                "compute_type": "float32",
                "phrase_id": "spanish_adult",
                "ok": True,
                "load_ms": 500,
                "transcribe_ms": 500,
                "detected_language": "es",
                "text": "Hola Reachy.",
            },
        ]
    )

    assert summary[0]["success"] == 2
    assert summary[0]["transcribe_p50_ms"] == 400
    assert summary[0]["languages"] == ["es"]


def test_stt_report_marks_policy_skips() -> None:
    report = make_markdown_report(
        {
            "generated_at": "2026-04-25 16:45:00 -0400",
            "resource_policy": {"decision": {"severity": "constrained", "allow_gpu_stt": False}},
            "records": [
                {
                    "model": "tiny",
                    "device": "cuda",
                    "compute_type": "int8",
                    "phrase_id": "english_adult",
                    "ok": False,
                    "skipped": True,
                    "error": "resource_policy_blocked_gpu_stt",
                }
            ],
        }
    )

    assert "Resource policy: constrained" in report
    assert "tiny cuda/int8 english_adult: skipped" in report
    assert "English-only `.en` Whisper models are intentionally excluded" in report


def test_stt_report_formats_missing_latency_cleanly() -> None:
    report = make_markdown_report(
        {
            "generated_at": "2026-04-25 16:45:00 -0400",
            "records": [
                {
                    "model": "tiny",
                    "device": "cpu",
                    "compute_type": "float32",
                    "phrase_id": "spanish_adult",
                    "ok": False,
                    "load_ms": 8000,
                    "error": "No SGEMM backend on CPU",
                }
            ],
        }
    )

    assert "transcribe p50/p95=unavailable/unavailable" in report
    assert "Nonems" not in report
