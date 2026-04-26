from __future__ import annotations
import logging
from typing import Any, Dict

from reachy_family.bridge_client import ReachyBridgeClient
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)


class FamilyMemory(Tool):
    name = "family_memory"
    description = "Read approved family profiles or propose a new memory for parent review."
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["profiles", "propose"],
                "description": "Use profiles to read known profiles, propose to create a parent-reviewed memory proposal.",
            },
            "profile": {"type": "string", "description": "Family profile such as brian, preston, greyson, or guest."},
            "memory": {"type": "string", "description": "A short stable memory to propose for parent review."},
            "reason": {"type": "string", "description": "Why this memory might matter later."},
        },
        "required": ["action"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        client = ReachyBridgeClient()
        action = str(kwargs["action"])
        if action == "profiles":
            return client.get("/memory/profiles")
        if action == "propose":
            profile = str(kwargs.get("profile") or "guest")[:80]
            memory = str(kwargs.get("memory") or "").strip()
            if len(memory) < 3:
                return {"ok": False, "error": "memory is required for propose"}
            payload = {
                "profile": profile,
                "proposed_memory": memory[:500],
                "reason": str(kwargs.get("reason") or "Conversation app proposed this memory.")[:500],
                "source_event_ids": [],
            }
            logger.info("Proposing family memory for %s", profile)
            return client.post("/memory/proposals", payload)
        return {"ok": False, "error": f"unknown action: {action}"}
