#!/usr/bin/env python3
from __future__ import annotations
import re
import html
import json
import time
import urllib.error
import urllib.request
from typing import Any
from pathlib import Path


BASE_URL = "http://127.0.0.1:8787"
ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "mac_bridge" / "artifacts"
OUT_DIR = ROOT / "docs" / "family"
MODELS = [
    "glm-5.1:cloud",
    "minimax-m2.7:cloud",
    "kimi-k2.6:cloud",
    "qwen3.5:cloud",
    "nemotron-3-super:cloud",
    "deepseek-v4-flash:cloud",
]
ROUNDS = [
    (
        "round-1-star-catcher",
        "Use the artifact tool to create a complete playable single-file HTML game named same-prompt-round-1. "
        "The game must be a kid-friendly star catching game. Requirements: visible title, score display, "
        "restart button, moving or changing star target, thirty second timer or clear win condition, inline CSS, "
        "inline JavaScript, no external assets, no markdown fences. Do not open the screen. Final reply one short sentence.",
    ),
    (
        "round-2-robot-maze",
        "Use the artifact tool to create a complete playable single-file HTML game named same-prompt-round-2. "
        "The game must be a kid-friendly robot maze game controlled by clicks, taps, or arrow keys. Requirements: "
        "visible title, score or moves display, restart button, goal state, obstacle or wall behavior, inline CSS, "
        "inline JavaScript, no external assets, no markdown fences. Do not open the screen. Final reply one short sentence.",
    ),
]


def post(path: str, body: dict[str, Any], timeout: float = 180.0) -> tuple[int, dict[str, Any], float]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8")), time.perf_counter() - t0
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"error": "HTTP error"}
        return exc.code, payload, time.perf_counter() - t0
    except Exception as exc:
        return 0, {"error": repr(exc)}, time.perf_counter() - t0


def run_model(round_id: str, prompt: str, model: str) -> dict[str, Any]:
    status, payload, seconds = post(
        "/task",
        {
            "model": model,
            "prompt": prompt,
            "open_artifacts": False,
            "max_tool_rounds": 3,
        },
    )
    row: dict[str, Any] = {
        "round": round_id,
        "model": model,
        "status": status,
        "seconds": round(seconds, 3),
        "text": (payload.get("text") or "")[:240],
        "tools": [item.get("tool") for item in payload.get("tool_results", [])],
        "tool_ok": [item.get("ok") for item in payload.get("tool_results", [])],
    }
    for item in payload.get("tool_results", []):
        if item.get("tool") == "artifact" and item.get("ok"):
            row["artifact"] = item.get("result")
            inspect_artifact(row, Path(item["result"]["path"]))
            break
    if "artifact" not in row:
        row["error"] = payload.get("detail") or payload.get("error") or payload
    return row


def inspect_artifact(row: dict[str, Any], path: Path) -> None:
    content = path.read_text(encoding="utf-8", errors="replace")
    lower = content.lower()
    checks = {
        "has_html": "<html" in lower or "<!doctype" in lower,
        "has_title": "<title" in lower or "<h1" in lower,
        "has_style": "<style" in lower or "style=" in lower,
        "has_script": "<script" in lower,
        "has_score_or_moves": "score" in lower or "moves" in lower,
        "has_restart": any(term in lower for term in ("restart", "reset", "play again")),
        "has_input": any(
            term in lower for term in ("click", "onclick", "addeventlistener", "pointerdown", "touchstart", "keydown")
        ),
        "has_goal_or_timer": any(term in lower for term in ("timer", "time", "win", "goal", "game over", "seconds")),
        "no_external_http": "http://" not in lower and "https://" not in lower,
        "not_tiny": len(content) > 1500,
    }
    title_match = re.search(r"<title[^>]*>(.*?)</title>", content, re.I | re.S)
    row["bytes"] = len(content)
    row["checks"] = checks
    row["static_score"] = sum(bool(value) for value in checks.values())
    row["title"] = title_match.group(1).strip()[:100] if title_match else ""


def write_launcher(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for round_id, prompt in ROUNDS:
        cards = []
        for row in [item for item in rows if item["round"] == round_id]:
            artifact = row.get("artifact") or {}
            url = artifact.get("url")
            label = row["model"].replace(":cloud", "")
            status = "PASS" if url else "FAILED"
            score = row.get("static_score", 0)
            link = f'<a href="{html.escape(url)}">Open game</a>' if url else "<span>No artifact</span>"
            cards.append(
                f"""<article>
                    <h3>{html.escape(label)}</h3>
                    <p class="status">{status} · {row.get("seconds")}s · static {score}/10</p>
                    <p>{html.escape(row.get("title") or row.get("text") or "")}</p>
                    <p class="meta">{html.escape(", ".join(row.get("tools") or []))}</p>
                    {link}
                </article>"""
            )
        sections.append(
            f"""<section>
                <h2>{html.escape(round_id)}</h2>
                <details><summary>Exact shared prompt</summary><pre>{html.escape(prompt)}</pre></details>
                <div class="grid">{"".join(cards)}</div>
            </section>"""
        )
    page = f"""<!doctype html><meta charset="utf-8"><title>Reachy Equal Prompt Game Bake-Off</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#08111f;color:#f8fafc;padding:28px}}
h1{{font-size:38px;margin:0 0 8px}} h2{{margin-top:30px}} .sub,.meta{{color:#cbd5e1}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}}
article{{background:#142033;border:1px solid #334155;border-radius:8px;padding:16px}}
h3{{margin:0 0 8px}} .status{{font-weight:700;color:#bfdbfe}} a{{display:inline-block;margin-top:10px;padding:10px 13px;border-radius:6px;background:#4ade80;color:#052e16;font-weight:800;text-decoration:none}}
pre{{white-space:pre-wrap;background:#020617;border:1px solid #334155;border-radius:8px;padding:12px;color:#dbeafe}}
</style>
<h1>Reachy Equal Prompt Game Bake-Off</h1>
<p class="sub">Every model got the exact same prompt within each round. Click each card to judge actual play feel.</p>
{"".join(sections)}"""
    status, payload, _seconds = post(
        "/artifact",
        {
            "name": "reachy-equal-prompt-game-bakeoff",
            "kind": "html",
            "content": page,
        },
        timeout=15,
    )
    if status != 200:
        raise RuntimeError(f"launcher artifact failed: {payload}")
    post("/screen/open", {"url": payload["url"]}, timeout=15)
    return payload


def main() -> int:
    rows = []
    for round_id, prompt in ROUNDS:
        for model in MODELS:
            row = run_model(round_id, prompt, model)
            rows.append(row)
            print(json.dumps(row), flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results_path = OUT_DIR / "ollama-equal-game-rounds.json"
    results_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    launcher = write_launcher(rows)
    print("RESULTS", results_path)
    print("LAUNCHER", json.dumps(launcher))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
