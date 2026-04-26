#!/usr/bin/env python3
from __future__ import annotations
import json
import time
import urllib.error
import urllib.request
from typing import Any
from pathlib import Path


BASE_URL = "http://127.0.0.1:8787"
ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "docs" / "family" / "ollama-family-task-bakeoff.json"
MODELS = [
    "glm-5.1:cloud",
    "kimi-k2.6:cloud",
    "deepseek-v4-flash:cloud",
    "minimax-m2.7:cloud",
    "gemma4:31b-cloud",
    "qwen3.5:cloud",
    "nemotron-3-super:cloud",
]

TASKS = [
    {
        "id": "memory_proposal",
        "prompt": (
            "Turn this log entry into one concise parent-reviewable memory proposal. "
            "Do not invent facts. Output JSON with keys proposed_memory and reason.\n"
            "Profile: Preston. Log: Preston showed Reachy a drawing captioned 'space castle with a robot guard'."
        ),
        "must": ["proposed_memory", "reason", "Preston", "space castle"],
        "max_chars": 500,
    },
    {
        "id": "calendar_extract",
        "prompt": (
            "Extract a family calendar event as JSON only. Keys: title, date, category, profiles, notes.\n"
            "Input: Build Reachy with Preston and Greyson on April 25, 2026. It is a family build day."
        ),
        "must": ["title", "date", "category", "profiles", "2026-04-25"],
        "max_chars": 700,
    },
    {
        "id": "kid_homework_coach",
        "prompt": (
            "A 9 year old asks: what is 7 x 8? Answer like a playful tutor. "
            "Give a hint first, then the answer. Keep it under 70 words."
        ),
        "must": ["56"],
        "max_chars": 500,
    },
    {
        "id": "parent_ops_summary",
        "prompt": (
            "Summarize this robot status for Brian in 4 short bullets: "
            "cloud enabled, game model glm-5.1, one pending Preston memory, family board has one schedule item and one chore."
        ),
        "must": ["cloud", "glm", "Preston", "family"],
        "max_chars": 700,
    },
]


def post_reason(model: str, prompt: str) -> tuple[int, dict[str, Any], float]:
    body = {"model": model, "prompt": prompt, "prefer": "ollama"}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/reason",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return response.status, json.loads(response.read().decode("utf-8")), time.perf_counter() - started
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"error": "HTTP error"}
        return exc.code, payload, time.perf_counter() - started
    except Exception as exc:
        return 0, {"error": repr(exc)}, time.perf_counter() - started


def score(task: dict[str, Any], text: str) -> dict[str, Any]:
    lowered = text.lower()
    checks = {
        "nonempty": bool(text.strip()),
        "not_too_long": len(text) <= int(task["max_chars"]),
        "has_required_terms": all(term.lower() in lowered for term in task["must"]),
    }
    if task["id"] in {"memory_proposal", "calendar_extract"}:
        try:
            json.loads(_strip_fences(text))
            checks["valid_json"] = True
        except json.JSONDecodeError:
            checks["valid_json"] = False
    return {"checks": checks, "score": sum(bool(value) for value in checks.values())}


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def main() -> int:
    rows: list[dict[str, Any]] = []
    for task in TASKS:
        for model in MODELS:
            status, payload, seconds = post_reason(model, task["prompt"])
            text = payload.get("text") or payload.get("response") or json.dumps(payload)[:1000]
            row = {
                "task": task["id"],
                "model": model,
                "status": status,
                "seconds": round(seconds, 3),
                "text": text[:1200],
            }
            row.update(score(task, text))
            rows.append(row)
            print(json.dumps(row), flush=True)

    summary: dict[str, Any] = {"tasks": TASKS, "rows": rows, "leaderboard": {}}
    for task in TASKS:
        task_rows = [row for row in rows if row["task"] == task["id"]]
        summary["leaderboard"][task["id"]] = sorted(
            task_rows,
            key=lambda row: (-int(row["score"]), float(row["seconds"])),
        )
    OUT_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"WROTE {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
