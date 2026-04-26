from __future__ import annotations

import asyncio
import base64
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Literal
from urllib import error, parse, request

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from reachy_runtime.behavior import BehaviorEngine, FakeReachyAdapter, SafetyPolicy
from reachy_runtime.protocol import (
    MacAction,
    GestureAction,
    JetsonEvent,
    LatencySampleEvent,
    MotionBlockedEvent,
    StoryBeatAction,
    protocol_inventory,
    validate_jetson_event,
    validate_mac_action,
)
from reachy_runtime.resources import ResourceSnapshot, decide_resource_policy


ROOT_DIR = Path(__file__).resolve().parent
ARTIFACT_DIR = ROOT_DIR / "artifacts"
STATIC_DIR = ROOT_DIR / "static"
BRIDGE_PORT = int(os.getenv("MAC_BRIDGE_PORT", "8787"))


class Settings(BaseModel):
    bind_host: str = Field(default_factory=lambda: os.getenv("MAC_BRIDGE_HOST", "127.0.0.1"))
    ollama_base_url: str = Field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    default_model: str = Field(
        default_factory=lambda: os.getenv("MAC_BRIDGE_DEFAULT_MODEL", "deepseek-v4-flash:cloud")
    )
    allowed_ollama_models: list[str] = Field(
        default_factory=lambda: _csv_env(
            "MAC_BRIDGE_ALLOWED_OLLAMA_MODELS",
            "kimi-k2.6:cloud,glm-5.1:cloud,deepseek-v4-flash:cloud,nemotron-3-super:cloud,qwen3.5:cloud,minimax-m2.7:cloud,gemma4:31b-cloud",
        )
    )
    require_ollama_cloud: bool = Field(
        default_factory=lambda: os.getenv("MAC_BRIDGE_REQUIRE_OLLAMA_CLOUD", "true").lower()
        in {"1", "true", "yes", "on"}
    )
    hermes_bin: str = Field(default_factory=lambda: os.getenv("MAC_BRIDGE_HERMES_BIN", "hermes"))
    hermes_timeout_seconds: float = Field(default_factory=lambda: float(os.getenv("MAC_BRIDGE_HERMES_TIMEOUT", "45")))
    ollama_timeout_seconds: float = Field(default_factory=lambda: float(os.getenv("MAC_BRIDGE_OLLAMA_TIMEOUT", "60")))
    openai_timeout_seconds: float = Field(default_factory=lambda: float(os.getenv("MAC_BRIDGE_OPENAI_TIMEOUT", "60")))
    ollama_api_key: str | None = Field(default_factory=lambda: os.getenv("OLLAMA_API_KEY"))
    openai_api_key: str | None = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    openai_default_model: str = Field(default_factory=lambda: os.getenv("MAC_BRIDGE_OPENAI_DEFAULT_MODEL", "gpt-5.5"))
    codex_bin: str = Field(default_factory=lambda: os.getenv("MAC_BRIDGE_CODEX_BIN", "codex"))
    codex_default_model: str = Field(default_factory=lambda: os.getenv("MAC_BRIDGE_CODEX_DEFAULT_MODEL", "gpt-5.5"))
    codex_default_reasoning_effort: str = Field(
        default_factory=lambda: os.getenv("MAC_BRIDGE_CODEX_REASONING_EFFORT", "low")
    )
    codex_timeout_seconds: float = Field(default_factory=lambda: float(os.getenv("MAC_BRIDGE_CODEX_TIMEOUT", "45")))
    gemini_api_key: str | None = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY"))
    gemini_base_url: str = Field(
        default_factory=lambda: os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    )
    gemini_timeout_seconds: float = Field(default_factory=lambda: float(os.getenv("MAC_BRIDGE_GEMINI_TIMEOUT", "90")))
    gemini_image_model: str = Field(
        default_factory=lambda: os.getenv("MAC_BRIDGE_GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image-preview")
    )
    gemini_live_model: str = Field(
        default_factory=lambda: os.getenv(
            "MAC_BRIDGE_GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"
        )
    )
    gemini_live_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("MAC_BRIDGE_GEMINI_LIVE_TIMEOUT", "20"))
    )
    allowed_gemini_image_models: list[str] = Field(
        default_factory=lambda: _csv_env(
            "MAC_BRIDGE_GEMINI_ALLOWED_IMAGE_MODELS",
            "gemini-3.1-flash-image-preview,gemini-2.5-flash-image,gemini-3-pro-image-preview",
        )
    )
    gemini_daily_image_limit: int = Field(
        default_factory=lambda: int(os.getenv("MAC_BRIDGE_GEMINI_DAILY_IMAGE_LIMIT", "5"))
    )
    screen_allowlist: list[str] = Field(
        default_factory=lambda: _csv_env(
            "MAC_BRIDGE_ALLOWED_URLS",
            f"http://127.0.0.1:{BRIDGE_PORT},http://localhost:{BRIDGE_PORT},http://127.0.0.1:3000,http://localhost:3000",
        )
    )
    jetson_host: str = Field(default_factory=lambda: os.getenv("MAC_BRIDGE_JETSON_HOST", "192.168.55.1"))
    jetson_user: str = Field(default_factory=lambda: os.getenv("MAC_BRIDGE_JETSON_USER", "brianmeyer"))
    jetson_ssh_key: str = Field(
        default_factory=lambda: os.getenv(
            "MAC_BRIDGE_JETSON_SSH_KEY", str(Path.home() / ".ssh" / "reachy_jetson_ed25519")
        )
    )
    jetson_project: str = Field(
        default_factory=lambda: os.getenv("MAC_BRIDGE_JETSON_PROJECT", "/home/brianmeyer/reachy-mini-jetson-assistant")
    )
    jetson_ssh_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("MAC_BRIDGE_JETSON_SSH_TIMEOUT", "8"))
    )


def _csv_env(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


settings = Settings()

app = FastAPI(
    title="Reachy Mini Mac Bridge",
    description="Local helper API for Reachy parent/dev back-office, artifact mirror, and Mac-only tools.",
    version="0.1.0",
)
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=str(ARTIFACT_DIR)), name="artifacts")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ReasonRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    system: str | None = Field(default=None, max_length=5_000)
    model: str | None = Field(default=None, max_length=200)
    prefer: str = Field(default="codex", pattern="^(hermes|ollama|openai|codex)$")
    reasoning_effort: str | None = Field(default=None, pattern="^(none|low|medium|high|xhigh)$")


class ArtifactRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    content: str = Field(min_length=1, max_length=200_000)
    kind: str = Field(default="text", max_length=40)


class ScreenOpenRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2_000)


class TaskRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    system: str | None = Field(default=None, max_length=5_000)
    model: str | None = Field(default=None, max_length=200)
    reasoning_effort: str | None = Field(default=None, pattern="^(none|low|medium|high|xhigh)$")
    open_artifacts: bool = True
    max_tool_rounds: int = Field(default=3, ge=1, le=5)


class GeminiImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4_000)
    model: str | None = Field(default=None, max_length=120)
    open_image: bool = True


class CloudToggleRequest(BaseModel):
    enabled: bool


class EventLogRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=500)
    actor: str = Field(default="reachy", max_length=80)
    profile: str | None = Field(default=None, max_length=80)
    details: dict[str, Any] = Field(default_factory=dict)


class CaptureImageRequest(BaseModel):
    image_base64: str = Field(min_length=1, max_length=12_000_000)
    mime_type: str = Field(default="image/jpeg", max_length=80)
    profile: str | None = Field(default=None, max_length=80)
    caption: str | None = Field(default=None, max_length=500)
    source: str = Field(default="reachy-camera", max_length=120)
    open_image: bool = False


class MemoryProposalRequest(BaseModel):
    profile: str = Field(min_length=1, max_length=80)
    proposed_memory: str = Field(min_length=3, max_length=500)
    reason: str | None = Field(default=None, max_length=500)
    source_event_ids: list[str] = Field(default_factory=list, max_length=12)


class MemoryProposalGenerateRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)
    profile: str | None = Field(default=None, max_length=80)


class MemoryProposalActionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    write_to_jetson: bool = True
    proposed_memory: str | None = Field(default=None, min_length=3, max_length=500)


class ProfileCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    role: str = Field(default="guest", pattern="^(parent|adult|child|guest)$")
    age_group: str = Field(default="unknown", pattern="^(adult|teen|child|unknown)$")
    relationship: str | None = Field(default=None, max_length=120)
    persona_mode: str | None = Field(default=None, max_length=80)
    communication_style: str | None = Field(default=None, max_length=240)
    aliases: list[str] = Field(default_factory=list, max_length=8)
    status: str = Field(default="pending", pattern="^(pending|active|inactive)$")
    cloud_approved: bool = False


class ProfileIntroductionRequest(BaseModel):
    utterance: str = Field(min_length=1, max_length=500)
    introduced_by: str | None = Field(default=None, max_length=80)


class FamilyEventRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    date: str = Field(min_length=4, max_length=40)
    end_date: str | None = Field(default=None, max_length=40)
    category: str = Field(default="family", max_length=60)
    profiles: list[str] = Field(default_factory=list, max_length=8)
    parent_only: bool = False
    notes: str | None = Field(default=None, max_length=500)


class ChoreRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    assigned_to: str = Field(min_length=1, max_length=80)
    cadence: str = Field(default="daily", max_length=60)
    parent_approval_required: bool = True
    reward: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=500)


class ChoreCompleteRequest(BaseModel):
    actor: str = Field(default="reachy", max_length=80)
    note: str | None = Field(default=None, max_length=500)
    approved_by_parent: bool = False


class AllowlistRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2_000)
    note: str | None = Field(default=None, max_length=500)


class ArtifactActionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class EmotionSimulateRequest(BaseModel):
    profile: str | None = Field(default=None, max_length=80)
    mood: str = Field(default="curious", max_length=80)
    energy: float = Field(default=0.6, ge=0, le=1)
    attention: float = Field(default=0.7, ge=0, le=1)
    confidence: float = Field(default=0.7, ge=0, le=1)
    stimulus: str | None = Field(default=None, max_length=500)


class RealtimeSessionRequest(BaseModel):
    mode: str = Field(default="audio", pattern="^(audio|audio_video)$")
    requested_seconds: int = Field(default=60, ge=5, le=300)
    dry_run: bool = True
    note: str | None = Field(default=None, max_length=500)


class GeminiLiveProbeRequest(BaseModel):
    prompt: str = Field(
        default="Say one short friendly sentence to confirm Gemini Live is connected.", min_length=1, max_length=1_000
    )
    model: str | None = Field(default=None, max_length=160)
    response_modality: str = Field(default="TEXT", pattern="^(TEXT|AUDIO)$")
    system: str | None = Field(
        default="You are Reachy, a warm family robot. Keep this probe under one sentence.", max_length=1_000
    )


class JetsonActionAckRequest(BaseModel):
    status: str = Field(default="acked", pattern="^(sent|acked|failed|expired)$")
    note: str | None = Field(default=None, max_length=500)


