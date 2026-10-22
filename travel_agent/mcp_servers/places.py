"""Places / Restaurant MCP server: Google Maps, Google Local, Google Maps Reviews (SerpApi)."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .. import net
from ..models import GeoPoint
from ..providers import ai_fallback, places
from . import envelope, error

server = MCPServer("places_mcp", instructions="Restaurants, cafes and places from Google Maps with real hours and ratings.")


@server.tool()
async def search_restaurants(city: str, lat: float, lon: float, local_currency: str, dietary: list[str] | None = None) -> dict:
    """Restaurants and cafes around a point, with opening hours, ratings and price ranges."""
    q = {"city": city, "lat": lat, "lon": lon, "dietary": dietary}
    try:
        res = await places.restaurants(city, GeoPoint(lat=lat, lon=lon), local_currency, dietary or [])
    except net.ProviderError as exc:
        if ai_fallback.available():  # live search failed: AI suggestions, clearly labelled
            res = await ai_fallback.restaurants(city, GeoPoint(lat=lat, lon=lon), dietary or [])
            if res:
                return envelope("restaurant_search_result", "places_mcp", q, results=res, fallback="ai_knowledge",
                                live_error=str(exc))
        return error("restaurant_search_result", "places_mcp", q, str(exc))
    return envelope("restaurant_search_result", "places_mcp", q, results=res)


@server.tool()
async def search_places(query: str, lat: float, lon: float, zoom: int = 14) -> dict:
    """Free Google Maps search around a point (e.g. 'gelato', 'rooftop bar')."""
    q = {"query": query, "lat": lat, "lon": lon}
    try:
        return envelope("place_search_result", "places_mcp", q,
                        results=await places.maps_search(query, GeoPoint(lat=lat, lon=lon), zoom))
    except net.ProviderError as exc:
        return error("place_search_result", "places_mcp", q, str(exc))


if __name__ == "__main__":
    server.run("stdio")
