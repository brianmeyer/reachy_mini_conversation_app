from __future__ import annotations
from typing import Any
from collections import defaultdict


DEFAULT_PHRASES: list[dict[str, str]] = [
    {
        "id": "english_adult",
        "language": "en",
        "text": "Hello Reachy, this is a quick voice test.",
    },
    {
        "id": "spanish_adult",
        "language": "es",
        "text": "Hola Reachy, esta es una prueba rapida.",
    },
    {
        "id": "spanish_tutor",
        "language": "es",
        "text": "Repite conmigo: buenos dias, como estas.",
    },
    {
        "id": "code_switch",
        "language": "mixed",
        "text": "Reachy, help me practice diciendo buenos dias.",
    },
]


DEFAULT_KOKORO_ENGINES: list[dict[str, Any]] = [
    {
        "engine": "kokoro_current",
        "voice": "af_sarah",
        "lang": "en-us",
        "phrase_languages": ["en", "mixed"],
        "streaming": False,
    },
    {
        "engine": "kokoro_spanish_dora",
        "voice": "ef_dora",
        "lang": "es",
        "phrase_languages": ["es", "mixed"],
        "streaming": False,
    },
    {
        "engine": "kokoro_spanish_alex",
        "voice": "em_alex",
        "lang": "es",
        "phrase_languages": ["es", "mixed"],
        "streaming": False,
    },
]


def percentile(values: list[float], pct: float) -> float | None:
    clean = sorted(value for value in values if value is not None)
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    rank = (len(clean) - 1) * pct
    lower = int(rank)
    upper = min(lower + 1, len(clean) - 1)
    weight = rank - lower
    return clean[lower] * (1 - weight) + clean[upper] * weight


def summarize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = (
            str(record.get("engine", "")),
            str(record.get("voice", "")),
            str(record.get("lang", "")),
            str(record.get("phrase_id", "")),
        )
        groups[key].append(record)

    summaries: list[dict[str, Any]] = []
    for (engine, voice, lang, phrase_id), items in sorted(groups.items()):
        ok_items = [item for item in items if item.get("ok")]
        synth_ms = [float(item["synth_ms"]) for item in ok_items if item.get("synth_ms") is not None]
        first_audio_ms = [float(item["first_audio_ms"]) for item in ok_items if item.get("first_audio_ms") is not None]
        load_ms = [float(item["cold_load_ms"]) for item in items if item.get("cold_load_ms") is not None]
        summaries.append(
            {
                "engine": engine,
                "voice": voice,
                "lang": lang,
                "phrase_id": phrase_id,
                "count": len(items),
                "success": len(ok_items),
                "cold_load_ms": round(load_ms[0], 1) if load_ms else None,
                "synth_p50_ms": _round_or_none(percentile(synth_ms, 0.50)),
                "synth_p95_ms": _round_or_none(percentile(synth_ms, 0.95)),
                "first_audio_p50_ms": _round_or_none(percentile(first_audio_ms, 0.50)),
                "first_audio_p95_ms": _round_or_none(percentile(first_audio_ms, 0.95)),
                "errors": sorted({str(item.get("error")) for item in items if item.get("error")})[:3],
            }
        )
    return summaries


def make_markdown_report(results: dict[str, Any]) -> str:
    summaries = summarize_records(results.get("records", []))
    lines = [
        "# Reachy Jetson TTS Benchmark",
        "",
        f"Generated: {results.get('generated_at', 'unknown')}",
        "",
        "## Summary",
        "",
    ]
    if not summaries:
        lines.append("- No benchmark records were produced.")
    for item in summaries:
        status = f"{item['success']}/{item['count']} ok"
        lines.append(
            "- "
            f"{item['engine']} `{item['voice']}`/{item['lang']} "
            f"{item['phrase_id']}: {status}, "
            f"load={item['cold_load_ms']}ms, "
            f"first-audio p50/p95={item['first_audio_p50_ms']}/{item['first_audio_p95_ms']}ms, "
            f"synth p50/p95={item['synth_p50_ms']}/{item['synth_p95_ms']}ms"
        )
        if item["errors"]:
            lines.append(f"  Error sample: {item['errors'][0]}")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Non-streaming engines report first-audio as full synthesis because no earlier chunk is available.",
            "- Streaming engines report first-audio at the first emitted audio chunk; short phrases may still fit in one chunk.",
            "",
            "## Raw JSON",
            "",
            "```json",
            _json_dump(results),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _round_or_none(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


def _json_dump(value: Any) -> str:
    import json

    return json.dumps(value, indent=2, ensure_ascii=False, default=str)[:60_000]
