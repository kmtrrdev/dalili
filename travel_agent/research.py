"""Research agents: every external fact reaches the planner through an MCP tool call.

Phase 1 (parallel): flights, hotels, restaurants, attractions + events, weather.
Phase 2 (enrich, needs phase-1 results): exchange rates for every currency seen, the city's
price level (from real hotel prices), airport transfers for the actual arrival airports,
hotel noise from guest reviews, and real walk/drive matrices for routing.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
import math
import re
import statistics
import unicodedata
from typing import Any

from . import pilgrimage
from .config import settings
from .mcp_hub import MCPHub, MCPToolError
from .models import (
    FlightOption,
    HotelOption,
    Metadata,
    Money,
    Place,
    PlaceRef,
    ResearchBundle,
    TransferOption,
    TripContract,
    WeatherDay,
)
from .models import GeoPoint, ReviewInsights, RoundTrip
from .providers import places as places_provider
from .providers import routing, world_events
from .utils import WEEKDAYS, haversine_km, weekday_key

log = logging.getLogger(__name__)

REFERENCE_NIGHTLY_USD = 140.0  # a mid-priced city's median hotel night; defines cost_factor = 1


async def resolve_place(hub: MCPHub, text: str) -> PlaceRef:
    res = await hub.call("knowledge", "resolve_place", {"query": text})
    return PlaceRef.model_validate(res["place"])


async def research_destination(hub: MCPHub, contract: TripContract) -> dict[str, Any]:
    ref = contract.destination_ref
    assert ref is not None
    try:
        res = await hub.call("knowledge", "get_destination_info",
                             {"city": ref.name, "country": ref.country, "country_code": ref.country_code})
        info = res["info"]
    except MCPToolError as exc:
        # Never fail the whole trip on destination facts: what the resolved place already tells us is enough to plan.
        log.warning("destination info for %s unavailable: %s", ref.name, exc)
        from .providers import geo
        meta = geo.country_meta(ref.country_code or "")
        info = {"name": ref.name, "country": ref.country, "country_code": (ref.country_code or "").upper(),
                "currency": meta.get("currency") or contract.budget.currency, "languages": meta.get("languages", []),
                "dinner_time": geo.dinner_time(ref.country_code or ""), "knowledge": {}}
    info.update({"center": {"lat": ref.lat, "lon": ref.lon}, "timezone": ref.timezone, "airports": ref.airports,
                 "airport_names": ref.airport_names, "city_id": ref.city_id})
    holy = pilgrimage.holy_city(ref.lat, ref.lon)
    if holy:
        # Makkah / Madinah: the Holy Mosque anchors the hotel choice, and every day shows the prayer times.
        info["holy"] = {"key": holy, **pilgrimage.HOLY[holy]}
        try:
            res = await hub.call("knowledge", "get_prayer_times", {
                "lat": pilgrimage.HOLY[holy]["lat"], "lon": pilgrimage.HOLY[holy]["lon"],
                "start_date": contract.start_date.isoformat(), "end_date": contract.end_date.isoformat()})
            info["prayer_times"] = res["days"]
        except MCPToolError as exc:
            log.warning("prayer times for %s unavailable: %s", holy, exc)
    return info


async def research_flights(hub: MCPHub, contract: TripContract) -> dict[str, Any]:
    o, d = contract.origin_ref, contract.destination_ref
    assert o is not None and d is not None
    args = {
        "origin": contract.origin if len(contract.origin) == 3 else o.flight_id, "destination": d.flight_id,
        "departure_date": contract.start_date.isoformat(), "return_date": contract.end_date.isoformat(),
        "currency": contract.budget.currency, "origin_timezone": o.timezone, "destination_timezone": d.timezone,
        "origin_name": f"{o.name}, {o.country}", "destination_name": f"{d.name}, {d.country}",
    }
    if contract.return_ref is not None:  # open-jaw: fly home to another city
        r = contract.return_ref
        args.update({"return_to": contract.return_to or r.flight_id, "return_timezone": r.timezone,
                     "return_name": f"{r.name}, {r.country}"})
    res = await hub.call("flights", "search_flights", args)
    return {"outbound": [FlightOption.model_validate(f) for f in res["outbound"]],
            "return": [FlightOption.model_validate(f) for f in res["return"]],
            "round_trips": [RoundTrip.model_validate(x) for x in res.get("round_trips") or []],
            "insights": res.get("price_insights", {})}


def _qualified(d) -> str:
    """'Naples, Italy', not 'Naples': text searches without coordinates (hotels, events) must not land in Naples,
    Florida or Alexandria, Virginia."""
    return f"{d.name}, {d.country}" if d.country and d.country.lower() not in d.name.lower() else d.name


async def research_hotels(hub: MCPHub, contract: TripContract) -> list[HotelOption]:
    d = contract.destination_ref
    # Google Hotels prices one room for the given guests: ask for the people sharing each room (3 in 1 room -> 3,
    # 4 in 2 rooms -> 2), then the planner multiplies by the number of rooms.
    per_room = max(1, math.ceil(contract.travelers / contract.rooms))
    res = await hub.call("hotels", "search_hotels", {
        "city": _qualified(d), "check_in": contract.start_date.isoformat(), "check_out": contract.end_date.isoformat(),
        "adults": per_room, "currency": contract.budget.currency, "center_lat": d.lat, "center_lon": d.lon})
    return [HotelOption.model_validate(h) for h in res["results"]]


async def research_restaurants(hub: MCPHub, contract: TripContract, local_currency: str, dietary: list[str]) -> list[Place]:
    d = contract.destination_ref
    res = await hub.call("places", "search_restaurants", {"city": d.name, "lat": d.lat, "lon": d.lon,
                                                          "local_currency": local_currency, "dietary": dietary})
    return [Place.model_validate(p) for p in res["results"]]


EVENT_INTERESTS = {"nightlife", "music", "culture", "art", "events", "festival", "festivals", "theatre", "concerts"}


async def research_activities(hub: MCPHub, contract: TripContract, local_currency: str, interests: list[str]) -> list[Place]:
    d = contract.destination_ref
    holy = pilgrimage.holy_city(d.lat, d.lon)
    sacred: list[Place] = []
    if holy:
        try:
            res = await hub.call("knowledge", "get_sacred_sites", {"city": holy})
            sacred = [Place.model_validate(p) for p in res["results"]]
        except MCPToolError as exc:
            log.warning("sacred sites of %s unavailable: %s", holy, exc)
        pilgrimage.umrah_days(sacred, contract.start_date)
        if contract.pilgrimage and sacred:
            return sacred  # an Umrah: the sacred sites are the plan (no tourist search, no search credit spent)
    sights = await hub.call("activities", "search_attractions", {"city": d.name, "lat": d.lat, "lon": d.lon,
                                                                 "local_currency": local_currency, "interests": interests,
                                                                 "country": d.country or None, "days": contract.num_days})
    out = sacred + [Place.model_validate(p) for p in sights["results"]]
    # Local events cost a search and are only worth it for travellers who go out (music, nightlife, culture).
    if not EVENT_INTERESTS & set(interests):
        return out
    try:
        ev = await hub.call("activities", "search_events", {"city": _qualified(d), "lat": d.lat, "lon": d.lon,
                                                            "start_date": contract.start_date.isoformat(),
                                                            "end_date": contract.end_date.isoformat()})
        out += [Place.model_validate(p) for p in ev["results"]]
    except MCPToolError as exc:
        log.warning("events unavailable: %s", exc)
    return out


async def research_weather(hub: MCPHub, contract: TripContract) -> list[WeatherDay]:
    d = contract.destination_ref
    res = await hub.call("weather", "get_weather_forecast", {"lat": d.lat, "lon": d.lon,
                                                            "start_date": contract.start_date.isoformat(),
                                                            "end_date": contract.end_date.isoformat()})
    return [WeatherDay.model_validate(w) for w in res["days"]]


# ---------------------------------------------------------------------------
# Phase 2: enrichment
# ---------------------------------------------------------------------------


def _currencies(bundle: ResearchBundle) -> set[str]:
    cur = {bundle.destination_info.get("currency", "USD"), "USD"}
    for p in bundle.restaurants + bundle.attractions:
        cur.add(p.cost_per_person.currency)
    return {c.upper() for c in cur}


MAX_PRICE_AGE_YEARS = 3  # a listing price edited longer ago than this is shown as "may have changed"


def apply_local_prices(bundle: ResearchBundle, prices: dict) -> None:
    """Replace estimates with published prices: Wikivoyage entry / restaurant prices (matched by name and
    location) and transport fares quoted from the guide. Records how much of the research is verified."""
    apply_listings(bundle, prices)
    apply_tariffs(bundle, prices.get("tariffs") or {}, prices.get("listings_total", 0))


def apply_listings(bundle: ResearchBundle, prices: dict) -> None:
    """Wikivoyage entry / restaurant prices, matched to the researched places by name and location."""
    from .config import today
    from .providers import local_prices

    items = prices.get("listings") or []
    cutoff = f"{today().year - MAX_PRICE_AGE_YEARS}-{today():%m-%d}"

    def fresh(it: dict) -> bool:
        """A listing price counts as verified only if someone checked it recently (prices go up)."""
        return bool(it.get("lastedit")) and it["lastedit"] >= cutoff

    for p in bundle.attractions:
        if p.price_known or p.dates:  # Google already published one / events keep their own ticket note
            continue
        it = local_prices.match(p.name, p.location.lat, p.location.lon, items, {"see", "do"})
        if not it:
            continue
        when = f"updated {it['lastedit'][:7]}" if it.get("lastedit") else "undated"
        if fresh(it) or it["free"]:  # a free public monument doesn't go stale the way a ticket price does
            p.cost_per_person = Money(amount=it["amount"], currency=it["currency"], price_type="known",
                                      source=f"Wikivoyage · {when}")
            p.price_known = True
            p.notes = f"Entry: {it['price_text'][:160]} (Wikivoyage, {when}). Check the official site before going."
        else:
            # An old published price is a better estimate than a generic one, but it is still an estimate.
            p.cost_per_person = Money(amount=it["amount"], currency=it["currency"], price_type="estimated",
                                      source=f"Wikivoyage · {when} - may have changed")
            p.notes = f"Last published entry price: {it['price_text'][:120]} (Wikivoyage, {when}) - may have changed; " \
                      "check the official site."
    for p in bundle.restaurants:
        if p.price_known:
            continue
        it = local_prices.match(p.name, p.location.lat, p.location.lon, items, {"eat", "drink"})
        if it and not it["free"] and fresh(it):
            p.cost_per_person = Money(amount=it["amount"], currency=it["currency"], price_type="range",
                                      source=f"Wikivoyage · updated {it['lastedit'][:7]}: {it['price_text'][:80]}")
            p.price_known = True


def apply_tariffs(bundle: ResearchBundle, t: dict, listings_total: int) -> None:
    """Transport fares quoted verbatim from the guide (converted to the traveller's currency): they replace the
    AI's typical fares. Records how much of the research is verified."""
    def to_user(q: dict) -> float | None:
        rate = bundle.fx_rates.get(str(q["currency"]).upper())
        return round(q["amount"] * rate, 2) if rate else None

    single = t.get("transit_single_ticket")
    usd = bundle.fx_rates.get("USD")
    if single and (v := to_user(single)) is not None and usd and v / usd > 10:
        # No city's single ride costs more than ~$10: the guide's number is an intercity fare misread as a ticket.
        log.info("transit fare %s %s rejected as implausible: %s", single["amount"], single["currency"], single["quote"])
        single = None
    if single and (v := to_user(single)) is not None:
        bundle.fares["transit"], bundle.fares["transit_verified"] = v, 1.0
        bundle.fares.pop("transit_ai", None)
        bundle.fare_sources["transit"] = f'Wikivoyage: "{single["quote"]}"'
    flag, per_km = t.get("taxi_flag_fall"), t.get("taxi_per_km")
    if flag and per_km and (a := to_user(flag)) is not None and (b := to_user(per_km)) is not None:
        bundle.fares.update({"taxi_base": a, "taxi_per_km": b, "taxi_verified": 1.0})
        bundle.fares.pop("taxi_ai", None)
        bundle.fare_sources["taxi"] = f'Wikivoyage: "{flag["quote"]}" / "{per_km["quote"]}"'
    if t.get("airport_fares"):
        bundle.fare_sources["airport"] = "; ".join(f'"{f["quote"]}"' for f in t["airport_fares"][:3])

    def share(places) -> dict:
        n = len(places)
        k = sum(1 for p in places if p.price_known)
        return {"verified": k, "total": n}

    bundle.price_coverage = {"attractions": share(bundle.attractions), "restaurants": share(bundle.restaurants),
                             "transit": "transit" in bundle.fare_sources, "taxi": "taxi" in bundle.fare_sources,
                             "listings_found": listings_total}


async def _best_times(bundle: ResearchBundle) -> None:
    """Tag sights that happen at a set time of day (sunset show, sunrise trek, night market) so they are scheduled
    then. Only places not tagged yet are asked about; any failure just leaves them untagged."""
    from .providers import ai_fallback

    todo = [a for a in bundle.attractions if a.best_time is None and a.kind in ("attraction", "activity")]
    if not todo or not ai_fallback.available():
        return
    info = bundle.destination_info
    try:
        times = await ai_fallback.best_times(info.get("name", ""), info.get("country", ""), [a.name for a in todo])
    except Exception as exc:  # noqa: BLE001 - an optional hint: never fail research over it
        log.info("best times unavailable: %s", exc)
        return
    for a in todo:
        a.best_time = times.get(a.name.strip().lower())  # type: ignore[assignment]


async def fetch_local_prices(hub: MCPHub, contract: TripContract, local_currency: str) -> dict:
    """The city's published prices (Wikivoyage listings): needs only the city, so it can start with the rest of the
    research. {"error": ...} instead of raising."""
    d = contract.destination_ref
    try:
        return await hub.call("knowledge", "get_local_prices", {"city": d.name if d else contract.destination,
                                                                 "country": d.country if d else "",
                                                                 "local_currency": local_currency})
    except MCPToolError as exc:
        return {"error": str(exc)}


async def fetch_transport_fares(hub: MCPHub, contract: TripContract) -> dict:
    """The transport fares quoted in the city's guide (a model reads them: the slowest free source, so nothing waits
    for it until the fares are needed). {"error": ...} instead of raising."""
    d = contract.destination_ref
    try:
        return await hub.call("knowledge", "get_transport_fares", {"city": d.name if d else contract.destination,
                                                                    "country": d.country if d else ""})
    except MCPToolError as exc:
        return {"error": str(exc)}


def start_local_prices(hub: MCPHub, contract: TripContract, local_currency: str) -> tuple[asyncio.Task, asyncio.Task]:
    """Both free price sources of a city, started now and collected by enrich()."""
    return (asyncio.create_task(fetch_local_prices(hub, contract, local_currency)),
            asyncio.create_task(fetch_transport_fares(hub, contract)))


async def enrich(hub: MCPHub, bundle: ResearchBundle, contract: TripContract, review_lookups: int | None = None,
                 price_scale: float = 1.0, local_prices: "tuple[asyncio.Task, asyncio.Task] | None" = None) -> None:
    user = contract.budget.currency.upper()
    bundle.errors = list(bundle.errors)
    from . import data_quality

    data_quality.check(bundle)  # impossible coordinates, duplicates, implausible prices never reach the plan
    timed = asyncio.create_task(_best_times(bundle))  # the model's call runs while everything below does
    import time as _time

    from . import telemetry

    marks, t0 = {}, _time.perf_counter()

    def mark(step: str) -> None:
        nonlocal t0
        now = _time.perf_counter()
        marks[step] = round(now - t0, 2)
        t0 = now
    # 0) Published local prices (free): Wikivoyage listings, and transport fares quoted from the guide - usually
    #    started with the other research (workflow.research_setup). The listings price places, so they are collected
    #    now; the fares (a model reads the guide) only when the transfers need them.
    listings_task, fares_task = local_prices or start_local_prices(hub, contract,
                                                                   bundle.destination_info.get("currency", "USD"))
    prices = await listings_task
    if prices.get("error"):
        bundle.errors.append(f"local prices: {prices['error']}")
    extra_cur = {x["currency"] for x in prices.get("listings") or [] if x.get("currency")}

    # 1) Exchange rates (user currency multipliers) for every currency present.
    try:
        res = await hub.call("currency", "get_exchange_rates", {"base": user, "quotes": sorted(_currencies(bundle) | extra_cur)})
        per_user = res["rates"]
        bundle.fx_rates = {c: (1.0 / v if c != user else 1.0) for c, v in per_user.items() if v}
        bundle.fx_metadata = Metadata(source="currency_mcp", provider=res.get("provider", "Frankfurter"), confidence=0.95,
                                      source_url="https://frankfurter.dev")
        if res.get("missing"):
            bundle.errors.append(f"currency: no exchange rate for {', '.join(res['missing'])} - "
                                 "prices in it can't be converted reliably")
    except MCPToolError as exc:
        bundle.errors.append(f"currency: {exc}")
        bundle.fx_rates = {user: 1.0}
    usd = bundle.fx_rates.get("USD", 1.0)

    # 2) City price level from real hotel prices -> scales every estimate.
    nightly = [h.price_per_night.amount * bundle.fx_rates.get(h.price_per_night.currency.upper(), 1.0) / usd
               for h in bundle.hotels if h.price_per_night.amount > 0]
    # Local services scale less than hotel rates, so the ratio is dampened (square root).
    ratio = statistics.median(nightly) / REFERENCE_NIGHTLY_USD if nightly else 1.0
    bundle.cost_factor = round(min(1.8, max(0.45, ratio ** 0.5)), 2)
    to_user = usd * bundle.cost_factor
    bundle.fares = {"transit": round(1.6 * to_user, 2), "airport_transit": round(8.0 * to_user, 2),
                    "taxi_base": round(3.5 * to_user, 2), "taxi_per_km": round(1.3 * to_user, 2),
                    "intercity_base": round(3.0 * to_user, 2), "intercity_per_km": round(0.06 * to_user, 3)}
    for p in bundle.restaurants + bundle.attractions:
        # Once per place: a reused place (later turn) is already scaled - scaling again would compound every turn.
        if not p.price_known and not p.price_checked and p.cost_per_person.currency == "USD" \
                and p.cost_per_person.price_type == "estimated":
            p.cost_per_person = Money(amount=round(p.cost_per_person.amount * bundle.cost_factor, 2), currency="USD",
                                      price_type="estimated")
    # Published prices replace the estimates wherever they exist; then the official websites of the likely
    # picks, then AI estimates for what nothing publishes (pricing.py: the full cascade, no SerpApi credits).
    apply_listings(bundle, prices)
    from . import pricing

    mark("local_prices_fx")
    await pricing.research_prices(hub, bundle, contract, scale=price_scale)
    await timed
    fares = await fares_task
    if fares.get("error"):
        bundle.errors.append(f"transport fares: {fares['error']}")
    t = fares.get("tariffs") or {}
    quoted = {q["currency"].upper() for q in [t.get(k) for k in ("transit_single_ticket", "taxi_flag_fall", "taxi_per_km")]
              + list(t.get("airport_fares") or []) if q}
    # Prices found just now (menus, official sites, the guide's fares) can be in a currency the first rates didn't
    # cover: fetch those too, so they are converted instead of being counted one-to-one.
    missing = sorted(c for c in _currencies(bundle) | quoted if c not in bundle.fx_rates and len(c) == 3 and c.isalpha())
    if missing and user in bundle.fx_rates:
        try:
            res = await hub.call("currency", "get_exchange_rates", {"base": user, "quotes": missing})
            bundle.fx_rates.update({c: 1.0 / v for c, v in res["rates"].items() if v and c != user})
        except (MCPToolError, KeyError, TypeError) as exc:
            bundle.errors.append(f"currency: {exc}")
    apply_tariffs(bundle, t, prices.get("listings_total", 0))  # published fares replace the AI's typical ones
    mark("pricing")

    # 3) Airport transfers for the airports the best flights actually land at.
    center = bundle.destination_info["center"]
    airports: list[str] = []
    for f in bundle.flights_outbound[:6]:
        if f.mode == "flight" and f.destination not in airports:
            airports.append(f.destination)
    names = bundle.destination_info.get("airport_names", {})
    transfers: list[TransferOption] = []
    for code in airports[:2]:
        try:
            res = await hub.call("transport", "get_airport_transfers", {
                "airport_code": code, "airport_name": names.get(code, f"{code} airport"), "lat": center["lat"],
                "lon": center["lon"], "currency": user, "fares": bundle.fares,
                "fixed_fares": t.get("airport_fares") or []})
            transfers += [TransferOption.model_validate(x) for x in res["results"]]
        except MCPToolError as exc:
            bundle.errors.append(f"transfers {code}: {exc}")
    bundle.airport_transfers = transfers
    mark("transfers")

    # 4) What real guests say about the most likely picks: noise, plus aspect-based insights from the
    #    review-analyst agent (in parallel - each one is a review search and a model call).
    candidates = sorted((h for h in bundle.hotels if h.property_token and h.rating >= 4.0),
                        key=lambda h: (-(h.rating * min(h.reviews_count, 3000) ** 0.25), h.price_per_night.amount))
    lookups = settings.hotel_review_lookups if review_lookups is None else review_lookups
    picks = candidates[:lookups]
    results = await hub.call_many([("hotels", "get_hotel_reviews", {"property_token": h.property_token, "hotel_name": h.name})
                                   for h in picks])
    for h, res in zip(picks, results):
        if isinstance(res, Exception):
            bundle.errors.append(f"hotel reviews: {res}")
            continue
        h.noise_level, h.noise_evidence = res["noise_level"], res["noise_evidence"]
        if res.get("insights"):
            h.review_insights = ReviewInsights.model_validate(res["insights"])

    mark("hotel_reviews")
    # 5) Real walking / driving times between everything the planner may use.
    await prepare_routing(bundle)
    mark("routing")
    telemetry.event("enrich_timing", city=bundle.destination_info.get("name"), **marks)


MAX_NEW_INSIGHTS = 3  # each is one (30-day cached) review search + one model call


def reviews_todo(trip, plans: dict) -> list:
    """The hotels of the plan the traveller sees (one, or one per city) that have no guest-review insights yet."""
    from . import llm

    if not llm.available() or trip.research is None:
        return []
    # Only the plan shown: each review lookup costs a credit.
    shown = plans.get(trip.selected_mode) or next(iter(plans.values()), None)
    if shown is None:
        return []
    chosen = ([shown.hotel] if shown.hotel else []) + [s.hotel for s in shown.stops if getattr(s, "hotel", None)]
    known = {h.id for b in [trip.research] + list(trip.research.stops) for h in b.hotels if h.review_insights}
    return list({h.id: h for h in chosen if h.property_token and h.id not in known}.values())[:MAX_NEW_INSIGHTS]


async def fetch_hotel_reviews(hub: MCPHub, hotels: list) -> dict:
    """Hotel id -> the review-analyst's result (or the exception). Nothing is written to the trip, so the reviews
    can be fetched ahead (while the expert reviews the plan) without changing what the planner reads."""
    results = await hub.call_many([("hotels", "get_hotel_reviews", {"property_token": h.property_token,
                                                                     "hotel_name": h.name}) for h in hotels])
    return {h.id: res for h, res in zip(hotels, results)}


async def plan_hotel_insights(hub: MCPHub, trip, plans: dict, prefetched: dict | None = None) -> None:
    """Run the review-analyst agent on the hotels the plans actually chose (the research-time lookups only
    cover the most popular hotels). Results are written to every copy of the hotel (research and plans).
    prefetched: fetch_hotel_reviews results already in for some of these hotels."""
    if trip.research is None:
        return
    bundles = [trip.research] + list(trip.research.stops)
    known = {h.id: h for b in bundles for h in b.hotels if h.review_insights}
    todo = reviews_todo(trip, plans)
    got = {h.id: prefetched[h.id] for h in todo if prefetched and h.id in prefetched}
    got |= await fetch_hotel_reviews(hub, [h for h in todo if h.id not in got])
    for h in todo:
        res = got[h.id]
        if isinstance(res, Exception):
            log.warning("hotel reviews for %s failed: %s", h.name, res)
            continue
        if res.get("insights"):
            known[h.id] = h.model_copy(update={"review_insights": ReviewInsights.model_validate(res["insights"]),
                                               "noise_level": res["noise_level"],
                                               "noise_evidence": res["noise_evidence"]})
    # Copy onto every instance of those hotels (the same hotel may be in several plans).
    everywhere = [p.hotel for p in plans.values() if p.hotel] + [s.hotel for p in plans.values() for s in p.stops
                                                                 if getattr(s, "hotel", None)]
    for obj in [h for b in bundles for h in b.hotels] + everywhere:
        src = known.get(obj.id)
        if src is not None and obj is not src and obj.review_insights is None:
            obj.review_insights, obj.noise_level, obj.noise_evidence = \
                src.review_insights, src.noise_level, src.noise_evidence


# ---------------------------------------------------------------------------
# Places the traveller asked for by name
# ---------------------------------------------------------------------------


# Arabic place words and their English equivalents: "Masjid Quba" is "Quba Mosque", "Jabal Uhud" is "Mount Uhud".
SAME_WORD = {"masjid": "mosque", "masjed": "mosque", "jami": "mosque", "jabal": "mount", "jebel": "mount",
             "qasr": "palace", "souq": "market", "souk": "market", "bab": "gate", "wadi": "valley"}


def _tokens(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return {SAME_WORD.get(t, t) for t in re.findall(r"[a-z0-9]+", s)
            if len(t) > 2 and t not in ("the", "and", "del", "della")}


def match_place(name: str, places: list[Place]) -> Place | None:
    """Best researched place for a name the traveller typed ("vatican museum" -> "Vatican Museums")."""
    want = _tokens(name)
    if not want:
        return None
    best, best_score = None, 0.0
    for p in places:
        have = _tokens(p.name)
        if not have:
            continue
        overlap = len({w for w in want if any(h.startswith(w[:5]) or w.startswith(h[:5]) for h in have)}) / len(want)
        ratio = difflib.SequenceMatcher(None, " ".join(sorted(want)), " ".join(sorted(have))).ratio()
        score = max(overlap, ratio)
        if score > best_score:
            best, best_score = p, score
    return best if best_score >= 0.8 else None


def resolve_wishes(trip) -> list[str]:
    """Places mentioned softly ("if there's time"): matched against what research already found - a wish never
    costs a paid lookup - and handed to the planner as a boost, not a forced stop."""
    r = trip.research
    if r is None or not trip.draft.wish_list:
        trip.user_knobs.wish_picks = []
        return []
    ids = []
    for name in trip.draft.wish_list:
        for b in r.stops or [r]:
            hit = match_place(name, b.attractions)
            if hit:
                ids.append(hit.id)
                break
    trip.user_knobs.wish_picks = list(dict.fromkeys(ids))
    return trip.user_knobs.wish_picks


async def ensure_must_visit(hub: MCPHub, trip) -> list[str]:
    """Make every place the traveller named part of the research and of the plan's must-include list.

    Already-researched places cost nothing; others get one Google Maps lookup (cached). For a
    multi-city trip the place is searched around each city until it is found near one of them.
    Returns notes for the reply (not found / too far for a day trip).
    """
    r, c = trip.research, trip.trip_contract
    names = list(trip.draft.must_visit)
    if not names or r is None or c is None:
        trip.user_knobs.must_include = []
        return []
    events = admit_offered_events(trip, names)  # "I'll go to Oktoberfest": the offered event, on its own dates
    resolved: dict[str, str] = trip.metadata.setdefault("must_visit", {})
    bundles = r.stops or [r]
    notes, ids = [], []
    cities = [s.name for s in c.stops] or [c.destination]
    for name in names:
        if any(_tokens(name) and _tokens(name) <= _tokens(city) | {"el", "al"} for city in cities):
            continue  # a city of the route itself (e.g. "Sharm El Sheikh"), not a sight to schedule
        key = f"{c.route_name}|{name}"  # a lookup is only valid for the destination it was made for
        if name in events:
            resolved[key] = events[name]
            ids.append(events[name])
            continue
        pid = resolved.get(key)
        if pid and r.place(pid):
            ids.append(pid)
            continue
        if pid == "":
            continue  # looked up before and not found
        found, home = None, None
        for b in bundles:
            hit = match_place(name, b.attractions) or match_place(name, b.restaurants)
            if hit:
                found, home = hit, b
                break
        if found is None:
            centers = [b.destination_info["center"] for b in bundles]
            if len(bundles) == 1:
                info = bundles[0].destination_info
                args = {"name": name, "city": info.get("name", c.destination), "lat": centers[0]["lat"],
                        "lon": centers[0]["lon"], "local_currency": info.get("currency", "USD"), "zoom": 11}
            else:
                # One search by name over the whole route; the place then belongs to its nearest city.
                args = {"name": name, "city": "", "lat": sum(x["lat"] for x in centers) / len(centers),
                        "lon": sum(x["lon"] for x in centers) / len(centers),
                        "local_currency": bundles[0].destination_info.get("currency", "USD"), "zoom": 5}
            try:
                res = await hub.call("activities", "find_place", args)
                p = Place.model_validate(res["result"]) if res.get("result") else None
            except MCPToolError as exc:
                log.warning("find_place %s failed: %s", name, exc)
                p = None
            if p is not None:
                home = min(bundles, key=lambda b: haversine_km(p.location.lat, p.location.lon,
                                                               b.destination_info["center"]["lat"],
                                                               b.destination_info["center"]["lon"]))
                hc = home.destination_info["center"]
                places_provider.tag_distance(p, GeoPoint(lat=hc["lat"], lon=hc["lon"]),
                                             home.destination_info.get("name", c.destination))
                found = next((x for x in home.attractions if x.id == p.id), None) or p
                if found is p:
                    home.attractions.append(p)
                    if home is not r:
                        r.attractions.append(p)
        if found is None:
            resolved[key] = ""
            notes.append(f"I couldn't find '{name}' on Google Maps near your destination - check the spelling?")
            continue
        resolved[key] = found.id
        ids.append(found.id)
        if "overnight_trip" in found.categories:
            notes.append(f"{found.name} is about {found.distance_km:.0f} km from "
                         f"{home.destination_info.get('name', c.destination)} - too far for a day trip, so I suggest it "
                         "as an overnight side trip instead of squeezing it into a day.")
    for pid in ids:  # asking for a place overrides an earlier "remove it"
        if pid in trip.user_knobs.exclude_ids:
            trip.user_knobs.exclude_ids.remove(pid)
        if pid in trip.excluded_ids:
            trip.excluded_ids.remove(pid)
    # A restaurant the traveller wants is a meal (lunch / dinner at it), not a sight to squeeze into the day.
    wanted_day = {k.split("|", 1)[-1].lower(): d for k, d in (trip.metadata.get("must_visit_day") or {}).items()}
    names_by_id = {pid: key.split("|", 1)[-1].lower() for key, pid in resolved.items() if pid}
    sights, meals = [], {}
    for pid in ids:
        p = r.place(pid)
        if p is not None and (p.kind in ("restaurant", "cafe") or p.meal_types):
            meals[pid] = int(wanted_day.get(names_by_id.get(pid, ""), 0) or 0)
            for b in bundles:  # it eats in the city it was found in
                if any(x.id == pid for x in b.attractions):
                    b.attractions = [x for x in b.attractions if x.id != pid]
                    if all(x.id != pid for x in b.restaurants):
                        b.restaurants.append(p)
            if p in r.attractions:
                r.attractions.remove(p)
            if all(x.id != pid for x in r.restaurants):
                r.restaurants.append(p)
        else:
            sights.append(pid)
    trip.user_knobs.must_include = sights
    trip.user_knobs.meal_requests = meals
    return notes


async def find_places(hub: MCPHub, trip, names: list[str], stop: int | None = None) -> list[str]:
    """Real places for names the strategist suggested (signature experiences): researched data first, else one Google
    Maps lookup each (cached per destination). Never invents a place; overnight-distance results are skipped.
    stop: the city of a multi-city trip to search in (its places are added to that city's research too)."""
    merged, c = trip.research, trip.trip_contract
    if not names or merged is None or c is None or (c.is_multi and (stop is None or stop >= len(merged.stops))):
        return []
    r = merged.stops[stop] if c.is_multi else merged
    ref = c.stops[stop].ref if c.is_multi else c.destination_ref
    info = r.destination_info
    center = info.get("center") or {"lat": ref.lat, "lon": ref.lon}
    cache: dict[str, str] = trip.metadata.setdefault("place_lookup", {})

    def key_of(name: str) -> str:
        return f"{ref.name}|{name}" if c.is_multi else f"{c.route_name}|{name}"

    def known(name: str) -> bool:  # looked up before (found or not), or already in the research
        pid = cache.get(key_of(name))
        return pid == "" or bool(pid and r.place(pid)) or match_place(name, r.attractions) is not None

    async def lookup(name: str) -> Place | None:
        try:
            res = await hub.call("activities", "find_place", {
                "name": name, "city": info.get("name", c.destination), "lat": center["lat"], "lon": center["lon"],
                "local_currency": info.get("currency", "USD"), "zoom": 11})
            return Place.model_validate(res["result"]) if res.get("result") else None
        except MCPToolError as exc:
            log.warning("find_place %s failed: %s", name, exc)
            return None

    # The Google Maps lookups run together; the results are then taken in the strategist's order.
    todo = [n for n in names[:4] if not known(n)]
    looked_up = dict(zip(todo, await asyncio.gather(*(lookup(n) for n in todo))))
    ids: list[str] = []
    for name in names[:4]:
        key = key_of(name)
        pid = cache.get(key)
        if pid and r.place(pid):
            ids.append(pid)
            continue
        if pid == "":
            continue  # looked up before, nothing usable
        hit = match_place(name, r.attractions)
        if hit is None:
            p = looked_up.get(name)
            if p is not None:
                places_provider.tag_distance(p, GeoPoint(lat=center["lat"], lon=center["lon"]), info.get("name", c.destination))
                if "overnight_trip" not in p.categories and p.kind not in ("restaurant", "cafe"):
                    found = next((x for x in r.attractions if x.id == p.id), None)
                    if found is None:
                        r.attractions.append(p)
                        if r is not merged and not any(x.id == p.id for x in merged.attractions):
                            merged.attractions.append(p)  # the whole journey's bundle sees it too
                    hit = found or p
        cache[key] = hit.id if hit else ""
        if hit:
            ids.append(hit.id)
    return ids


# ---------------------------------------------------------------------------
# World-famous events during the trip: offered, never added without the traveller's yes
# ---------------------------------------------------------------------------

MAJOR_EVENT = "major_event"  # category of an offered event: the planner schedules it only when it is asked for
EVENT_MINUTES = 240
EVENT_OUTING_KM = 60  # a few hours at a circuit or stadium out of town is an outing, not a day trip owning the day


async def fetch_major_events(hub: MCPHub, contract: TripContract) -> list[world_events.WorldEvent]:
    """The world-famous events in the trip's countries during its dates (empty on any failure)."""
    refs = [s.ref for s in contract.stops] or ([contract.destination_ref] if contract.destination_ref else [])
    codes = sorted({r.country_code.upper() for r in refs if r.country_code})
    if not codes:
        return []
    try:
        res = await hub.call("activities", "get_major_events", {"start_date": str(contract.start_date),
                                                                 "end_date": str(contract.end_date),
                                                                 "country_codes": codes})
    except MCPToolError as exc:
        log.info("major events unavailable: %s", exc)
        return []
    return [world_events.WorldEvent.model_validate(x) for x in res.get("results") or []]


def _same_city(a: str, b: str) -> bool:
    a, b = a.strip().lower(), b.strip().lower()
    return bool(a and b) and (a in b or b in a)


def _event_place(e: world_events.WorldEvent, days: list, bundle: ResearchBundle) -> Place:
    """The event as a place on its own dates (the planner keeps it out of the days until the traveller asks)."""
    info = bundle.destination_info
    center = GeoPoint(lat=info["center"]["lat"], lon=info["center"]["lon"])
    where = GeoPoint(lat=e.lat, lon=e.lon) if e.lat is not None and e.lon is not None else center
    hours = {w: [] for w in WEEKDAYS}
    for d in days:
        hours[weekday_key(d)] = [["10:00", "22:00"]]
    if e.ticket and e.ticket.source == "official site":
        cost = Money(amount=e.ticket.amount, currency=e.ticket.currency, price_type="known",
                     source=f"Official website · from {e.ticket.amount:g} {e.ticket.currency}")
    elif e.ticket:
        cost = Money(amount=e.ticket.amount, currency=e.ticket.currency, price_type="estimated",
                     source="AI estimate · typical cheapest ticket")
    else:
        cost = Money(amount=0.0, currency=info.get("currency", "USD"), price_type="estimated",
                     source="Free to attend, or price not published")
    when = "dates from the official website" if e.dates_source == "official site" else \
        "dates from Wikidata" if e.dates_source == "wikidata" else "usual dates - confirm them before booking"
    p = Place(id=f"wev_{e.id}", name=e.name, kind="activity", categories=["event", MAJOR_EVENT, e.category],
              location=where, rating=4.8, price_level=3, cost_per_person=cost, price_known=cost.price_type == "known",
              price_checked=True, opening_hours=hours, hours_verified=False, dates=list(days),
              duration_minutes=EVENT_MINUTES, indoor=False, popularity="must_see", description=e.why or e.description,
              website=e.website or e.wikipedia,
              metadata=Metadata(source="activities_mcp", provider="Wikipedia · Wikidata · official site",
                                confidence=0.9 if e.dates_source != "usual dates" else 0.6, source_url=e.wikipedia))
    places_provider.tag_distance(p, center, info.get("name", ""))
    if p.day_trip and p.distance_km <= EVENT_OUTING_KM:
        p.day_trip = False  # the ride there is planned like any other leg
        p.categories = [c for c in p.categories if c != "day_trip"]
    p.notes = f"{e.name}: {e.start:%d %b} - {e.end:%d %b %Y} ({when}). Exact times and tickets on the official site." \
        + (f" About {p.distance_km:.0f} km from the centre." if p.distance_km >= 10 else "")
    return p


def offer_major_events(trip, events: list[world_events.WorldEvent]) -> list[dict]:
    """Big events during the trip, remembered as offers: the reply asks, the trip agent understands the answer.
    One near a stop, on that stop's days, carries the dated place it becomes when the traveller says yes - it joins
    the research only then (admit_offered_events), so an offer never changes the plan, its costs or the review."""
    c, r = trip.trip_contract, trip.research
    if c is None or r is None:
        return []
    bundles = r.stops or [r]
    stops = [(s.ref, s.start_date, s.end_date) for s in c.stops] or [(c.destination_ref, c.start_date, c.end_date)]
    stops = [(ref, a, b) for ref, a, b in stops if ref is not None]
    offers = []
    matches = world_events.during(events, c.start_date, c.end_date, {ref.country_code.upper() for ref, _, _ in stops},
                                  [(ref.lat, ref.lon) for ref, _, _ in stops])
    for e, days, km in matches[:6]:
        offer = {"name": e.name, "name_ar": e.name_ar, "category": e.category, "city": e.city,
                 "country_code": e.country_code, "event_dates": [str(e.start), str(e.end)],
                 "dates_source": e.dates_source, "trip_days": [str(d) for d in days],
                 "km_from_trip": round(km) if km is not None else None, "why": e.why, "why_ar": e.why_ar,
                 "ticket": e.ticket.model_dump() if e.ticket else None, "url": e.website or e.wikipedia,
                 "image": e.image, "stop": None, "place": None}
        for i, (ref, a, b) in enumerate(stops):
            near = (e.lat is not None and haversine_km(e.lat, e.lon, ref.lat, ref.lon) <= world_events.NEAR_KM) or \
                (e.lat is None and _same_city(e.city, ref.name))
            here = [d for d in days if a <= d <= b]
            if near and here:
                place = _event_place(e, here, bundles[i] if i < len(bundles) else bundles[0])
                offer.update(stop=i, place=place.model_dump(mode="json"), trip_days=[str(d) for d in here],
                             city=e.city or ref.name)
                break
        offers.append(offer)
    trip.metadata["event_offers"] = offers
    return offers


def admit_offered_events(trip, names: list[str]) -> dict[str, str]:
    """Offered events the traveller asked for join the research of their city, on their dates - no search needed.
    A name matches an event when it names it, with or without more words ("Abu Dhabi Grand Prix (Yas Marina
    Circuit)"): the venue alone is not the event, so it must never be looked up on its own instead.
    Returns name asked -> the event's place id."""
    r = trip.research
    offers = [o for o in trip.metadata.get("event_offers") or [] if o.get("place")]
    if r is None or not offers:
        return {}
    bundles = r.stops or [r]
    admitted: dict[str, str] = {}
    for name in names:
        for o in offers:
            place = Place.model_validate(o["place"])
            own = _tokens(place.name)
            if not (own and own <= _tokens(name)) and match_place(name, [place]) is None:
                continue
            home = bundles[o["stop"]] if o["stop"] is not None and o["stop"] < len(bundles) else bundles[0]
            for b in {id(home): home, id(r): r}.values():  # the stop, and a tour's merged research
                if not any(x.id == place.id for x in b.attractions):
                    b.attractions.append(place)
            admitted[name] = place.id
            break
    return admitted


ROUTING_RADIUS_KM = 45  # day-trip sites further out use intercity estimates; far points break walking matrices


def routing_points(bundle: ResearchBundle):
    pts = [h.location for h in bundle.hotels] + [p.location for p in bundle.attractions + bundle.restaurants]
    c = bundle.destination_info.get("center")
    if not c:
        return pts
    return [p for p in pts if haversine_km(p.lat, p.lon, c["lat"], c["lon"]) <= ROUTING_RADIUS_KM]


async def prepare_routing(bundle: ResearchBundle) -> None:
    # Multi-city: one matrix per city (cross-city pairs would waste the routing quota).
    for b in bundle.stops or [bundle]:
        await routing.prepare(routing_points(b))


async def gather_all(hub: MCPHub, contract: TripContract, dietary: list[str], interests: list[str]) -> ResearchBundle:
    """Convenience for scripts/tests: run the whole research pipeline without the graph."""
    info = await research_destination(hub, contract)
    fl, hotels, rest, acts, weather = await asyncio.gather(
        research_flights(hub, contract), research_hotels(hub, contract),
        research_restaurants(hub, contract, info["currency"], dietary),
        research_activities(hub, contract, info["currency"], interests), research_weather(hub, contract))
    bundle = ResearchBundle(flights_outbound=fl["outbound"], flights_return=fl["return"], flight_insights=fl["insights"],
                            round_trips=fl.get("round_trips", []),
                            hotels=hotels, restaurants=rest, attractions=acts, weather=weather, destination_info=info)
    await enrich(hub, bundle, contract)
    return bundle
