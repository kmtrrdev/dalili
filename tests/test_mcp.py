import anyio
import pytest

from travel_agent.mcp_hub import SERVERS, MCPHub

EXPECTED_TOOLS = {
    "flights": {"search_flights", "search_one_way_flights"},
    "hotels": {"search_hotels", "get_hotel_reviews", "get_hotel_offers"},
    "places": {"search_restaurants", "search_places"},
    "activities": {"search_attractions", "search_events", "get_major_events", "explore_destinations", "find_place"},
    "transport": {"get_directions", "get_airport_transfers", "get_intercity_journeys"},
    "weather": {"get_weather_forecast"},
    "currency": {"get_exchange_rates", "convert_currency"},
    "knowledge": {"resolve_place", "resolve_destination", "get_destination_info", "get_local_prices", "get_transport_fares", "get_prayer_times", "get_sacred_sites", "get_menu_price",
                  "get_official_price"},
}


@pytest.mark.parametrize("server", list(SERVERS))
def test_servers_expose_expected_tools(server):
    # Exactly the tools Dalili uses: a tool nothing calls is dead code, not a feature.
    assert EXPECTED_TOOLS[server] == set(anyio.run(MCPHub("inmemory").list_tools, server))


def test_resolve_place_real_data():
    res = anyio.run(lambda: MCPHub("inmemory").call("knowledge", "resolve_place", {"query": "Rome"}))
    place = res["place"]
    assert place["country_code"] == "IT" and place["timezone"] == "Europe/Rome" and "FCO" in place["airports"]


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
