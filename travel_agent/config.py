"""Runtime settings, read from the environment (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # LLM
    model: str = os.getenv("TRAVEL_AGENT_MODEL", "claude-opus-5")
    effort: str = os.getenv("TRAVEL_AGENT_EFFORT", "medium")
    llm_enabled: bool = _bool("TRAVEL_AGENT_LLM", True)
    # The keyword parser is NOT used in production: understanding is the model's job. It stays only as the offline
    # test harness (tests / eval run without a model and turn this on).
    rules_fallback: bool = _bool("TRAVEL_AGENT_RULES_FALLBACK", False)
    llm_provider: str = os.getenv("TRAVEL_AGENT_LLM_PROVIDER", "auto")  # auto | azure | anthropic
    # Azure AI Foundry, e.g. gpt-5-mini on .../openai/v1/responses (Responses API) or a chat-completions endpoint
    azure_key: str = os.getenv("AZURE_AI_KEY", "")
    azure_endpoint: str = os.getenv("AZURE_AI_ENDPOINT", "")
    azure_model: str = os.getenv("AZURE_AI_MODEL", "gpt-5-mini")
    azure_api: str = os.getenv("AZURE_AI_API", "auto")  # auto (from the endpoint URL) | responses | chat
    azure_reasoning_effort: str = os.getenv("AZURE_AI_REASONING_EFFORT", "low")  # minimal | low | medium | high
    azure_reasoning_budget: int = int(os.getenv("AZURE_AI_REASONING_BUDGET", "8000"))  # extra output tokens for reasoning
    azure_timeout: float = float(os.getenv("AZURE_AI_TIMEOUT", "60"))  # one HTTP attempt
    llm_call_timeout: float = float(os.getenv("TRAVEL_AGENT_LLM_CALL_TIMEOUT", "75"))  # a whole call, retries included

    # Data providers (keys live in .env, never in code)
    serpapi_key: str = os.getenv("SERPAPI_API_KEY", "")
    ors_key: str = os.getenv("ORS_API_KEY", "")
    opentripmap_key: str = os.getenv("OPENTRIPMAP_API_KEY", "")
    geoapify_key: str = os.getenv("GEOAPIFY_API_KEY", "")

    # HTTP layer: "cache" (default: fresh cache, else live), "live" (always call), "replay" (cache only, no network)
    http_mode: str = os.getenv("TRAVEL_AGENT_HTTP_MODE", "cache")
    http_cache_path: str = os.getenv("TRAVEL_AGENT_HTTP_CACHE", str(PROJECT_DIR / ".cache" / "http_cache.sqlite"))
    http_timeout: float = float(os.getenv("TRAVEL_AGENT_HTTP_TIMEOUT", "30"))
    # SerpApi is quota-limited (free plan: 250 searches / month): cap live calls per chat turn.
    serpapi_calls_per_turn: int = int(os.getenv("TRAVEL_AGENT_SERPAPI_CALLS_PER_TURN", "20"))
    hotel_review_lookups: int = int(os.getenv("TRAVEL_AGENT_HOTEL_REVIEW_LOOKUPS", "2"))

    mcp_transport: str = os.getenv("TRAVEL_AGENT_MCP_TRANSPORT", "inmemory")
    mcp_call_timeout: float = float(os.getenv("TRAVEL_AGENT_MCP_TIMEOUT", "150"))
    db_path: str = os.getenv("TRAVEL_AGENT_DB", str(PROJECT_DIR / "travel_agent.db"))
    default_origin: str = os.getenv("TRAVEL_AGENT_DEFAULT_ORIGIN", "Cairo")
    language: str = os.getenv("TRAVEL_AGENT_LANGUAGE", "en")

    # Planner knobs
    budget_buffer_ratio: float = float(os.getenv("TRAVEL_AGENT_BUDGET_BUFFER", "0.05"))
    max_repair_iterations: int = 6
    # Preference memory (preferences.py): when an inferred preference is trusted enough to use, and how fast old
    # behaviour fades. Fallback values, configurable.
    preference_apply_threshold: float = float(os.getenv("TRAVEL_AGENT_PREF_THRESHOLD", "0.5"))
    preference_half_life_days: float = float(os.getenv("TRAVEL_AGENT_PREF_HALF_LIFE_DAYS", "180"))
    extra: dict = field(default_factory=dict)


settings = Settings()


def today():
    """Today's date; TRAVEL_AGENT_TODAY pins it so recorded API sessions replay identically (tests, evals)."""
    from datetime import date

    pinned = os.getenv("TRAVEL_AGENT_TODAY")
    return date.fromisoformat(pinned) if pinned else date.today()
