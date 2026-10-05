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
from .providers import routing
from .utils import haversine_km

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
    sights = await hub.call("activities", "search_attractions", {"city": d.name, "lat": d.lat, "lon": d.lon,
                                                                 "local_currency": local_currency, "interests": interests,
                                                                 "country": d.country or None, "days": contract.num_days})
    out = [Place.model_validate(p) for p in sights["results"]]
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


def apply_local_prices(bundle: ResearchBundle, prices: dict, user: str) -> None:
    """Replace estimates with published prices: Wikivoyage entry / restaurant prices (matched by name and
    location) and transport fares quoted from the guide. Records how much of the research is verified."""
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

    # Transport fares quoted verbatim from the guide (converted to the traveller's currency).
    t = prices.get("tariffs") or {}

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
        bundle.fare_sources["transit"] = f'Wikivoyage: "{single["quote"]}"'
    flag, per_km = t.get("taxi_flag_fall"), t.get("taxi_per_km")
    if flag and per_km and (a := to_user(flag)) is not None and (b := to_user(per_km)) is not None:
        bundle.fares.update({"taxi_base": a, "taxi_per_km": b, "taxi_verified": 1.0})
        bundle.fare_sources["taxi"] = f'Wikivoyage: "{flag["quote"]}" / "{per_km["quote"]}"'
    if t.get("airport_fares"):
        bundle.fare_sources["airport"] = "; ".join(f'"{f["quote"]}"' for f in t["airport_fares"][:3])

    def share(places) -> dict:
        n = len(places)
        k = sum(1 for p in places if p.price_known)
        return {"verified": k, "total": n}

    bundle.price_coverage = {"attractions": share(bundle.attractions), "restaurants": share(bundle.restaurants),
                             "transit": "transit" in bundle.fare_sources, "taxi": "taxi" in bundle.fare_sources,
                             "listings_found": prices.get("listings_total", 0)}


async def enrich(hub: MCPHub, bundle: ResearchBundle, contract: TripContract, review_lookups: int | None = None,
                 price_scale: float = 1.0) -> None:
    user = contract.budget.currency.upper()
    bundle.errors = list(bundle.errors)
    local = bundle.destination_info.get("currency", "USD")
    d = contract.destination_ref

    # 0) Published local prices (free): Wikivoyage listings + transport fares quoted from the guide.
    prices: dict = {}
    try:
        prices = await hub.call("knowledge", "get_local_prices", {"city": d.name if d else contract.destination,
                                                                   "country": d.country if d else "",
                                                                   "local_currency": local})
    except MCPToolError as exc:
        bundle.errors.append(f"local prices: {exc}")
    extra_cur = {x["currency"] for x in prices.get("listings") or [] if x.get("currency")}
    t = prices.get("tariffs") or {}
    extra_cur |= {q["currency"] for q in [t.get(k) for k in ("transit_single_ticket", "taxi_flag_fall", "taxi_per_km")]
                  + list(t.get("airport_fares") or []) if q}

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
        if not p.price_known and p.cost_per_person.currency == "USD" and p.cost_per_person.price_type == "estimated":
            p.cost_per_person = Money(amount=round(p.cost_per_person.amount * bundle.cost_factor, 2), currency="USD",
                                      price_type="estimated")
    # Published prices replace the estimates wherever they exist; then the official websites of the likely
    # picks, then AI estimates for what nothing publishes (pricing.py: the full cascade, no SerpApi credits).
    apply_local_prices(bundle, prices, user)
    from . import pricing

    await pricing.research_prices(hub, bundle, contract, scale=price_scale)

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
                "fixed_fares": (prices.get("tariffs") or {}).get("airport_fares") or []})
            transfers += [TransferOption.model_validate(t) for t in res["results"]]
        except MCPToolError as exc:
            bundle.errors.append(f"transfers {code}: {exc}")
    bundle.airport_transfers = transfers

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

    # 5) Real walking / driving times between everything the planner may use.
    await prepare_routing(bundle)


MAX_NEW_INSIGHTS = 3  # each is one (30-day cached) review search + one model call


async def plan_hotel_insights(hub: MCPHub, trip, plans: dict) -> None:
    """Run the review-analyst agent on the hotels the plans actually chose (the research-time lookups only
    cover the most popular hotels). Results are written to every copy of the hotel (research and plans)."""
    from . import llm

    if not llm.available() or trip.research is None:
        return
    # Only the plan the traveller sees (one hotel, or one per city): each review lookup costs a credit.
    shown = plans.get(trip.selected_mode) or next(iter(plans.values()), None)
    if shown is None:
        return
    chosen = ([shown.hotel] if shown.hotel else []) + [s.hotel for s in shown.stops if getattr(s, "hotel", None)]
    bundles = [trip.research] + list(trip.research.stops)
    known = {h.id: h for b in bundles for h in b.hotels if h.review_insights}
    todo = list({h.id: h for h in chosen if h.property_token and h.id not in known}.values())[:MAX_NEW_INSIGHTS]
    results = await hub.call_many([("hotels", "get_hotel_reviews", {"property_token": h.property_token,
                                                                     "hotel_name": h.name}) for h in todo])
    for h, res in zip(todo, results):
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


def _tokens(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return {t for t in re.findall(r"[a-z0-9]+", s) if len(t) > 2 and t not in ("the", "and", "del", "della")}


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
    resolved: dict[str, str] = trip.metadata.setdefault("must_visit", {})
    bundles = r.stops or [r]
    notes, ids = [], []
    cities = [s.name for s in c.stops] or [c.destination]
    for name in names:
        if any(_tokens(name) and _tokens(name) <= _tokens(city) | {"el", "al"} for city in cities):
            continue  # a city of the route itself (e.g. "Sharm El Sheikh"), not a sight to schedule
        key = f"{c.route_name}|{name}"  # a lookup is only valid for the destination it was made for
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
    ids: list[str] = []
    for name in names[:4]:
        key = f"{ref.name}|{name}" if c.is_multi else f"{c.route_name}|{name}"
        pid = cache.get(key)
        if pid and r.place(pid):
            ids.append(pid)
            continue
        if pid == "":
            continue  # looked up before, nothing usable
        hit = match_place(name, r.attractions)
        if hit is None:
            try:
                res = await hub.call("activities", "find_place", {
                    "name": name, "city": info.get("name", c.destination), "lat": center["lat"], "lon": center["lon"],
                    "local_currency": info.get("currency", "USD"), "zoom": 11})
                p = Place.model_validate(res["result"]) if res.get("result") else None
            except MCPToolError as exc:
                log.warning("find_place %s failed: %s", name, exc)
                p = None
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
