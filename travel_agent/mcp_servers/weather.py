"""Weather MCP server (Open-Meteo)."""

from __future__ import annotations

from datetime import date

from mcp.server.mcpserver import MCPServer

from .. import net
from ..providers.weather import get_weather
from . import envelope, error

server = MCPServer("weather_mcp", instructions="Daily forecast, or last year's observed weather beyond the forecast range.")


@server.tool()
async def get_weather_forecast(lat: float, lon: float, start_date: str, end_date: str) -> dict:
    """Daily weather for the trip dates."""
    q = {"lat": lat, "lon": lon, "start_date": start_date, "end_date": end_date}
    try:
        days = await get_weather(lat, lon, date.fromisoformat(start_date), date.fromisoformat(end_date))
    except net.ProviderError as exc:
        return error("weather_forecast", "weather_mcp", q, str(exc))
    return envelope("weather_forecast", "weather_mcp", q, days=days)


@server.tool()
async def get_weather_risk(lat: float, lon: float, on_date: str) -> dict:
    """Weather risk (low/medium/high) for outdoor plans on one date."""
    d = date.fromisoformat(on_date)
    try:
        day = (await get_weather(lat, lon, d, d))[0]
    except (net.ProviderError, IndexError) as exc:
        return error("weather_risk", "weather_mcp", {"on_date": on_date}, str(exc))
    return envelope("weather_risk", "weather_mcp", {"on_date": on_date}, risk=day.risk, condition=day.condition,
                    precipitation_probability=day.precipitation_probability, provider=day.metadata.provider)


if __name__ == "__main__":
    server.run("stdio")