class BehaviorDryRunRequest(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    actions: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class ResourcePolicyRequest(BaseModel):
    requested_mode: Literal[
        "voice_realtime",
        "local_gemma_fallback",
        "jetson_codex_async",
        "gemini_live_visual",
        "dance_tracking",
        "maintenance",
    ] = "voice_realtime"
    snapshot: ResourceSnapshot


@app.get("/tools")
async def tools() -> dict[str, Any]:
    return {
        "ok": True,
        "default_reasoning_model": settings.codex_default_model,
        "default_tool_model": settings.default_model,
        "policy": {
            "primary_cloud_reasoning": settings.codex_default_model,
            "primary_cloud_reasoning_backend": "codex-cli",
            "codex_reasoning_effort": settings.codex_default_reasoning_effort,
            "premium_realtime_model": "gemini-live",
            "mac_ollama": "cloud-only" if settings.require_ollama_cloud else "cloud-and-local",
            "accepted_cloud_suffixes": ["-cloud", ":cloud"],
            "allowed_ollama_models": settings.allowed_ollama_models,
            "cloud_enabled": _cloud_enabled(),
            "voice_default": "jetson-local-first-audio",
            "hermes_role": "explicit deep/agentic tasks, not default kid-latency path",
            "routing": {
                "plain_fast_reasoning": settings.codex_default_model,
                "quick_screen_or_tool_actions": settings.codex_default_model,
                "playable_game_generation": settings.codex_default_model,
                "quick_game_draft": settings.codex_default_model,
                "game_generation_backups": ["deepseek-v4-flash:cloud", "minimax-m2.7:cloud", "kimi-k2.6:cloud"],
                "avoid_for_games": ["qwen3.5:cloud", "nemotron-3-super:cloud"],
                "creative_or_code_heavy": settings.codex_default_model,
                "backup_general": "deepseek-v4-flash:cloud",
                "explicit_deep_slow": settings.codex_default_model,
                "family_calendar_memory": settings.codex_default_model,
                "parent_status_summary": settings.codex_default_model,
                "kid_image_generation": settings.gemini_image_model,
                "premium_realtime": settings.gemini_live_model,
                "ollama_fallbacks": {
                    "games": "glm-5.1:cloud",
                    "family_structured": "gemma4:31b-cloud",
                    "fast_summary": "deepseek-v4-flash:cloud",
                },
            },
        },
        "tools": [
            {
                "name": "reason",
                "endpoint": "POST /reason",
                "owner": "mac",
                "preferred_for": [
                    "game/app/code generation",
                    "screen tasks",
                    "web/video requests",
                    "heavier reasoning",
                ],
                "default_backend": "codex-cli",
                "default_model": settings.codex_default_model,
                "default_reasoning_effort": settings.codex_default_reasoning_effort,
            },
            {
                "name": "task",
                "endpoint": "POST /task",
                "owner": "mac",
                "preferred_for": [
                    "Ollama-driven artifact and screen tasks",
                    "one-shot game/page creation",
                    "safe tool-calling escalation",
                ],
                "available_to_ollama": [
                    "artifact",
                    "screen_open",
                    "screen_clear",
                    "youtube_search",
                    "weather_current",
                    "web_search",
                    "gemini_image",
                ],
                "default_model": settings.default_model,
            },
            {
                "name": "artifact",
                "endpoint": "POST /artifact",
                "owner": "mac",
                "preferred_for": [
                    "HTML games",
                    "interactive pages",
                    "generated text/json/js/css artifacts",
                ],
            },
            {
                "name": "screen_open",
                "endpoint": "POST /screen/open",
                "owner": "mac",
                "preferred_for": [
                    "opening generated artifacts",
                    "opening allowlisted kid sites",
                    "opening local dev servers",
                ],
                "allowed_prefixes": settings.screen_allowlist,
            },
            {
                "name": "screen_clear",
                "endpoint": "POST /screen/clear",
                "owner": "mac",
                "preferred_for": ["clearing the shared monitor"],
            },
            {
                "name": "youtube_search",
                "endpoint": "tool-only via POST /task",
                "owner": "mac",
                "preferred_for": ["opening kid-requested YouTube searches on the shared screen"],
            },
            {
                "name": "weather_current",
                "endpoint": "tool-only via POST /task",
                "owner": "mac",
                "preferred_for": ["current weather questions"],
                "provider": "Open-Meteo",
            },
            {
                "name": "web_search",
                "endpoint": "tool-only via POST /task",
                "owner": "mac",
                "preferred_for": ["fresh kid questions and homework facts that need current sources"],
                "available": bool(settings.ollama_api_key),
                "needs": "OLLAMA_API_KEY" if not settings.ollama_api_key else None,
            },
            {
                "name": "gemini_image",
                "endpoint": "POST /gemini/image",
                "owner": "mac",
                "preferred_for": ["kid-safe picture generation and visual art prompts"],
                "provider": "Gemini API",
                "available": bool(settings.gemini_api_key),
                "default_model": settings.gemini_image_model,
                "allowed_models": settings.allowed_gemini_image_models,
                "daily_limit": settings.gemini_daily_image_limit,
                "needs": "GEMINI_API_KEY" if not settings.gemini_api_key else None,
            },
            {
                "name": "gemini_live_probe",
                "endpoint": "POST /gemini/live/probe",
                "owner": "mac",
                "preferred_for": [
                    "server-side Gemini Live connectivity test",
                    "pre-duplex low-latency probe",
                ],
                "provider": "Gemini Live API",
                "available": bool(settings.gemini_api_key),
                "default_model": settings.gemini_live_model,
                "needs": "GEMINI_API_KEY" if not settings.gemini_api_key else None,
            },
        ],
        "local_jetson_tools": [
            "stt:temporary faster-whisper base.en cuda/int8 diagnostic fallback; bilingual path required",
            "vad:silero onnx",
            "llm:gemma-4-E2B-it-Q4_K_M via llama.cpp",
            "tts:kokoro",
            "emotion:distilbert sst-2 onnx",
            "movement:Reachy Mini SDK when hardware is connected",
        ],
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "reachy-mini-mac-bridge",
        "bind_host": settings.bind_host,
        "port": BRIDGE_PORT,
        "safe_default": settings.bind_host in {"127.0.0.1", "localhost"},
        "gemini_configured": bool(settings.gemini_api_key),
        "cloud_enabled": _cloud_enabled(),
    }


@app.get("/models")
async def models() -> dict[str, Any]:
    hermes_info, ollama_info = await asyncio.gather(
        asyncio.to_thread(_probe_hermes),
        asyncio.to_thread(_ollama_tags),
    )
    return {
        "primary_model": settings.codex_default_model,
        "default_model": settings.default_model,
        "require_ollama_cloud": settings.require_ollama_cloud,
        "cloud_enabled": _cloud_enabled(),
        "codex": _probe_codex(),
        "openai": {
            "available": bool(settings.openai_api_key),
            "default_model": settings.openai_default_model,
            "realtime_model": None,
            "realtime_note": "Not used unless a proper OpenAI API realtime auth path is configured.",
        },
        "hermes": hermes_info,
        "ollama": ollama_info,
    }


@app.post("/reason")
async def reason(payload: ReasonRequest) -> dict[str, Any]:
    if not _cloud_enabled():
        _log_event(
            "cloud_blocked",
            "Blocked reasoning request because cloud is disabled.",
            details={"endpoint": "/reason", "prompt": payload.prompt},
        )
        raise HTTPException(
            status_code=503, detail={"message": "Cloud reasoning is disabled by the parent/operator control panel."}
        )
    started = time.monotonic()
    if payload.prefer == "hermes":
        hermes = await asyncio.to_thread(_run_hermes, payload)
        if hermes["ok"]:
            _log_event(
                "reason",
                "Reasoning request answered.",
                details={
                    "backend": hermes.get("backend"),
                    "prefer": payload.prefer,
                    "model": payload.model,
                    "prompt": payload.prompt,
                    "duration_ms": _elapsed_ms(started),
                },
            )
            return hermes

    codex: dict[str, Any] | None = None
    if payload.prefer == "codex" or (payload.prefer == "openai" and not settings.openai_api_key):
        codex = await asyncio.to_thread(_run_codex_reason, payload)
        if codex["ok"]:
            _log_event(
                "reason",
                "Reasoning request answered.",
                details={
                    "backend": codex.get("backend"),
                    "prefer": payload.prefer,
                    "model": codex.get("model") or payload.model,
                    "reasoning_effort": codex.get("reasoning_effort"),
                    "prompt": payload.prompt,
                    "duration_ms": _elapsed_ms(started),
                },
            )
            return codex

    openai: dict[str, Any] | None = None
    if payload.prefer == "openai":
        openai = await asyncio.to_thread(_run_openai_reason, payload)
        if openai["ok"]:
            _log_event(
                "reason",
                "Reasoning request answered.",
                details={
                    "backend": openai.get("backend"),
                    "prefer": payload.prefer,
                    "model": openai.get("model") or payload.model,
                    "prompt": payload.prompt,
                    "duration_ms": _elapsed_ms(started),
                },
            )
            return openai

    ollama = await asyncio.to_thread(_run_ollama, payload)
    if ollama["ok"]:
        if payload.prefer == "hermes":
            ollama["fallback_from"] = "hermes"
        elif payload.prefer == "openai":
            ollama["fallback_from"] = "openai"
            ollama["fallback_reason"] = (openai or codex or {}).get("error") or "openai/codex not attempted"
        elif payload.prefer == "codex":
            ollama["fallback_from"] = "codex"
            ollama["fallback_reason"] = codex.get("error") if codex else "codex not attempted"
        _log_event(
            "reason",
            "Reasoning request answered.",
            details={
                "backend": ollama.get("backend"),
                "prefer": payload.prefer,
                "model": ollama.get("model") or payload.model,
                "prompt": payload.prompt,
                "duration_ms": _elapsed_ms(started),
            },
        )
        return ollama

    raise HTTPException(
        status_code=503,
        detail={
            "message": "No local reasoning backend answered in time.",
            "hermes": "Try `hermes doctor` if Hermes is installed.",
            "openai": openai,
            "ollama": ollama,
        },
    )


@app.post("/task")
async def task(payload: TaskRequest) -> dict[str, Any]:
    if not _cloud_enabled():
        _log_event(
            "cloud_blocked",
            "Blocked tool task because cloud is disabled.",
            details={"endpoint": "/task", "prompt": payload.prompt},
        )
        raise HTTPException(
            status_code=503, detail={"message": "Cloud tool routing is disabled by the parent/operator control panel."}
        )
    started = time.monotonic()
    result = await asyncio.to_thread(_run_ollama_tool_task, payload)
    if result["ok"]:
        _log_event(
            "task",
            "Tool task completed.",
            details={
                "backend": result.get("backend"),
                "model": result.get("model"),
                "prompt": payload.prompt,
                "text": result.get("text"),
                "tool_names": [item.get("tool") for item in result.get("tool_results", [])],
                "duration_ms": _elapsed_ms(started),
            },
        )
        return result
    _log_event(
        "task_error",
        "Tool task failed.",
        details={
            "model": result.get("model"),
            "prompt": payload.prompt,
            "error": result.get("error"),
            "duration_ms": _elapsed_ms(started),
        },
    )
    raise HTTPException(status_code=503, detail=result)


@app.post("/artifact")
async def artifact(payload: ArtifactRequest) -> dict[str, Any]:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    result = _save_artifact(payload.name, payload.kind, payload.content)
    _log_event(
        "artifact", "Artifact created.", details={"name": payload.name, "kind": payload.kind, "artifact": result}
    )
    return result


@app.post("/gemini/image")
async def gemini_image(payload: GeminiImageRequest) -> dict[str, Any]:
    if not _cloud_enabled():
        _log_event(
            "cloud_blocked",
            "Blocked Gemini image request because cloud is disabled.",
            details={"endpoint": "/gemini/image", "prompt": payload.prompt},
        )
        raise HTTPException(
            status_code=503,
            detail={"message": "Gemini image generation is disabled by the parent/operator control panel."},
        )
    started = time.monotonic()
    result = await asyncio.to_thread(_gemini_generate_image, payload)
    if result["ok"]:
        _log_event(
            "image",
            "Gemini image generated.",
            details={
                "model": result.get("model"),
                "prompt": payload.prompt,
                "image": result.get("image"),
                "quota": result.get("quota"),
                "usage_metadata": result.get("usage_metadata"),
                "duration_ms": _elapsed_ms(started),
            },
        )
        return result
    _log_event(
        "image_error",
        "Gemini image request failed.",
        details={
            "model": payload.model,
            "prompt": payload.prompt,
            "error": result.get("error"),
            "duration_ms": _elapsed_ms(started),
        },
    )
    raise HTTPException(status_code=503, detail=result)


@app.post("/screen/open")
async def screen_open(payload: ScreenOpenRequest) -> dict[str, Any]:
    if not _url_allowed(payload.url):
        _log_event("screen_blocked", "Blocked screen open for non-allowlisted URL.", details={"url": payload.url})
        raise HTTPException(
            status_code=403,
            detail={
                "message": "URL is not in the local allowlist.",
                "allowed_prefixes": settings.screen_allowlist,
                "how_to_change": "Set MAC_BRIDGE_ALLOWED_URLS to comma-separated local URLs.",
            },
        )
    result = await asyncio.to_thread(_open_screen_url, payload.url)
    _log_event("screen_open", "Opened URL on screen.", details={"url": payload.url, "result": result})
    return result


@app.post("/screen/clear")
async def screen_clear() -> dict[str, Any]:
    blank_url = "about:blank"
    opened = await asyncio.to_thread(webbrowser.open, blank_url, 2)
    result = {"ok": bool(opened), "url": blank_url}
    _log_event("screen_clear", "Cleared the screen.", details=result)
    return result


@app.get("/artifacts/list")
async def artifacts_list(limit: int = 30) -> dict[str, Any]:
    return {"ok": True, "artifacts": _list_artifacts(max(1, min(limit, 100)))}


@app.post("/admin/artifacts/{artifact_name}/delete")
async def artifact_delete(artifact_name: str, payload: ArtifactActionRequest) -> dict[str, Any]:
    result = await asyncio.to_thread(_delete_artifact, artifact_name, payload)
    if result["ok"]:
        return result
    raise HTTPException(status_code=404, detail=result)


@app.get("/events")
async def events(limit: int = 100, event_type: str | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "events": _read_events(max(1, min(limit, 500)), event_type=event_type),
        "stats": _event_stats(),
    }


@app.post("/events/log")
async def events_log(payload: EventLogRequest) -> dict[str, Any]:
    event = _log_event(
        payload.event_type, payload.summary, actor=payload.actor, profile=payload.profile, details=payload.details
    )
    return {"ok": True, "event": event}


@app.get("/protocol")
async def protocol() -> dict[str, Any]:
    return {"ok": True, "protocol": protocol_inventory(), "gestures": _behavior_gesture_inventory()}


@app.post("/jetson/events")
async def jetson_event(payload: JetsonEvent) -> dict[str, Any]:
    result = _ingest_jetson_event(payload)
    return {"ok": True, **result}


@app.post("/jetson/actions")
async def jetson_action_enqueue(payload: MacAction) -> dict[str, Any]:
    result = _enqueue_jetson_action(payload)
    if result["ok"]:
        return result
    raise HTTPException(status_code=400, detail=result)


@app.get("/jetson/actions/pending")
async def jetson_actions_pending(limit: int = 20) -> dict[str, Any]:
    return {"ok": True, "actions": _pending_jetson_actions(max(1, min(limit, 100)))}


@app.post("/jetson/actions/{action_id}/ack")
async def jetson_action_ack(action_id: str, payload: JetsonActionAckRequest) -> dict[str, Any]:
    result = _ack_jetson_action(action_id, payload)
    if result["ok"]:
        return result
    raise HTTPException(status_code=404, detail=result)


@app.get("/behavior/gestures")
async def behavior_gestures() -> dict[str, Any]:
    return {"ok": True, "gestures": _behavior_gesture_inventory()}


@app.post("/behavior/dry-run")
async def behavior_dry_run(payload: BehaviorDryRunRequest) -> dict[str, Any]:
    try:
        return _behavior_dry_run(payload)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc)}) from exc


@app.post("/resource/policy")
async def resource_policy(payload: ResourcePolicyRequest) -> dict[str, Any]:
    decision = decide_resource_policy(payload.snapshot, payload.requested_mode)
    event = _log_event(
        "resource_decision",
        f"Resource mode {decision.requested_mode}: {decision.severity}.",
        actor="jetson",
        details={"snapshot": payload.snapshot.model_dump(), "decision": decision.model_dump()},
    )
    return {"ok": True, "decision": decision.model_dump(), "event": event}


@app.get("/analytics/latency")
async def latency_analytics(limit: int = 500) -> dict[str, Any]:
    return {"ok": True, "latency": _latency_analytics(max(1, min(limit, 2_000)))}


@app.get("/analytics/routing")
async def routing_analytics(limit: int = 500) -> dict[str, Any]:
    return {"ok": True, "routing": _routing_analytics(max(1, min(limit, 2_000))), "policy": _routing_policy()}


@app.get("/reports/summary")
async def reports_summary(limit: int = 500) -> dict[str, Any]:
    return {"ok": True, "report": _parent_report(max(1, min(limit, 2_000)))}


@app.get("/media/policy")
async def media_policy() -> dict[str, Any]:
    return {"ok": True, "policy": _media_policy()}


@app.post("/media/allowlist")
async def media_allowlist_add(payload: AllowlistRequest) -> dict[str, Any]:
    result = await asyncio.to_thread(_allowlist_add, payload)
    if result["ok"]:
        return result
    raise HTTPException(status_code=400, detail=result)


