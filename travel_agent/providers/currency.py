"""Exchange rates: Frankfurter v2 (central banks, no key) first, open.er-api.com for any currency it lacks.

A currency neither source knows is reported as missing - never silently treated as 1:1 with another one.
"""

from __future__ import annotations

from .. import net
from ..models import Metadata

URL = "https://api.frankfurter.dev/v2/rates"
BACKUP_URL = "https://open.er-api.com/v6/latest/{base}"


async def _frankfurter(base: str, wanted: list[str]) -> tuple[dict[str, float], str | None]:
    data = await net.fetch_json("frankfurter", URL, {"base": base, "quotes": ",".join(wanted)}, ttl_s=6 * net.HOUR)
    out, as_of = {}, None
    for row in data:
        out[row["quote"].upper()] = float(row["rate"])
        as_of = row.get("date")
    return out, as_of


async def _backup(base: str, wanted: list[str]) -> tuple[dict[str, float], str | None]:
    data = await net.fetch_json("open_er_api", BACKUP_URL.format(base=base), {}, ttl_s=6 * net.HOUR)
    if data.get("result") != "success":
        raise net.ProviderError(f"open.er-api: {data.get('error-type', 'error')}")
    rates = data.get("rates") or {}
    return {q: float(rates[q]) for q in wanted if rates.get(q)}, data.get("time_last_update_utc")


async def rates(base: str, quotes: list[str], allow_missing: bool = False) -> tuple[dict[str, float], Metadata]:
    """Units of each quote currency per 1 `base`. A currency with no rate raises ProviderError, unless allow_missing
    (then it is simply absent from the result and the caller reports it)."""
    base = base.upper()
    wanted = sorted({q.upper() for q in quotes if q.upper() != base})
    out = {base: 1.0}
    if not wanted:
        return out, Metadata(source="currency_mcp", provider="identity", confidence=1.0)
    providers, errors = [], []
    try:
        got, as_of = await _frankfurter(base, wanted)
        out.update(got)
        providers.append(f"Frankfurter (central-bank rates, {as_of})")
    except net.ProviderError as exc:
        errors.append(str(exc))
    missing = [q for q in wanted if q not in out]
    if missing:
        try:
            got, as_of = await _backup(base, missing)
            if got:
                out.update(got)
                providers.append(f"open.er-api.com ({as_of}) for {', '.join(sorted(got))}")
        except net.ProviderError as exc:
            errors.append(str(exc))
    missing = [q for q in wanted if q not in out]
    if missing and (not allow_missing or len(out) == 1):
        raise net.ProviderError(f"no exchange rate for {', '.join(missing)}" + (f" ({'; '.join(errors)})" if errors else ""))
    return out, Metadata(source="currency_mcp", provider=" + ".join(providers), confidence=0.95,
                         source_url="https://frankfurter.dev")


async def convert(amount: float, from_cur: str, to_cur: str) -> tuple[float, float, Metadata]:
    r, meta = await rates(from_cur, [to_cur])
    rate = r[to_cur.upper()]
    return amount * rate, rate, meta
