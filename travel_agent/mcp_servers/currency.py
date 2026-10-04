"""Currency MCP server (Frankfurter v2)."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .. import net
from ..providers import currency
from . import envelope, error

server = MCPServer("currency_mcp", instructions="Central-bank exchange rates and conversions.")


@server.tool()
async def get_exchange_rates(base: str, quotes: list[str]) -> dict:
    """Units of each quote currency per 1 base."""
    try:
        rates, meta = await currency.rates(base, quotes, allow_missing=True)
    except net.ProviderError as exc:
        return error("exchange_rates", "currency_mcp", {"base": base}, str(exc))
    missing = sorted({q.upper() for q in quotes} - set(rates))
    return envelope("exchange_rates", "currency_mcp", {"base": base, "quotes": quotes}, rates=rates, provider=meta.provider,
                    missing=missing)


@server.tool()
async def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    """Convert an amount between currencies."""
    q = {"amount": amount, "from": from_currency, "to": to_currency}
    try:
        value, rate, meta = await currency.convert(amount, from_currency, to_currency)
    except net.ProviderError as exc:
        return error("currency_conversion", "currency_mcp", q, str(exc))
    return envelope("currency_conversion", "currency_mcp", q, converted=round(value, 2), rate=rate, provider=meta.provider)


if __name__ == "__main__":
    server.run("stdio")