@app.post("/media/allowlist/remove")
async def media_allowlist_remove(payload: AllowlistRequest) -> dict[str, Any]:
    result = await asyncio.to_thread(_allowlist_remove, payload)
    if result["ok"]:
        return result
    raise HTTPException(status_code=404, detail=result)


@app.get("/emotion/state")
async def emotion_state() -> dict[str, Any]:
    return {"ok": True, "state": _emotion_state()}


@app.post("/emotion/simulate")
async def emotion_simulate(payload: EmotionSimulateRequest) -> dict[str, Any]:
    return await asyncio.to_thread(_emotion_simulate, payload)


@app.get("/gemini/live/status")
async def gemini_live_status() -> dict[str, Any]:
    return {"ok": True, "live": _gemini_live_status()}


@app.post("/gemini/live/session")
async def gemini_live_session(payload: RealtimeSessionRequest) -> dict[str, Any]:
    result = await asyncio.to_thread(_gemini_live_session, payload)
    if result["ok"]:
        return result
    raise HTTPException(status_code=400, detail=result)


@app.post("/gemini/live/probe")
async def gemini_live_probe(payload: GeminiLiveProbeRequest) -> dict[str, Any]:
    if not _cloud_enabled():
        _log_event(
            "cloud_blocked",
            "Blocked Gemini Live probe because cloud is disabled.",
            details={"endpoint": "/gemini/live/probe", "prompt": payload.prompt},
        )
        raise HTTPException(
            status_code=503, detail={"message": "Gemini Live is disabled by the parent/operator control panel."}
        )
    result = await asyncio.to_thread(_run_gemini_live_probe, payload)
    if result["ok"]:
        _log_event(
            "gemini_live_probe",
            "Gemini Live probe completed.",
            actor="parent",
            details={
                "model": result.get("model"),
                "response_modality": payload.response_modality,
                "duration_ms": result.get("duration_ms"),
                "text": result.get("text"),
                "audio_bytes": result.get("audio_bytes"),
            },
        )
        return result
    _log_event(
        "gemini_live_error",
        "Gemini Live probe failed.",
        actor="parent",
        details={"model": payload.model or settings.gemini_live_model, "error": result.get("error")},
    )
    raise HTTPException(status_code=503, detail=result)


@app.post("/memory/capture-image")
async def memory_capture_image(payload: CaptureImageRequest) -> dict[str, Any]:
    result = await asyncio.to_thread(_capture_image_memory, payload)
    if result["ok"]:
        return result
    raise HTTPException(status_code=400, detail=result)


@app.get("/memory/profiles")
async def memory_profiles() -> dict[str, Any]:
    return {"ok": True, "profiles": _memory_profiles()}


@app.post("/memory/profiles")
async def memory_profile_create(payload: ProfileCreateRequest) -> dict[str, Any]:
    result = await asyncio.to_thread(_create_memory_profile, payload, "parent")
    if result["ok"]:
        return result
    raise HTTPException(status_code=400, detail=result)


@app.post("/memory/profiles/introduction")
async def memory_profile_introduction(payload: ProfileIntroductionRequest) -> dict[str, Any]:
    result = await asyncio.to_thread(_create_profile_from_introduction, payload)
    if result["ok"]:
        return result
    raise HTTPException(status_code=400, detail=result)


@app.get("/memory/proposals")
async def memory_proposals(limit: int = 100, status: str | None = None, profile: str | None = None) -> dict[str, Any]:
    proposals = _read_memory_proposals()
    if status:
        proposals = [item for item in proposals if item.get("status") == status]
    if profile:
        normalized = _normalize_profile(profile)
        proposals = [item for item in proposals if item.get("profile") == normalized]
    proposals = proposals[-max(1, min(limit, 500)) :][::-1]
    return {"ok": True, "proposals": proposals, "profiles": _memory_profiles(), "stats": _memory_proposal_stats()}


@app.post("/memory/proposals")
async def memory_proposal_create(payload: MemoryProposalRequest) -> dict[str, Any]:
    result = await asyncio.to_thread(_create_memory_proposal, payload, "manual")
    if result["ok"]:
        return result
    raise HTTPException(status_code=400, detail=result)


@app.post("/memory/proposals/generate")
async def memory_proposal_generate(payload: MemoryProposalGenerateRequest) -> dict[str, Any]:
    return await asyncio.to_thread(_generate_memory_proposals, payload)


@app.post("/memory/proposals/{proposal_id}/approve")
async def memory_proposal_approve(proposal_id: str, payload: MemoryProposalActionRequest) -> dict[str, Any]:
    result = await asyncio.to_thread(_approve_memory_proposal, proposal_id, payload)
    if result["ok"]:
        return result
    raise HTTPException(status_code=400 if result.get("kind") == "policy" else 503, detail=result)


@app.post("/memory/proposals/{proposal_id}/reject")
async def memory_proposal_reject(proposal_id: str, payload: MemoryProposalActionRequest) -> dict[str, Any]:
    result = await asyncio.to_thread(_reject_memory_proposal, proposal_id, payload)
    if result["ok"]:
        return result
    raise HTTPException(status_code=404, detail=result)


@app.post("/memory/proposals/{proposal_id}/delete")
async def memory_proposal_delete(proposal_id: str, payload: MemoryProposalActionRequest) -> dict[str, Any]:
    result = await asyncio.to_thread(_delete_memory_proposal, proposal_id, payload)
    if result["ok"]:
        return result
    raise HTTPException(status_code=404, detail=result)


@app.get("/family/board")
async def family_board() -> dict[str, Any]:
    return {"ok": True, "board": _family_board(), "profiles": _memory_profiles()}


@app.post("/family/events")
async def family_event_create(payload: FamilyEventRequest) -> dict[str, Any]:
    result = await asyncio.to_thread(_create_family_event, payload)
    if result["ok"]:
        return result
    raise HTTPException(status_code=400, detail=result)


@app.post("/family/events/{event_id}/delete")
async def family_event_delete(event_id: str) -> dict[str, Any]:
    result = await asyncio.to_thread(_delete_family_event, event_id)
    if result["ok"]:
        return result
    raise HTTPException(status_code=404, detail=result)


@app.post("/family/chores")
async def family_chore_create(payload: ChoreRequest) -> dict[str, Any]:
    result = await asyncio.to_thread(_create_chore, payload)
    if result["ok"]:
        return result
    raise HTTPException(status_code=400, detail=result)


@app.post("/family/chores/{chore_id}/complete")
async def family_chore_complete(chore_id: str, payload: ChoreCompleteRequest) -> dict[str, Any]:
    result = await asyncio.to_thread(_complete_chore, chore_id, payload)
    if result["ok"]:
        return result
    raise HTTPException(status_code=404, detail=result)


@app.get("/admin/status")
async def admin_status() -> dict[str, Any]:
    return _admin_status()


@app.post("/admin/cloud")
async def admin_cloud(payload: CloudToggleRequest) -> dict[str, Any]:
    _set_cloud_enabled(payload.enabled)
    _log_event("cloud_toggle", "Cloud setting changed.", actor="parent", details={"enabled": payload.enabled})
    return _admin_status()


@app.get("/parent")
async def parent_dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "parent-dashboard.html")


@app.get("/logs")
async def logs_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "parent-logs.html")


@app.get("/memory")
async def memory_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "parent-memory.html")


@app.get("/family")
async def family_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "parent-family.html")


@app.get("/kids")
async def kids_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "kid-family.html")


@app.get("/ops")
async def ops_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "parent-ops.html")


@app.get("/gallery")
async def gallery_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "artifact-gallery.html")


@app.get("/command")
async def command_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "touch-command.html")


def _probe_hermes() -> dict[str, Any]:
    hermes_path = shutil.which(settings.hermes_bin)
    if not hermes_path:
        return {"available": False, "reason": f"`{settings.hermes_bin}` not found on PATH"}
    try:
        result = subprocess.run(
            [hermes_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"available": True, "path": hermes_path, "version": "timeout"}
    return {
        "available": True,
        "path": hermes_path,
        "version": (result.stdout or result.stderr).strip()[:500],
    }


def _probe_codex() -> dict[str, Any]:
    codex_path = shutil.which(settings.codex_bin)
    if not codex_path:
        return {"available": False, "reason": f"`{settings.codex_bin}` not found on PATH"}
    try:
        version = subprocess.run(
            [codex_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - health-style probe.
        return {"available": False, "path": codex_path, "error": str(exc)}
    return {
        "available": version.returncode == 0,
        "path": codex_path,
        "version": (version.stdout or version.stderr).strip()[:300],
        "default_model": settings.codex_default_model,
        "default_reasoning_effort": settings.codex_default_reasoning_effort,
    }


def _admin_status() -> dict[str, Any]:
    routing = _routing_policy()
    return {
        "ok": True,
        "service": "reachy-mini-mac-bridge",
        "cloud_enabled": _cloud_enabled(),
        "cloud_state_path": str(_cloud_state_path()),
        "default_tool_model": settings.default_model,
        "openai_configured": bool(settings.openai_api_key),
        "openai_default_model": settings.openai_default_model,
        "routing": routing,
        "game_model": routing["playable_game_generation"],
        "ollama_cloud_only": settings.require_ollama_cloud,
        "allowed_ollama_models": settings.allowed_ollama_models,
        "gemini_configured": bool(settings.gemini_api_key),
        "gemini_image_model": settings.gemini_image_model,
        "gemini_live_model": settings.gemini_live_model,
        "gemini_image_quota": _gemini_image_quota(),
        "screen_allowlist": settings.screen_allowlist,
        "runtime_screen_allowlist": _runtime_allowlist(),
        "latest_artifacts": _list_artifacts(12),
        "latency": _latency_analytics(500),
        "routing_analytics": _routing_analytics(500),
        "gemini_live": _gemini_live_status(),
        "emotion": _emotion_state(),
        "event_stats": _event_stats(),
        "memory_proposal_stats": _memory_proposal_stats(),
        "latest_events": _read_events(8),
    }


def _routing_policy() -> dict[str, Any]:
    return {
        "primary_cloud_reasoning": settings.codex_default_model,
        "primary_cloud_reasoning_backend": "codex-cli",
        "codex_reasoning_effort": settings.codex_default_reasoning_effort,
        "premium_realtime": "gemini-live",
        "plain_fast_reasoning": settings.codex_default_model,
        "quick_screen_or_tool_actions": settings.codex_default_model,
        "playable_game_generation": settings.codex_default_model,
        "quick_game_draft": settings.codex_default_model,
        "game_generation_backups": ["deepseek-v4-flash:cloud", "minimax-m2.7:cloud", "kimi-k2.6:cloud"],
        "avoid_for_games": ["qwen3.5:cloud", "nemotron-3-super:cloud"],
        "creative_or_code_heavy": settings.codex_default_model,
        "backup_general": "deepseek-v4-flash:cloud",
        "explicit_deep_slow": settings.codex_default_model,
        "family_calendar_memory": settings.codex_default_model,
        "parent_status_summary": settings.codex_default_model,
        "kid_image_generation": settings.gemini_image_model,
        "ollama_fallbacks": {
            "games": "glm-5.1:cloud",
            "family_structured": "gemma4:31b-cloud",
            "fast_summary": "deepseek-v4-flash:cloud",
        },
    }


def _cloud_enabled() -> bool:
    path = _cloud_state_path()
    if not path.exists():
        return True
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True
    return bool(state.get("enabled", True))


def _set_cloud_enabled(enabled: bool) -> None:
    path = _cloud_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"enabled": enabled, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, indent=2),
        encoding="utf-8",
    )


def _cloud_state_path() -> Path:
    return ROOT_DIR / ".state" / "cloud-control.json"


def _list_artifacts(limit: int = 30) -> list[dict[str, Any]]:
    if not ARTIFACT_DIR.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in ARTIFACT_DIR.iterdir():
        if not path.is_file() or path.name.startswith("."):
            continue
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "path": str(path),
                "url": f"http://127.0.0.1:{BRIDGE_PORT}/artifacts/{parse.quote(path.name)}",
                "bytes": stat.st_size,
                "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                "kind": _artifact_kind(path),
            }
        )
    return sorted(items, key=lambda item: item["modified"], reverse=True)[:limit]


def _delete_artifact(artifact_name: str, payload: ArtifactActionRequest) -> dict[str, Any]:
    safe_name = Path(artifact_name).name
    path = (ARTIFACT_DIR / safe_name).resolve()
    artifact_root = ARTIFACT_DIR.resolve()
    if (
        not str(path).startswith(str(artifact_root))
        or not path.exists()
        or not path.is_file()
        or path.name.startswith(".")
    ):
        return {"ok": False, "error": f"Artifact not found: {artifact_name}"}
    info = {
        "name": path.name,
        "path": str(path),
        "bytes": path.stat().st_size,
        "kind": _artifact_kind(path),
    }
    path.unlink()
    _log_event(
        "artifact_deleted",
        f"Deleted artifact: {safe_name}.",
        actor="parent",
        details={"artifact": info, "note": payload.note},
    )
    return {"ok": True, "deleted": info}


def _capture_image_memory(payload: CaptureImageRequest) -> dict[str, Any]:
    try:
        image_bytes = base64.b64decode(payload.image_base64, validate=True)
    except Exception as exc:  # noqa: BLE001 - returned to local caller.
        return {"ok": False, "error": f"Invalid base64 image data: {exc}"}
    suffix = _image_suffix(payload.mime_type)
    name_parts = ["shown-image"]
    if payload.profile:
        name_parts.append(payload.profile)
    saved = _save_binary_artifact("-".join(name_parts), suffix, image_bytes)
    opened = _open_screen_url(saved["url"]) if payload.open_image else None
    event = _log_event(
        "shown_image",
        payload.caption or "Saved an image shown to Reachy.",
        actor="reachy",
        profile=payload.profile,
        details={
            "caption": payload.caption,
            "source": payload.source,
            "mime_type": payload.mime_type,
            "image": saved,
            "opened": opened,
        },
    )
    return {"ok": True, "image": saved, "opened": opened, "event": event}


