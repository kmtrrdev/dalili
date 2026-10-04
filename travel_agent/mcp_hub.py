"""MCP client layer: the only way the agent reaches external travel capabilities.

`MCPHub.call(server, tool, args)` returns the tool's structured JSON result.
Transport is either in-memory (servers run in this process) or stdio
(each server is spawned as its own process, exactly like a third-party MCP server).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from typing import Any

from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters

from .config import PROJECT_DIR, settings
from .mcp_servers import activities, currency, flights, hotels, knowledge, maps, places, weather

log = logging.getLogger(__name__)

SERVERS = {
    "flights": flights,
    "hotels": hotels,
    "places": places,
    "activities": activities,
    "transport": maps,
    "weather": weather,
    "currency": currency,
    "knowledge": knowledge,
}


class MCPToolError(RuntimeError):
    pass


class MCPHub:
    def __init__(self, transport: str | None = None, cache_ttl_s: int = 900):
        self.transport = transport or settings.mcp_transport
        self.cache_ttl_s = cache_ttl_s
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.call_log: list[dict[str, Any]] = []
        # Callbacks notified after every tool call (used to stream live progress to the UI).
        self.listeners: list = []

    def _notify(self, event: dict[str, Any]) -> None:
        for fn in list(self.listeners):
            try:
                fn(event)
            except Exception:  # a UI listener must never break planning
                pass

    def _target(self, server: str):
        module = SERVERS[server]
        if self.transport == "stdio":
            # The SDK gives child processes a minimal environment by default; the servers need the keys, which in
            # production come from environment variables (not a .env file).
            return StdioServerParameters(command=sys.executable, args=["-m", module.__name__], cwd=str(PROJECT_DIR),
                                         env=dict(os.environ))
        return module.server

    async def list_tools(self, server: str) -> list[str]:
        async with Client(self._target(server)) as client:
            result = await client.list_tools()
            return [t.name for t in result.tools]

    async def call(self, server: str, tool: str, args: dict[str, Any], use_cache: bool = True) -> dict[str, Any]:
        key = f"{server}.{tool}:{json.dumps(args, sort_keys=True, default=str)}"
        cached = self._cache.get(key)
        if use_cache and cached and time.time() - cached[0] < self.cache_ttl_s:
            return cached[1]
        started = time.perf_counter()
        async with Client(self._target(server)) as client:
            result = await client.call_tool(tool, args)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        if result.is_error:
            text = " ".join(getattr(c, "text", "") for c in result.content)
            self.call_log.append({"server": server, "tool": tool, "ok": False, "ms": elapsed_ms})
            self._notify({"server": server, "tool": tool, "ok": False, "ms": elapsed_ms})
            raise MCPToolError(f"{server}.{tool} failed: {text}")
        payload = self._parse(result)
        ok = payload.get("status") != "error"
        self.call_log.append({"server": server, "tool": tool, "ok": ok, "ms": elapsed_ms})
        self._notify({"server": server, "tool": tool, "ok": ok, "ms": elapsed_ms})
        if not ok:
            raise MCPToolError(f"{server}.{tool}: {payload.get('error')}")
        self._cache[key] = (time.time(), payload)
        return payload

    async def call_many(self, calls: list[tuple[str, str, dict[str, Any]]]) -> list[dict[str, Any] | Exception]:
        return await asyncio.gather(*(self.call(s, t, a) for s, t, a in calls), return_exceptions=True)

    @staticmethod
    def _parse(result: Any) -> dict[str, Any]:
        structured = getattr(result, "structured_content", None)
        if isinstance(structured, dict):
            return structured.get("result", structured) if set(structured) == {"result"} else structured
        for block in result.content:
            text = getattr(block, "text", None)
            if text:
                return json.loads(text)
        raise MCPToolError("Empty MCP tool result")


_hub: MCPHub | None = None


def get_hub() -> MCPHub:
    global _hub
    if _hub is None:
        _hub = MCPHub()
    return _hub
