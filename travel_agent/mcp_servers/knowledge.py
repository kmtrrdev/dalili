"""Knowledge MCP server: place resolution + Wikivoyage destination knowledge (RAG)."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .. import knowledge, net
from ..providers import geo, local_prices, menus, official_prices
from . import envelope, error

server = MCPServer("knowledge_mcp", instructions="Resolve places; stable destination knowledge from Wikivoyage.")


@server.tool()
async def resolve_place(query: str) -> dict:
    """City / country / airport text -> coordinates, timezone, Google city id and airports."""
    try:
        ref = await geo.resolve_place(query)
    except net.ProviderError as exc:
        return error("place", "knowledge_mcp", {"query": query}, str(exc))
    return envelope("place", "knowledge_mcp", {"query": query}, place=ref)


@server.tool()
async def resolve_destination(query: str) -> dict:
    """A country / region or city to explore trips to -> {kind: region|city, id, name} (Google ids)."""
    try:
        return envelope("destination", "knowledge_mcp", {"query": query}, result=await geo.resolve_destination(query))
    except net.ProviderError as exc:
        return error("destination", "knowledge_mcp", {"query": query}, str(exc))


@server.tool()
async def get_destination_info(city: str, country: str, country_code: str) -> dict:
    """Currency, languages, dinner norms and the Wikivoyage guide for a destination."""
    q = {"city": city, "country": country}
    meta = geo.country_meta(country_code)
    extra = {}
    try:
        guide = await knowledge.destination_guide(city, country, meta["languages"])
    except net.ProviderError as exc:
        # The guide is enrichment, not a requirement: currency, languages and dinner norms come from country data,
        # so the trip still plans when Wikivoyage is down (tips and local prices are simply missing).
        guide, extra = {"source": None, "overview": "", "sections": {}, "local_tips": [], "phrases": [],
                        "emergency": []}, {"degraded": f"guide unavailable: {exc}"}
    return envelope("destination_info", "knowledge_mcp", q, info={
        "name": city, "country": country, "country_code": country_code.upper(), "currency": meta["currency"],
        "languages": meta["languages"], "dinner_time": geo.dinner_time(country_code), "knowledge": guide}, **extra)


@server.tool()
async def get_local_prices(city: str, country: str, local_currency: str) -> dict:
    """Published local prices from Wikivoyage (free): entry / restaurant prices from the city's listings (with
    their edit date) and public-transport, taxi and airport fares quoted verbatim from the guide."""
    q = {"city": city, "country": country}
    try:
        items = await local_prices.listings(city, country)
        text = await local_prices.guide_transport_text(city, country)
    except net.ProviderError as exc:
        return error("local_prices", "knowledge_mcp", q, str(exc))
    priced = []
    for it in items:
        amount, cur, free = local_prices.parse_price(it["price_text"], local_currency)
        if amount is not None:
            priced.append({**it, "amount": amount, "currency": cur, "free": free})
    return envelope("local_prices", "knowledge_mcp", q, listings=priced, listings_total=len(items),
                    tariffs=await local_prices.tariffs(city, text))


@server.tool()
async def get_official_price(name: str, kind: str, website: str) -> dict:
    """The price published on a place's own website: adult entry (attraction) or main-course range (restaurant),
    with the verbatim quote and the page it came from. result=None when the site doesn't state it."""
    q = {"name": name, "kind": kind}
    if kind not in ("attraction", "restaurant"):
        return error("official_price", "knowledge_mcp", q, "kind must be attraction or restaurant")
    return envelope("official_price", "knowledge_mcp", q,
                    result=await official_prices.official_price(name, kind, website))  # type: ignore[arg-type]


@server.tool()
async def get_menu_price(name: str, city: str, kind: str = "restaurant", address: str = "",
                         local_currency: str = "USD") -> dict:
    """A restaurant's menu found by web search: link to the menu and a typical meal per person (main + drink),
    built only from prices quoted in the sources. result=None when no real menu prices are found."""
    q = {"name": name, "city": city}
    return envelope("menu_price", "knowledge_mcp", q, result=await menus.menu_price(name, city, kind, address, local_currency))


if __name__ == "__main__":
    server.run("stdio")
