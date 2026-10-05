"""Test environment.

Tests replay real API responses recorded in tests/fixtures/http_cache.sqlite, so they run
offline, deterministically and without spending SerpApi quota. To re-record after changing
queries:   RECORD=1 python -m pytest     (uses live APIs for anything missing from the cache)
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["TRAVEL_AGENT_HTTP_MODE"] = "cache" if os.getenv("RECORD") == "1" else "replay"
os.environ["TRAVEL_AGENT_HTTP_CACHE"] = str(ROOT / "tests" / "fixtures" / "http_cache.sqlite")
os.environ["TRAVEL_AGENT_TODAY"] = "2026-09-27"
os.environ["TRAVEL_AGENT_LLM"] = "0"
os.environ["TRAVEL_AGENT_RULES_FALLBACK"] = "1"  # offline harness: the keyword parser stands in for the model
os.environ["TRAVEL_AGENT_DB"] = ":memory:"
if os.getenv("RECORD") != "1":
    # Replay never sends a request, but providers refuse to run without a key: placeholders let the suite run
    # anywhere (CI has no .env). Recorded cache keys never include API keys, so lookups still match.
    for key in ("SERPAPI_API_KEY", "ORS_API_KEY", "OPENTRIPMAP_API_KEY", "GEOAPIFY_API_KEY"):
        os.environ[key] = "replay-placeholder"
sys.path.insert(0, str(ROOT))

from datetime import date  # noqa: E402

import anyio  # noqa: E402
import pytest  # noqa: E402

from travel_agent import research  # noqa: E402
from travel_agent.mcp_hub import MCPHub  # noqa: E402
from travel_agent.models import Budget, TravelerProfile, TripContract  # noqa: E402

ROME_REQUEST = "7 days in Rome from October 12 for two, budget $3,500. We love food, history and photography."
ISTANBUL_REQUEST = ("Relaxed 7-day trip to Istanbul from Cairo, November 3, budget $2,000, vegetarian, "
                    "no early flights, I don't like walking much")


async def make_contract(city: str, start: date, end: date, travelers: int, budget: float, **kw) -> TripContract:
    hub = MCPHub("inmemory")
    dest = await research.resolve_place(hub, city)
    origin = await research.resolve_place(hub, "Cairo")
    return TripContract(origin="CAI", origin_city="Cairo", origin_ref=origin, destination=dest.name,
                        destination_name=dest.name, destination_ref=dest, start_date=start, end_date=end,
                        travelers=travelers, budget=Budget(amount=budget), **kw)


@pytest.fixture(scope="session")
def rome_contract():
    return anyio.run(lambda: make_contract("Rome", date(2026, 10, 12), date(2026, 10, 18), 2, 3500.0))


@pytest.fixture(scope="session")
def rome_research(rome_contract):
    return anyio.run(lambda: research.gather_all(MCPHub("inmemory"), rome_contract, [], ["food", "history", "photography"]))


@pytest.fixture
def profile():
    return TravelerProfile(food_preferences=["italian"], activity_preferences=["food", "history", "photography"],
                           preferred_wake_up_time="08:30")


@pytest.fixture(autouse=True)
def _fresh_llm_cache():
    """Each test starts with an empty model-answer cache (tests script different answers to the same prompt)."""
    from travel_agent import llm

    llm._PARSE_CACHE.clear()
    yield
