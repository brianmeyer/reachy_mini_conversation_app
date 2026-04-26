#!/usr/bin/env python3
from __future__ import annotations
import re
import sys
import json
import time
import argparse
import subprocess
from urllib import request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reachy_runtime.resources import ResourceSnapshot, decide_resource_policy


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


def http_json(method: str, url: str, body: dict, timeout: float = 10) -> None:
    encoded = json.dumps(body).encode("utf-8")
    req = request.Request(url, data=encoded, method=method, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=timeout) as response:
        response.read()


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


def post_resource_policy(args: argparse.Namespace, snapshot_output: str) -> dict:
    body = {
        "requested_mode": args.requested_mode,
        "snapshot": build_resource_snapshot(snapshot_output).model_dump(),
    }
    started = time.monotonic()
    try:
        http_json("POST", f"{args.bridge_url.rstrip('/')}/resource/policy", body, timeout=args.http_timeout)
    except Exception as exc:  # noqa: BLE001 - resource probe should still write a report.
        return {"ok": False, "duration_ms": elapsed_ms(started), "error": str(exc), "body": body}
    return {"ok": True, "duration_ms": elapsed_ms(started), "body": body}


def memory_snapshot_command(top_n: int) -> str:
    return f"""
set -u
echo SECTION identity
hostname
date -Is
uname -a
cat /etc/nv_tegra_release 2>/dev/null || true
dpkg-query -W nvidia-l4t-core 2>/dev/null || true
echo SECTION free
free -h
echo SECTION meminfo
egrep 'MemTotal|MemFree|MemAvailable|Buffers|Cached|SwapTotal|SwapFree|SwapCached|Slab|SReclaimable|SUnreclaim|Shmem|Unevictable|Mlocked|CommitLimit|Committed_AS|CmaTotal|CmaFree' /proc/meminfo
echo SECTION swaps
swapon --show --bytes
zramctl 2>/dev/null || true
echo SECTION buddyinfo
cat /proc/buddyinfo
echo SECTION top_rss
ps -eo pid,ppid,user,comm,rss,vsz,pmem,args --sort=-rss | head -{top_n}
echo SECTION known_process_status
for name in llama-server claude codex gnome-shell gnome-software Xorg; do
  pgrep -x "$name" || true
done | sort -n | uniq | while read -r pid; do
  [ -r /proc/$pid/status ] || continue
  echo ===PID $pid===
  tr '\\0' ' ' < /proc/$pid/cmdline
  echo
  egrep 'Name|State|PPid|VmRSS|VmSize|RssAnon|RssFile|RssShmem|VmSwap|Threads' /proc/$pid/status
  cat /proc/$pid/cgroup
done
echo SECTION docker
docker ps --format '{{{{.Names}}}} {{{{.Image}}}} {{{{.Status}}}}' 2>/dev/null || true
docker stats --no-stream --format '{{{{.Name}}}} {{{{.MemUsage}}}} {{{{.CPUPerc}}}}' 2>/dev/null || true
for id in $(docker ps -q 2>/dev/null || true); do
  docker inspect --format '{{{{.Name}}}} Memory={{{{.HostConfig.Memory}}}} MemorySwap={{{{.HostConfig.MemorySwap}}}} NanoCpus={{{{.HostConfig.NanoCpus}}}} PidsLimit={{{{.HostConfig.PidsLimit}}}} Id={{{{.Id}}}}' "$id" 2>/dev/null || true
  pid=$(docker inspect --format '{{{{.State.Pid}}}}' "$id" 2>/dev/null || echo 0)
  cgroup_path=""
  if [ "$pid" != "0" ] && [ -r "/proc/$pid/cgroup" ]; then
    cgroup_path=$(awk -F: 'NR == 1 {{print $3}}' "/proc/$pid/cgroup")
  fi
  scope="/sys/fs/cgroup${{cgroup_path}}"
  fallback="/sys/fs/cgroup/system.slice/docker-${{id}}.scope"
  if [ ! -r "$scope/memory.current" ] && [ -r "$fallback/memory.current" ]; then
    scope="$fallback"
  fi
  if [ -r "$scope/memory.current" ]; then
    echo "cgroup $id pid=$pid path=$scope memory.current=$(cat "$scope/memory.current") memory.swap.current=$(cat "$scope/memory.swap.current" 2>/dev/null || echo unknown)"
  fi
done
echo SECTION tegrastats
timeout 3 tegrastats --interval 1000 2>/dev/null || true
"""


def stop_claude_login_command() -> str:
    return r"""
set -u
echo BEFORE
pgrep -af 'claude|codex mcp-server' || true
for pid in $(pgrep -x claude || true); do
  cmd=$(tr '\0' ' ' < /proc/$pid/cmdline | sed 's/[[:space:]]$//')
  if [ "$cmd" = "claude login" ]; then
    echo "stopping $pid $cmd"
    kill "$pid" || true
  fi
done
sleep 2
echo AFTER
pgrep -af 'claude|codex mcp-server' || true
"""


