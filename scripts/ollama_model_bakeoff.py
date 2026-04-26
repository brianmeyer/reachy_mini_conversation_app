#!/usr/bin/env python3
from __future__ import annotations
import re
import json
import time
import urllib.error
import urllib.request
from typing import Any
from pathlib import Path


BASE_URL = "http://127.0.0.1:8787"
MODELS = [
    "kimi-k2.6:cloud",
    "glm-5.1:cloud",
    "deepseek-v4-flash:cloud",
    "nemotron-3-super:cloud",
    "qwen3.5:cloud",
]


PROMPT = """Use the artifact tool to create a complete playable single-file HTML game named {safe_name}.
Requirements: kid-friendly click or tap game, visible title, score display, restart button,
moving or changing target, win condition or timer, all CSS and JS inline, no external assets,
no markdown fences. Do not open the screen. Final reply one short sentence."""


def post_task(model: str) -> dict[str, Any]:
    safe_name = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-") + "-game-eval"
    body = {
        "model": model,
        "open_artifacts": False,
        "prompt": PROMPT.format(safe_name=safe_name),
        "max_tool_rounds": 3,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/task",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"error": "HTTP error"}
    except Exception as exc:
        return {
            "model": model,
            "status": 0,
            "seconds": round(time.perf_counter() - t0, 3),
            "error": repr(exc),
        }

    row: dict[str, Any] = {
        "model": model,
        "status": status,
        "seconds": round(time.perf_counter() - t0, 3),
        "text": (payload.get("text") or "")[:200],
    }
    tool_results = payload.get("tool_results") or []
    row["tools"] = [result.get("tool") for result in tool_results]
    row["tool_ok"] = [result.get("ok") for result in tool_results]

    artifact = None
    for result in tool_results:
        if result.get("tool") == "artifact" and result.get("ok"):
            artifact = result.get("result")
            break
    row["artifact"] = artifact
    if artifact and artifact.get("path"):
        inspect_artifact(row, Path(artifact["path"]))
    return row


def inspect_artifact(row: dict[str, Any], path: Path) -> None:
    html = path.read_text(encoding="utf-8", errors="replace")
    lower = html.lower()
    checks = {
        "has_html": "<html" in lower or "<!doctype" in lower,
        "has_script": "<script" in lower,
        "has_style": "<style" in lower or "style=" in lower,
        "has_score": "score" in lower,
        "has_restart": any(term in lower for term in ("restart", "reset", "play again")),
        "has_click_or_pointer": any(
            term in lower
            for term in ("onclick", "addeventlistener", "pointerdown", "mousedown", "touchstart", "click")
        ),
        "has_timer_or_win": any(term in lower for term in ("timer", "time", "win", "game over", "level", "seconds")),
        "no_external_http": "http://" not in lower and "https://" not in lower,
        "not_tiny": len(html) > 1000,
    }
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    row["bytes"] = len(html)
    row["checks"] = checks
    row["static_score"] = sum(bool(value) for value in checks.values())
    row["title"] = title_match.group(1).strip()[:80] if title_match else ""


def main() -> int:
    rows = []
    for model in MODELS:
        row = post_task(model)
        rows.append(row)
        print(json.dumps(row), flush=True)
    summary = sorted(rows, key=lambda item: (-int(item.get("static_score") or 0), float(item.get("seconds") or 999)))
    print("SUMMARY")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