def _memory_profiles() -> list[dict[str, Any]]:
    profiles = [
        {
            "id": "brian",
            "display_name": "Brian",
            "role": "parent",
            "age_group": "adult",
            "relationship": "parent/operator",
            "persona_mode": "eager_assistant",
            "communication_style": "concise, operational, setup-aware",
            "status": "active",
            "cloud_approved": True,
            "memory_file": "data/memories/brian.md",
            "aliases": ["dad", "brianmeyer"],
        },
        {
            "id": "preston",
            "display_name": "Preston",
            "role": "child",
            "age_group": "child",
            "relationship": "family",
            "persona_mode": "playful_coach",
            "communication_style": "short, fun, encouraging, hints before answers",
            "status": "active",
            "cloud_approved": False,
            "memory_file": "data/memories/preston.md",
            "aliases": ["kid_1"],
        },
        {
            "id": "greyson",
            "display_name": "Greyson",
            "role": "child",
            "age_group": "child",
            "relationship": "family",
            "persona_mode": "playful_coach",
            "communication_style": "short, fun, encouraging, hints before answers",
            "status": "active",
            "cloud_approved": False,
            "memory_file": "data/memories/greyson.md",
            "aliases": ["kid_2", "grayson"],
        },
        {
            "id": "unknown_guest",
            "display_name": "Unknown guest",
            "role": "guest",
            "age_group": "unknown",
            "relationship": "guest",
            "persona_mode": "friendly_limited",
            "communication_style": "friendly, conservative memory, no private context",
            "status": "active",
            "cloud_approved": False,
            "memory_file": "data/memories/unknown_guest.md",
            "aliases": ["guest"],
        },
    ]
    seen = {str(item["id"]) for item in profiles}
    for profile in _read_dynamic_profiles():
        if profile.get("id") not in seen:
            profiles.append(profile)
            seen.add(str(profile.get("id")))
    return profiles


def _create_memory_profile(payload: ProfileCreateRequest, source: str) -> dict[str, Any]:
    display_name = " ".join(payload.display_name.split())
    violation = _profile_policy_violation(display_name)
    if violation:
        return {"ok": False, "error": violation}
    profile_id = _profile_id_from_name(display_name)
    existing = {item["id"] for item in _memory_profiles()}
    if profile_id in existing:
        return {"ok": False, "error": f"Profile already exists: {profile_id}"}
    profile = {
        "id": profile_id,
        "display_name": display_name,
        "role": payload.role,
        "age_group": payload.age_group,
        "relationship": _safe_text(payload.relationship, 120) if payload.relationship else None,
        "persona_mode": payload.persona_mode or _default_persona_mode(payload.role, payload.age_group),
        "communication_style": payload.communication_style
        or _default_communication_style(payload.role, payload.age_group),
        "status": payload.status,
        "cloud_approved": bool(payload.cloud_approved and payload.role in {"parent", "adult"}),
        "memory_file": f"data/memories/{profile_id}.md",
        "aliases": [_safe_text(alias, 80) for alias in payload.aliases[:8]],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": source,
    }
    profiles = _read_dynamic_profiles()
    profiles.append(profile)
    _write_dynamic_profiles(profiles)
    _log_event(
        "profile_created",
        f"Created {profile['status']} profile for {profile['display_name']}.",
        actor="parent" if source == "parent" else "reachy",
        profile=profile["id"],
        details={
            "profile_id": profile["id"],
            "source": source,
            "role": profile["role"],
            "age_group": profile["age_group"],
        },
    )
    return {"ok": True, "profile": profile}


def _create_profile_from_introduction(payload: ProfileIntroductionRequest) -> dict[str, Any]:
    name = _extract_introduced_name(payload.utterance)
    if not name:
        return {"ok": False, "error": "Could not identify the introduced name."}
    result = _create_memory_profile(
        ProfileCreateRequest(
            display_name=name,
            role="guest",
            age_group="unknown",
            relationship="introduced to Reachy",
            status="pending",
            aliases=[name],
            cloud_approved=False,
        ),
        "voice_introduction",
    )
    if result.get("ok"):
        _log_event(
            "profile_introduction",
            f"Reachy heard an introduction for {name}.",
            actor="reachy",
            profile=result["profile"]["id"],
            details={
                "utterance": payload.utterance,
                "introduced_by": payload.introduced_by,
                "profile_id": result["profile"]["id"],
            },
        )
    return result


def _read_dynamic_profiles() -> list[dict[str, Any]]:
    path = _profiles_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    profiles = data.get("profiles") if isinstance(data, dict) else []
    return [item for item in profiles if isinstance(item, dict) and item.get("id")]


def _write_dynamic_profiles(profiles: list[dict[str, Any]]) -> None:
    path = _profiles_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"profiles": profiles}, indent=2, sort_keys=True), encoding="utf-8")


def _profiles_path() -> Path:
    return ROOT_DIR / ".state" / "profiles.json"


def _profile_id_from_name(name: str) -> str:
    lowered = name.strip().lower()
    safe = "".join(ch if ch.isalnum() else "_" for ch in lowered).strip("_")
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe[:50] or f"profile_{uuid.uuid4().hex[:8]}"


def _profile_policy_violation(name: str) -> str | None:
    if _memory_policy_violation(name):
        return "Profile name looks unsafe."
    if len(name.split()) > 4:
        return "Profile display name is too long."
    return None


def _extract_introduced_name(utterance: str) -> str | None:
    text = " ".join(utterance.replace(",", " ").replace(".", " ").split())
    lowered = text.lower()
    markers = ("this is ", "meet ", "say hi to ", "i am ", "i'm ")
    for marker in markers:
        index = lowered.find(marker)
        if index >= 0:
            raw = text[index + len(marker) :].strip()
            words = []
            for word in raw.split():
                clean = "".join(ch for ch in word if ch.isalpha() or ch in {"'", "-"})
                if not clean:
                    break
                if clean.lower() in {"and", "from", "with", "today", "here"}:
                    break
                words.append(clean)
                if len(words) >= 2:
                    break
            if words:
                return " ".join(word[:1].upper() + word[1:] for word in words)
    return None


def _default_persona_mode(role: str, age_group: str) -> str:
    if role == "child" or age_group == "child":
        return "playful_coach"
    if role in {"parent", "adult"} or age_group == "adult":
        return "eager_assistant"
    return "friendly_limited"


def _default_communication_style(role: str, age_group: str) -> str:
    if role == "child" or age_group == "child":
        return "short, playful, encouraging, hints before answers"
    if role in {"parent", "adult"} or age_group == "adult":
        return "concise, helpful, operational, proactive"
    return "friendly, simple, conservative with memory"


def _normalize_profile(profile: str | None) -> str | None:
    if not profile:
        return None
    lowered = profile.strip().lower()
    for item in _memory_profiles():
        names = {str(item["id"]).lower(), str(item["display_name"]).lower()}
        names.update(str(alias).lower() for alias in item.get("aliases", []))
        if lowered in names:
            return str(item["id"])
    return lowered


def _profile_display_name(profile: str | None) -> str:
    normalized = _normalize_profile(profile)
    for item in _memory_profiles():
        if item["id"] == normalized:
            return str(item["display_name"])
    return normalized or "Someone"


def _create_memory_proposal(payload: MemoryProposalRequest, source: str) -> dict[str, Any]:
    profile = _normalize_profile(payload.profile)
    if not _profile_allowed(profile):
        return {"ok": False, "error": f"Unknown memory profile: {payload.profile}"}
    violation = _memory_policy_violation(payload.proposed_memory)
    if violation:
        return {"ok": False, "kind": "policy", "error": violation}
    proposal = {
        "id": f"mem_{uuid.uuid4().hex[:12]}",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "profile": profile,
        "display_name": _profile_display_name(profile),
        "proposed_memory": _safe_memory_text(payload.proposed_memory),
        "reason": _safe_text(payload.reason, 500) if payload.reason else None,
        "source": source,
        "source_event_ids": [_safe_text(item, 80) for item in payload.source_event_ids[:12]],
        "status": "pending",
        "review_note": None,
        "write_result": None,
    }
    proposals = _read_memory_proposals()
    proposals.append(proposal)
    _write_memory_proposals(proposals)
    _log_event(
        "memory_proposed",
        f"Proposed a memory for {proposal['display_name']}.",
        actor="reachy",
        profile=profile,
        details={"proposal_id": proposal["id"], "memory": proposal["proposed_memory"], "source": source},
    )
    return {"ok": True, "proposal": proposal}


def _generate_memory_proposals(payload: MemoryProposalGenerateRequest) -> dict[str, Any]:
    events = _read_events(payload.limit)
    existing_event_ids = {
        event_id for proposal in _read_memory_proposals() for event_id in proposal.get("source_event_ids", [])
    }
    created: list[dict[str, Any]] = []
    requested_profile = _normalize_profile(payload.profile)

    for event in reversed(events):
        event_id = event.get("id")
        if not event_id or event_id in existing_event_ids:
            continue
        profile = _normalize_profile(event.get("profile"))
        if requested_profile and profile != requested_profile:
            continue
        proposal_text = _proposal_from_event(event, profile)
        if not profile or not proposal_text:
            continue
        result = _create_memory_proposal(
            MemoryProposalRequest(
                profile=profile,
                proposed_memory=proposal_text,
                reason=f"Suggested from {event.get('event_type')} on {event.get('timestamp')}.",
                source_event_ids=[str(event_id)],
            ),
            "event_summarizer",
        )
        if result.get("ok"):
            created.append(result["proposal"])
            existing_event_ids.add(event_id)

    return {"ok": True, "created": created, "count": len(created), "stats": _memory_proposal_stats()}


def _proposal_from_event(event: dict[str, Any], profile: str | None) -> str | None:
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    name = _profile_display_name(profile)
    event_type = event.get("event_type")

    if event_type == "shown_image":
        caption = _safe_text(details.get("caption") or event.get("summary") or "an image", 180)
        image = details.get("image") if isinstance(details.get("image"), dict) else {}
        suffix = f" Saved image: {image.get('url')}." if image.get("url") else ""
        return f'{name} showed Reachy an image described as "{caption}".{suffix}'
    if event_type == "image":
        prompt = _safe_text(details.get("prompt") or event.get("summary") or "", 180)
        if prompt:
            return f'{name} asked Reachy to make an image about "{prompt}".'
    if event_type in {"task", "reason"}:
        prompt = _safe_text(details.get("prompt") or "", 180)
        lowered = prompt.lower()
        interest_words = ("minecraft", "roblox", "game", "drawing", "draw", "spelling", "reading", "math", "story")
        if prompt and any(word in lowered for word in interest_words):
            return f'{name} asked Reachy for help or play around "{prompt}".'
    return None


