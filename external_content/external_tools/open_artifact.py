from __future__ import annotations
from typing import Any, Dict

from reachy_family.bridge_client import ReachyBridgeClient
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


class OpenArtifact(Tool):
    name = "open_artifact"
    description = "Create and open a local touchscreen artifact such as a simple game, page, or text display."
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short safe artifact name."},
            "kind": {"type": "string", "description": "Artifact kind such as html, text, json, js, css."},
            "content": {"type": "string", "description": "Complete artifact content."},
        },
        "required": ["content"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        client = ReachyBridgeClient()
        artifact = client.post(
            "/artifact",
            {
                "name": kwargs.get("name") or "reachy-artifact",
                "kind": kwargs.get("kind") or "html",
                "content": kwargs["content"],
            },
        )
        if artifact.get("ok") and isinstance(artifact.get("artifact"), dict) and artifact["artifact"].get("url"):
            screen = client.post("/screen/open", {"url": artifact["artifact"]["url"]})
            artifact["screen"] = screen
        return artifact
