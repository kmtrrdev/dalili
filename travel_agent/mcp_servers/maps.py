"""Maps / Transportation MCP server: Google Maps Directions (SerpApi) + openrouteservice matrices."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .. import net
from ..models import GeoPoint
from ..providers import routing
from . import envelope, error

server = MCPServer("transport_mcp", instructions="Walking/driving/transit times between points and airport transfers.")


@server.tool()
async def get_directions(start: str, end_lat: float, end_lon: float, travel_mode: int = 6) -> dict:
    """Google Maps directions. travel_mode: 6 best, 0 driving, 3 transit, 2 walking, 1 cycling."""
    q = {"start": start, "end": [end_lat, end_lon], "travel_mode": travel_mode}
    try:
        return envelope("directions", "transport_mcp", q,
                        routes=await routing.directions(start, GeoPoint(lat=end_lat, lon=end_lon), travel_mode))
    except net.ProviderError as exc:
        return error("directions", "transport_mcp", q, str(exc))


@server.tool()
async def get_airport_transfers(airport_code: str, airport_name: str, lat: float, lon: float, currency: str,
                                fares: dict[str, float] | None = None, fixed_fares: list[dict] | None = None) -> dict:
    """Airport -> centre by public transport and by taxi (Google Maps times). Fares: Google's transit fare when
    shown, fixed fares quoted in the city guide, the official taxi tariff x road km, else a labelled estimate."""
    q = {"airport": airport_code}
    try:
        res = await routing.airport_transfers(airport_code, airport_name, GeoPoint(lat=lat, lon=lon), fares or {},
                                              currency, fixed_fares)
    except net.ProviderError as exc:
        return error("airport_transfers", "transport_mcp", q, str(exc))
    return envelope("airport_transfers", "transport_mcp", q, results=res)


@server.tool()
async def get_intercity_journeys(from_city: str, from_lat: float, from_lon: float, to_city: str, to_lat: float,
                                 to_lon: float, travel_date: str, from_timezone: str = "UTC",
                                 to_timezone: str = "UTC") -> dict:
    """Train / coach options between two cities of a multi-city trip (Google Maps travel time, estimated fare)."""
    from datetime import date

    q = {"from": from_city, "to": to_city, "date": travel_date}
    res = await routing.intercity_journeys(from_city, GeoPoint(lat=from_lat, lon=from_lon), to_city,
                                           GeoPoint(lat=to_lat, lon=to_lon), date.fromisoformat(travel_date),
                                           from_timezone, to_timezone)
    return envelope("intercity_journeys", "transport_mcp", q, results=res)


if __name__ == "__main__":
    server.run("stdio")