def _approve_memory_proposal(proposal_id: str, payload: MemoryProposalActionRequest) -> dict[str, Any]:
    proposals = _read_memory_proposals()
    index, proposal = _find_memory_proposal(proposals, proposal_id)
    if proposal is None:
        return {"ok": False, "error": f"Memory proposal not found: {proposal_id}"}
    if proposal.get("status") != "pending":
        return {"ok": False, "error": f"Memory proposal is already {proposal.get('status')}."}
    if payload.proposed_memory is not None:
        proposal["proposed_memory"] = _safe_memory_text(payload.proposed_memory)
        proposal["edited_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    violation = _memory_policy_violation(str(proposal.get("proposed_memory") or ""))
    if violation:
        return {"ok": False, "kind": "policy", "error": violation}

    write_result = {"ok": True, "skipped": True, "reason": "write_to_jetson=false"}
    if payload.write_to_jetson:
        write_result = _append_profile_memory(str(proposal["profile"]), str(proposal["proposed_memory"]))
        if not write_result.get("ok"):
            return {
                "ok": False,
                "error": "Could not write approved memory to the Jetson profile.",
                "write_result": write_result,
            }

    proposal["status"] = "approved"
    proposal["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    proposal["reviewed_at"] = proposal["updated_at"]
    proposal["review_note"] = _safe_text(payload.note, 500) if payload.note else None
    proposal["write_result"] = write_result
    proposals[index] = proposal
    _write_memory_proposals(proposals)
    _log_event(
        "memory_approved",
        f"Approved a memory for {proposal.get('display_name') or proposal.get('profile')}.",
        actor="parent",
        profile=str(proposal.get("profile")),
        details={"proposal_id": proposal["id"], "write_result": write_result, "note": payload.note},
    )
    return {"ok": True, "proposal": proposal}


def _reject_memory_proposal(proposal_id: str, payload: MemoryProposalActionRequest) -> dict[str, Any]:
    proposals = _read_memory_proposals()
    index, proposal = _find_memory_proposal(proposals, proposal_id)
    if proposal is None:
        return {"ok": False, "error": f"Memory proposal not found: {proposal_id}"}
    proposal["status"] = "rejected"
    proposal["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    proposal["reviewed_at"] = proposal["updated_at"]
    proposal["review_note"] = _safe_text(payload.note, 500) if payload.note else None
    proposals[index] = proposal
    _write_memory_proposals(proposals)
    _log_event(
        "memory_rejected",
        f"Rejected a memory for {proposal.get('display_name') or proposal.get('profile')}.",
        actor="parent",
        profile=str(proposal.get("profile")),
        details={"proposal_id": proposal["id"], "note": payload.note},
    )
    return {"ok": True, "proposal": proposal}


def _delete_memory_proposal(proposal_id: str, payload: MemoryProposalActionRequest) -> dict[str, Any]:
    proposals = _read_memory_proposals()
    index, proposal = _find_memory_proposal(proposals, proposal_id)
    if proposal is None:
        return {"ok": False, "error": f"Memory proposal not found: {proposal_id}"}
    proposal["status"] = "deleted"
    proposal["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    proposal["reviewed_at"] = proposal["updated_at"]
    proposal["review_note"] = _safe_text(payload.note, 500) if payload.note else "Deleted from parent review."
    proposals[index] = proposal
    _write_memory_proposals(proposals)
    _log_event(
        "memory_deleted",
        f"Deleted a memory proposal for {proposal.get('display_name') or proposal.get('profile')}.",
        actor="parent",
        profile=str(proposal.get("profile")),
        details={"proposal_id": proposal["id"], "note": payload.note},
    )
    return {"ok": True, "proposal": proposal}


def _find_memory_proposal(proposals: list[dict[str, Any]], proposal_id: str) -> tuple[int, dict[str, Any] | None]:
    for index, proposal in enumerate(proposals):
        if proposal.get("id") == proposal_id:
            return index, proposal
    return -1, None


def _read_memory_proposals() -> list[dict[str, Any]]:
    path = _memory_proposals_path()
    if not path.exists():
        return []
    proposals: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("id"):
                proposals.append(item)
    return proposals


def _write_memory_proposals(proposals: list[dict[str, Any]]) -> None:
    path = _memory_proposals_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for proposal in proposals:
            handle.write(json.dumps(proposal, sort_keys=True) + "\n")
    temp.replace(path)


def _memory_proposal_stats() -> dict[str, Any]:
    counts: dict[str, int] = {}
    by_profile: dict[str, int] = {}
    for proposal in _read_memory_proposals():
        status = str(proposal.get("status") or "unknown")
        profile = str(proposal.get("profile") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        by_profile[profile] = by_profile.get(profile, 0) + 1
    return {
        "total": sum(counts.values()),
        "by_status": counts,
        "by_profile": by_profile,
        "path": str(_memory_proposals_path()),
    }


def _memory_proposals_path() -> Path:
    return ROOT_DIR / ".state" / "memory-proposals.jsonl"


def _profile_allowed(profile: str | None) -> bool:
    return profile in {str(item["id"]) for item in _memory_profiles()}


def _safe_memory_text(text: str) -> str:
    return " ".join(_safe_text(text, 500).split())


def _memory_policy_violation(text: str) -> str | None:
    lowered = text.lower()
    blocked_markers = (
        "ignore previous instructions",
        "system prompt",
        "developer message",
        "api key",
        "apikey",
        "password",
        "secret",
        "token",
        "authorization",
        "authorized_keys",
        ".ssh",
        "curl ",
        "rm -rf",
    )
    if any(marker in lowered for marker in blocked_markers):
        return "Memory text looks like a secret, credential, shell command, or prompt-injection attempt."
    if len(text.split()) > 90:
        return "Memory text is too long for a stable profile fact. Keep it short and specific."
    return None


def _append_profile_memory(profile: str, memory: str) -> dict[str, Any]:
    profile = _normalize_profile(profile) or ""
    if not _profile_allowed(profile):
        return {"ok": False, "error": f"Unknown memory profile: {profile}"}
    if _memory_policy_violation(memory):
        return {"ok": False, "error": _memory_policy_violation(memory)}
    if not Path(settings.jetson_ssh_key).exists():
        return {"ok": False, "error": f"Jetson SSH key is missing: {settings.jetson_ssh_key}"}

    remote_payload = {
        "project": settings.jetson_project,
        "profile": profile,
        "memory": _safe_memory_text(memory),
        "date": time.strftime("%Y-%m-%d"),
        "memory_files": {item["id"]: item["memory_file"] for item in _memory_profiles()},
    }
    remote_script = r"""
import json
import pathlib
import sys

data = json.loads(sys.stdin.read())
project = pathlib.Path(data["project"]).expanduser().resolve()
profile = data["profile"]
memory_files = data["memory_files"]
if profile not in memory_files:
    raise SystemExit(f"unknown profile: {profile}")
target = (project / memory_files[profile]).resolve()
if not str(target).startswith(str(project)):
    raise SystemExit("memory path escaped project")
target.parent.mkdir(parents=True, exist_ok=True)
existing = target.read_text(encoding="utf-8") if target.exists() else f"# {profile}\n"
heading = "## Parent-approved memories"
if heading not in existing:
    if not existing.endswith("\n"):
        existing += "\n"
    existing += f"\n{heading}\n"
line = f"- {data['date']}: {data['memory']}\n"
target.write_text(existing.rstrip() + "\n" + line, encoding="utf-8")
print(json.dumps({"ok": True, "path": str(target)}))
"""
    destination = f"{settings.jetson_user}@{settings.jetson_host}"
    cmd = [
        "ssh",
        "-i",
        settings.jetson_ssh_key,
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={int(settings.jetson_ssh_timeout_seconds)}",
        destination,
        f"python3 -c {shlex.quote(remote_script)}",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=json.dumps(remote_payload),
            capture_output=True,
            text=True,
            timeout=settings.jetson_ssh_timeout_seconds + 3,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - returned for parent UI.
        return {"ok": False, "error": str(exc), "destination": destination}
    if result.returncode != 0:
        return {
            "ok": False,
            "returncode": result.returncode,
            "error": (result.stderr or result.stdout).strip()[:1_000],
            "destination": destination,
        }
    try:
        data = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {"ok": False, "error": "Jetson memory writer returned invalid JSON.", "stdout": result.stdout[:1_000]}
    data["destination"] = destination
    return data


def _family_board() -> dict[str, Any]:
    path = _family_board_path()
    if not path.exists():
        return {"events": [], "chores": [], "updated_at": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"events": [], "chores": [], "updated_at": None}
    return {
        "events": [item for item in data.get("events", []) if isinstance(item, dict)],
        "chores": [item for item in data.get("chores", []) if isinstance(item, dict)],
        "updated_at": data.get("updated_at"),
    }


def _write_family_board(board: dict[str, Any]) -> None:
    path = _family_board_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    board["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    path.write_text(json.dumps(board, indent=2, sort_keys=True), encoding="utf-8")


def _family_board_path() -> Path:
    return ROOT_DIR / ".state" / "family-board.json"


def _create_family_event(payload: FamilyEventRequest) -> dict[str, Any]:
    title = _safe_text(payload.title, 160).strip()
    if _memory_policy_violation(title):
        return {"ok": False, "error": "Event title looks unsafe."}
    profiles = [_normalize_profile(item) or item for item in payload.profiles[:8]]
    event = {
        "id": f"evt_{uuid.uuid4().hex[:10]}",
        "title": title,
        "date": _safe_text(payload.date, 40),
        "end_date": _safe_text(payload.end_date, 40) if payload.end_date else None,
        "category": _safe_text(payload.category, 60),
        "profiles": profiles,
        "parent_only": bool(payload.parent_only),
        "notes": _safe_text(payload.notes, 500) if payload.notes else None,
        "source": "local_parent",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": "active",
    }
    board = _family_board()
    board["events"].append(event)
    _write_family_board(board)
    _log_event(
        "family_event_created",
        f"Added family event: {title}.",
        actor="parent",
        details={"event_id": event["id"], "category": event["category"], "profiles": profiles},
    )
    return {"ok": True, "event": event, "board": board}


def _delete_family_event(event_id: str) -> dict[str, Any]:
    board = _family_board()
    for event in board["events"]:
        if event.get("id") == event_id:
            event["status"] = "deleted"
            event["deleted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            _write_family_board(board)
            _log_event(
                "family_event_deleted",
                f"Deleted family event: {event.get('title')}.",
                actor="parent",
                details={"event_id": event_id},
            )
            return {"ok": True, "event": event, "board": board}
    return {"ok": False, "error": f"Family event not found: {event_id}"}


def _create_chore(payload: ChoreRequest) -> dict[str, Any]:
    assigned_to = _normalize_profile(payload.assigned_to)
    if not _profile_allowed(assigned_to):
        return {"ok": False, "error": f"Unknown assigned profile: {payload.assigned_to}"}
    title = _safe_text(payload.title, 160).strip()
    if _memory_policy_violation(title):
        return {"ok": False, "error": "Chore title looks unsafe."}
    chore = {
        "id": f"chr_{uuid.uuid4().hex[:10]}",
        "title": title,
        "assigned_to": assigned_to,
        "cadence": _safe_text(payload.cadence, 60),
        "parent_approval_required": bool(payload.parent_approval_required),
        "reward": _safe_text(payload.reward, 160) if payload.reward else None,
        "notes": _safe_text(payload.notes, 500) if payload.notes else None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": "active",
        "completions": [],
    }
    board = _family_board()
    board["chores"].append(chore)
    _write_family_board(board)
    _log_event(
        "chore_created",
        f"Added chore: {title}.",
        actor="parent",
        profile=assigned_to,
        details={"chore_id": chore["id"], "cadence": chore["cadence"]},
    )
    return {"ok": True, "chore": chore, "board": board}


def _complete_chore(chore_id: str, payload: ChoreCompleteRequest) -> dict[str, Any]:
    board = _family_board()
    for chore in board["chores"]:
        if chore.get("id") == chore_id:
            completion = {
                "id": f"done_{uuid.uuid4().hex[:10]}",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "actor": _safe_text(payload.actor, 80),
                "note": _safe_text(payload.note, 500) if payload.note else None,
                "approved_by_parent": bool(payload.approved_by_parent),
                "status": "approved"
                if payload.approved_by_parent or not chore.get("parent_approval_required")
                else "needs_parent",
            }
            chore.setdefault("completions", []).append(completion)
            _write_family_board(board)
            _log_event(
                "chore_completed",
                f"Chore marked complete: {chore.get('title')}.",
                actor=completion["actor"],
                profile=str(chore.get("assigned_to")),
                details={"chore_id": chore_id, "completion": completion},
            )
            return {"ok": True, "chore": chore, "completion": completion, "board": board}
    return {"ok": False, "error": f"Chore not found: {chore_id}"}


def _artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix == ".json":
        return "json"
    if suffix in {".js", ".css"}:
        return suffix.lstrip(".")
    return "text"


def _log_event(
    event_type: str,
    summary: str,
    *,
    actor: str = "reachy",
    profile: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "id": uuid.uuid4().hex[:12],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event_type": event_type,
        "summary": _safe_text(summary, 500),
        "actor": _safe_text(actor, 80),
        "profile": _safe_text(profile, 80) if profile else None,
        "details": _sanitize_for_log(details or {}),
    }
    path = _event_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return event


def _read_events(limit: int = 100, *, event_type: str | None = None) -> list[dict[str, Any]]:
    path = _event_log_path()
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_type and event.get("event_type") != event_type:
                continue
            rows.append(event)
    return rows[-limit:][::-1]


def _event_stats() -> dict[str, Any]:
    path = _event_log_path()
    counts: dict[str, int] = {}
    total = 0
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                total += 1
                key = str(event.get("event_type") or "unknown")
                counts[key] = counts.get(key, 0) + 1
    return {"total": total, "by_type": counts, "path": str(path)}


def _event_log_path() -> Path:
    return ROOT_DIR / ".state" / "events.jsonl"


def _ingest_jetson_event(payload: JetsonEvent) -> dict[str, Any]:
    data = payload.model_dump(mode="json")
    details: dict[str, Any] = {"protocol": data}
    if isinstance(payload, LatencySampleEvent):
        details.update(
            {
                "duration_ms": payload.duration_ms,
                "timings_ms": {payload.stage: payload.duration_ms},
                "route": payload.route,
                "model": payload.model,
            }
        )
    if isinstance(payload, MotionBlockedEvent):
        details["gesture"] = payload.gesture
        details["reason"] = payload.reason
    event = _log_event(
        str(data["type"]),
        _jetson_event_summary(payload),
        actor="jetson",
        profile=data.get("profile"),
        details=details,
    )
    return {"event": event, "protocol": data}


def _jetson_event_summary(payload: JetsonEvent) -> str:
    event_type = payload.type
    if hasattr(payload, "text"):
        text = getattr(payload, "text")
        return f"Jetson {event_type}: {_safe_text(text, 120)}"
    if isinstance(payload, LatencySampleEvent):
        return f"Jetson latency {payload.stage}: {payload.duration_ms} ms."
    if isinstance(payload, MotionBlockedEvent):
        return f"Jetson blocked motion {payload.gesture}: {payload.reason}."
    if hasattr(payload, "target_id"):
        target = getattr(payload, "target_id") or event_type
        return f"Jetson saw {target}."
    if hasattr(payload, "gesture"):
        return f"Jetson motion event: {getattr(payload, 'gesture')}."
    return f"Jetson event: {event_type}."


def _behavior_gesture_inventory() -> dict[str, Any]:
    engine = BehaviorEngine(FakeReachyAdapter(SafetyPolicy(min_interval_ms=0)))
    return {
        "gesture_names": engine.gesture_names(),
        "policy": {
            "named_gestures_only": True,
            "raw_motor_commands_allowed": False,
            "real_motion_enabled": False,
        },
    }


def _behavior_dry_run(payload: BehaviorDryRunRequest) -> dict[str, Any]:
    engine = BehaviorEngine(FakeReachyAdapter(SafetyPolicy(min_interval_ms=0)))
    results: list[dict[str, Any]] = []
    for raw_event in payload.events:
        event = validate_jetson_event(raw_event)
        results.append(engine.process_event(event))
    for raw_action in payload.actions:
        action = validate_mac_action(raw_action)
        _validate_safe_action(action)
        results.append(engine.process_action(action))
    event = _log_event(
        "behavior_dry_run",
        f"Behavior dry run produced {len(engine.adapter.timeline)} motion timeline entries.",
        details={"motion_count": len(engine.adapter.timeline), "state": engine.state.model_dump()},
    )
    return {
        "ok": True,
        "state": engine.state.model_dump(),
        "results": results,
        "timeline": engine.adapter.export_timeline(),
        "event": event,
    }


def _enqueue_jetson_action(payload: MacAction) -> dict[str, Any]:
    try:
        _validate_safe_action(payload)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    action = payload.model_dump(mode="json")
    now_ms = int(time.time() * 1000)
    record = {
        "id": action["message_id"],
        "status": "queued",
        "action": action,
        "created_at_ms": now_ms,
        "expires_at_ms": now_ms + 30_000,
    }
    _append_jetson_action_record(record)
    event = _log_event(
        "jetson_action_queued",
        f"Queued Jetson action: {action['type']}.",
        actor="mac",
        profile=action.get("profile"),
        details={"action": action, "status": "queued"},
    )
    return {"ok": True, "action": record, "event": event}


def _validate_safe_action(payload: MacAction) -> None:
    engine = BehaviorEngine(FakeReachyAdapter(SafetyPolicy(min_interval_ms=0)))
    if isinstance(payload, GestureAction):
        engine.command_for_gesture(
            payload.gesture,
            intensity=payload.intensity,
            duration_ms=payload.duration_ms,
            reason=payload.reason or "validate",
        )
    if isinstance(payload, StoryBeatAction):
        engine.command_for_gesture(payload.gesture, reason="validate_story_beat")
        _validate_screen_payload(payload.screen.model_dump())
    if hasattr(payload, "screen"):
        screen = getattr(payload, "screen")
        if screen is not None and not isinstance(payload, StoryBeatAction):
            _validate_screen_payload(screen.model_dump())


def _validate_screen_payload(screen: dict[str, Any]) -> None:
    url = screen.get("url")
    if url and not _url_allowed(str(url)):
        raise ValueError("screen_url_not_allowlisted")


def _pending_jetson_actions(limit: int = 20) -> list[dict[str, Any]]:
    now_ms = int(time.time() * 1000)
    latest = _latest_jetson_actions()
    pending = [
        item
        for item in latest.values()
        if item.get("status") == "queued" and int(item.get("expires_at_ms") or 0) >= now_ms
    ]
    pending.sort(key=lambda item: int(item.get("created_at_ms") or 0))
    return pending[:limit]


def _ack_jetson_action(action_id: str, payload: JetsonActionAckRequest) -> dict[str, Any]:
    latest = _latest_jetson_actions()
    current = latest.get(action_id)
    if not current:
        return {"ok": False, "error": "action_not_found"}
    record = {
        "id": action_id,
        "status": payload.status,
        "note": _safe_text(payload.note, 500) if payload.note else None,
        "ack_at_ms": int(time.time() * 1000),
    }
    _append_jetson_action_record(record)
    event = _log_event(
        "jetson_action_ack",
        f"Jetson action {action_id} marked {payload.status}.",
        actor="jetson",
        profile=(current.get("action") or {}).get("profile") if isinstance(current.get("action"), dict) else None,
        details={"id": action_id, "status": payload.status, "note": payload.note},
    )
    updated = _latest_jetson_actions().get(action_id, record)
    return {"ok": True, "action": updated, "event": event}


def _append_jetson_action_record(record: dict[str, Any]) -> None:
    path = _jetson_actions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_sanitize_for_log(record), sort_keys=True) + "\n")


def _latest_jetson_actions() -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    path = _jetson_actions_path()
    if not path.exists():
        return latest
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            action_id = str(record.get("id") or "")
            if not action_id:
                continue
            previous = latest.get(action_id, {})
            merged = {**previous, **record}
            if "action" not in merged and "action" in previous:
                merged["action"] = previous["action"]
            if "created_at_ms" not in merged and "created_at_ms" in previous:
                merged["created_at_ms"] = previous["created_at_ms"]
            if "expires_at_ms" not in merged and "expires_at_ms" in previous:
                merged["expires_at_ms"] = previous["expires_at_ms"]
            latest[action_id] = merged
    return latest


def _jetson_actions_path() -> Path:
    return ROOT_DIR / ".state" / "jetson-actions.jsonl"


def _latency_analytics(limit: int = 500) -> dict[str, Any]:
    events = _read_events(limit)
    stages: dict[str, list[int]] = {}
    for event in events:
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        event_type = str(event.get("event_type") or "unknown")
        if isinstance(details.get("duration_ms"), int):
            stages.setdefault(event_type, []).append(int(details["duration_ms"]))
        timings = details.get("timings_ms")
        if isinstance(timings, dict):
            for stage, value in timings.items():
                if isinstance(value, (int, float)):
                    stages.setdefault(str(stage), []).append(int(value))
    return {
        "samples": sum(len(items) for items in stages.values()),
        "stages": {stage: _duration_summary(values) for stage, values in sorted(stages.items())},
        "target_ms": {
            "kid_first_audio": 1500,
            "stretch_first_audio": 1000,
            "tool_ack": 2500,
        },
    }


def _routing_analytics(limit: int = 500) -> dict[str, Any]:
    events = _read_events(limit)
    by_model: dict[str, dict[str, Any]] = {}
    by_tool: dict[str, int] = {}
    failures: list[dict[str, Any]] = []
    for event in events:
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        model = details.get("model")
        if isinstance(model, str) and model:
            bucket = by_model.setdefault(model, {"count": 0, "durations_ms": [], "event_types": {}})
            bucket["count"] += 1
            event_type = str(event.get("event_type") or "unknown")
            bucket["event_types"][event_type] = bucket["event_types"].get(event_type, 0) + 1
            if isinstance(details.get("duration_ms"), int):
                bucket["durations_ms"].append(int(details["duration_ms"]))
        for tool in details.get("tool_names") or []:
            if tool:
                by_tool[str(tool)] = by_tool.get(str(tool), 0) + 1
        if event.get("event_type") in {"task_error", "image_error", "tool_error", "cloud_blocked", "screen_blocked"}:
            failures.append(
                {
                    "timestamp": event.get("timestamp"),
                    "event_type": event.get("event_type"),
                    "summary": event.get("summary"),
                    "model": model,
                    "error": details.get("error"),
                }
            )
    return {
        "models": {
            model: {
                "count": data["count"],
                "latency": _duration_summary(data["durations_ms"]),
                "event_types": data["event_types"],
            }
            for model, data in sorted(by_model.items())
        },
        "tools": dict(sorted(by_tool.items())),
        "recent_failures": failures[:12],
    }


def _parent_report(limit: int = 500) -> dict[str, Any]:
    events = _read_events(limit)
    counts: dict[str, int] = {}
    profiles: dict[str, int] = {}
    websites: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    games: list[dict[str, Any]] = []
    models: dict[str, int] = {}
    for event in events:
        event_type = str(event.get("event_type") or "unknown")
        counts[event_type] = counts.get(event_type, 0) + 1
        profile = event.get("profile") or "unknown"
        profiles[str(profile)] = profiles.get(str(profile), 0) + 1
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        if isinstance(details.get("model"), str):
            models[details["model"]] = models.get(details["model"], 0) + 1
        if event_type in {"screen_open", "screen_blocked", "youtube_search"}:
            url = (
                details.get("url") or (details.get("arguments") or {}).get("url")
                if isinstance(details.get("arguments"), dict)
                else details.get("url")
            )
            websites.append(
                {
                    "timestamp": event.get("timestamp"),
                    "event_type": event_type,
                    "url": url,
                    "summary": event.get("summary"),
                }
            )
        if event_type in {"image", "shown_image"}:
            image = details.get("image") if isinstance(details.get("image"), dict) else {}
            images.append(
                {
                    "timestamp": event.get("timestamp"),
                    "profile": event.get("profile"),
                    "summary": event.get("summary"),
                    "url": image.get("url"),
                }
            )
        if event_type in {"artifact", "task"}:
            prompt = str(details.get("prompt") or "").lower()
            artifact_data = details.get("artifact") if isinstance(details.get("artifact"), dict) else {}
            if "game" in prompt or artifact_data.get("kind") == "html":
                games.append(
                    {
                        "timestamp": event.get("timestamp"),
                        "summary": event.get("summary"),
                        "url": artifact_data.get("url"),
                        "model": details.get("model"),
                    }
                )
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event_counts": counts,
        "profile_counts": profiles,
        "model_counts": models,
        "websites": websites[:20],
        "images": images[:20],
        "games": games[:20],
        "blocked_count": counts.get("cloud_blocked", 0) + counts.get("screen_blocked", 0),
        "summary_cards": [
            {"label": "Events", "value": len(events)},
            {"label": "Screen Opens", "value": counts.get("screen_open", 0)},
            {"label": "Images", "value": counts.get("image", 0) + counts.get("shown_image", 0)},
            {"label": "Cloud Blocks", "value": counts.get("cloud_blocked", 0)},
        ],
    }


def _duration_summary(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p50_ms": _percentile(ordered, 0.50),
        "p95_ms": _percentile(ordered, 0.95),
        "max_ms": ordered[-1],
    }


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    index = min(len(values) - 1, max(0, round((len(values) - 1) * percentile)))
    return values[index]


def _media_policy() -> dict[str, Any]:
    return {
        "base_allowlist": settings.screen_allowlist,
        "runtime_allowlist": _runtime_allowlist(),
        "effective_allowlist": _effective_allowlist(),
        "blocked": [
            {
                "id": event.get("id"),
                "timestamp": event.get("timestamp"),
                "url": (event.get("details") or {}).get("url") if isinstance(event.get("details"), dict) else None,
                "summary": event.get("summary"),
            }
            for event in _read_events(100, event_type="screen_blocked")
        ],
    }


def _allowlist_add(payload: AllowlistRequest) -> dict[str, Any]:
    normalized = _normalize_allowlist_url(payload.url)
    if not normalized:
        return {"ok": False, "error": "Only http and https URLs with a host can be allowlisted."}
    state = _read_media_policy_state()
    allowlist = state.setdefault("runtime_allowlist", [])
    if normalized not in allowlist:
        allowlist.append(normalized)
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _write_media_policy_state(state)
    _log_event(
        "screen_allowlist_added",
        f"Allowed screen URL prefix: {normalized}.",
        actor="parent",
        details={"url": normalized, "note": payload.note},
    )
    return {"ok": True, "policy": _media_policy()}


def _allowlist_remove(payload: AllowlistRequest) -> dict[str, Any]:
    normalized = _normalize_allowlist_url(payload.url)
    state = _read_media_policy_state()
    allowlist = state.setdefault("runtime_allowlist", [])
    if normalized not in allowlist:
        return {"ok": False, "error": f"Runtime allowlist entry not found: {normalized}"}
    state["runtime_allowlist"] = [item for item in allowlist if item != normalized]
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _write_media_policy_state(state)
    _log_event(
        "screen_allowlist_removed",
        f"Removed screen URL prefix: {normalized}.",
        actor="parent",
        details={"url": normalized, "note": payload.note},
    )
    return {"ok": True, "policy": _media_policy()}


def _runtime_allowlist() -> list[str]:
    return [str(item) for item in _read_media_policy_state().get("runtime_allowlist", []) if isinstance(item, str)]


def _effective_allowlist() -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for url in [*settings.screen_allowlist, *_runtime_allowlist()]:
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _read_media_policy_state() -> dict[str, Any]:
    path = _media_policy_path()
    if not path.exists():
        return {"runtime_allowlist": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"runtime_allowlist": []}
    if not isinstance(data, dict):
        return {"runtime_allowlist": []}
    data.setdefault("runtime_allowlist", [])
    return data


def _write_media_policy_state(state: dict[str, Any]) -> None:
    path = _media_policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _media_policy_path() -> Path:
    return ROOT_DIR / ".state" / "media-policy.json"


def _normalize_allowlist_url(url: str) -> str | None:
    parsed = parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    netloc = parsed.hostname.lower()
    if parsed.port:
        netloc += f":{parsed.port}"
    path = parsed.path.rstrip("/")
    return parse.urlunparse((parsed.scheme, netloc, path, "", "", ""))


def _emotion_state() -> dict[str, Any]:
    path = _emotion_state_path()
    if not path.exists():
        return {
            "mood": "curious",
            "energy": 0.55,
            "attention": 0.65,
            "confidence": 0.75,
            "gesture": "listening_idle",
            "movement_allowed": False,
            "updated_at": None,
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"mood": "curious", "gesture": "listening_idle", "movement_allowed": False}


def _emotion_simulate(payload: EmotionSimulateRequest) -> dict[str, Any]:
    gesture = _emotion_gesture(payload.mood, payload.energy, payload.confidence)
    state = {
        "profile": _normalize_profile(payload.profile),
        "display_name": _profile_display_name(payload.profile),
        "mood": _safe_text(payload.mood, 80),
        "energy": round(payload.energy, 2),
        "attention": round(payload.attention, 2),
        "confidence": round(payload.confidence, 2),
        "stimulus": _safe_text(payload.stimulus, 500) if payload.stimulus else None,
        "gesture": gesture,
        "movement_allowed": False,
        "movement_note": "Dry run only. Real movement remains blocked until hardware enumeration and tiny neutral pose pass.",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    path = _emotion_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    event = _log_event(
        "emotion_simulated", f"Emotion dry run: {gesture}.", actor="reachy", profile=state["profile"], details=state
    )
    return {"ok": True, "state": state, "event": event}


def _emotion_gesture(mood: str, energy: float, confidence: float) -> str:
    lowered = mood.lower()
    if "happy" in lowered or "excited" in lowered or energy > 0.82:
        return "celebration_bounce"
    if "confused" in lowered or confidence < 0.35:
        return "curious_tilt"
    if "sleep" in lowered or energy < 0.25:
        return "sleepy_rest"
    if "sad" in lowered or "sorry" in lowered:
        return "soft_apology"
    return "listening_idle"


def _emotion_state_path() -> Path:
    return ROOT_DIR / ".state" / "emotion-state.json"


def _gemini_live_status() -> dict[str, Any]:
    state = _read_gemini_live_state()
    today = time.strftime("%Y-%m-%d")
    used_seconds = int(state.get(today, {}).get("used_seconds", 0))
    cap_seconds = int(state.get("daily_cap_seconds", 120))
    return {
        "enabled": False,
        "prototype": "dry-run",
        "provider": "gemini",
        "model": "gemini-live",
        "configured": bool(settings.gemini_api_key),
        "auth_note": "Use Gemini API auth for Live sessions. OpenAI Realtime is not assumed available through Codex OAuth.",
        "daily_cap_seconds": cap_seconds,
        "used_seconds_today": used_seconds,
        "remaining_seconds_today": max(0, cap_seconds - used_seconds),
        "visible_indicator_required": True,
        "default_session_cap_seconds": 120,
        "note": "Gemini Live is not streaming yet. This prototype logs capped dry-run sessions for UX and budget testing.",
        "sessions": state.get("sessions", [])[-10:][::-1],
    }


def _gemini_live_session(payload: RealtimeSessionRequest) -> dict[str, Any]:
    state = _read_gemini_live_state()
    today = time.strftime("%Y-%m-%d")
    bucket = state.setdefault(today, {"used_seconds": 0})
    cap_seconds = int(state.get("daily_cap_seconds", 120))
    used = int(bucket.get("used_seconds", 0))
    seconds = min(payload.requested_seconds, 120)
    if used + seconds > cap_seconds:
        return {"ok": False, "error": "Daily Gemini Live cap would be exceeded.", "live": _gemini_live_status()}
    session = {
        "id": f"live_{uuid.uuid4().hex[:10]}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "provider": "gemini",
        "model": "gemini-live",
        "mode": payload.mode,
        "seconds": seconds,
        "dry_run": payload.dry_run,
        "note": _safe_text(payload.note, 500) if payload.note else None,
        "status": "simulated" if payload.dry_run else "blocked_not_implemented",
    }
    bucket["used_seconds"] = used + seconds
    state.setdefault("sessions", []).append(session)
    _write_gemini_live_state(state)
    _log_event("gemini_live_session", "Logged Gemini Live prototype session.", actor="parent", details=session)
    return {"ok": True, "session": session, "live": _gemini_live_status()}


def _run_gemini_live_probe(payload: GeminiLiveProbeRequest) -> dict[str, Any]:
    if not _cloud_enabled():
        return {
            "ok": False,
            "backend": "gemini-live",
            "error": "Cloud reasoning is disabled by the parent/operator control panel.",
        }
    if not settings.gemini_api_key:
        return {
            "ok": False,
            "backend": "gemini-live",
            "model": payload.model or settings.gemini_live_model,
            "error": "GEMINI_API_KEY is not configured.",
        }
    started = time.monotonic()
    try:
        import google.genai as genai  # type: ignore[import-not-found]
        from google.genai import types  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001 - setup status for parent dashboard.
        return {
            "ok": False,
            "backend": "gemini-live",
            "model": payload.model or settings.gemini_live_model,
            "error": f"google-genai is not installed or importable: {exc}",
            "install_hint": ".venv-mac-bridge/bin/pip install -r mac_bridge/requirements.txt",
        }

    async def run_probe() -> dict[str, Any]:
        model = payload.model or settings.gemini_live_model
        client = genai.Client(api_key=settings.gemini_api_key)
        config: dict[str, Any] = {"response_modalities": [payload.response_modality]}
        if payload.system:
            config["system_instruction"] = payload.system
        text_parts: list[str] = []
        audio_bytes = 0
        async with client.aio.live.connect(model=model, config=config) as session:
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=payload.prompt)])
            )
            async for message in session.receive():
                if getattr(message, "text", None):
                    text_parts.append(message.text)
                server_content = getattr(message, "server_content", None)
                model_turn = getattr(server_content, "model_turn", None) if server_content else None
                for part in getattr(model_turn, "parts", []) or []:
                    inline_data = getattr(part, "inline_data", None)
                    data = getattr(inline_data, "data", None) if inline_data else None
                    if data:
                        audio_bytes += len(data)
                if server_content and getattr(server_content, "turn_complete", False):
                    break
        return {
            "ok": True,
            "backend": "gemini-live",
            "model": model,
            "response_modality": payload.response_modality,
            "text": "".join(text_parts).strip(),
            "audio_bytes": audio_bytes,
            "duration_ms": _elapsed_ms(started),
            "note": "This is a real server-side Gemini Live connection probe, not a dry-run counter.",
        }

    try:
        return asyncio.run(asyncio.wait_for(run_probe(), timeout=settings.gemini_live_timeout_seconds))
    except Exception as exc:  # noqa: BLE001 - returned to local caller and logged.
        return {
            "ok": False,
            "backend": "gemini-live",
            "model": payload.model or settings.gemini_live_model,
            "duration_ms": _elapsed_ms(started),
            "error": str(exc),
        }


def _read_gemini_live_state() -> dict[str, Any]:
    path = _gemini_live_path()
    if not path.exists():
        return {"daily_cap_seconds": 120, "sessions": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"daily_cap_seconds": 120, "sessions": []}
    if not isinstance(data, dict):
        return {"daily_cap_seconds": 120, "sessions": []}
    data.setdefault("daily_cap_seconds", 120)
    data.setdefault("sessions", [])
    return data


def _write_gemini_live_state(state: dict[str, Any]) -> None:
    path = _gemini_live_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _gemini_live_path() -> Path:
    return ROOT_DIR / ".state" / "gemini-live.json"


def _sanitize_for_log(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_for_log(item) for key, item in value.items() if _log_key_allowed(str(key))}
    if isinstance(value, list):
        return [_sanitize_for_log(item) for item in value[:30]]
    if isinstance(value, tuple):
        return [_sanitize_for_log(item) for item in value[:30]]
    if isinstance(value, str):
        return _safe_text(value, 2_000)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _safe_text(str(value), 500)


def _log_key_allowed(key: str) -> bool:
    lowered = key.lower()
    blocked = ("api_key", "apikey", "authorization", "token", "password", "secret", "credential")
    return not any(item in lowered for item in blocked)


def _safe_text(value: str | None, limit: int) -> str:
    text = "" if value is None else str(value)
    replacements = (
        (settings.ollama_api_key, "[redacted-ollama-key]"),
        (settings.gemini_api_key, "[redacted-gemini-key]"),
        (settings.openai_api_key, "[redacted-openai-key]"),
    )
    for secret, marker in replacements:
        if secret:
            text = text.replace(secret, marker)
    text = text.replace("\x00", "")
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _run_hermes(payload: ReasonRequest) -> dict[str, Any]:
    if not _cloud_enabled():
        return {
            "ok": False,
            "backend": "hermes",
            "error": "Cloud reasoning is disabled by the parent/operator control panel.",
        }
    hermes_path = shutil.which(settings.hermes_bin)
    if not hermes_path:
        return {"ok": False, "backend": "hermes", "error": "Hermes CLI not found"}

    prompt = _compose_prompt(payload)
    try:
        result = subprocess.run(
            [hermes_path, "chat", "-Q", "--source", "tool", "-q", prompt],
            capture_output=True,
            text=True,
            timeout=settings.hermes_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "backend": "hermes", "error": "Hermes timed out"}
    except OSError as exc:
        return {"ok": False, "backend": "hermes", "error": str(exc)}

    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0 or not output:
        return {
            "ok": False,
            "backend": "hermes",
            "returncode": result.returncode,
            "error": output[:2_000] or "Hermes returned no text",
        }
    return {"ok": True, "backend": "hermes", "text": output}


def _run_codex_reason(payload: ReasonRequest) -> dict[str, Any]:
    if not _cloud_enabled():
        return {
            "ok": False,
            "backend": "codex",
            "error": "Cloud reasoning is disabled by the parent/operator control panel.",
        }
    codex_path = shutil.which(settings.codex_bin)
    if not codex_path:
        return {
            "ok": False,
            "backend": "codex",
            "model": payload.model or settings.codex_default_model,
            "error": "Codex CLI not found",
        }

    model = payload.model or settings.codex_default_model
    effort = payload.reasoning_effort or settings.codex_default_reasoning_effort
    prompt = _compose_prompt(payload)
    with tempfile.NamedTemporaryFile(prefix="reachy-codex-", suffix=".txt", delete=False) as handle:
        output_path = Path(handle.name)

    cmd = [
        codex_path,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--cd",
        str(ROOT_DIR.parent),
        "--model",
        model,
        "--config",
        f'model_reasoning_effort="{effort}"',
        "--output-last-message",
        str(output_path),
        prompt,
    ]
    started = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=settings.codex_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        output_path.unlink(missing_ok=True)
        return {
            "ok": False,
            "backend": "codex",
            "model": model,
            "reasoning_effort": effort,
            "error": "Codex timed out",
        }
    except OSError as exc:
        output_path.unlink(missing_ok=True)
        return {"ok": False, "backend": "codex", "model": model, "reasoning_effort": effort, "error": str(exc)}

    output = ""
    if output_path.exists():
        output = output_path.read_text(encoding="utf-8", errors="replace").strip()
        output_path.unlink(missing_ok=True)
    if result.returncode != 0 or not output:
        return {
            "ok": False,
            "backend": "codex",
            "model": model,
            "reasoning_effort": effort,
            "returncode": result.returncode,
            "error": (result.stderr or result.stdout or "Codex returned no text").strip()[:2_000],
            "duration_ms": _elapsed_ms(started),
        }
    return {
        "ok": True,
        "backend": "codex",
        "model": model,
        "reasoning_effort": effort,
        "text": output,
        "duration_ms": _elapsed_ms(started),
    }


def _run_openai_reason(payload: ReasonRequest) -> dict[str, Any]:
    if not _cloud_enabled():
        return {
            "ok": False,
            "backend": "openai",
            "error": "Cloud reasoning is disabled by the parent/operator control panel.",
        }
    if not settings.openai_api_key:
        return {
            "ok": False,
            "backend": "openai",
            "model": payload.model or settings.openai_default_model,
            "error": "OPENAI_API_KEY is not configured.",
        }
    model = payload.model or settings.openai_default_model
    body: dict[str, Any] = {
        "model": model,
        "input": payload.prompt,
    }
    if payload.system:
        body["instructions"] = payload.system
    try:
        data = _http_json(
            "POST",
            "https://api.openai.com/v1/responses",
            body,
            settings.openai_timeout_seconds,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )
    except Exception as exc:  # noqa: BLE001 - returned to local caller for fallback/help.
        return {"ok": False, "backend": "openai", "model": model, "error": str(exc)}
    text = _openai_response_text(data)
    return {
        "ok": True,
        "backend": "openai",
        "model": data.get("model", model),
        "text": text,
        "raw": data,
    }


def _openai_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    chunks: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


def _run_ollama(payload: ReasonRequest) -> dict[str, Any]:
    if not _cloud_enabled():
        return {
            "ok": False,
            "backend": "ollama",
            "error": "Cloud reasoning is disabled by the parent/operator control panel.",
        }
    model = payload.model or _select_ollama_model(payload.prompt, tool_task=False)
    model_error = _validate_ollama_model(model)
    if model_error:
        return {
            "ok": False,
            "backend": "ollama",
            "model": model,
            "error": model_error,
            "allowed_models": settings.allowed_ollama_models,
        }
    body = {
        "model": model,
        "prompt": payload.prompt,
        "system": payload.system,
        "stream": False,
    }
    body = {key: value for key, value in body.items() if value is not None}
    try:
        data = _http_json(
            "POST", f"{settings.ollama_base_url.rstrip('/')}/api/generate", body, settings.ollama_timeout_seconds
        )
    except Exception as exc:  # noqa: BLE001 - returned to local caller for setup help.
        return {"ok": False, "backend": "ollama", "model": model, "error": str(exc)}
    return {
        "ok": True,
        "backend": "ollama",
        "model": data.get("model", model),
        "text": data.get("response", ""),
        "raw": data,
    }


def _run_ollama_tool_task(payload: TaskRequest) -> dict[str, Any]:
    if not _cloud_enabled():
        return {
            "ok": False,
            "backend": "ollama-tools",
            "error": "Cloud tool routing is disabled by the parent/operator control panel.",
        }
    model = payload.model or _select_ollama_model(payload.prompt, tool_task=True)
    model_error = _validate_ollama_model(model)
    if model_error:
        return {
            "ok": False,
            "backend": "ollama",
            "model": model,
            "error": model_error,
            "allowed_models": settings.allowed_ollama_models,
        }

    system = payload.system or (
        "You are the Mac-side tool runner for a kid-friendly Reachy Mini robot. "
        "Use tools when the user asks to make, show, open, search, answer current facts, or clear something on the screen. "
        "For games or interactive pages, create one complete HTML artifact. "
        "For YouTube requests, use youtube_search instead of inventing URLs. "
        "For weather requests, use weather_current. For current web facts, use web_search if available. "
        "For requests to draw, generate, or make a picture, use gemini_image. "
        "Only open URLs using the provided screen_open or youtube_search tools. "
        "Keep the final spoken response short."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": payload.prompt},
    ]
    tools = _ollama_tool_schemas()
    tool_results: list[dict[str, Any]] = []
    opened = False
    last_message: dict[str, Any] | None = None

    for _ in range(payload.max_tool_rounds):
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
            "tools": tools,
        }
        try:
            data = _http_json(
                "POST", f"{settings.ollama_base_url.rstrip('/')}/api/chat", body, settings.ollama_timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001 - returned to local caller for setup help.
            return {"ok": False, "backend": "ollama", "model": model, "error": str(exc)}

        message = data.get("message") or {}
        last_message = message
        calls = message.get("tool_calls") or []
        if not calls:
            break

        messages.append(message)
        for call in calls:
            result = _execute_ollama_tool_call(call)
            tool_results.append(result)
            if result.get("tool") == "screen_open" and result.get("ok"):
                opened = True
            messages.append(
                {
                    "role": "tool",
                    "tool_name": result.get("tool", "unknown"),
                    "content": json.dumps(result),
                }
            )

    if payload.open_artifacts and not opened:
        artifact_urls = [
            result.get("result", {}).get("url")
            for result in tool_results
            if result.get("tool") == "artifact" and result.get("ok")
        ]
        artifact_urls = [url for url in artifact_urls if url]
        if artifact_urls:
            result = {
                "tool": "screen_open",
                "arguments": {"url": artifact_urls[-1]},
                "ok": True,
                "result": _open_screen_url(artifact_urls[-1]),
                "auto": True,
            }
            tool_results.append(result)
            opened = True

    text = (last_message or {}).get("content", "").strip()
    if not text and tool_results:
        if opened:
            text = "I made it and opened it on the screen."
        else:
            text = "I finished that on the Mac."

    return {
        "ok": True,
        "backend": "ollama-tools",
        "model": model,
        "text": text,
        "tool_results": tool_results,
    }


def _execute_ollama_tool_call(call: dict[str, Any]) -> dict[str, Any]:
    function = call.get("function") or {}
    name = function.get("name")
    args = function.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}

    try:
        if name == "artifact":
            result = _save_artifact(
                str(args.get("name") or "artifact"),
                str(args.get("kind") or "html"),
                str(args.get("content") or ""),
            )
        elif name == "screen_open":
            result = _open_screen_url(str(args.get("url") or ""))
        elif name == "screen_clear":
            result = {"ok": bool(webbrowser.open("about:blank", 2)), "url": "about:blank"}
        elif name == "youtube_search":
            result = _youtube_search(str(args.get("query") or ""))
        elif name == "weather_current":
            result = _weather_current(str(args.get("location") or ""))
        elif name == "web_search":
            result = _ollama_web_search(
                str(args.get("query") or ""),
                int(args.get("max_results") or 5),
            )
        elif name == "gemini_image":
            result = _gemini_generate_image(
                GeminiImageRequest(
                    prompt=str(args.get("prompt") or ""),
                    model=args.get("model") or None,
                    open_image=True,
                )
            )
        else:
            return {"tool": name or "unknown", "arguments": args, "ok": False, "error": "Tool is not allowed."}
    except Exception as exc:  # noqa: BLE001 - tool result should be visible to caller/model.
        failed = {"tool": name or "unknown", "arguments": args, "ok": False, "error": str(exc)}
        _log_event("tool_error", f"Tool failed: {name or 'unknown'}.", details=failed)
        return failed

    event_result = {"tool": name, "arguments": args, "ok": True, "result": result}
    _log_event("tool", f"Tool used: {name}.", details=event_result)
    return event_result


def _ollama_tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "artifact",
                "description": "Create a hosted artifact on the Mac. Use this for generated HTML games, interactive pages, text, JSON, JavaScript, or CSS.",
                "parameters": {
                    "type": "object",
                    "required": ["name", "kind", "content"],
                    "properties": {
                        "name": {"type": "string", "description": "Short safe artifact name."},
                        "kind": {"type": "string", "enum": ["html", "text", "json", "js", "css"]},
                        "content": {"type": "string", "description": "Complete artifact content."},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "screen_open",
                "description": "Open an allowlisted URL on the Mac screen. Use generated artifact URLs or allowlisted kid-safe URLs only.",
                "parameters": {
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {"type": "string", "description": "URL to open on the Mac screen."},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "screen_clear",
                "description": "Clear the Mac screen by opening a blank page.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "youtube_search",
                "description": "Open a YouTube search results page on the Mac screen for a kid-requested topic.",
                "parameters": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "description": "YouTube search query."},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "weather_current",
                "description": "Get current weather for a city or place.",
                "parameters": {
                    "type": "object",
                    "required": ["location"],
                    "properties": {
                        "location": {"type": "string", "description": "City or place name, e.g. Rochester, NY."},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for current information. Requires OLLAMA_API_KEY on the Mac bridge.",
                "parameters": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "description": "Search query."},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "gemini_image",
                "description": "Generate one kid-safe image with Gemini and open it on the Mac screen. Use for drawing or picture requests, not games.",
                "parameters": {
                    "type": "object",
                    "required": ["prompt"],
                    "properties": {
                        "prompt": {"type": "string", "description": "Detailed, kid-safe image prompt."},
                        "model": {
                            "type": "string",
                            "enum": settings.allowed_gemini_image_models,
                            "description": "Optional Gemini image model.",
                        },
                    },
                },
            },
        },
    ]


def _save_artifact(name: str | None, kind: str, content: str) -> dict[str, Any]:
    if not content:
        raise ValueError("Artifact content is empty.")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    filename = _artifact_filename(name, kind)
    path = ARTIFACT_DIR / filename
    path.write_text(content, encoding="utf-8")
    return {
        "ok": True,
        "path": str(path),
        "url": f"http://127.0.0.1:{BRIDGE_PORT}/artifacts/{filename}",
        "bytes": path.stat().st_size,
    }


def _save_binary_artifact(name: str | None, suffix: str, content: bytes) -> dict[str, Any]:
    if not content:
        raise ValueError("Binary artifact content is empty.")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in (name or "artifact")).strip("-")
    safe_suffix = "".join(ch if ch.isalnum() else "" for ch in suffix) or "bin"
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f"{timestamp}-{safe_name[:60]}-{uuid.uuid4().hex[:8]}.{safe_suffix}"
    path = ARTIFACT_DIR / filename
    path.write_bytes(content)
    return {
        "ok": True,
        "path": str(path),
        "url": f"http://127.0.0.1:{BRIDGE_PORT}/artifacts/{filename}",
        "bytes": path.stat().st_size,
    }


