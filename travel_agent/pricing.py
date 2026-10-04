"""Price research: every price goes through a cascade of sources, most certain first.

Entry tickets:  Google Maps listing  ->  the place's official website (model reads the price page, verbatim
                quote required)  ->  Wikivoyage listing edited < 3 years ago  ->  AI estimate for that
                specific place  ->  generic category estimate
Restaurants:    Google price range  ->  Wikivoyage listing  ->  the restaurant's own menu page  ->  its menu found by
                web search (typical meal per person + menu link)  ->  AI estimate
Transport:      Google Maps transit fare  ->  official tariff quoted in the city guide  ->  AI estimate

Steps 1-3 (Google, Wikivoyage, guide tariffs) run in research.enrich / apply_local_prices. This module adds
the official websites and the AI estimates. When two independent published sources agree (within 15%)
the price is marked as confirmed. Every price keeps its source; estimates are never shown as verified.
Only the menu searches cost SerpApi credits (one per restaurant); everything is cached for 30 days.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from . import llm, net
from .mcp_hub import MCPHub, MCPToolError
from .models import Money, Place, ResearchBundle, TripContract
from .providers import ai_fallback

log = logging.getLogger(__name__)

OFFICIAL_ATTRACTIONS = 12   # likely picks checked on their own website (per city)
OFFICIAL_RESTAURANTS = 8
MENU_SEARCHES = 10          # likely restaurant picks whose menu is searched on the web (SerpApi, per city)
CONCURRENCY = 6
TIME_LIMIT_S = 35           # official-site checks stop here; whatever is found by then is used


def _host(url: str) -> str:
    return (urlparse(url).hostname or url).removeprefix("www.")


def _agrees(a: Money, amount: float, currency: str) -> bool:
    return a.currency.upper() == currency.upper() and a.amount > 0 and abs(a.amount - amount) / a.amount <= 0.15


def _candidates(bundle: ResearchBundle, scale: float) -> tuple[list[Place], list[Place]]:
    """Places whose price is not yet published by Google / a recent Wikivoyage edit, most likely picks first."""
    def unpriced(p: Place) -> bool:
        return not p.price_known and bool(p.website) and "wikipedia.org" not in (p.website or "") and not p.dates

    atts = sorted((p for p in bundle.attractions if unpriced(p)),
                  key=lambda p: (p.popularity != "must_see", -(p.reviews_count or 0)))
    rests = sorted((p for p in bundle.restaurants if unpriced(p)),
                   key=lambda p: -(p.rating * min(p.reviews_count or 0, 3000) ** 0.25))
    return atts[:max(3, int(OFFICIAL_ATTRACTIONS * scale))], rests[:max(2, int(OFFICIAL_RESTAURANTS * scale))]


def _apply_official(p: Place, res: dict) -> None:
    site = _host(res["page"])
    if p.kind in ("restaurant", "cafe"):
        low, high = res["amount"], res.get("amount_max") or res["amount"]
        mid = round((low + high) / 2, 2)
        span = f"{low:g}–{high:g}" if high != low else f"{low:g}"
        p.cost_per_person = Money(amount=mid, currency=res["currency"], price_type="range",
                                  source=f"Official menu ({site}) · mains {span} {res['currency']}")
    else:
        confirmed = ""
        prev = p.cost_per_person
        if prev.source and prev.source.startswith("Wikivoyage") and _agrees(prev, res["amount"], res["currency"]):
            confirmed = " · confirmed by Wikivoyage"
        p.cost_per_person = Money(amount=res["amount"], currency=res["currency"], price_type="known",
                                  source=f"Official website ({site}){confirmed}")
        what = "Free entry" if res.get("free") else f"Adult entry {res['amount']:g} {res['currency']}"
        p.notes = f'{what} - official website: "{(res.get("quote") or "")[:140]}".'
    p.price_known = True
    p.website = p.website or res["page"]


async def _official(hub: MCPHub, bundle: ResearchBundle, scale: float) -> int:
    atts, rests = _candidates(bundle, scale)
    gate = asyncio.Semaphore(CONCURRENCY)
    found = 0

    async def one(p: Place, kind: str) -> None:
        nonlocal found
        async with gate:
            try:
                res = await hub.call("knowledge", "get_official_price", {"name": p.name, "kind": kind, "website": p.website})
            except MCPToolError as exc:
                log.info("official price %s: %s", p.name, exc)
                return
        if res.get("result"):
            _apply_official(p, res["result"])
            found += 1

    tasks = [asyncio.create_task(one(p, "attraction")) for p in atts] + \
            [asyncio.create_task(one(p, "restaurant")) for p in rests]
    if tasks:
        done, pending = await asyncio.wait(tasks, timeout=TIME_LIMIT_S)
        for t in pending:
            t.cancel()
    return found


async def _menus(hub: MCPHub, bundle: ResearchBundle, contract: TripContract, skip: set[str], scale: float) -> int:
    """Web-searched menus for the likeliest restaurant picks that still have no published price: a menu link and
    a typical meal per person built from the prices on it (one SerpApi search each, cached 30 days)."""
    city = bundle.destination_info.get("name") or contract.destination
    local = bundle.destination_info.get("currency", "USD")
    todo = sorted((p for p in bundle.restaurants if not p.price_known and p.id not in skip and not p.dates),
                  key=lambda p: -(p.rating * min(p.reviews_count or 0, 3000) ** 0.25))[:max(3, int(MENU_SEARCHES * scale))]
    net.allow_extra_calls(len(todo))  # menu searches on top of the turn's flight / hotel / places searches
    gate = asyncio.Semaphore(CONCURRENCY)
    found = 0

    async def one(p: Place) -> None:
        nonlocal found
        async with gate:
            try:
                res = await hub.call("knowledge", "get_menu_price", {"name": p.name, "city": city, "kind": p.kind, "address": p.address or "",
                                                                            "local_currency": local})
            except MCPToolError as exc:
                log.info("menu price %s: %s", p.name, exc)
                return
        r = res.get("result")
        if r and not p.price_known:  # the official site may have answered meanwhile
            p.cost_per_person = Money(amount=r["amount"], currency=r["currency"], price_type="range",
                                      source=(f"Google · {r['basis']}" if r.get("google") else
                                              f"Menu ({_host(r['menu_url']) if r.get('menu_url') else 'web search'}) · "
                                              f"typical meal ≈ {r['amount']:g} {r['currency']}: {r['basis']}"))
            p.menu_url = r.get("menu_url")
            p.price_known = True
            found += 1

    tasks = [asyncio.create_task(one(p)) for p in todo]
    if tasks:
        _, pending = await asyncio.wait(tasks, timeout=TIME_LIMIT_S)
        for t in pending:
            t.cancel()
    return found


def _unpriced(bundle: ResearchBundle) -> list[Place]:
    return [p for p in bundle.attractions + bundle.restaurants
            if not p.price_known and not p.dates and not (p.cost_per_person.source or "").startswith("Wikivoyage")]


async def _ai_guess(bundle: ResearchBundle, contract: TripContract) -> ai_fallback.CityPriceGuess | None:
    """The model's typical price for every place no published source prices yet (and transport if unverified).
    Runs alongside the official-site checks; official prices found meanwhile simply override it."""
    info = bundle.destination_info
    brief = [{"name": p.name, "type": p.kind, "categories": p.categories[:3], "cuisine": p.cuisine[:2],
              "price_level": p.price_level} for p in _unpriced(bundle)]
    return await ai_fallback.estimate_prices(info.get("name") or contract.destination, info.get("country", ""),
                                             info.get("currency", "USD"), brief,
                                             "transit_verified" not in bundle.fares, "taxi_verified" not in bundle.fares)


def _apply_ai(bundle: ResearchBundle, guess: ai_fallback.CityPriceGuess | None) -> int:
    if guess is None:
        return 0
    todo = _unpriced(bundle)  # recomputed: places priced by their official site meanwhile keep that price
    need_transit = "transit_verified" not in bundle.fares
    need_taxi = "taxi_verified" not in bundle.fares
    cur = (guess.currency or bundle.destination_info.get("currency", "USD")).upper()
    by_name = {g.name.strip().lower(): g for g in guess.places}
    n = 0
    for p in todo:
        g = by_name.get(p.name.strip().lower())
        if g is None or g.amount < 0:
            continue
        low = " · low confidence" if g.confidence == "low" else ""
        p.cost_per_person = Money(amount=round(g.amount, 2), currency=cur, price_type="estimated",
                                  source=f"AI estimate · {g.basis[:40]}{low}")
        n += 1
    rate = bundle.fx_rates.get(cur)
    if rate:
        if need_transit and guess.transit_single_ticket:
            bundle.fares["transit"], bundle.fares["transit_ai"] = round(guess.transit_single_ticket * rate, 2), 1.0
            bundle.fare_sources["transit"] = f"AI estimate: single ticket ≈ {guess.transit_single_ticket:g} {cur}"
        if need_taxi and guess.taxi_flag_fall and guess.taxi_per_km:
            bundle.fares.update({"taxi_base": round(guess.taxi_flag_fall * rate, 2),
                                 "taxi_per_km": round(guess.taxi_per_km * rate, 2), "taxi_ai": 1.0})
            bundle.fare_sources["taxi"] = (f"AI estimate: ≈ {guess.taxi_flag_fall:g} {cur} + "
                                           f"{guess.taxi_per_km:g} {cur}/km")
    return n


def coverage(bundle: ResearchBundle) -> dict:
    """Where each researched price comes from (shown in the UI)."""
    def source(p: Place) -> str:
        s = p.cost_per_person.source or ""
        if p.price_known:
            if s.startswith("Official"):
                return "official"
            if s.startswith("Wikivoyage"):
                return "wikivoyage"
            return "google"
        if s.startswith("AI estimate"):
            return "ai"
        if s.startswith("Wikivoyage"):
            return "reference"  # an older published price
        return "none"

    def count(places: list[Place]) -> dict:
        out = {"verified": sum(1 for p in places if p.price_known), "total": len(places)}
        for p in places:
            k = source(p)
            out[k] = out.get(k, 0) + 1
        return out

    cov = dict(bundle.price_coverage)
    cov.update({"attractions": count(bundle.attractions), "restaurants": count(bundle.restaurants),
                "transit": "transit_verified" in bundle.fares, "taxi": "taxi_verified" in bundle.fares})
    return cov


async def research_prices(hub: MCPHub, bundle: ResearchBundle, contract: TripContract, scale: float = 1.0) -> None:
    """Official websites for the likely picks, then AI estimates for everything still unpriced."""
    if llm.available():
        try:
            # In parallel: the AI estimate for everything unpriced, and the official-site checks (which win).
            guess_task = asyncio.create_task(_ai_guess(bundle, contract))
            on_site = {p.id for p in _candidates(bundle, scale)[1]}  # restaurants whose own site is checked
            official, menus = await asyncio.gather(_official(hub, bundle, scale),
                                                   _menus(hub, bundle, contract, on_site, scale))
            estimated = _apply_ai(bundle, await guess_task)
            log.info("prices %s: %d from official sites, %d from web-searched menus, %d AI estimates",
                     contract.destination, official, menus, estimated)
        except Exception as exc:  # pricing enrichment must never break planning
            log.warning("price research failed: %s", exc)
    bundle.price_coverage = coverage(bundle)