def codex_memory_command(args: argparse.Namespace) -> str:
    prompt = "Reply with exactly: codex-memory-ok"
    return f"""
set -u
PROJECT={shell_quote(args.jetson_project)}
OUT=$(mktemp)
ERR=$(mktemp)
SAMPLES=$(mktemp)
echo BEFORE_FREE
free -h
(
  /home/brianmeyer/.local/bin/codex exec \
    --skip-git-repo-check \
    --cd "$PROJECT" \
    --model {shell_quote(args.codex_model)} \
    --config 'model_reasoning_effort="{args.codex_effort}"' \
    --sandbox read-only \
    {shell_quote(prompt)}
) >"$OUT" 2>"$ERR" &
PID=$!
PEAK=0
while kill -0 "$PID" 2>/dev/null; do
  RSS=$(ps -o rss= -p "$PID" | awk '{{print $1+0}}')
  CHILDREN=$(pgrep -P "$PID" | tr '\\n' ',' | sed 's/,$//')
  CHILD_RSS=0
  if [ -n "$CHILDREN" ]; then
    CHILD_RSS=$(ps -o rss= -p "$CHILDREN" | awk '{{s+=$1}} END {{print s+0}}')
  fi
  AVAIL=$(awk '/MemAvailable/ {{print $2}}' /proc/meminfo)
  TOTAL=$((RSS + CHILD_RSS))
  if [ "$TOTAL" -gt "$PEAK" ]; then PEAK=$TOTAL; fi
  printf '%s rss_kb=%s child_rss_kb=%s total_kb=%s mem_available_kb=%s\\n' "$(date +%s.%N)" "$RSS" "$CHILD_RSS" "$TOTAL" "$AVAIL" >> "$SAMPLES"
  sleep 0.25
done
wait "$PID"
RC=$?
echo CODEX_RC=$RC
echo CODEX_PEAK_KB=$PEAK
echo AFTER_FREE
free -h
echo OUTPUT
cat "$OUT"
echo STDERR_TAIL
tail -80 "$ERR"
echo SAMPLES_TAIL
tail -40 "$SAMPLES"
rm -f "$OUT" "$ERR" "$SAMPLES"
exit 0
"""


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def extract_codex_peak_kb(output: str) -> int | None:
    match = re.search(r"CODEX_PEAK_KB=(\d+)", output)
    return int(match.group(1)) if match else None


def extract_lfb(tegrastats_output: str) -> str | None:
    match = re.search(r"RAM\s+\d+/\d+MB\s+\(lfb\s+([^)]+)\)", tegrastats_output)
    return match.group(1) if match else None


