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


if __name__ == "__main__":
    server.run("stdio")
