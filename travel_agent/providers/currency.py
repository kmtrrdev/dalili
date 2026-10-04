"""Exchange rates from Frankfurter v2 (no key; 200+ currencies from central banks)."""

from __future__ import annotations

from .. import net
from ..models import Metadata

URL = "https://api.frankfurter.dev/v2/rates"


async def rates(base: str, quotes: list[str]) -> tuple[dict[str, float], Metadata]:
    """Units of each quote currency per 1 `base`."""
    base = base.upper()
    wanted = sorted({q.upper() for q in quotes if q.upper() != base})
    out = {base: 1.0}
    if not wanted:
        return out, Metadata(source="currency_mcp", provider="identity", confidence=1.0)
    data = await net.fetch_json("frankfurter", URL, {"base": base, "quotes": ",".join(wanted)}, ttl_s=6 * net.HOUR)
    as_of = None
    for row in data:
        out[row["quote"].upper()] = float(row["rate"])
        as_of = row.get("date")
    missing = [q for q in wanted if q not in out]
    if missing:
        raise net.ProviderError(f"Frankfurter has no rate for {', '.join(missing)}")
    return out, Metadata(source="currency_mcp", provider=f"Frankfurter (central-bank rates, {as_of})", confidence=0.95,
                         source_url="https://frankfurter.dev")


async def to_user_rates(user_currency: str, currencies: list[str]) -> tuple[dict[str, float], Metadata]:
    """Multipliers that convert an amount in each currency into the user's currency."""
    user = user_currency.upper()
    per_user, meta = await rates(user, currencies)
    return {c: (1.0 / v if c != user else 1.0) for c, v in per_user.items()}, meta


async def convert(amount: float, from_cur: str, to_cur: str) -> tuple[float, float, Metadata]:
    r, meta = await rates(from_cur, [to_cur])
    rate = r[to_cur.upper()]
    return amount * rate, rate, meta
