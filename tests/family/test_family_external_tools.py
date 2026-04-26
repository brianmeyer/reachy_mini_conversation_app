from __future__ import annotations
import sys
import importlib
from types import ModuleType
from pathlib import Path

import pytest

import reachy_mini_conversation_app.config as config_mod
from reachy_family.bridge_client import ReachyBridgeClient


ROOT = Path(__file__).resolve().parents[2]
FAMILY_TOOL_MODULES = {
    "family_memory",
    "open_artifact",
    "parent_log_event",
    "request_codex_async",
    "show_chore_board",
    "show_kid_schedule",
    "story_screen_image",
}


def _reload_core_tools() -> ModuleType:
    for module_name in list(sys.modules):
        if module_name.startswith("reachy_mini_conversation_app.tools.") or module_name in FAMILY_TOOL_MODULES:
            sys.modules.pop(module_name, None)
    sys.modules.pop("reachy_mini_conversation_app.tools.core_tools", None)
    return importlib.import_module("reachy_mini_conversation_app.tools.core_tools")


def test_reachy_family_profile_loads_family_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_mod.config, "REACHY_MINI_CUSTOM_PROFILE", "reachy_family")
    monkeypatch.setattr(config_mod.config, "PROFILES_DIRECTORY", ROOT / "external_content" / "external_profiles")
    monkeypatch.setattr(config_mod.config, "TOOLS_DIRECTORY", ROOT / "external_content" / "external_tools")
    monkeypatch.setattr(config_mod.config, "AUTOLOAD_EXTERNAL_TOOLS", False)

    core_tools_mod = _reload_core_tools()

    expected_tools = FAMILY_TOOL_MODULES | {
        "camera",
        "dance",
        "do_nothing",
        "head_tracking",
        "move_head",
        "play_emotion",
        "stop_dance",
        "stop_emotion",
    }
    assert expected_tools <= set(core_tools_mod.ALL_TOOLS)


def test_bridge_client_reports_connection_failures_without_crashing() -> None:
    client = ReachyBridgeClient(base_url="http://127.0.0.1:9", timeout=0.01)

    result = client.get("/health")

    assert result["ok"] is False
    assert result["url"] == "http://127.0.0.1:9/health"
    assert "error" in result
