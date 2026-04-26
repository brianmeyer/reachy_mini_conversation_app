from __future__ import annotations
from typing import Any, Dict

from reachy_family.bridge_client import ReachyBridgeClient
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


class ShowKidSchedule(Tool):
    name = "show_kid_schedule"
    description = "Open the kid-friendly family schedule/calendar screen."
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        client = ReachyBridgeClient()
        base = client.base_url
        return client.post("/screen/open", {"url": f"{base}/kids"})
