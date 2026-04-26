from __future__ import annotations
import html
from typing import Any, Dict

from reachy_family.bridge_client import ReachyBridgeClient
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


class StoryScreenImage(Tool):
    name = "story_screen_image"
    description = "Create or log a story image prompt for the screen during a narrated story beat."
    parameters_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Story beat title."},
            "prompt": {"type": "string", "description": "Kid-safe image prompt or scene description."},
            "profile": {"type": "string", "description": "Optional profile requesting the story."},
        },
        "required": ["prompt"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        client = ReachyBridgeClient()
        title = str(kwargs.get("title") or "Story picture")
        prompt = str(kwargs["prompt"])

        image = client.post("/gemini/image", {"prompt": prompt, "open_image": True})
        if image.get("ok"):
            client.post(
                "/events/log",
                {
                    "event_type": "story_screen_image",
                    "summary": f"Generated story screen image: {title}",
                    "actor": "reachy",
                    "profile": kwargs.get("profile"),
                    "details": {"prompt": prompt, "image": image.get("image")},
                },
            )
            return image

        escaped_title = html.escape(title)
        escaped_prompt = html.escape(prompt)
        fallback_html = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escaped_title}</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#101820;color:white;font-family:system-ui,sans-serif}}main{{max-width:900px;padding:40px;text-align:center}}h1{{font-size:42px}}p{{font-size:26px;line-height:1.35}}</style></head>
<body><main><h1>{escaped_title}</h1><p>{escaped_prompt}</p></main></body></html>"""
        artifact = client.post("/artifact", {"name": "story-scene", "kind": "html", "content": fallback_html})
        if artifact.get("ok") and isinstance(artifact.get("artifact"), dict) and artifact["artifact"].get("url"):
            artifact["screen"] = client.post("/screen/open", {"url": artifact["artifact"]["url"]})
        client.post(
            "/events/log",
            {
                "event_type": "story_screen_image",
                "summary": f"Prepared story screen image prompt: {title}",
                "actor": "reachy",
                "profile": kwargs.get("profile"),
                "details": {"prompt": prompt, "artifact": artifact.get("artifact"), "image_error": image.get("error")},
            },
        )
        return artifact