def _open_screen_url(url: str) -> dict[str, Any]:
    if not _url_allowed(url):
        raise ValueError(f"URL is not in the local allowlist: {url}")
    opened = webbrowser.open(url, 2)
    return {"ok": bool(opened), "url": url}


def _youtube_search(query: str) -> dict[str, Any]:
    if not query.strip():
        raise ValueError("YouTube query is empty.")
    url = "https://www.youtube.com/results?search_query=" + parse.quote_plus(query.strip())
    return _open_screen_url(url)


def _weather_current(location: str) -> dict[str, Any]:
    if not location.strip():
        raise ValueError("Weather location is empty.")
    search_name = location.strip()
    admin_hint = None
    if "," in search_name:
        search_name, admin_hint = [part.strip() for part in search_name.split(",", 1)]
    geo_url = "https://geocoding-api.open-meteo.com/v1/search?" + parse.urlencode(
        {
            "name": search_name,
            "count": 10,
            "language": "en",
            "format": "json",
        }
    )
    geo = _http_json("GET", geo_url, None, 10)
    results = geo.get("results") or []
    if not results:
        raise ValueError(f"Location not found: {location}")
    place = _choose_geo_result(results, admin_hint)
    weather_url = "https://api.open-meteo.com/v1/forecast?" + parse.urlencode(
        {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "auto",
        }
    )
    weather = _http_json("GET", weather_url, None, 10)
    return {
        "ok": True,
        "location": {
            "name": place.get("name"),
            "admin1": place.get("admin1"),
            "country": place.get("country"),
            "latitude": place.get("latitude"),
            "longitude": place.get("longitude"),
        },
        "current": weather.get("current"),
        "units": weather.get("current_units"),
        "source": "open-meteo.com",
    }


