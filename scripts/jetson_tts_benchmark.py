#!/usr/bin/env python3
from __future__ import annotations
import json
import time
import shlex
import argparse
import subprocess
from urllib import request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "docs" / "health-reports"

import sys


sys.path.insert(0, str(ROOT))

from reachy_runtime.tts_benchmark import make_markdown_report


REMOTE_BENCHMARK = r"""
from __future__ import annotations

import argparse
import json
import time

from app.tts import create_tts


PHRASES = [
    {"id": "english_adult", "language": "en", "text": "Hello Reachy, this is a quick voice test."},
    {"id": "spanish_adult", "language": "es", "text": "Hola Reachy, esta es una prueba rapida."},
    {"id": "spanish_tutor", "language": "es", "text": "Repite conmigo: buenos dias, como estas."},
    {"id": "code_switch", "language": "mixed", "text": "Reachy, help me practice diciendo buenos dias."},
]

ENGINES = [
    {"engine": "kokoro_current", "voice": "af_sarah", "lang": "en-us", "phrase_languages": ["en", "mixed"], "streaming": False},
    {"engine": "kokoro_spanish_dora", "voice": "ef_dora", "lang": "es", "phrase_languages": ["es", "mixed"], "streaming": False},
    {"engine": "kokoro_spanish_alex", "voice": "em_alex", "lang": "es", "phrase_languages": ["es", "mixed"], "streaming": False},
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=3)
    args = parser.parse_args()

    records = []
    engines = []
    for engine in ENGINES:
        started = time.perf_counter()
        tts = create_tts(voice=engine["voice"], speed=1.0, lang=engine["lang"])
        loaded = tts.load()
        cold_load_ms = (time.perf_counter() - started) * 1000
        engine_info = dict(engine)
        engine_info["loaded"] = loaded
        engine_info["provider"] = getattr(tts, "provider", "unknown")
        engine_info["cold_load_ms"] = cold_load_ms
        engines.append(engine_info)
        if not loaded:
            records.append({
                **engine,
                "phrase_id": "load",
                "ok": False,
                "cold_load_ms": cold_load_ms,
                "error": "load_failed",
            })
            continue

        for phrase in PHRASES:
            if phrase["language"] not in engine["phrase_languages"]:
                continue
            for iteration in range(args.iterations):
                started = time.perf_counter()
                result = tts.synthesize(phrase["text"])
                synth_ms = (time.perf_counter() - started) * 1000
                audio = result.get("audio")
                sample_rate = result.get("sample_rate")
                ok = audio is not None
                records.append({
                    **engine,
                    "phrase_id": phrase["id"],
                    "phrase_language": phrase["language"],
                    "iteration": iteration + 1,
                    "ok": ok,
                    "cold_load_ms": cold_load_ms,
                    "synth_ms": synth_ms if ok else None,
                    "first_audio_ms": synth_ms if ok and not engine["streaming"] else None,
                    "audio_ms": (len(audio) / sample_rate * 1000) if ok and sample_rate else None,
                    "sample_rate": sample_rate,
                    "error": result.get("error"),
                })
        tts.unload()

    print(json.dumps({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "engines": engines,
        "phrases": PHRASES,
        "records": records,
        "notes": [
            "Kokoro current backend is non-streaming; first_audio_ms equals synth_ms.",
            "Use Piper or Riva later for true chunked first-audio latency.",
        ],
    }, ensure_ascii=False))
    return 0


raise SystemExit(main())
"""


def elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def run(cmd: list[str], timeout: float = 30) -> dict:
    started = time.monotonic()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "timeout": True,
            "duration_ms": elapsed_ms(started),
            "cmd": cmd,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "duration_ms": elapsed_ms(started),
        "cmd": cmd,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def ssh_cmd(args: argparse.Namespace, remote_cmd: str, timeout: float = 30) -> dict:
    return run(
        [
            "ssh",
            "-i",
            args.jetson_key,
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={args.connect_timeout}",
            f"{args.jetson_user}@{args.jetson_host}",
            remote_cmd,
        ],
        timeout=timeout,
    )


def parse_json_blob(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def post_event(args: argparse.Namespace, body: dict) -> None:
    encoded = json.dumps(body).encode("utf-8")
    req = request.Request(
        f"{args.bridge_url.rstrip('/')}/jetson/events",
        data=encoded,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        request.urlopen(req, timeout=args.http_timeout).read()
    except Exception:
        pass


def mirror_latency(args: argparse.Namespace, results: dict) -> None:
    for record in results.get("records", []):
        if not record.get("ok"):
            continue
        model = f"{record.get('voice')}:{record.get('lang')}"
        if record.get("first_audio_ms") is not None:
            post_event(
                args,
                {
                    "schema_version": "1",
                    "type": "latency_sample",
                    "stage": "tts",
                    "duration_ms": int(record["first_audio_ms"]),
                    "route": f"jetson:{record.get('engine')}:first_audio",
                    "model": model,
                },
            )
        if record.get("synth_ms") is not None:
            post_event(
                args,
                {
                    "schema_version": "1",
                    "type": "latency_sample",
                    "stage": "tts",
                    "duration_ms": int(record["synth_ms"]),
                    "route": f"jetson:{record.get('engine')}:full_synth",
                    "model": model,
                },
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark current Jetson TTS engines across English and Spanish phrases."
    )
    parser.add_argument("--bridge-url", default="http://127.0.0.1:8787")
    parser.add_argument("--jetson-host", default="192.168.55.1")
    parser.add_argument("--jetson-user", default="brianmeyer")
    parser.add_argument("--jetson-key", default=str(Path.home() / ".ssh" / "reachy_jetson_ed25519"))
    parser.add_argument("--jetson-project", default="/home/brianmeyer/reachy-mini-jetson-assistant")
    parser.add_argument("--connect-timeout", type=int, default=5)
    parser.add_argument("--http-timeout", type=float, default=10)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--probe-timeout", type=int, default=180)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of the report path.")
    args = parser.parse_args()

    remote = (
        f"cd {shlex.quote(args.jetson_project)} && "
        "source venv/bin/activate && "
        f"python -c {shlex.quote(REMOTE_BENCHMARK)} --iterations {args.iterations}"
    )
    run_result = ssh_cmd(args, remote, timeout=args.probe_timeout + args.connect_timeout)
    parsed = parse_json_blob(run_result.get("stdout", ""))
    results = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "ssh": run_result,
        "parsed": parsed,
    }
    if parsed is not None:
        mirror_latency(args, parsed)
        report_body = make_markdown_report(parsed)
    else:
        report_body = make_markdown_report({"generated_at": results["generated_at"], "records": []})
        report_body += (
            "\n\n## SSH Result\n\n```json\n" + json.dumps(results, indent=2, default=str)[:60_000] + "\n```\n"
        )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-jetson-tts-benchmark.md"
    report_path.write_text(report_body, encoding="utf-8")

    if args.json:
        print(json.dumps({"report": str(report_path), "results": results}, indent=2, ensure_ascii=False, default=str))
    else:
        print(report_path)
    return 0 if run_result.get("ok") and parsed is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
