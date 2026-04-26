from __future__ import annotations
from typing import Any, Dict

from reachy_family.bridge_client import ReachyBridgeClient
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


class RequestCodexAsync(Tool):
    name = "request_codex_async"
    description = "Ask the bridge for slower Codex/GPT-5.5 planning, games, diagnostics, or code/artifact help."
    parameters_schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Task for the higher-brain async lane."},
            "reasoning_effort": {
                "type": "string",
                "enum": ["none", "low", "medium", "high"],
                "description": "Use low by default; none only for tiny deterministic tasks.",
            },
            "open_artifacts": {
                "type": "boolean",
                "description": "Whether generated artifacts may be opened on the screen.",
            },
        },
        "required": ["prompt"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        return ReachyBridgeClient(timeout=45).post(
            "/reason",
            {
                "prompt": kwargs["prompt"],
                "model": "gpt-5.5",
                "prefer": "codex",
                "reasoning_effort": kwargs.get("reasoning_effort") or "low",
            },
        )
