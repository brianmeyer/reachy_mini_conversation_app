from __future__ import annotations
import os
import json
from typing import Any
from urllib import error, request


DEFAULT_BRIDGE_URL = "http://127.0.0.1:8787"


class ReachyBridgeClient:
    """Small JSON client for the family robot Mac/Jetson bridge."""

    def __init__(self, base_url: str | None = None, timeout: float = 8.0) -> None:
        self.base_url = (
            base_url or os.getenv("REACHY_FAMILY_BRIDGE_URL") or os.getenv("MAC_BRIDGE_URL") or DEFAULT_BRIDGE_URL
        ).rstrip("/")
        self.timeout = timeout

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", path, payload or {})

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "url": url, "status": exc.code, "error": body[:1000]}
        except Exception as exc:  # noqa: BLE001 - tools should report bridge failures, not crash conversations.
            return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {"ok": False, "url": url, "error": "Bridge returned non-JSON response.", "body": raw[:1000]}
        if isinstance(parsed, dict):
            parsed.setdefault("url", url)
            return parsed
        return {"ok": True, "url": url, "data": parsed}