def _ollama_web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    if not _cloud_enabled():
        return {"ok": False, "error": "Cloud web search is disabled by the parent/operator control panel."}
    if not query.strip():
        raise ValueError("Web search query is empty.")
    if not settings.ollama_api_key:
        return {
            "ok": False,
            "error": "Ollama web search requires OLLAMA_API_KEY on the Mac bridge.",
        }
    body = {"query": query.strip(), "max_results": max(1, min(max_results, 10))}
    return _http_json(
        "POST",
        "https://ollama.com/api/web_search",
        body,
        20,
        headers={"Authorization": f"Bearer {settings.ollama_api_key}"},
    )


def _gemini_generate_image(payload: GeminiImageRequest) -> dict[str, Any]:
    if not _cloud_enabled():
        return {
            "ok": False,
            "backend": "gemini-image",
            "error": "Gemini image generation is disabled by the parent/operator control panel.",
        }
    if not settings.gemini_api_key:
        return {"ok": False, "backend": "gemini-image", "error": "GEMINI_API_KEY is not configured."}

    model = payload.model or settings.gemini_image_model
    if model not in settings.allowed_gemini_image_models:
        return {
            "ok": False,
            "backend": "gemini-image",
            "model": model,
            "error": "Gemini image model is not on the Reachy image allowlist.",
            "allowed_models": settings.allowed_gemini_image_models,
        }

    quota = _gemini_image_quota()
    if quota["used"] >= settings.gemini_daily_image_limit:
        return {
            "ok": False,
            "backend": "gemini-image",
            "model": model,
            "error": "Daily Gemini image limit reached.",
            "quota": quota,
        }

    prompt = (
        "Create a family-friendly image suitable for children. "
        "Avoid scary, sexual, violent, hateful, or unsafe content. "
        f"User request: {payload.prompt}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    url = f"{settings.gemini_base_url.rstrip('/')}/models/{parse.quote(model, safe='')}:generateContent"
    try:
        data = _http_json(
            "POST",
            url,
            body,
            settings.gemini_timeout_seconds,
            headers={"x-goog-api-key": settings.gemini_api_key},
        )
    except Exception as exc:  # noqa: BLE001 - returned to local caller for setup help.
        return {"ok": False, "backend": "gemini-image", "model": model, "error": str(exc)}

    text_parts: list[str] = []
    images: list[tuple[str, bytes]] = []
    for candidate in data.get("candidates", []):
        for part in (candidate.get("content") or {}).get("parts", []):
            if "text" in part:
                text_parts.append(str(part["text"]))
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                mime_type = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                images.append((mime_type, base64.b64decode(inline["data"])))

    if not images:
        return {
            "ok": False,
            "backend": "gemini-image",
            "model": model,
            "error": "Gemini returned no image data.",
            "text": "\n".join(text_parts).strip(),
            "raw": data,
        }

    mime_type, image_bytes = images[0]
    saved = _save_binary_artifact("gemini-image", _image_suffix(mime_type), image_bytes)
    _record_gemini_image_use(model)
    opened = _open_screen_url(saved["url"]) if payload.open_image else None
    return {
        "ok": True,
        "backend": "gemini-image",
        "model": model,
        "text": "\n".join(text_parts).strip(),
        "image": saved,
        "opened": opened,
        "quota": _gemini_image_quota(),
        "usage_metadata": data.get("usageMetadata") or data.get("usage_metadata"),
    }


def _gemini_image_quota() -> dict[str, Any]:
    today = time.strftime("%Y-%m-%d")
    state = _read_gemini_usage()
    used = int(state.get(today, {}).get("images", 0))
    return {"date": today, "used": used, "limit": settings.gemini_daily_image_limit}


def _record_gemini_image_use(model: str) -> None:
    today = time.strftime("%Y-%m-%d")
    path = _gemini_usage_path()
    state = _read_gemini_usage()
    bucket = state.setdefault(today, {"images": 0, "models": {}})
    bucket["images"] = int(bucket.get("images", 0)) + 1
    models = bucket.setdefault("models", {})
    models[model] = int(models.get(model, 0)) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _read_gemini_usage() -> dict[str, Any]:
    path = _gemini_usage_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _gemini_usage_path() -> Path:
    return ROOT_DIR / ".state" / "gemini-usage.json"


def _choose_geo_result(results: list[dict[str, Any]], admin_hint: str | None) -> dict[str, Any]:
    if not admin_hint:
        return results[0]
    hint = admin_hint.lower()
    state_aliases = {
        "ny": "new york",
        "ca": "california",
        "fl": "florida",
        "tx": "texas",
        "pa": "pennsylvania",
        "oh": "ohio",
        "mi": "michigan",
        "il": "illinois",
        "ma": "massachusetts",
        "ga": "georgia",
        "nc": "north carolina",
        "nj": "new jersey",
        "va": "virginia",
    }
    expanded = state_aliases.get(hint, hint)
    for item in results:
        admin = str(item.get("admin1") or "").lower()
        country = str(item.get("country_code") or item.get("country") or "").lower()
        if hint in {admin, country} or expanded in {admin, country}:
            return item
    return results[0]


def _is_ollama_cloud_model(model: str) -> bool:
    return model.endswith("-cloud") or model.endswith(":cloud")


def _validate_ollama_model(model: str) -> str | None:
    if settings.require_ollama_cloud and not _is_ollama_cloud_model(model):
        return "Local Mac Ollama models are disabled. Use an allowed Ollama cloud model."
    if settings.allowed_ollama_models and model not in settings.allowed_ollama_models:
        return "Ollama model is not on the Reachy escalation allowlist."
    return None


def _select_ollama_model(prompt: str, *, tool_task: bool) -> str:
    lowered = prompt.lower()
    preferred = "deepseek-v4-flash:cloud" if tool_task else "nemotron-3-super:cloud"

    if any(marker in lowered for marker in ("very deep", "deepest", "use glm", "slow but thorough")):
        preferred = "glm-5.1:cloud"
    elif any(
        marker in lowered
        for marker in ("calendar", "schedule", "chore", "memory proposal", "summarize memory", "family board")
    ):
        preferred = "gemma4:31b-cloud"
    elif any(marker in lowered for marker in ("status summary", "ops summary", "parent summary")):
        preferred = "deepseek-v4-flash:cloud"
    elif any(marker in lowered for marker in ("use minimax", "minimax")):
        preferred = "minimax-m2.7:cloud"
    elif tool_task and any(marker in lowered for marker in ("game", "playable", "score", "restart", "win condition")):
        if any(marker in lowered for marker in ("quick", "prototype", "draft", "fast")):
            preferred = "deepseek-v4-flash:cloud"
        else:
            preferred = "glm-5.1:cloud"
    elif any(
        marker in lowered
        for marker in ("polished", "complex game", "write code", "make an app", "full app", "creative", "story")
    ):
        preferred = "kimi-k2.6:cloud"
    elif any(marker in lowered for marker in ("screen", "open", "show", "video", "youtube", "artifact", "clear")):
        preferred = "deepseek-v4-flash:cloud"

    if preferred in settings.allowed_ollama_models:
        return preferred
    if settings.default_model in settings.allowed_ollama_models:
        return settings.default_model
    return settings.allowed_ollama_models[0] if settings.allowed_ollama_models else settings.default_model


def _ollama_tags() -> dict[str, Any]:
    try:
        data = _http_json("GET", f"{settings.ollama_base_url.rstrip('/')}/api/tags", None, 5)
    except Exception as exc:  # noqa: BLE001 - health-style probe.
        return {"available": False, "base_url": settings.ollama_base_url, "error": str(exc)}
    names = [model.get("name") for model in data.get("models", []) if model.get("name")]
    return {"available": True, "base_url": settings.ollama_base_url, "models": names}


def _http_json(
    method: str,
    url: str,
    body: dict[str, Any] | None,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    encoded = None if body is None else json.dumps(body).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    req = request.Request(
        url,
        data=encoded,
        method=method,
        headers=request_headers,
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def _compose_prompt(payload: ReasonRequest) -> str:
    if payload.system:
        return f"System:\n{payload.system}\n\nUser:\n{payload.prompt}\n"
    return payload.prompt


def _artifact_filename(name: str | None, kind: str) -> str:
    safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in (name or "artifact")).strip("-")
    safe_kind = "".join(ch if ch.isalnum() else "" for ch in kind) or "text"
    suffix_by_kind = {
        "html": "html",
        "text": "txt",
        "txt": "txt",
        "json": "json",
        "js": "js",
        "css": "css",
    }
    suffix = suffix_by_kind.get(safe_kind.lower(), "txt")
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{safe_name[:60]}-{uuid.uuid4().hex[:8]}.{suffix}"


def _image_suffix(mime_type: str) -> str:
    suffix_by_mime = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/webp": "webp",
    }
    return suffix_by_mime.get(mime_type.lower(), "png")


def _url_allowed(url: str) -> bool:
    parsed = parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.hostname:
        return False
    for prefix in _effective_allowlist():
        allowed = parse.urlparse(prefix)
        if parsed.scheme != allowed.scheme:
            continue
        if (parsed.hostname or "").lower() != (allowed.hostname or "").lower():
            continue
        if parsed.port != allowed.port:
            continue
        allowed_path = (allowed.path or "/").rstrip("/")
        if (
            allowed_path
            and allowed_path != "/"
            and not parsed.path.startswith(allowed_path + "/")
            and parsed.path != allowed_path
        ):
            continue
        return True
    return False