def parse_meminfo(meminfo_output: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in meminfo_output.splitlines():
        match = re.match(r"^([A-Za-z_()]+):\s+(\d+)\s+kB", line)
        if match:
            values[match.group(1)] = int(match.group(2))
    return values


def mib(kb: int | None) -> str:
    if kb is None:
        return "unknown"
    return f"{kb / 1024:.1f} MiB"


def gib_from_bytes(value: int | None) -> str:
    if value is None:
        return "unknown"
    return f"{value / (1024**3):.2f} GiB"


def docker_cgroup_summary(docker_output: str) -> str | None:
    for line in docker_output.splitlines():
        if not line.startswith("cgroup "):
            continue
        memory = re.search(r"memory\.current=(\d+)", line)
        swap = re.search(r"memory\.swap\.current=(\d+)", line)
        memory_value = int(memory.group(1)) if memory else None
        swap_value = int(swap.group(1)) if swap else None
        return f"{line.split()[1]} current={gib_from_bytes(memory_value)}, swap={gib_from_bytes(swap_value)}"
    return None


def parse_docker_cgroup_values(docker_output: str) -> dict[str, float | None]:
    for line in docker_output.splitlines():
        if not line.startswith("cgroup "):
            continue
        memory = re.search(r"memory\.current=(\d+)", line)
        swap = re.search(r"memory\.swap\.current=(\d+)", line)
        return {
            "memory_gib": int(memory.group(1)) / (1024**3) if memory else None,
            "swap_gib": int(swap.group(1)) / (1024**3) if swap else None,
        }
    return {"memory_gib": None, "swap_gib": None}


def parse_lfb_parts(tegrastats_output: str) -> tuple[int | None, float | None]:
    lfb = extract_lfb(tegrastats_output)
    if not lfb:
        return None, None
    match = re.match(r"(\d+)x(\d+(?:\.\d+)?)([KMG]B)", lfb)
    if not match:
        return None, None
    count = int(match.group(1))
    size = float(match.group(2))
    unit = match.group(3)
    if unit == "KB":
        size /= 1024
    elif unit == "GB":
        size *= 1024
    return count, size


def build_resource_snapshot(snapshot_output: str) -> ResourceSnapshot:
    meminfo = parse_meminfo(section(snapshot_output, "meminfo"))
    docker = section(snapshot_output, "docker")
    top_rss = section(snapshot_output, "top_rss")
    known = section(snapshot_output, "known_process_status")
    lfb_count, lfb_mb = parse_lfb_parts(section(snapshot_output, "tegrastats"))
    cgroup = parse_docker_cgroup_values(docker)
    return ResourceSnapshot(
        mem_available_mib=meminfo.get("MemAvailable", 0) / 1024,
        cma_free_mib=meminfo.get("CmaFree", 0) / 1024 if "CmaFree" in meminfo else None,
        largest_free_block_mb=lfb_mb,
        largest_free_block_count=lfb_count,
        gemma_running="llama-server" in top_rss or "assistant-llm" in docker,
        gemma_memory_gib=cgroup["memory_gib"],
        gemma_swap_gib=cgroup["swap_gib"],
        codex_active="codex" in known,
    )


def top_processes(top_rss_output: str, count: int = 6) -> list[str]:
    lines = [line for line in top_rss_output.splitlines() if line.strip()]
    return lines[1 : count + 1] if len(lines) > 1 else []


def resource_warnings(snapshot_output: str) -> list[str]:
    warnings: list[str] = []
    meminfo = parse_meminfo(section(snapshot_output, "meminfo"))
    top_rss = section(snapshot_output, "top_rss")
    tegrastats = section(snapshot_output, "tegrastats")
    if meminfo.get("MemAvailable", 0) < 2_500_000:
        warnings.append(f"MemAvailable is low for mixed STT/TTS/vision work: {mib(meminfo.get('MemAvailable'))}.")
    if meminfo.get("CmaFree", 0) < 16_384:
        warnings.append(f"CmaFree is very low: {mib(meminfo.get('CmaFree'))}; GPU/driver allocations may be fragile.")
    lfb = extract_lfb(tegrastats)
    if lfb and "4MB" in lfb:
        warnings.append(
            f"tegrastats largest free block is only {lfb}; contiguous allocation fragmentation is present."
        )
    if "claude login" in top_rss:
        warnings.append("stale `claude login` is running and should be stopped for this no-Claude stack.")
    if "llama-server" in top_rss:
        warnings.append(
            "Gemma llama-server is the largest resident process; schedule it around CUDA STT/vision tests."
        )
    return warnings


def section(output: str, name: str) -> str:
    marker = f"SECTION {name}"
    match = re.search(rf"^{re.escape(marker)}$", output, flags=re.MULTILINE)
    if match is None:
        return ""
    start = match.end()
    next_match = re.search(r"^SECTION .*$", output[start:], flags=re.MULTILINE)
    end = start + next_match.start() if next_match else len(output)
    return output[start:end].strip()


def make_report(results: dict) -> str:
    snapshot = (results.get("snapshot_after_cleanup") or results.get("snapshot") or {}).get("stdout", "")
    docker = section(snapshot, "docker")
    top_rss = section(snapshot, "top_rss")
    tegrastats = section(snapshot, "tegrastats")
    meminfo = parse_meminfo(section(snapshot, "meminfo"))
    codex = results.get("codex_memory", {})
    codex_peak_kb = extract_codex_peak_kb(codex.get("stdout", ""))
    warnings = resource_warnings(snapshot)
    requested_mode = results.get("requested_mode", "voice_realtime")
    decision = decide_resource_policy(build_resource_snapshot(snapshot), requested_mode)
    lines = [
        "# Reachy Jetson Resource Probe",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
        "",
        "## Summary",
        "",
        f"- Jetson snapshot: {'OK' if (results.get('snapshot_after_cleanup') or results.get('snapshot') or {}).get('ok') else 'CHECK'}",
    ]
    if meminfo:
        lines.append(
            f"- Memory: available={mib(meminfo.get('MemAvailable'))}, "
            f"free={mib(meminfo.get('MemFree'))}, swap_free={mib(meminfo.get('SwapFree'))}, "
            f"CmaFree={mib(meminfo.get('CmaFree'))}"
        )
    lfb = extract_lfb(tegrastats)
    if lfb:
        lines.append(f"- Tegrastats largest free block: `{lfb}`")
    if docker:
        lines.append(f"- Docker: `{docker.replace(chr(10), ' / ')[:240]}`")
        cgroup_summary = docker_cgroup_summary(docker)
        if cgroup_summary:
            lines.append(f"- Docker cgroup: `{cgroup_summary}`")
    if codex:
        peak_text = f"{codex_peak_kb / 1024:.1f} MiB" if codex_peak_kb is not None else "unknown"
        lines.append(f"- Codex memory test: {'OK' if codex.get('ok') else 'CHECK'}, peak RSS+children: {peak_text}")
    lines.append(
        f"- Resource decision: `{decision.severity}` for `{decision.requested_mode}` "
        f"(local_gemma={decision.allow_local_gemma}, gpu_stt={decision.allow_gpu_stt}, "
        f"cached_ack={decision.prefer_cached_ack})"
    )
    if results.get("claude_cleanup"):
        lines.append("- Claude login cleanup was requested; see raw JSON for before/after process list.")
    if results.get("resource_policy_post"):
        post = results["resource_policy_post"]
        lines.append(
            f"- Resource policy post: {'OK' if post.get('ok') else 'CHECK'} in {post.get('duration_ms', 'unknown')} ms"
        )
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    if top_rss:
        lines.extend(["", "## Top RSS", "", "```text", "\n".join(top_rss.splitlines()[:18]), "```"])
    top = top_processes(top_rss)
    if top:
        lines.extend(["", "## Biggest Processes", ""])
        lines.extend(f"- `{item}`" for item in top)
    lines.extend(["", "## Resource Decision", ""])
    lines.append("```json")
    lines.append(decision.model_dump_json(indent=2))
    lines.append("```")
    lines.extend(["", "## Raw JSON", "", "```json", json.dumps(results, indent=2)[:50_000], "```", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile Jetson RAM/process/swap/fragmentation state.")
    parser.add_argument("--bridge-url", default="http://127.0.0.1:8787")
    parser.add_argument("--jetson-host", default="192.168.55.1")
    parser.add_argument("--jetson-user", default="brianmeyer")
    parser.add_argument("--jetson-key", default=str(Path.home() / ".ssh" / "reachy_jetson_ed25519"))
    parser.add_argument("--jetson-project", default="/home/brianmeyer/reachy-mini-jetson-assistant")
    parser.add_argument("--connect-timeout", type=int, default=5)
    parser.add_argument("--http-timeout", type=float, default=10)
    parser.add_argument("--top", type=int, default=35)
    parser.add_argument(
        "--include-codex", action="store_true", help="Spend one small Jetson Codex call and sample RSS."
    )
    parser.add_argument("--codex-model", default="gpt-5.5")
    parser.add_argument("--codex-effort", default="low")
    parser.add_argument("--codex-timeout", type=float, default=75)
    parser.add_argument(
        "--stop-claude-login", action="store_true", help="Stop a stale exact `claude login` process on Jetson."
    )
    parser.add_argument(
        "--requested-mode",
        default="voice_realtime",
        choices=[
            "voice_realtime",
            "local_gemma_fallback",
            "jetson_codex_async",
            "gemini_live_visual",
            "dance_tracking",
            "maintenance",
        ],
        help="Resource mode to evaluate in the report decision.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of the report path.")
    args = parser.parse_args()

    results: dict = {"requested_mode": args.requested_mode}
    snapshot = ssh_cmd(args, memory_snapshot_command(args.top), timeout=25)
    results["snapshot"] = snapshot
    if snapshot.get("duration_ms") is not None:
        log_latency(args, "resource", int(snapshot["duration_ms"]), "jetson:resource_probe:snapshot")

    if args.include_codex:
        codex = ssh_cmd(args, codex_memory_command(args), timeout=args.codex_timeout + args.connect_timeout)
        results["codex_memory"] = codex
        if codex.get("duration_ms") is not None:
            log_latency(
                args, "codex", int(codex["duration_ms"]), "jetson:resource_probe:codex_memory", args.codex_model
            )

    if args.stop_claude_login:
        cleanup = ssh_cmd(args, stop_claude_login_command(), timeout=15)
        results["claude_cleanup"] = cleanup
        after = ssh_cmd(args, memory_snapshot_command(args.top), timeout=25)
        results["snapshot_after_cleanup"] = after
        if cleanup.get("duration_ms") is not None:
            log_latency(args, "resource", int(cleanup["duration_ms"]), "jetson:resource_probe:claude_cleanup")

    final_snapshot = (results.get("snapshot_after_cleanup") or results.get("snapshot") or {}).get("stdout", "")
    if final_snapshot:
        policy_post = post_resource_policy(args, final_snapshot)
        results["resource_policy_post"] = policy_post
        if policy_post.get("duration_ms") is not None:
            log_latency(args, "resource", int(policy_post["duration_ms"]), "jetson:resource_probe:policy_post")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-jetson-resource-probe.md"
    report_path.write_text(make_report(results), encoding="utf-8")

    if args.json:
        print(json.dumps({"report": str(report_path), "results": results}, indent=2))
    else:
        print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
