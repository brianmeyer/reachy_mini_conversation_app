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


def elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def http_json(method: str, url: str, body: dict | None = None, timeout: float = 15) -> tuple[dict, int]:
    started = time.monotonic()
    encoded = None if body is None else json.dumps(body).encode("utf-8")
    req = request.Request(
        url,
        data=encoded,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data, elapsed_ms(started)


def run(cmd: list[str], timeout: float = 30, stdin: str | None = None) -> dict:
    started = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "timeout": True,
            "cmd": cmd,
            "duration_ms": elapsed_ms(started),
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "cmd": cmd,
        "duration_ms": elapsed_ms(started),
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


def bridge_probe(args: argparse.Namespace, path: str, method: str = "GET", body: dict | None = None) -> dict:
    url = f"{args.bridge_url.rstrip('/')}{path}"
    try:
        data, duration = http_json(method, url, body, timeout=args.http_timeout)
    except Exception as exc:  # noqa: BLE001 - local benchmark should keep going.
        return {"ok": False, "path": path, "url": url, "error": str(exc)}
    return {"ok": True, "path": path, "url": url, "duration_ms": duration, "data": data}


def log_latency(args: argparse.Namespace, stage: str, duration_ms: int, route: str, model: str | None = None) -> None:
    body = {
        "schema_version": "1",
        "type": "latency_sample",
        "stage": stage,
        "duration_ms": duration_ms,
        "route": route,
    }
    if model:
        body["model"] = model
    try:
        http_json("POST", f"{args.bridge_url.rstrip('/')}/jetson/events", body, timeout=args.http_timeout)
    except Exception:
        pass


def codex_exec(args: argparse.Namespace, effort: str, *, on_jetson: bool) -> dict:
    prompt = f"Reply with exactly: reachy-{effort}"
    if on_jetson:
        quoted_prompt = shlex.quote(prompt)
        cmd = (
            f"/home/brianmeyer/.local/bin/codex exec "
            f"-m {shlex.quote(args.codex_model)} "
            f"-c model_reasoning_effort='\"{effort}\"' "
            f"--skip-git-repo-check --cd {shlex.quote(args.jetson_project)} "
            f"{quoted_prompt}"
        )
        result = ssh_cmd(args, cmd, timeout=args.codex_timeout + args.connect_timeout)
    else:
        result = run(
            [
                "codex",
                "exec",
                "-m",
                args.codex_model,
                "-c",
                f'model_reasoning_effort="{effort}"',
                "--skip-git-repo-check",
                "--cd",
                str(ROOT),
                prompt,
            ],
            timeout=args.codex_timeout,
        )
    result["effort"] = effort
    result["surface"] = "jetson" if on_jetson else "mac"
    result["matched_expected"] = f"reachy-{effort}" in result.get("stdout", "")
    return result


def make_report(results: dict) -> str:
    lines = [
        "# Reachy Current Hardware Benchmark",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
        "",
        "## Summary",
        "",
    ]
    bridge = results.get("bridge", {})
    health = bridge.get("/health", {})
    lines.append(f"- Mac bridge health: {'OK' if health.get('ok') and health.get('data', {}).get('ok') else 'CHECK'}")
    jetson = results.get("jetson", {})
    lines.append(f"- Jetson SSH: {'OK' if jetson.get('identity', {}).get('ok') else 'CHECK'}")
    memory = jetson.get("memory", {}).get("stdout", "").replace("\n", " / ")
    if memory:
        lines.append(f"- Jetson memory: `{memory[:240]}`")
    for item in results.get("codex", []):
        lines.append(
            f"- Codex {item['surface']} effort `{item['effort']}`: "
            f"{item['duration_ms']} ms, matched={item.get('matched_expected')}"
        )
    lines.extend(["", "## Raw JSON", "", "```json", json.dumps(results, indent=2)[:40_000], "```", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark current Reachy Mac/Jetson hardware paths.")
    parser.add_argument("--bridge-url", default="http://127.0.0.1:8787")
    parser.add_argument("--jetson-host", default="192.168.55.1")
    parser.add_argument("--jetson-user", default="brianmeyer")
    parser.add_argument("--jetson-key", default=str(Path.home() / ".ssh" / "reachy_jetson_ed25519"))
    parser.add_argument("--jetson-project", default="/home/brianmeyer/reachy-mini-jetson-assistant")
    parser.add_argument("--connect-timeout", type=int, default=5)
    parser.add_argument("--http-timeout", type=float, default=15)
    parser.add_argument("--codex-timeout", type=float, default=45)
    parser.add_argument("--codex-model", default="gpt-5.5")
    parser.add_argument("--include-codex", action="store_true", help="Spend small Codex calls on Mac and Jetson.")
    parser.add_argument("--codex-efforts", default="low,none", help="Comma-separated efforts to test.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of the report path.")
    args = parser.parse_args()

    results: dict = {"bridge": {}, "jetson": {}, "codex": []}

    for path in ("/health", "/models", "/protocol", "/analytics/latency", "/analytics/routing"):
        probe = bridge_probe(args, path)
        results["bridge"][path] = probe
        if probe.get("ok"):
            log_latency(args, "mac_route", int(probe["duration_ms"]), f"benchmark:{path}")

    results["jetson"]["identity"] = ssh_cmd(args, "hostname; date -Is; uname -m", timeout=10)
    results["jetson"]["memory"] = ssh_cmd(args, "free -h", timeout=10)
    results["jetson"]["services"] = ssh_cmd(
        args,
        "docker ps --format '{{.Names}} {{.Image}} {{.Status}}'; "
        "docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.CPUPerc}}' 2>/dev/null || true",
        timeout=15,
    )
    results["jetson"]["hardware"] = ssh_cmd(
        args,
        "lsusb; ls -l /dev/video* /dev/ttyACM* /dev/ttyUSB* /dev/serial/by-id/* 2>/dev/null || true; arecord -l 2>/dev/null || true",
        timeout=15,
    )
    for key, value in results["jetson"].items():
        if isinstance(value, dict) and value.get("duration_ms") is not None:
            log_latency(args, "resource", int(value["duration_ms"]), f"benchmark:jetson:{key}")

    if args.include_codex:
        efforts = [item.strip() for item in args.codex_efforts.split(",") if item.strip()]
        for effort in efforts:
            mac_result = codex_exec(args, effort, on_jetson=False)
            results["codex"].append(mac_result)
            log_latency(args, "codex", int(mac_result["duration_ms"]), "benchmark:mac-codex", args.codex_model)
            jetson_result = codex_exec(args, effort, on_jetson=True)
            results["codex"].append(jetson_result)
            log_latency(args, "codex", int(jetson_result["duration_ms"]), "benchmark:jetson-codex", args.codex_model)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    report_path = REPORT_DIR / f"{stamp}-current-hardware-benchmark.md"
    report_path.write_text(make_report(results), encoding="utf-8")

    if args.json:
        print(json.dumps({"report": str(report_path), "results": results}, indent=2))
    else:
        print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
