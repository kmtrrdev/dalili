"""Observability: request ids, per-turn usage (model calls, tokens, cost estimate, tool calls, live searches) and
structured one-line logs - enough to debug a turn without logging anyone's trip content.

Per-turn counters live in a ContextVar holding one mutable dict: every task a turn starts (graph nodes, tool calls)
inherits the same dict, so concurrent turns of different users never mix their numbers. The same dict records the
turn's path - each graph step, tool call and model call with its timing - which the UI draws as the message's route
through the system.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextvars import ContextVar
from typing import Any

log = logging.getLogger("dalili.telemetry")

REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)
USAGE: ContextVar[dict | None] = ContextVar("turn_usage", default=None)

# Model prices for the cost estimate (USD per 1M tokens) - configuration, defaulting to gpt-5-mini list prices.
PRICE_IN = float(os.getenv("DALILI_LLM_PRICE_IN_PER_M", "0.25"))
PRICE_OUT = float(os.getenv("DALILI_LLM_PRICE_OUT_PER_M", "2.0"))


PATH_MAX = 150  # entries per kind: a long turn still draws, a runaway loop can't grow without bound


def new_usage() -> dict[str, Any]:
    return {"llm_calls": 0, "llm_failures": 0, "input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0,
            "tool_calls": 0, "tool_failures": 0, "tool_ms": 0.0,
            "path": {"t0": time.perf_counter(), "nodes": [], "tools": [], "llm": []}}


def _trace(kind: str, entry: dict[str, Any]) -> None:
    """Add one step to the turn's path; `end` is when it finished, in ms since the turn began."""
    u = USAGE.get()
    if u is None or len(u["path"][kind]) >= PATH_MAX:
        return
    u["path"][kind].append({**entry, "end": round((time.perf_counter() - u["path"]["t0"]) * 1000)})


def record_node(name: str, ms: float) -> None:
    _trace("nodes", {"name": name, "ms": round(ms)})


def record_model_call(what: str, ms: float, ok: bool, cached: bool = False) -> None:
    _trace("llm", {"what": what, "ms": round(ms), "ok": ok, "cached": cached})


def record_llm(usage: dict | None, ok: bool = True) -> None:
    u = USAGE.get()
    if u is None:
        return
    u["llm_calls"] += 1
    u["llm_failures"] += int(not ok)
    if usage:
        u["input_tokens"] += int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        u["output_tokens"] += int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        details = usage.get("output_tokens_details") or usage.get("completion_tokens_details") or {}
        u["reasoning_tokens"] += int(details.get("reasoning_tokens") or 0)


def record_tool(ok: bool, ms: float, name: str | None = None) -> None:
    u = USAGE.get()
    if u is None:
        return
    u["tool_calls"] += 1
    u["tool_failures"] += int(not ok)
    u["tool_ms"] = round(u["tool_ms"] + ms, 1)
    if name:
        _trace("tools", {"name": name, "ms": round(ms), "ok": ok})


def finish(usage: dict[str, Any], serpapi_calls: int, ms: float) -> dict[str, Any]:
    out = {k: v for k, v in usage.items() if k != "path"}
    out["serpapi_calls"] = serpapi_calls
    out["turn_ms"] = round(ms)
    out["llm_cost_usd_est"] = round((usage["input_tokens"] * PRICE_IN + usage["output_tokens"] * PRICE_OUT) / 1e6, 5)
    return out


def path(usage: dict[str, Any], ms: float) -> dict[str, Any]:
    """The turn's route through the system, for the UI: graph steps, tool calls and model calls (each with its time)."""
    p = usage["path"]
    return {"total_ms": round(ms), "nodes": p["nodes"], "tools": p["tools"], "llm": p["llm"]}


def event(name: str, **fields: Any) -> None:
    """One structured log line (JSON) tagged with the request id. Never pass trip content or personal data."""
    log.info(json.dumps({"event": name, "request_id": REQUEST_ID.get(), **fields}, default=str))
