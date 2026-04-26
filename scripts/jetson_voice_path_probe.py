#!/usr/bin/env python3
from __future__ import annotations
import json
import time
import argparse
import subprocess
from urllib import request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "docs" / "health-reports"


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


def log_latency(
    args: argparse.Namespace, stage: str, seconds: float | None, route: str, model: str | None = None
) -> None:
    if seconds is None:
        return
    body = {
        "schema_version": "1",
        "type": "latency_sample",
        "stage": stage,
        "duration_ms": int(seconds * 1000),
        "route": route,
    }
    if model:
        body["model"] = model
    post_event(args, body)


def make_report(results: dict) -> str:
    voice = results.get("voice", {}).get("parsed") or {}
    policy = voice.get("resource_policy", {}).get("voice_realtime", {}).get("decision", {})
    stt = voice.get("stt", {})
    tts = voice.get("synthetic_wav", {})
    llm = voice.get("llm", {})
    lines = [
        "# Reachy Jetson Voice Path Probe",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
        "",
        "## Summary",
        "",
        f"- Jetson SSH: {'OK' if results.get('identity', {}).get('ok') else 'CHECK'}",
        f"- Voice probe command: {'OK' if results.get('voice', {}).get('ok') else 'CHECK'}",
    ]
    if policy:
        warnings = policy.get("warnings") or []
        lines.append(
            f"- Resource policy: {policy.get('severity', 'unknown')} "
            f"(GPU STT={'yes' if policy.get('allow_gpu_stt') else 'no'}, "
            f"local Gemma={'yes' if policy.get('allow_local_gemma') else 'no'}, "
            f"warnings={len(warnings)})"
        )
    if tts:
        lines.append(f"- TTS: load={tts.get('tts_load_s')}s, synth={tts.get('tts_synth_s')}s, wav={tts.get('wav_s')}s")
    if stt:
        if stt.get("skipped"):
            lines.append(f"- STT: skipped ({stt.get('reason', 'no_reason')})")
        else:
            result = stt.get("result") or {}
            lines.append(
                f"- STT: load={stt.get('load_s')}s, transcribe={stt.get('transcribe_s')}s, text={result.get('text')!r}"
            )
    if llm:
        lines.append(f"- LLM: ttft={llm.get('ttft_s')}s, total={llm.get('total_s')}s, text={llm.get('text')!r}")
    lines.extend(["", "## Raw JSON", "", "```json", json.dumps(results, indent=2)[:40_000], "```", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Jetson voice latency probe and mirror key timings.")
    parser.add_argument("--bridge-url", default="http://127.0.0.1:8787")
    parser.add_argument("--jetson-host", default="192.168.55.1")
    parser.add_argument("--jetson-user", default="brianmeyer")
    parser.add_argument("--jetson-key", default=str(Path.home() / ".ssh" / "reachy_jetson_ed25519"))
    parser.add_argument("--jetson-project", default="/home/brianmeyer/reachy-mini-jetson-assistant")
    parser.add_argument("--connect-timeout", type=int, default=5)
    parser.add_argument("--http-timeout", type=float, default=10)
    parser.add_argument("--probe-timeout", type=int, default=120)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of the report path.")
    args = parser.parse_args()

    results: dict = {}
    results["identity"] = ssh_cmd(args, "hostname; date -Is; free -h", timeout=10)
    remote = (
        f"cd {args.jetson_project} && "
        "source venv/bin/activate && "
        f"timeout {args.probe_timeout} python scripts/voice_latency_probe.py --skip-bridge --json"
    )
    voice = ssh_cmd(args, remote, timeout=args.probe_timeout + args.connect_timeout)
    parsed = parse_json_blob(voice.get("stdout", ""))
    if parsed is not None:
        voice["parsed"] = parsed
        config = parsed.get("config", {})
        stt = parsed.get("stt", {})
        tts = parsed.get("synthetic_wav", {})
        llm = parsed.get("llm", {})
        log_latency(args, "tts", tts.get("tts_load_s"), "jetson:voice_probe:tts_load")
        log_latency(args, "tts", tts.get("tts_synth_s"), "jetson:voice_probe:tts_synth")
        log_latency(args, "stt", stt.get("load_s"), "jetson:voice_probe:stt_load", config.get("stt_model"))
        log_latency(args, "stt", stt.get("transcribe_s"), "jetson:voice_probe:stt_transcribe", config.get("stt_model"))
        log_latency(args, "local_model", llm.get("ttft_s"), "jetson:voice_probe:llm_ttft", llm.get("model"))
        log_latency(args, "local_model", llm.get("total_s"), "jetson:voice_probe:llm_total", llm.get("model"))
    results["voice"] = voice

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-jetson-voice-path-probe.md"
    report_path.write_text(make_report(results), encoding="utf-8")

    if args.json:
        print(json.dumps({"report": str(report_path), "results": results}, indent=2))
    else:
        print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
