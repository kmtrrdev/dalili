"""MCP servers exposing travel capabilities.

Every server can run standalone over stdio, e.g.:

    python -m travel_agent.mcp_servers.flights

and is also importable so the agent can talk to it in-process (in-memory transport).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..models import utcnow


def dump(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, list):
        return [dump(o) for o in obj]
    if isinstance(obj, dict):
        return {k: dump(v) for k, v in obj.items()}
    return obj


def envelope(result_type: str, source: str, query: dict[str, Any], **payload: Any) -> dict[str, Any]:
    """Uniform structured tool result: type, status, query, payload, source, retrieved_at."""
    return {
        "type": result_type,
        "status": "success",
        "query": query,
        **{k: dump(v) for k, v in payload.items()},
        "source": source,
        "retrieved_at": utcnow().isoformat(),
    }


def error(result_type: str, source: str, query: dict[str, Any], message: str) -> dict[str, Any]:
    return {"type": result_type, "status": "error", "query": query, "error": message, "source": source,
            "retrieved_at": utcnow().isoformat()}
