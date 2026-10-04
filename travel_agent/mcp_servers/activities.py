"""Activities MCP server: attractions (Google Maps + OpenTripMap), Google Events, Google Travel Explore."""

from __future__ import annotations

from datetime import date

from mcp.server.mcpserver import MCPServer

from .. import net
from ..models import GeoPoint
from ..providers import ai_fallback, events, flights, places
from . import envelope, error

server = MCPServer("activities_mcp", instructions="Attractions, hidden gems, local events and destination ideas.")


@server.tool()
async def search_attractions(city: str, lat: float, lon: float, local_currency: str, interests: list[str] | None = None,
                             country: str | None = None, days: int = 7) -> dict:
    """Top sights in and around the city (Google Maps, incl. famous day trips within ~250 km)
    plus less-visited places (OpenTripMap), with hours, popularity and distance from the centre.
    `days` sizes the search: short trips need fewer (paid) searches."""
    q = {"city": city, "interests": interests, "country": country, "days": days}
    try:
        res = await places.attractions(city, GeoPoint(lat=lat, lon=lon), local_currency, interests or [], country, days)
    except net.ProviderError as exc:
        if ai_fallback.available():  # live search failed: AI suggestions, clearly labelled
            res = await ai_fallback.attractions(city, GeoPoint(lat=lat, lon=lon), interests or [], country)
            if res:
                return envelope("activity_search_result", "activities_mcp", q, results=res, fallback="ai_knowledge",
                                live_error=str(exc))
        return error("activity_search_result", "activities_mcp", q, str(exc))
    return envelope("activity_search_result", "activities_mcp", q, results=res)


@server.tool()
async def find_place(name: str, city: str, lat: float, lon: float, local_currency: str, zoom: int = 11) -> dict:
    """One specific place the traveller named (e.g. 'Vatican Museums'), with hours, rating and distance.
    city="" searches by name only around (lat, lon) - use a low zoom to cover a whole region."""
    q = {"name": name, "city": city}
    try:
        p = await places.find_place(name, city, GeoPoint(lat=lat, lon=lon), local_currency, zoom)
    except net.ProviderError as exc:
        if ai_fallback.available():
            p = await ai_fallback.find_place(name, city, GeoPoint(lat=lat, lon=lon))
            if p:
                return envelope("place_lookup_result", "activities_mcp", q, result=p, fallback="ai_knowledge",
                                live_error=str(exc))
        return error("place_lookup_result", "activities_mcp", q, str(exc))
    return envelope("place_lookup_result", "activities_mcp", q, result=p)


@server.tool()
async def search_events(city: str, lat: float, lon: float, start_date: str, end_date: str) -> dict:
    """Concerts, exhibitions and festivals happening during the trip."""
    q = {"city": city, "start_date": start_date, "end_date": end_date}
    try:
        res = await events.events(city, GeoPoint(lat=lat, lon=lon), date.fromisoformat(start_date), date.fromisoformat(end_date))
    except net.ProviderError as exc:
        return error("event_search_result", "activities_mcp", q, str(exc))
    return envelope("event_search_result", "activities_mcp", q, results=res)


@server.tool()
async def explore_destinations(departure_id: str, currency: str = "USD", month: int | None = None,
                               travel_duration: int | None = None, interest: str | None = None,
                               outbound_date: str | None = None, return_date: str | None = None,
                               adults: int | None = None, stops: int | None = None,
                               max_duration: int | None = None, arrival_id: str | None = None,
                               arrival_area_id: str | None = None) -> dict:
    """Destination ideas with flight and hotel prices from an origin (Google Travel Explore).
    Exact dates (outbound_date + return_date) replace month/travel_duration; stops=1 = nonstop only;
    max_duration = longest acceptable flight in minutes; interest = a Google topic id (beaches, museums...);
    arrival_area_id = only destinations in this country / region; arrival_id = only this city."""
    q = {"departure_id": departure_id, "month": month, "interest": interest, "outbound_date": outbound_date,
         "return_date": return_date, "stops": stops, "max_duration": max_duration, "arrival_id": arrival_id,
         "arrival_area_id": arrival_area_id}
    try:
        return envelope("explore_result", "activities_mcp", q,
                        destinations=await flights.explore(departure_id, currency, month, travel_duration, interest,
                                                           outbound_date, return_date, adults, stops, max_duration,
                                                           arrival_id, arrival_area_id))
    except net.ProviderError as exc:
        return error("explore_result", "activities_mcp", q, str(exc))


if __name__ == "__main__":
    server.run("stdio")
