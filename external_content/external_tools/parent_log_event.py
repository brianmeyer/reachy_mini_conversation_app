from __future__ import annotations
import logging
from typing import Any, Dict

from reachy_family.bridge_client import ReachyBridgeClient
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)


class ParentLogEvent(Tool):
    name = "parent_log_event"
    description = "Log a parent-visible Reachy event, model/tool decision, media action, or activity summary."
    parameters_schema = {
        "type": "object",
        "properties": {
            "event_type": {
                "type": "string",
                "description": "Short event type such as live_session, media_opened, tool_used, story, memory_candidate.",
            },
            "summary": {"type": "string", "description": "Parent-readable one-sentence summary."},
            "profile": {
                "type": "string",
                "description": "Optional family profile: brian, preston, greyson, or guest.",
            },
            "details": {"type": "object", "description": "Optional structured details for audit/debugging."},
        },
        "required": ["event_type", "summary"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        payload = {
            "event_type": str(kwargs["event_type"])[:80],
            "summary": str(kwargs["summary"])[:500],
            "actor": "reachy",
            "profile": kwargs.get("profile"),
            "details": kwargs.get("details") if isinstance(kwargs.get("details"), dict) else {},
        }
        logger.info("Family log event: %s", payload["event_type"])
        return ReachyBridgeClient().post("/events/log", payload)
