"""When a live source is out (e.g. SerpApi quota used up) the MCP tools fall back to the AI model, clearly labelled."""

import anyio
import pytest

from travel_agent import net
from travel_agent.mcp_hub import MCPHub, MCPToolError
from travel_agent.providers import ai_fallback, flights, hotels


@pytest.fixture
def quota_gone(monkeypatch):
    async def out_of_searches(*_a, **_k):
        raise net.QuotaExceeded("serpapi HTTP 429: Your account has run out of searches.")

    monkeypatch.setattr(hotels, "search", out_of_searches)
    monkeypatch.setattr(flights, "search_one_way", out_of_searches)

    async def no_geocoder(*_a, **_k):
        return None

    monkeypatch.setattr(ai_fallback, "_geocode", no_geocoder)


def test_hotels_fall_back_to_labelled_ai_estimates(quota_gone, monkeypatch):
    async def fake_ask(system, user, schema):
        return ai_fallback.AIHotels(hotels=[ai_fallback.AIHotel(name="Steigenberger Hotel El Tahrir", neighborhood="Downtown",
                                                                 stars=4, typical_price_per_night_usd=95, lat=30.047, lon=31.236)])

    monkeypatch.setattr(ai_fallback, "available", lambda: True)
    monkeypatch.setattr(ai_fallback, "_ask", fake_ask)
    res = anyio.run(lambda: MCPHub("inmemory").call("hotels", "search_hotels", {
        "city": "Cairo", "check_in": "2026-10-15", "check_out": "2026-10-20", "adults": 1, "currency": "USD",
        "center_lat": 30.044, "center_lon": 31.236}))
    assert res["fallback"] == "ai_knowledge" and "run out of searches" in res["live_error"]
    h = res["results"][0]
    assert h["metadata"]["source"] == "ai_knowledge" and h["price_per_night"]["price_type"] == "estimated"
    assert h["total_price"]["amount"] == 95 * 5
    assert "verify" in h["metadata"]["notes"].lower()


def test_flights_fall_back_with_a_real_search_link(quota_gone, monkeypatch):
    async def fake_ask(system, user, schema):
        return ai_fallback.AIFlights(flights=[ai_fallback.AIFlight(
            airline="flyadeal", flight_number="F3 605", origin_airport="RUH", destination_airport="CAI",
            depart_time="10:15", duration_minutes=160, typical_economy_fare_usd=120)])

    monkeypatch.setattr(ai_fallback, "available", lambda: True)
    monkeypatch.setattr(ai_fallback, "_ask", fake_ask)
    res = anyio.run(lambda: MCPHub("inmemory").call("flights", "search_one_way_flights", {
        "origin": "RUH", "destination": "CAI", "departure_date": "2026-10-15", "origin_timezone": "Asia/Riyadh",
        "destination_timezone": "Africa/Cairo", "origin_name": "Riyadh", "destination_name": "Cairo"}))
    f = res["results"][0]
    assert res["fallback"] == "ai_knowledge"
    assert f["price_per_person"]["price_type"] == "estimated" and f["id"].startswith("fl_ai_")
    assert f["booking_url"].startswith("https://www.google.com/travel/flights")
    assert f["depart_at"].startswith("2026-10-15T10:15") and f["arrive_at"].startswith("2026-10-15T12:55")


def test_without_a_model_the_live_error_is_reported(quota_gone, monkeypatch):
    monkeypatch.setattr(ai_fallback, "available", lambda: False)
    with pytest.raises(MCPToolError, match="run out of searches"):
        anyio.run(lambda: MCPHub("inmemory").call("hotels", "search_hotels", {
            "city": "Cairo", "check_in": "2026-10-15", "check_out": "2026-10-20", "adults": 1, "currency": "USD",
            "center_lat": 30.044, "center_lon": 31.236}))
