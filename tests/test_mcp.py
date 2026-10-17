import anyio
import pytest

from travel_agent.mcp_hub import SERVERS, MCPHub

EXPECTED_TOOLS = {
    "flights": {"search_flights", "autocomplete_airports", "find_flight_deals"},
    "hotels": {"search_hotels", "get_hotel_reviews", "get_hotel_photos", "autocomplete_hotels"},
    "places": {"search_restaurants", "search_places", "search_local", "get_place_reviews"},
    "activities": {"search_attractions", "search_events", "explore_destinations"},
    "transport": {"get_directions", "travel_time_matrix", "get_airport_transfers"},
    "weather": {"get_weather_forecast", "get_weather_risk"},
    "currency": {"get_exchange_rates", "convert_currency"},
    "knowledge": {"resolve_place", "get_destination_info", "search_travel_knowledge"},
}


@pytest.mark.parametrize("server", list(SERVERS))
def test_servers_expose_expected_tools(server):
    assert EXPECTED_TOOLS[server] <= set(anyio.run(MCPHub("inmemory").list_tools, server))


def test_resolve_place_real_data():
    res = anyio.run(lambda: MCPHub("inmemory").call("knowledge", "resolve_place", {"query": "Rome"}))
    place = res["place"]
    assert place["country_code"] == "IT" and place["timezone"] == "Europe/Rome" and "FCO" in place["airports"]


def test_guide_search_returns_passages():
    res = anyio.run(lambda: MCPHub("inmemory").call("knowledge", "search_travel_knowledge", {
        "city": "Rome", "country": "Italy", "country_code": "IT", "query": "tipping in restaurants"}))
    assert res["source"] == "knowledge_mcp" and isinstance(res["results"], list)


def test_research_is_real_and_grounded(rome_research):
    r = rome_research
    assert r.flights_outbound and all(f.metadata.provider.startswith("Google Flights") for f in r.flights_outbound)
    assert all(f.price_per_person.price_type == "known" for f in r.flights_outbound)
    assert r.hotels and all(h.price_per_night.price_type == "known" for h in r.hotels)
    assert len(r.restaurants) >= 15 and len(r.attractions) >= 15
    assert any(a.metadata.provider == "OpenTripMap" for a in r.attractions), "hidden gems from a second source"
    assert r.fx_rates.get("EUR", 0) > 0 and r.airport_transfers and r.weather
    assert r.destination_info["currency"] == "EUR" and r.destination_info["knowledge"]["sections"]


def test_stdio_transport_matches_inmemory():
    args = {"query": "Rome"}
    a = anyio.run(lambda: MCPHub("inmemory").call("knowledge", "resolve_place", args))
    b = anyio.run(lambda: MCPHub("stdio").call("knowledge", "resolve_place", args))
    assert a["place"] == b["place"]
