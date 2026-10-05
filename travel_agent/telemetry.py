"""Observability: request ids, per-turn usage (model calls, tokens, cost estimate, tool calls, live searches) and
structured one-line logs - enough to debug a turn without logging anyone's trip content.

Per-turn counters live in a ContextVar holding one mutable dict: every task a turn starts (graph nodes, tool calls)
inherits the same dict, so concurrent turns of different users never mix their numbers.
"""

from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar
from typing import Any

log = logging.getLogger("dalili.telemetry")

REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)
USAGE: ContextVar[dict | None] = ContextVar("turn_usage", default=None)

# Model prices for the cost estimate (USD per 1M tokens) - configuration, defaulting to gpt-5-mini list prices.
PRICE_IN = float(os.getenv("DALILI_LLM_PRICE_IN_PER_M", "0.25"))
PRICE_OUT = float(os.getenv("DALILI_LLM_PRICE_OUT_PER_M", "2.0"))


def new_usage() -> dict[str, Any]:
    return {"llm_calls": 0, "llm_failures": 0, "input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0,
            "tool_calls": 0, "tool_failures": 0, "tool_ms": 0.0}


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


def record_tool(ok: bool, ms: float) -> None:
    u = USAGE.get()
    if u is None:
        return
    u["tool_calls"] += 1
    u["tool_failures"] += int(not ok)
    u["tool_ms"] = round(u["tool_ms"] + ms, 1)


def finish(usage: dict[str, Any], serpapi_calls: int, ms: float) -> dict[str, Any]:
    out = dict(usage)
    out["serpapi_calls"] = serpapi_calls
    out["turn_ms"] = round(ms)
    out["llm_cost_usd_est"] = round((usage["input_tokens"] * PRICE_IN + usage["output_tokens"] * PRICE_OUT) / 1e6, 5)
    return out


def event(name: str, **fields: Any) -> None:
    """One structured log line (JSON) tagged with the request id. Never pass trip content or personal data."""
    log.info(json.dumps({"event": name, "request_id": REQUEST_ID.get(), **fields}, default=str))
