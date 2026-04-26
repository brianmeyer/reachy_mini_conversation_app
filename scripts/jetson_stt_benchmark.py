#!/usr/bin/env python3
from __future__ import annotations
import sys
import json
import time
import shlex
import argparse
import subprocess
from urllib import request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "docs" / "health-reports"
sys.path.insert(0, str(ROOT))

from reachy_runtime.stt_benchmark import make_markdown_report


REMOTE_BENCHMARK = r"""
from __future__ import annotations

import argparse
import json
import time
import wave
from pathlib import Path

import numpy as np

from app.mac_bridge import MacBridgeClient
from app.resource_policy import preflight
from app.tts import create_tts


PHRASES = [
    {"id": "english_adult", "expected_language": "en", "text": "Hello Reachy, this is a quick speech test.", "tts_voice": "af_sarah", "tts_lang": "en-us"},
    {"id": "spanish_adult", "expected_language": "es", "text": "Hola Reachy, esta es una prueba de voz.", "tts_voice": "ef_dora", "tts_lang": "es"},
    {"id": "code_switch", "expected_language": "mixed", "text": "Reachy, help me practice diciendo buenos dias.", "tts_voice": "ef_dora", "tts_lang": "es"},
]


def write_wav_16k(path, audio, sample_rate):
    audio = audio.astype(np.int16)
    x = np.arange(len(audio), dtype=np.float32)
    out_len = int(len(audio) * 16000 / sample_rate)
    xi = np.linspace(0, len(audio) - 1, out_len, dtype=np.float32)
    out = np.interp(xi, x, audio.astype(np.float32)).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(out.tobytes())
    return len(out) / 16000


def make_wavs():
    wavs = {}
    loaded = {}
    for phrase in PHRASES:
        key = (phrase["tts_voice"], phrase["tts_lang"])
        tts = loaded.get(key)
        if tts is None:
            tts = create_tts(voice=phrase["tts_voice"], speed=1.0, lang=phrase["tts_lang"])
            if not tts.load():
                wavs[phrase["id"]] = {"ok": False, "error": "tts_load_failed"}
                continue
            loaded[key] = tts
        result = tts.synthesize(phrase["text"])
        if result.get("audio") is None:
            wavs[phrase["id"]] = {"ok": False, "error": result.get("error", "tts_synth_failed")}
            continue
        path = Path("/tmp") / f"reachy_stt_bench_{phrase['id']}.wav"
        duration = write_wav_16k(path, result["audio"], int(result["sample_rate"]))
        wavs[phrase["id"]] = {"ok": True, "path": str(path), "duration_s": duration}
    for tts in loaded.values():
        tts.unload()
    return wavs


def ctranslate2_capabilities():
    try:
        import ctranslate2
    except Exception as exc:
        return {"error": repr(exc)}
    caps = {"cuda_devices": ctranslate2.get_cuda_device_count()}
    for device in ["cuda", "cpu"]:
        try:
            caps[device] = sorted(ctranslate2.get_supported_compute_types(device))
        except Exception as exc:
            caps[device] = {"error": repr(exc)}
    return caps


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--models", default="tiny,base")
    parser.add_argument("--force-heavy", action="store_true")
    args = parser.parse_args()

    bridge = MacBridgeClient()
    policy = preflight("voice_realtime", bridge)
    capabilities = ctranslate2_capabilities()
    wavs = make_wavs()
    records = []

    configs = []
    for model in [item.strip() for item in args.models.split(",") if item.strip()]:
        configs.append({"model": model, "device": "cpu", "compute_type": "float32", "beam_size": 1})
        configs.append({"model": model, "device": "cuda", "compute_type": "int8", "beam_size": 1})

    for config in configs:
        device = config["device"]
        compute_type = config["compute_type"]
        model_name = config["model"]
        for phrase in PHRASES:
            wav = wavs.get(phrase["id"], {})
            if not wav.get("ok"):
                records.append({**config, "phrase_id": phrase["id"], "ok": False, "error": wav.get("error", "wav_missing")})
                continue
            if device == "cuda" and not policy.allow_gpu_stt and not args.force_heavy:
                records.append({
                    **config,
                    "phrase_id": phrase["id"],
                    "expected_language": phrase["expected_language"],
                    "ok": False,
                    "skipped": True,
                    "error": "resource_policy_blocked_gpu_stt",
                })
                continue
            supported = capabilities.get(device)
            if isinstance(supported, list) and compute_type not in supported:
                records.append({
                    **config,
                    "phrase_id": phrase["id"],
                    "expected_language": phrase["expected_language"],
                    "ok": False,
                    "skipped": True,
                    "error": f"unsupported_compute_type:{device}:{compute_type}",
                })
                continue

        runnable = [
            phrase for phrase in PHRASES
            if wavs.get(phrase["id"], {}).get("ok")
            and not (device == "cuda" and not policy.allow_gpu_stt and not args.force_heavy)
            and not (isinstance(capabilities.get(device), list) and compute_type not in capabilities.get(device))
        ]
        if not runnable:
            continue
        try:
            from faster_whisper import WhisperModel
            started = time.perf_counter()
            model = WhisperModel(model_name, device=device, compute_type=compute_type)
            load_ms = (time.perf_counter() - started) * 1000
        except Exception as exc:
            for phrase in runnable:
                records.append({**config, "phrase_id": phrase["id"], "ok": False, "load_ms": None, "error": repr(exc)})
            continue

        for phrase in runnable:
            wav = wavs[phrase["id"]]
            for iteration in range(args.iterations):
                try:
                    started = time.perf_counter()
                    segments, info = model.transcribe(
                        wav["path"],
                        beam_size=config["beam_size"],
                        language=None,
                        vad_filter=True,
                        condition_on_previous_text=False,
                    )
                    text = " ".join(segment.text.strip() for segment in segments).strip()
                    transcribe_ms = (time.perf_counter() - started) * 1000
                    records.append({
                        **config,
                        "phrase_id": phrase["id"],
                        "expected_language": phrase["expected_language"],
                        "iteration": iteration + 1,
                        "ok": True,
                        "load_ms": load_ms,
                        "transcribe_ms": transcribe_ms,
                        "detected_language": info.language,
                        "language_probability": getattr(info, "language_probability", None),
                        "text": text,
                        "audio_duration_s": wav["duration_s"],
                    })
                except Exception as exc:
                    records.append({**config, "phrase_id": phrase["id"], "ok": False, "load_ms": load_ms, "error": repr(exc)})
        del model

    print(json.dumps({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "resource_policy": {
            "source": policy.source,
            "snapshot": policy.snapshot,
            "decision": policy.decision,
        },
        "capabilities": capabilities,
        "phrases": PHRASES,
        "wavs": wavs,
        "records": records,
    }, ensure_ascii=False, default=str))
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
        if not record.get("ok") or record.get("transcribe_ms") is None:
            continue
        post_event(
            args,
            {
                "schema_version": "1",
                "type": "latency_sample",
                "stage": "stt",
                "duration_ms": int(record["transcribe_ms"]),
                "route": f"jetson:faster_whisper:{record.get('device')}:{record.get('compute_type')}",
                "model": str(record.get("model")),
            },
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark multilingual faster-whisper STT candidates on the Jetson.")
    parser.add_argument("--bridge-url", default="http://127.0.0.1:8787")
    parser.add_argument("--jetson-host", default="192.168.55.1")
    parser.add_argument("--jetson-user", default="brianmeyer")
    parser.add_argument("--jetson-key", default=str(Path.home() / ".ssh" / "reachy_jetson_ed25519"))
    parser.add_argument("--jetson-project", default="/home/brianmeyer/reachy-mini-jetson-assistant")
    parser.add_argument("--connect-timeout", type=int, default=5)
    parser.add_argument("--http-timeout", type=float, default=10)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--models", default="tiny,base")
    parser.add_argument("--probe-timeout", type=int, default=600)
    parser.add_argument("--force-heavy", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of the report path.")
    args = parser.parse_args()

    remote = (
        f"cd {shlex.quote(args.jetson_project)} && "
        "source venv/bin/activate && "
        f"python -c {shlex.quote(REMOTE_BENCHMARK)} "
        f"--iterations {args.iterations} --models {shlex.quote(args.models)}"
    )
    if args.force_heavy:
        remote += " --force-heavy"
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
    report_path = REPORT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-jetson-stt-benchmark.md"
    report_path.write_text(report_body, encoding="utf-8")

    if args.json:
        print(json.dumps({"report": str(report_path), "results": results}, indent=2, ensure_ascii=False, default=str))
    else:
        print(report_path)
    return 0 if run_result.get("ok") and parsed is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
