"""Trip ideas for a budget: "I have 2,000 USD - where can I go?"

Google Travel Explore (through the activities MCP server) lists real destinations from the traveller's
airport with a current round-trip fare, a typical hotel night and suggested dates. The search follows the
traveller's preferences: exact dates or a flexible month + length, direct flights, a maximum flight time,
and interests Google can filter on (beaches, museums, history, outdoors, skiing).

Each idea is costed for the group (flights x travellers + hotel nights x rooms) and kept only if it fits
the budget with room left for food and sightseeing. The model then scores how well every idea matches
what the traveller asked for (interests, who is travelling, free-text wishes, season) and explains why,
so the best match comes first. Without the model a simple interest/price score is used. If live search
is unavailable, the AI fallback suggests destinations with estimated prices (clearly labelled).
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import date

from pydantic import BaseModel

from . import llm, research
from .mcp_hub import MCPHub, MCPToolError
from .providers import ai_fallback

log = logging.getLogger(__name__)

DURATION = {"weekend": (1, 2), "week": (2, 6), "two_weeks": (3, 13)}  # -> (Google travel_duration, nights)
SPENDING_SHARE = 0.25  # keep at least this share of the budget for food, transport and sights
# Interests Google Travel Explore can filter on (its own topic ids).
GOOGLE_INTEREST = {"beach": "/m/0b3yr", "culture": "/m/09cmq", "history": "/m/03g3w",
                   "nature": "/g/11bc58l13w", "adventure": "/g/11bc58l13w", "ski": "/m/071k0"}
MAX_INTEREST_SEARCHES = 2  # each search costs one SerpApi credit
MIN_IDEAS = 6  # show at least this many (over-budget ones are marked) so the page is never near-empty
MIN_TOPIC_RESULTS = 12  # fewer priced interest results than this -> also search the popular list
INTERESTS = ("beach", "culture", "history", "nature", "ski", "food", "nightlife", "shopping", "relax", "adventure")
OCCASIONS = ("solo", "couple", "honeymoon", "family", "friends")


class IdeaFit(BaseModel):
    name: str
    score: int  # 0-100: how well the destination matches the traveller
    why: str  # one short sentence in the traveller's language
    tags: list[str] = []  # 2-3 short highlights, e.g. "beaches", "old town"


class IdeaFits(BaseModel):
    fits: list[IdeaFit]


def _city_key(name: str) -> str:
    """'Paris, France' / 'Dubai - United Arab Emirates' / 'paris' -> 'paris'."""
    return re.split(r",| - ", name or "", maxsplit=1)[0].strip().lower()


def _nights(d: dict, default: int) -> int:
    try:
        n = (date.fromisoformat(d["end_date"]) - date.fromisoformat(d["start_date"])).days
    except (KeyError, TypeError, ValueError):
        n = default
    return max(1, n or default)


async def _explore(hub: MCPHub, departure: str, currency: str, travelers: int, when: dict,
                   direct_only: bool, max_flight_hours: float | None, interest: str | None,
                   where: dict | None = None) -> list[dict]:
    args = {"departure_id": departure, "currency": currency, "adults": travelers, **when, **(where or {}),
            "stops": 1 if direct_only else None,
            "max_duration": int(max_flight_hours * 60) if max_flight_hours else None, "interest": interest}
    try:
        res = await hub.call("activities", "explore_destinations", {k: v for k, v in args.items() if v is not None})
    except MCPToolError as exc:
        log.warning("travel explore unavailable (%s): %s", interest or "popular", exc)
        return []
    return res.get("destinations") or []


async def _rank(ideas: list[dict], prefs: dict, lang: str) -> dict[str, IdeaFit]:
    """The model scores every idea against what the traveller asked for."""
    if not llm.available() or not ideas:
        return {}
    brief = [{"name": i["name"], "country": i["country"], "dates": f"{i['start_date']} to {i['end_date']}",
              "nights": i["nights"], "flight_minutes": i["flight_minutes"], "stops": i["stops"],
              "total_flight_hotel": i["total"], "left_for_spending": i["left"]} for i in ideas]
    system = ("You are a travel expert matching destinations to a traveller. For EVERY destination give: score 0-100 "
              "(how well it suits the traveller's interests, who is travelling, their wishes and the season of the "
              "dates; do not score on price - that is handled separately), 'why': one short, specific sentence "
              f"(max 18 words) written in {'Egyptian Arabic' if lang == 'ar' else 'English'}, and 2-3 short 'tags' in "
              "the same language naming what makes it a match. Be honest: a city with no beach must score low for a "
              "beach lover; winter dates suit skiing, not swimming. Use the destination names exactly as given.")
    res = await llm.parse(system, json.dumps({"traveller": prefs, "destinations": brief}, ensure_ascii=False), IdeaFits)
    return {f.name.strip().lower(): f for f in (res.fits if res else [])}


def _simple_score(idea: dict, interests: list[str]) -> int:
    """Offline score: interests Google matched, then how comfortably it fits the budget."""
    hit = len(set(idea.get("matched") or []) & set(interests))
    return min(100, 50 + 20 * hit)


async def suggest(hub: MCPHub, budget: float, currency: str, origin: str, travelers: int = 1,
                  duration: str = "week", month: int | None = None, start_date: date | None = None,
                  end_date: date | None = None, interests: list[str] | None = None, occasion: str | None = None,
                  direct_only: bool = False, max_flight_hours: float | None = None, notes: str = "",
                  lang: str = "en", destination: str = "", taste=None) -> dict:
    """taste: optional async callable(names) -> {name: {"match": 0-100, "because": ...}} from the personal
    recommender (the user's trips, likes and searches); blended into the ranking when available."""
    travelers = max(1, min(travelers, 9))
    rooms = max(1, math.ceil(travelers / 2))
    currency = currency.upper()
    interests = [i for i in (interests or []) if i in INTERESTS]
    g_duration, default_nights = DURATION.get(duration, DURATION["week"])
    exact = bool(start_date and end_date and end_date > start_date)
    if exact:
        default_nights = (end_date - start_date).days
        when = {"outbound_date": start_date.isoformat(), "return_date": end_date.isoformat()}
    else:
        when = {"month": month or None, "travel_duration": g_duration}
    ref = await research.resolve_place(hub, origin)
    departure = ref.airports[0] if ref.airports else ref.flight_id
    # Optional "To": a country / region (ideas inside it) or one city (its best dates and prices).
    where, dest, city_only = None, None, None
    if destination.strip():
        dest = (await hub.call("knowledge", "resolve_destination", {"query": destination.strip()}))["result"]
        if dest["kind"] == "region":
            where = {"arrival_area_id": dest["id"]}
        else:
            # A city: search its whole country - the city comes back with real flight AND hotel prices, and the
            # country's other cities make good alternatives. A city missing from that list is searched alone.
            city_only = {"arrival_id": dest["id"]}
            country = re.split(r",| - ", dest["name"], maxsplit=1)[-1].strip() if re.search(r",| - ", dest["name"]) else ""
            try:
                region = (await hub.call("knowledge", "resolve_destination", {"query": country}))["result"] if country else None
            except MCPToolError:
                region = None
            where = {"arrival_area_id": region["id"]} if region and region["kind"] == "region" else city_only
    target = _city_key(dest["name"]) if dest and dest["kind"] == "city" else None

    # One search per interest Google understands (at most two), otherwise the popular list.
    topics = list(dict.fromkeys(GOOGLE_INTEREST[i] for i in interests if i in GOOGLE_INTEREST))[:MAX_INTEREST_SEARCHES]
    topic_names = {v: [k for k in interests if GOOGLE_INTEREST.get(k) == v] for v in topics}
    merged: dict[str, dict] = {}

    def add(found: list[dict], topic: str | None) -> None:
        for d in found:
            key = (d.get("name") or "").strip().lower()
            if not key:
                continue
            if d.get("flight_price") and travelers > 1:  # searched with adults=N: Google's fare is for the whole group
                d = {**d, "flight_price": round(d["flight_price"] / travelers)}
            item = merged.setdefault(key, {**d, "matched": []})
            item["matched"] += topic_names.get(topic, [])

    # One city: its best dates and prices (topics don't apply). A region / anywhere: per-interest searches.
    for topic in (topics if not target else []):
        add(await _explore(hub, departure, currency, travelers, when, direct_only, max_flight_hours, topic, where), topic)
    # Google has no topic results for some airports (or only a handful): widen with the popular list and let the
    # ranking judge the fit. Real prices always beat estimates.
    if sum(1 for d in merged.values() if d.get("flight_price")) < MIN_TOPIC_RESULTS:
        add(await _explore(hub, departure, currency, travelers, when, direct_only, max_flight_hours, None, where), None)
    if target and not any(_city_key(k) == target for k in merged) and where is not city_only:
        # The city isn't in its country's list: ask for it alone (real flights; no hotel price from Google).
        for d in await _explore(hub, departure, currency, travelers, when, direct_only, max_flight_hours, None, city_only):
            d["name"], d["country"] = re.split(r",| - ", dest["name"], maxsplit=1)[0].strip(), \
                (re.split(r",| - ", dest["name"], maxsplit=1)[1].strip() if re.search(r",| - ", dest["name"]) else "")
            add([d], None)
    ideas, estimated = list(merged.values()), False

    prefs = {"interests": interests, "occasion": occasion, "travellers": travelers, "wishes": notes.strip()[:300],
             "dates": f"{start_date} to {end_date}" if exact else None, "month": None if exact else month,
             "nights": default_nights, "origin": f"{ref.name}, {ref.country}", "direct_only": direct_only,
             "max_flight_hours": max_flight_hours, "destination": dest["name"] if dest else None}
    if not ideas and ai_fallback.available():
        ideas = await ai_fallback.destination_ideas(ref.name, ref.country, currency, default_nights, month, prefs)
        estimated = True
        if ideas and currency != "USD":  # the estimates are in USD: convert with live rates
            try:
                fx = (await hub.call("currency", "get_exchange_rates", {"base": "USD", "quotes": [currency]}))["rates"]
                rate = float(fx[currency]) if fx.get(currency) else None
            except (MCPToolError, KeyError, ValueError, TypeError):
                rate = None
            if rate is None:
                # Dollar estimates must never be shown as pounds: without a rate there are no comparable ideas.
                log.warning("no USD->%s rate; dropping AI-estimated ideas", currency)
                ideas = []
            for d in ideas:
                d["flight_price"] = round(d["flight_price"] * rate)
                d["hotel_price"] = round(d["hotel_price"] * rate)

    out = []
    for d in ideas:
        flight, hotel = d.get("flight_price"), d.get("hotel_price")
        if not flight or not d.get("name"):
            continue
        if exact:  # Google may shift dates slightly; the traveller's dates are what count
            d["start_date"], d["end_date"] = start_date.isoformat(), end_date.isoformat()
        nights = _nights(d, default_nights)
        total = flight * travelers + (hotel or 0) * nights * rooms
        out.append({
            "name": d["name"], "country": d.get("country", ""), "thumbnail": d.get("thumbnail"),
            "start_date": d.get("start_date"), "end_date": d.get("end_date"), "nights": nights,
            "flight_price": flight, "hotel_price": hotel, "airline": d.get("airline"),
            "stops": d.get("number_of_stops"), "flight_minutes": d.get("flight_duration"),
            "total": round(total), "left": round(budget - total), "fits": total <= budget,
            # comfortable: a quarter of the budget stays for food & sights; tight: fits, with less to spend
            "fit": "comfortable" if total <= budget * (1 - SPENDING_SHARE) else "tight" if total <= budget else "over",
            "lat": d.get("lat"), "lon": d.get("lon"), "link": d.get("link"),
            "matched": d.get("matched") or [], "estimated": estimated or bool(d.get("estimated")),
            "hotel_unknown": hotel is None,  # Google gave no hotel price: the total is the flights only
            "target": bool(target) and _city_key(d["name"]) == target,
        })
    fitting = [x for x in out if x["fits"]]
    # Never leave the traveller with a near-empty page: top up with the closest over-budget trips (clearly marked).
    over = sorted((x for x in out if not x["fits"]), key=lambda x: x["total"])
    pool = fitting + over[:max(0, MIN_IDEAS - len(fitting))]
    pool += [x for x in out if x["target"] and x not in pool]  # the named city is always shown (marked if over)

    # Hybrid ranking: the model's fit to what was asked now, plus the traveller's long-term taste (Doc2Vec over
    # their past trips, likes and searches) - each where available, never invented.
    affinity: dict = {}
    if taste is not None:
        try:
            affinity = await taste([x["name"] for x in pool[:30]]) or {}
        except Exception as exc:  # personalisation is a bonus, never a failure
            log.info("taste affinity unavailable: %s", exc)
    personal = bool(interests or occasion or notes.strip() or exact or month or affinity)
    fits = await _rank(pool[:30], prefs, lang) if personal else {}
    for i, x in enumerate(pool):
        f = fits.get(x["name"].strip().lower())
        base = f.score if f else (_simple_score(x, interests) if personal else None)
        t = affinity.get(x["name"])
        x["taste_match"] = t["match"] if t else None
        x["taste_because"] = t["because"] if t else None
        # The request in hand leads; long-term taste refines (weights: a ranking choice, documented in the audit).
        x["score"] = round(0.75 * base + 0.25 * t["match"]) if (base is not None and t) else base
        x["why"], x["tags"] = (f.why, f.tags[:3]) if f else ("", [])
        x["rank"] = i  # Google lists the most popular first: the tie-breaker
    # Trips within budget always come before over-budget ones; within that, best match (or most popular) first.
    tier = {"comfortable": 0, "tight": 0, "over": 1}
    # The city the traveller named always comes first; then within budget, best match (or most popular).
    pool.sort(key=lambda x: (not x["target"], tier[x["fit"]], -(x["score"] or 0) if personal else 0, x["rank"]))
    return {"origin": {"name": ref.name, "country": ref.country, "lat": ref.lat, "lon": ref.lon},
            "currency": currency, "budget": budget, "travelers": travelers, "duration": duration,
            "start_date": start_date.isoformat() if exact else None, "end_date": end_date.isoformat() if exact else None,
            "interests": interests, "occasion": occasion, "notes": notes.strip(), "personal": personal,
            "destination": dest,
            "all_fit": bool(fitting), "estimated": estimated, "ideas": pool[:16]}
