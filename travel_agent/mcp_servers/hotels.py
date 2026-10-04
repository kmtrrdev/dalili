"""Hotel MCP server: Google Hotels, Hotels Autocomplete, Hotels Reviews, Hotels Photos (SerpApi)."""

from __future__ import annotations

from datetime import date

from mcp.server.mcpserver import MCPServer

from .. import net
from ..agents import review_analyst
from ..models import GeoPoint
from ..providers import ai_fallback, hotels
from . import envelope, error

server = MCPServer("hotel_mcp", instructions="Real hotel prices, reviews and photos from Google Hotels. No booking.")


@server.tool()
async def search_hotels(city: str, check_in: str, check_out: str, adults: int, currency: str, center_lat: float,
                        center_lon: float, query: str | None = None) -> dict:
    """Hotels with real nightly prices for the dates (per room, in `currency`)."""
    q = {"city": city, "check_in": check_in, "check_out": check_out, "adults": adults, "currency": currency, "query": query}
    try:
        res = await hotels.search(city, date.fromisoformat(check_in), date.fromisoformat(check_out), adults, currency,
                                  GeoPoint(lat=center_lat, lon=center_lon), query)
    except net.ProviderError as exc:
        # Live search failed (e.g. quota used up): fall back to the AI model's knowledge, clearly labelled.
        if ai_fallback.available():
            res = await ai_fallback.hotels(city, date.fromisoformat(check_in), date.fromisoformat(check_out), adults,
                                           GeoPoint(lat=center_lat, lon=center_lon))
            if res:
                return envelope("hotel_search_result", "hotel_mcp", q, results=res, fallback="ai_knowledge",
                                live_error=str(exc))
        return error("hotel_search_result", "hotel_mcp", q, str(exc))
    return envelope("hotel_search_result", "hotel_mcp", q, results=res)


@server.tool()
async def get_hotel_offers(property_token: str, city: str, check_in: str, check_out: str, adults: int,
                           currency: str) -> dict:
    """Live booking offers for one hotel and exact dates: booking site, price per night, total and a direct link
    to that site's booking page (the same price the plan used)."""
    q = {"property_token": property_token, "check_in": check_in, "check_out": check_out}
    try:
        res = await hotels.offers(property_token, city, date.fromisoformat(check_in), date.fromisoformat(check_out),
                                  adults, currency)
    except net.ProviderError as exc:
        return error("hotel_offers", "hotel_mcp", q, str(exc))
    return envelope("hotel_offers", "hotel_mcp", q, **res)


@server.tool()
async def get_hotel_reviews(property_token: str, hotel_name: str = "") -> dict:
    """Recent guest reviews plus what they say: aspect-based insights from the review-analyst agent
    (when a model is available) and a noise assessment backed by quotes."""
    try:
        items = await hotels.reviews(property_token)
    except net.ProviderError as exc:
        return error("hotel_reviews", "hotel_mcp", {"property_token": property_token}, str(exc))
    level, evidence = hotels.noise_from_reviews(items)
    insights = await review_analyst.analyze(hotel_name, items) if hotel_name else None
    if insights and insights.noise_level != "unknown":  # the model reads context ("quiet despite the bars") better
        level, evidence = insights.noise_level, insights.noise_evidence or evidence
    return envelope("hotel_reviews", "hotel_mcp", {"property_token": property_token}, reviews=items,
                    noise_level=level, noise_evidence=evidence,
                    insights=insights.model_dump() if insights else None)


@server.tool()
async def get_hotel_photos(property_token: str) -> dict:
    """Photo gallery of a hotel."""
    try:
        return envelope("hotel_photos", "hotel_mcp", {"property_token": property_token}, photos=await hotels.photos(property_token))
    except net.ProviderError as exc:
        return error("hotel_photos", "hotel_mcp", {"property_token": property_token}, str(exc))


@server.tool()
async def autocomplete_hotels(query: str) -> dict:
    """Hotel / area name suggestions."""
    try:
        return envelope("hotel_autocomplete", "hotel_mcp", {"query": query}, suggestions=await hotels.autocomplete(query))
    except net.ProviderError as exc:
        return error("hotel_autocomplete", "hotel_mcp", {"query": query}, str(exc))


if __name__ == "__main__":
    server.run("stdio")
