"""LLM wrapper with two interchangeable providers.

- "azure": a model deployed on Azure AI Foundry, default gpt-5-mini. Endpoints ending in /responses use the
  OpenAI Responses API (reasoning models, structured output via text.format=json_schema); other endpoints use
  OpenAI-compatible chat completions (response_format=json_schema). Output is validated with Pydantic.
- "anthropic": Claude via the Anthropic SDK (structured outputs + refusal fallbacks).

TRAVEL_AGENT_LLM_PROVIDER=auto picks Azure when AZURE_AI_KEY and AZURE_AI_ENDPOINT are set, else
Claude when Anthropic credentials exist. The LLM only does understanding and phrasing: every number
(prices, times, distances, scores) comes from tools and deterministic code. Any failure
returns None so callers fall back to the rule-based implementations.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from collections import OrderedDict
from pathlib import Path
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from . import telemetry
from .config import settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]

# Server-side refusal fallback for Claude: if the primary model declines, the API reruns
# the request on a fallback model chosen by refusal category.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client = None
last_error: str | None = None  # why the last model call failed (shown in /api/health and the UI), None when fine


def _anthropic_configured() -> bool:
    if anthropic is None:
        return False
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_PROFILE"):
        return True
    return (Path.home() / ".config" / "anthropic").exists()  # `ant auth login` profile


def provider() -> str | None:
    """The active provider: "azure", "anthropic" or None (rule-based only)."""
    if not settings.llm_enabled:
        return None
    wanted = settings.llm_provider
    if wanted in ("azure", "auto") and settings.azure_key and settings.azure_endpoint:
        return "azure"
    if wanted in ("anthropic", "auto") and _anthropic_configured():
        return "anthropic"
    return None


def available() -> bool:
    return provider() is not None


def model_name() -> str | None:
    p = provider()
    return settings.azure_model if p == "azure" else (settings.model if p == "anthropic" else None)


# ---------------------------------------------------------------------------
# Azure AI Foundry (Responses API or OpenAI-compatible chat completions)
# ---------------------------------------------------------------------------


def _uses_responses_api() -> bool:
    api = settings.azure_api
    return api == "responses" or (api == "auto" and settings.azure_endpoint.rstrip("/").endswith("/responses"))


async def _azure_post(body: dict):
    """POST with retries on rate limits (429) and provider hiccups (5xx). Returns the response or None."""
    global last_error
    resp = None
    # Rate limits (429) and provider hiccups (5xx) are usually gone within seconds: retry before
    # falling back, because the rule-based parser can't read every language the model can.
    for attempt, wait in enumerate((0.0, 2.0, 5.0, 10.0)):
        if wait:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=settings.azure_timeout) as client:
                resp = await client.post(settings.azure_endpoint, json=body, headers={"api-key": settings.azure_key})
        except httpx.HTTPError as exc:
            log.warning("Azure AI unreachable (attempt %d): %s", attempt + 1, type(exc).__name__)
            resp = None
            continue
        if resp.status_code not in (429, 500, 502, 503, 504):
            break
        log.warning("Azure AI returned %s (attempt %d), retrying", resp.status_code, attempt + 1)
    if resp is None:
        last_error = "Azure AI endpoint unreachable"
        log.warning("Azure AI unreachable, using rule-based fallback")
        telemetry.record_llm(None, ok=False)
        return None
    if resp.status_code != 200:
        last_error = {401: "Azure AI key rejected (HTTP 401)", 403: "Azure AI access denied (HTTP 403)",
                      429: "Azure AI rate limit / quota reached (HTTP 429)"}.get(
            resp.status_code, f"Azure AI returned HTTP {resp.status_code}")
        log.warning("Azure AI returned %s, using rule-based fallback: %s", resp.status_code, resp.text[:200])
        telemetry.record_llm(None, ok=False)
        return None
    last_error = None
    try:
        telemetry.record_llm(resp.json().get("usage"), ok=True)
    except ValueError:
        telemetry.record_llm(None, ok=True)
    return resp


def _reasoning_model() -> bool:
    """gpt-4.x / gpt-3.5 (and AZURE_AI_REASONING_EFFORT=none) take no reasoning parameter: sending one is an HTTP 400."""
    model = settings.azure_model.lower()
    return settings.azure_reasoning_effort.lower() != "none" and not model.startswith(("gpt-4", "gpt-35", "gpt-3.5"))


async def _azure_responses(messages: list[dict], max_tokens: int, text_format: dict | None = None,
                           effort: str | None = None) -> str | None:
    body: dict = {"model": settings.azure_model, "input": messages, "max_output_tokens": max_tokens}
    if _reasoning_model():
        # Reasoning tokens count against max_output_tokens: leave room for them on top of the visible answer.
        body["max_output_tokens"] = max_tokens + settings.azure_reasoning_budget
        body["reasoning"] = {"effort": effort or settings.azure_reasoning_effort}
    if text_format:
        body["text"] = {"format": text_format}
    resp = await _azure_post(body)
    if resp is None:
        return None
    data = resp.json()
    if data.get("status") == "incomplete":
        log.warning("Azure AI response incomplete (%s); using fallback", (data.get("incomplete_details") or {}).get("reason"))
        return None
    parts = [c.get("text") or "" for item in data.get("output") or [] if item.get("type") == "message"
             for c in item.get("content") or [] if c.get("type") == "output_text"]
    return "".join(parts).strip() or None


async def _azure_chat(messages: list[dict], max_tokens: int, response_format: dict | None = None,
                      effort: str | None = None) -> str | None:
    if _uses_responses_api():
        text_format = None
        if response_format and response_format.get("type") == "json_schema":
            js = response_format["json_schema"]
            text_format = {"type": "json_schema", "name": js["name"], "schema": js["schema"], "strict": js.get("strict", False)}
        return await _azure_responses(messages, max_tokens, text_format, effort)
    body = {"model": settings.azure_model, "messages": messages, "max_tokens": max_tokens}
    if response_format:
        body["response_format"] = response_format
    resp = await _azure_post(body)
    if resp is None:
        return None
    choice = resp.json()["choices"][0]
    if choice.get("finish_reason") == "length":
        log.warning("Azure AI response hit max_tokens; using fallback")
        return None
    return (choice["message"].get("content") or "").strip() or None


def _json_block(text: str) -> str:
    """Tolerate ```json fences or prose around the JSON object."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start >= 0 and end > start else text


def _azure_user(user: str, images: list[str] | None) -> str | list[dict]:
    """The user turn: text, plus pictures (data: URLs) in the shape the endpoint's API expects."""
    if not images:
        return user
    if _uses_responses_api():
        return [{"type": "input_text", "text": user}] + [{"type": "input_image", "image_url": i} for i in images]
    return [{"type": "text", "text": user}] + [{"type": "image_url", "image_url": {"url": i}} for i in images]


async def _azure_parse(system: str, user: str, schema: type[T], effort: str | None = None,
                       images: list[str] | None = None) -> T | None:
    js = schema.model_json_schema()
    content = await _azure_chat(
        [{"role": "system", "content": system + "\n\nAnswer with a single JSON object that matches this JSON schema:\n"
                                                  + json.dumps(js)},
         {"role": "user", "content": _azure_user(user, images)}],
        max_tokens=6000,
        response_format={"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": js, "strict": False}},
        effort=effort,
    )
    if content is None:
        return None
    try:
        return schema.model_validate_json(_json_block(content))
    except ValidationError as exc:
        log.warning("Model JSON did not match %s (%d errors); using fallback", schema.__name__, exc.error_count())
        return None


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(max_retries=2, timeout=90.0)
    return _client


def _claude_user(user: str, images: list[str] | None) -> str | list[dict]:
    if not images:
        return user
    blocks = []
    for i in images:  # data:image/jpeg;base64,....
        head, _, data = i.partition(",")
        blocks.append({"type": "image", "source": {"type": "base64", "data": data,
                                                    "media_type": head.removeprefix("data:").split(";")[0]}})
    return blocks + [{"type": "text", "text": user}]


async def _claude_parse(system: str, user: str, schema: type[T], max_tokens: int,
                        images: list[str] | None = None) -> T | None:
    try:
        response = await _get_client().beta.messages.parse(
            model=settings.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": _claude_user(user, images)}], thinking={"type": "adaptive"},
            output_config={"effort": settings.effort}, output_format=schema,
            betas=[FALLBACK_BETA], fallbacks="default",
        )
    except anthropic.APIConnectionError as exc:
        log.warning("Claude unreachable, using rule-based fallback: %s", exc)
        return None
    except anthropic.RateLimitError as exc:
        log.warning("Claude rate limited, using rule-based fallback: %s", exc)
        return None
    except anthropic.APIStatusError as exc:
        log.warning("Claude API error %s, using rule-based fallback: %s", exc.status_code, exc.message)
        return None
    telemetry.record_llm({"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
                         ok=response.stop_reason != "refusal")
    if response.stop_reason == "refusal":
        log.warning("Claude declined the request; using rule-based fallback.")
        return None
    return response.parsed_output


async def _claude_text(system: str, user: str, max_tokens: int) -> str | None:
    try:
        response = await _get_client().beta.messages.create(
            model=settings.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}], thinking={"type": "adaptive"},
            output_config={"effort": "low"}, betas=[FALLBACK_BETA], fallbacks="default",
        )
    except anthropic.APIError as exc:
        log.warning("Claude text generation failed, using template: %s", exc)
        return None
    if response.stop_reason == "refusal":
        return None
    return "".join(b.text for b in response.content if b.type == "text").strip() or None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_PARSE_CACHE: "OrderedDict[str, tuple[float, BaseModel]]" = OrderedDict()
PARSE_CACHE_MAX = 400
PARSE_CACHE_TTL_S = 6 * 3600


def _cache_key(p: str | None, system: str, user: str, schema: type, effort: str | None) -> str:
    raw = json.dumps([p, model_name(), effort, system, user, schema.__name__], ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


async def _bounded(coro, timeout: float | None):
    """A whole model call (retries included) within a time budget: a slow provider must never stall a turn - on
    timeout the caller's fallback is used (templates, defaults, or no optional step)."""
    budget = timeout or settings.llm_call_timeout
    try:
        async with asyncio.timeout(budget):
            return await coro
    except TimeoutError:
        global last_error
        last_error = f"model call exceeded {budget:.0f}s"
        log.warning("model call exceeded %.0fs - using the fallback", budget)
        telemetry.record_llm(None, ok=False)
        return None


async def parse(system: str, user: str, schema: type[T], max_tokens: int = 16000, effort: str | None = None,
                timeout: float | None = None, images: list[str] | None = None) -> T | None:
    """Structured output call. Returns None on any failure so callers can fall back.
    `effort` (minimal / low / medium / high) applies to reasoning models; None uses the configured default.
    `images`: pictures as data: URLs (a traveller's photo), read with the text.
    The same request within a few hours is answered from memory (research extraction - guide tariffs, menus, price
    estimates - repeats across turns of one trip); only successful answers are kept, and each hit is a fresh copy."""
    p = provider()
    if p is None:
        return None
    key = _cache_key(p, system, user + "".join(hashlib.sha256(i.encode()).hexdigest() for i in images or []),
                     schema, effort)
    hit = _PARSE_CACHE.get(key)
    if hit and time.time() - hit[0] < PARSE_CACHE_TTL_S:
        _PARSE_CACHE.move_to_end(key)
        telemetry.record_model_call(schema.__name__, 0, True, cached=True)
        return hit[1].model_copy(deep=True)  # type: ignore[return-value]
    started = time.perf_counter()
    out = await _bounded(_azure_parse(system, user, schema, effort, images) if p == "azure" else
                         _claude_parse(system, user, schema, max_tokens, images), timeout)
    telemetry.record_model_call(schema.__name__, (time.perf_counter() - started) * 1000, out is not None)
    if out is not None:
        _PARSE_CACHE[key] = (time.time(), out.model_copy(deep=True))
        while len(_PARSE_CACHE) > PARSE_CACHE_MAX:
            _PARSE_CACHE.popitem(last=False)
    return out


async def text(system: str, user: str, max_tokens: int = 4000, effort: str | None = None,
               timeout: float | None = None) -> str | None:
    """Free-text generation (conversational summary, grounded answers)."""
    p = provider()
    if p is None:
        return None
    started = time.perf_counter()
    if p == "azure":
        out = await _bounded(_azure_chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                         max_tokens=max_tokens, effort=effort), timeout)
    else:
        out = await _bounded(_claude_text(system, user, max_tokens), timeout)
    telemetry.record_model_call("text", (time.perf_counter() - started) * 1000, out is not None)
    return out
