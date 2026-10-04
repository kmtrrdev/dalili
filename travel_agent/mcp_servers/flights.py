"""Flight MCP server: Google Flights, Flights Autocomplete and Flights Deals (SerpApi)."""

from __future__ import annotations

from datetime import date

from mcp.server.mcpserver import MCPServer

from .. import net
from ..providers import ai_fallback, flights, geo
from . import envelope, error

server = MCPServer("flight_mcp", instructions="Real flight search via Google Flights. Planning only - never books.")


@server.tool()
async def search_flights(origin: str, destination: str, departure_date: str, return_date: str, currency: str = "USD",
                         origin_timezone: str = "UTC", destination_timezone: str = "UTC", travel_class: int = 1,
                         origin_name: str = "", destination_name: str = "", return_to: str | None = None,
                         return_timezone: str | None = None, return_name: str = "") -> dict:
    """One-way searches in both directions. origin/destination: IATA code or Google city id (e.g. /m/06c62).
    return_to (open-jaw): fly home to another city than the origin. Prices are per person in `currency`."""
    q = {"origin": origin, "destination": destination, "departure_date": departure_date, "return_date": return_date,
         "currency": currency, "return_to": return_to}
    home, home_tz, home_name = (return_to, return_timezone or origin_timezone, return_name or origin_name) if return_to \
        else (origin, origin_timezone, origin_name)
    # Each direction stands on its own: a failed return search never throws away the live outbound results.
    live_errors: dict[str, str] = {}
    try:
        out, out_ins = await flights.search_one_way(origin, destination, date.fromisoformat(departure_date), currency,
                                                    "outbound", origin_timezone, destination_timezone, travel_class)
    except net.ProviderError as exc:
        out, out_ins, live_errors["outbound"] = [], {}, str(exc)
    try:
        back, back_ins = await flights.search_one_way(destination, home, date.fromisoformat(return_date), currency,
                                                      "return", destination_timezone, home_tz, travel_class)
    except net.ProviderError as exc:
        back, back_ins, live_errors["return"] = [], {}, str(exc)
    fallback = []
    if ai_fallback.available():
        # A direction that failed or came back empty: AI estimates for just that direction, clearly labelled.
        if not out:
            out = await ai_fallback.flights(origin, destination, date.fromisoformat(departure_date), "outbound",
                                            origin_timezone, destination_timezone, origin_name, destination_name)
            fallback += ["outbound"] if out else []
        if not back:
            back = await ai_fallback.flights(destination, home, date.fromisoformat(return_date), "return",
                                             destination_timezone, home_tz, destination_name, home_name)
            fallback += ["return"] if back else []
    if not out or not back:
        return error("flight_search_result", "flight_mcp", q, "; ".join(f"{d}: {e}" for d, e in live_errors.items())
                     or "no flights found")
    extra = {"fallback": "ai_knowledge", "fallback_directions": fallback} if fallback else {}
    if live_errors:
        extra["live_error"] = "; ".join(f"{d}: {e}" for d, e in live_errors.items())
    # A round-trip ticket is often cheaper than two one-ways: keep it when it beats the cheapest pair of one-ways.
    # (Only for a trip that ends where it started - an open-jaw trip is two one-ways by definition.)
    round_trips = []
    pairs = []
    if not return_to:
        try:
            pairs = await flights.search_round_trip(origin, destination, date.fromisoformat(departure_date),
                                                    date.fromisoformat(return_date), currency, origin_timezone,
                                                    destination_timezone, travel_class)
        except net.ProviderError:
            pairs = []
    live_out = [f for f in out if f.metadata.source != "ai_knowledge"]
    live_back = [f for f in back if f.metadata.source != "ai_knowledge"]
    one_way_min = (min(f.price_per_person.amount for f in live_out) + min(f.price_per_person.amount for f in live_back)
                   if live_out and live_back else float("inf"))
    for o, b, total in pairs:
        if total < one_way_min:
            round_trips.append({"outbound": o, "inbound": b,
                                "total_per_person": {"amount": total, "currency": currency.upper(), "price_type": "known",
                                                     "source": "Google Flights round-trip fare"}})
    return envelope("flight_search_result", "flight_mcp", q, outbound=out, **{"return": back}, round_trips=round_trips,
                    price_insights={"outbound": out_ins, "return": back_ins,
                                    "cheapest_one_way_pair": None if one_way_min == float("inf") else one_way_min,
                                    "cheapest_round_trip": pairs[0][2] if pairs else None}, **extra)


@server.tool()
async def search_one_way_flights(origin: str, destination: str, departure_date: str, currency: str = "USD",
                                 origin_timezone: str = "UTC", destination_timezone: str = "UTC",
                                 direction: str = "outbound", travel_class: int = 1, origin_name: str = "",
                                 destination_name: str = "") -> dict:
    """One leg of a multi-city journey. Prices are per person in `currency`."""
    q = {"origin": origin, "destination": destination, "departure_date": departure_date, "currency": currency}
    try:
        res, ins = await flights.search_one_way(origin, destination, date.fromisoformat(departure_date), currency,
                                                direction, origin_timezone, destination_timezone, travel_class)
    except net.ProviderError as exc:
        if ai_fallback.available():
            res = await ai_fallback.flights(origin, destination, date.fromisoformat(departure_date), direction,
                                            origin_timezone, destination_timezone, origin_name, destination_name)
            if res:
                return envelope("flight_search_result", "flight_mcp", q, results=res, price_insights={},
                                fallback="ai_knowledge", live_error=str(exc))
        return error("flight_search_result", "flight_mcp", q, str(exc))
    if not res and ai_fallback.available():
        # The live search answered but found nothing (e.g. a stale or partial result): estimate instead.
        est = await ai_fallback.flights(origin, destination, date.fromisoformat(departure_date), direction,
                                        origin_timezone, destination_timezone, origin_name, destination_name)
        if est:
            return envelope("flight_search_result", "flight_mcp", q, results=est, price_insights={},
                            fallback="ai_knowledge", live_error="no flights returned by the live search")
    return envelope("flight_search_result", "flight_mcp", q, results=res, price_insights=ins)


@server.tool()
async def autocomplete_airports(query: str) -> dict:
    """Resolve a city/country/airport name to Google city ids and IATA airport codes."""
    try:
        return envelope("airport_autocomplete", "flight_mcp", {"query": query}, suggestions=await geo.autocomplete(query))
    except net.ProviderError as exc:
        return error("airport_autocomplete", "flight_mcp", {"query": query}, str(exc))


@server.tool()
async def find_flight_deals(departure_id: str, currency: str = "USD") -> dict:
    """Current discounted fares from an airport/city (Google Flights Deals)."""
    try:
        return envelope("flight_deals", "flight_mcp", {"departure_id": departure_id}, deals=await flights.deals(departure_id, currency))
    except net.ProviderError as exc:
        return error("flight_deals", "flight_mcp", {"departure_id": departure_id}, str(exc))


if __name__ == "__main__":
    server.run("stdio")
