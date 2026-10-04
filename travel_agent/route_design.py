"""Route design: turn "Italy, France and Spain + the Leaning Tower of Pisa" into a concrete route to confirm.

When the traveller names countries (or just a region) instead of cities, planning shouldn't guess one city
per country. The agent proposes a route and waits for the traveller's answer:

1. The places the traveller named are located on Google Maps (real coordinates).
2. The LLM designs the route: which base cities, how many nights each, which named places become day trips
   (e.g. Florence as the base for Pisa). Without an LLM a deterministic design is used instead.
3. Every city is checked against real data (Google Flights autocomplete + Geoapify): it must exist and have
   an airport or station. Unknown cities are dropped.
4. The order is optimised for the shortest total travel from the origin and back, nights are fitted to the
   dates, and every named place is checked to be within day-trip reach of a base.
5. The proposal goes to the chat. The traveller accepts it, changes it (other cities, more nights, a
   different order) or asks the agent to decide. Each change produces a new proposal: a feedback loop
   until the route is confirmed, and only then does the expensive research start.
"""

from __future__ import annotations

import itertools
import json
import logging
import re
from datetime import timedelta

from pydantic import BaseModel, Field

from . import llm, research
from .journey import split_nights
from .mcp_hub import MCPHub, MCPToolError
from .models import Place, PlaceRef, ProposedStop, RouteProposal, TripState
from .providers import geo
from .providers.places import MAX_DAY_TRIP_KM
from .utils import haversine_km

log = logging.getLogger(__name__)

def needs_design(trip: TripState) -> bool:
    """Countries or a region (not cities) were given and the traveller hasn't confirmed a route yet."""
    d = trip.draft
    return not d.route_confirmed and (d.redesign or bool(d.countries)
                                      or (bool(d.region) and not d.destinations and not d.destination))


def total_nights(trip: TripState) -> int:
    d = trip.draft
    if d.start_date and d.end_date:
        return max((d.end_date - d.start_date).days, 1)
    return max((d.duration_days or 7) - 1, 1)


# ---------------------------------------------------------------------------
# LLM design schema
# ---------------------------------------------------------------------------


class DesignStop(BaseModel):
    city: str = Field(description="Base city in English (must have an airport or a main train station)")
    country: str
    nights: int
    why: str = Field(description="One short sentence: why this base")
    covers: list[str] = Field(default_factory=list, description="Named places this base covers (exact names from the input)")
    day_trips: list[str] = Field(default_factory=list, description="Places visited as day trips from this base")


class RouteDesign(BaseModel):
    stops: list[DesignStop]
    summary: str = Field(description="Two sentences explaining the route logic")
    warnings: list[str] = Field(default_factory=list, description="Honest trade-offs, e.g. too few nights for everything")
    keep_order: bool = Field(default=False, description=(
        "true only if the traveller explicitly asked for a particular order of cities (in any language); "
        "otherwise false and the route will be re-ordered for the shortest travel"))


DESIGN_SYSTEM = """You are an expert travel route designer. Design a multi-city route (the traveller confirms it before any booking research).

Rules:
- Include every city in cities_already_chosen / current_route unless the traveller's feedback drops it.
- When the traveller's feedback names the cities they want, use exactly those cities (plus the current route's cities
  unless dropped) - never add other cities they didn't ask for. Suggest extra places in warnings instead.
- Only choose cities yourself for countries/regions the traveller named without cities.
- A named place that is itself a city or resort town (e.g. Sharm El Sheikh) must be a base with its own nights.
- Cover EVERY named place the traveller wants, using the given coordinates. A named place far (>60 km) from a big city can be a day trip from a base up to ~150 km away (e.g. the Leaning Tower of Pisa as a day trip from Florence), or be a base itself.
- Cover every country listed (or, for a region, choose the best countries yourself). A big country may get 2 bases if the nights allow.
- Pick bases that show the countries' most famous highlights and have an airport or a main train station.
- Nights must add up exactly to the total nights. Prefer >= 2 nights per base; with too few nights, say which trade-off you made in warnings (never silently drop a named place).
- Order the bases geographically so the journey from the origin and back is short (no zig-zag).
- Respect the traveller's feedback on earlier proposals (it may be in any language): it overrides these rules.
- If the traveller says where the trip starts or ends, or which city comes first/last (e.g. "go to Sharm, then fly to Cairo at the end" = Sharm first, Cairo last), list the stops in exactly that order and set keep_order=true. Otherwise keep_order=false.
- Cities and countries in English."""


async def _locate_named(hub: MCPHub, names: list[str], anchors: list[PlaceRef]) -> list[tuple[str, Place]]:
    """Real coordinates for the places the traveller named (one Google Maps lookup each, cached)."""
    if not names or not anchors:
        return []
    lat = sum(a.lat for a in anchors) / len(anchors)
    lon = sum(a.lon for a in anchors) / len(anchors)
    spread = max(haversine_km(lat, lon, a.lat, a.lon) for a in anchors)
    zoom = 4 if spread > 600 else 5 if spread > 200 else 7
    out = []
    for name in names:
        try:
            res = await hub.call("activities", "find_place", {"name": name, "city": "", "lat": lat, "lon": lon,
                                                              "local_currency": "USD", "zoom": zoom})
        except MCPToolError as exc:
            log.warning("could not locate %s: %s", name, exc)
            continue
        if res.get("result"):
            out.append((name, Place.model_validate(res["result"])))
    return out


def _route_km(origin: PlaceRef | None, stops: list[PlaceRef]) -> float:
    pts = ([origin] if origin else []) + stops + ([origin] if origin else [])
    return sum(haversine_km(a.lat, a.lon, b.lat, b.lon) for a, b in zip(pts, pts[1:]))


def best_order(origin: PlaceRef | None, stops: list[ProposedStop]) -> list[ProposedStop]:
    """Shortest origin -> stops -> origin order (exact for up to 7 stops)."""
    if len(stops) < 3 or len(stops) > 7:
        return stops
    return list(min(itertools.permutations(stops), key=lambda p: _route_km(origin, [s.ref for s in p])))


async def _fallback_design(hub: MCPHub, trip: TripState, located: list[tuple[str, Place]]) -> RouteDesign:
    """No LLM: one base per country (its main city), plus a base next to any named place out of day-trip reach."""
    d = trip.draft
    stops: list[DesignStop] = []
    bases = [(r, r.country) for r in d.destination_refs] or ([(d.destination_ref, d.destination_ref.country)]
                                                               if d.destination_ref else [])
    for ref, country in bases:
        stops.append(DesignStop(city=ref.name, country=country, nights=1, why=f"Main gateway to {country}"))
    for name, p in located:
        near = [s for s in stops for r in bases if r[0].name == s.city
                and haversine_km(r[0].lat, r[0].lon, p.location.lat, p.location.lon) <= 150]
        if near:
            near[0].covers.append(name)
            continue
        try:
            ref = await research.resolve_place(hub, name)
        except MCPToolError:
            continue
        stops.append(DesignStop(city=ref.name, country=ref.country, nights=1, why=f"Base for {name}", covers=[name]))
    return RouteDesign(stops=stops, summary="One base per country, plus a base close to each place you named.")


async def propose(hub: MCPHub, trip: TripState) -> RouteProposal:
    d, p = trip.draft, trip.traveler_profile
    nights = total_nights(trip)
    anchors = list(d.destination_refs) or ([d.destination_ref] if d.destination_ref else [])
    located = await _locate_named(hub, d.must_visit, anchors or ([d.origin_ref] if d.origin_ref else []))

    facts = {
        "origin": d.origin_ref.name if d.origin_ref else None,
        "countries": d.countries, "cities_already_chosen": [x for x in d.destinations if not geo.country_code(x)],
        "region": d.region, "total_nights": nights,
        "dates": f"{d.start_date} to {d.end_date}" if d.start_date and d.end_date else None,
        "travelers": d.travelers, "budget": f"{d.budget_amount} {d.budget_currency or 'USD'}" if d.budget_amount else None,
        "interests": p.activity_preferences, "pace": p.travel_style,
        "named_places": [{"name": n, "found_as": pl.name, "lat": round(pl.location.lat, 4), "lon": round(pl.location.lon, 4),
                          "address": pl.address} for n, pl in located],
        "current_route": [f"{s.name} ({s.nights} nights)" for s in trip.trip_contract.stops]
        if d.redesign and trip.trip_contract and trip.trip_contract.stops
        else ([f"{trip.trip_contract.destination} ({trip.trip_contract.nights} nights)"]
              if d.redesign and trip.trip_contract else None),
        "previous_proposal": [f"{s.city} ({s.nights} nights)" for s in d.route_proposal.stops] if d.route_proposal else None,
        "traveller_feedback": d.route_feedback,
    }
    design = await llm.parse(DESIGN_SYSTEM, json.dumps(facts, default=str), RouteDesign) if llm.available() else None
    if design is None or not design.stops:
        design = await _fallback_design(hub, trip, located)

    stops, warnings = await _verified_stops(hub, design)
    missed = _uncovered(stops, located)
    if missed and llm.available():
        # A named place is out of reach: tell the model exactly what it missed and ask again, once.
        facts["problem_with_your_last_design"] = [
            f"'{pl.name}' (lat {pl.location.lat:.3f}, lon {pl.location.lon:.3f}) is {km:.0f} km from the nearest base - "
            "every named place must be within ~150 km of a base (use a nearby base city)" for pl, km in missed]
        facts["your_last_design"] = [f"{s.city} ({s.nights})" for s in design.stops]
        retry = await llm.parse(DESIGN_SYSTEM, json.dumps(facts, default=str), RouteDesign)
        if retry and retry.stops:
            retry_stops, retry_warnings = await _verified_stops(hub, retry)
            if retry_stops and len(_uncovered(retry_stops, located)) < len(missed):
                design, stops, warnings = retry, retry_stops, retry_warnings
    for pl, _km in _uncovered(stops, located):
        # Still out of reach: move that country's base next to the place (deterministic fix).
        # The place's own city comes from reverse geocoding its real coordinates (Geoapify).
        try:
            city = await geo.reverse_city(pl.location.lat, pl.location.lon)
            ref = await research.resolve_place(hub, city or pl.name)
        except Exception as exc:  # noqa: BLE001 - any lookup failure: keep the warning instead
            log.warning("no base near %s: %s", pl.name, exc)
            continue
        if haversine_km(ref.lat, ref.lon, pl.location.lat, pl.location.lon) > 150:
            continue
        same = [s for s in stops if s.ref.country_code == ref.country_code and not s.covers]
        if same:
            old = same[0]
            warnings.append(f"I moved the {old.country} base from {old.city} to {ref.name} so {pl.name} fits in.")
            old.city, old.ref, old.why = ref.name, ref, f"Close to {pl.name}"
            design = design.model_copy(update={"summary": ""})  # the model's summary described the old base
        elif all(s.ref.name != ref.name for s in stops):
            stops.append(ProposedStop(city=ref.name, country=ref.country, nights=1, why=f"Close to {pl.name}", ref=ref))
    return await _finish(trip, design, stops, warnings, located)


async def _verified_stops(hub: MCPHub, design: RouteDesign) -> tuple[list[ProposedStop], list[str]]:
    """Every base must be a real place with an airport / station (Google Flights autocomplete + Geoapify)."""
    stops: list[ProposedStop] = []
    warnings = list(design.warnings)
    for s in design.stops:
        try:
            ref = await research.resolve_place(hub, f"{s.city}, {s.country}" if s.country else s.city)
        except MCPToolError:
            try:
                ref = await research.resolve_place(hub, s.city)
            except MCPToolError:
                warnings.append(f"I couldn't verify {s.city}, so I left it out.")
                continue
        if any(x.ref and x.ref.name == ref.name for x in stops):
            continue
        stops.append(ProposedStop(city=ref.name, country=ref.country, nights=max(1, s.nights), why=s.why,
                                  covers=s.covers, day_trips=s.day_trips, ref=ref))
    return stops, warnings


def _uncovered(stops: list[ProposedStop], located: list[tuple[str, Place]], reach_km: float = 150) -> list[tuple[Place, float]]:
    """Named places farther than a comfortable day trip from every base."""
    out = []
    for _name, pl in located:
        km = min((haversine_km(s.ref.lat, s.ref.lon, pl.location.lat, pl.location.lon) for s in stops), default=1e9)
        if km > reach_km:
            out.append((pl, km))
    return out


async def _finish(trip: TripState, design: RouteDesign, stops: list[ProposedStop], warnings: list[str],
                  located: list[tuple[str, Place]]) -> RouteProposal:
    d = trip.draft
    nights = total_nights(trip)
    if not stops:
        return RouteProposal(warnings=warnings or ["I couldn't build a route - which cities would you like?"])

    # The order the traveller typed the countries in, to show what the optimisation saved.
    typed_codes = [geo.country_code(x) for x in d.countries]
    typed = sorted(stops, key=lambda s: typed_codes.index(s.ref.country_code)
                   if s.ref.country_code in typed_codes else len(typed_codes))
    if not design.keep_order:  # the traveller didn't ask for a specific order: take the shortest one
        stops = best_order(d.origin_ref, stops)
    fitted = split_nights(nights, len(stops), [s.nights for s in stops])
    for s, n in zip(stops, fitted):
        s.nights = n
    if len(stops) > nights:
        warnings.append(f"{len(stops)} cities in {nights} nights is too many - drop one or add days.")

    # Every named place must be reachable (day trip at most) from some base; report the real distances.
    for name, pl in located:
        base = min(stops, key=lambda s: haversine_km(s.ref.lat, s.ref.lon, pl.location.lat, pl.location.lon))
        km = haversine_km(base.ref.lat, base.ref.lon, pl.location.lat, pl.location.lon)
        label = f"{pl.name} (~{km:.0f} km)" if km > 25 else pl.name
        if km > MAX_DAY_TRIP_KM:
            warnings.append(f"{pl.name} is ~{km:.0f} km from {base.city} - too far for a day trip from any base. "
                            "Add a stop near it, or drop it?")
        elif km > 25:
            if label not in base.day_trips and not any(pl.name.split()[0] in x for x in base.day_trips):
                base.day_trips.append(label)
        elif name not in base.covers and pl.name not in base.covers:
            base.covers.append(pl.name)

    for s in stops:  # a day trip isn't also "in the city"
        s.covers = [x for x in s.covers if not any(x.split()[-1].lower() in t.lower() for t in s.day_trips)]
    refs = [s.ref for s in stops]
    km = _route_km(d.origin_ref, refs)
    typed_km = _route_km(d.origin_ref, [s.ref for s in typed])
    prev = d.route_proposal.version if d.route_proposal else 0
    return RouteProposal(stops=stops, summary=design.summary, warnings=warnings, travel_km=round(km),
                         typed_order_km=round(typed_km) if typed_km > km * 1.05 else None, version=prev + 1)


# ---------------------------------------------------------------------------
# Chat message
# ---------------------------------------------------------------------------


def template_message(trip: TripState) -> str:
    d = trip.draft
    pr = d.route_proposal
    assert pr is not None
    if not pr.stops:
        return " ".join(pr.warnings)
    dates = f" ({d.start_date:%b %d} → {d.end_date:%b %d})" if d.start_date and d.end_date else ""
    lines = [f"**Here's the route I suggest for your {sum(s.nights for s in pr.stops)} nights{dates}:**", ""]
    for i, s in enumerate(pr.stops, 1):
        extra = []
        if s.covers:
            extra.append(", ".join(s.covers))
        if s.day_trips:
            extra.append("day trip: " + ", ".join(s.day_trips))
        lines.append(f"{i}. **{s.city}**, {s.country} - {s.nights} night{'s' if s.nights > 1 else ''}"
                     + (f" · {' · '.join(extra)}" if extra else "") + (f"  \n   _{s.why}_" if s.why else ""))
    origin = d.origin_ref.name if d.origin_ref else "home"
    lines += ["", f"Route: {origin} → " + " → ".join(s.city for s in pr.stops) + f" → {origin} "
                  f"(~{pr.travel_km:,.0f} km of travel between cities)."]
    if pr.typed_order_km:
        lines.append(f"I changed the order to avoid zig-zagging: the order you typed would be ~{pr.typed_order_km:,.0f} km.")
    if pr.summary:
        lines.append(pr.summary)
    if pr.warnings:
        lines += [""] + [f"⚠️ {w}" for w in pr.warnings]
    lines += ["", "Shall I plan it? Reply **yes**, or change anything - other cities, more nights somewhere, "
                  "a different order, drop a country - or tell me to decide for you."]
    return "\n".join(lines)


PROPOSAL_SYSTEM = """You are a friendly travel agent chatting with a traveller. Present the proposed route from the JSON facts.
Use only the facts. Write in the same language (and dialect) as 'traveller_latest_message', keeping city and place names readable.
Structure: one warm line; a numbered list of the bases (nights, what each covers, day trips); one line on why this order
(mention the km figures if given); any warnings honestly; then ask clearly: shall I plan it, or would they like to change
cities, nights or order (or let you decide). Under 180 words. Nothing is booked.
Never mention internal tools, models or technical terms."""


async def compose_message(trip: TripState, user_message: str) -> str:
    pr = trip.draft.route_proposal
    if llm.available() and pr and pr.stops:
        facts = {"traveller_latest_message": user_message,
                 "origin": trip.draft.origin_ref.name if trip.draft.origin_ref else None,
                 "dates": f"{trip.draft.start_date} to {trip.draft.end_date}",
                 "stops": [s.model_dump(exclude={"ref"}) for s in pr.stops], "summary": pr.summary,
                 "warnings": pr.warnings, "travel_km": pr.travel_km, "order_you_typed_km": pr.typed_order_km}
        out = await llm.text(PROPOSAL_SYSTEM, json.dumps(facts, default=str, ensure_ascii=False))
        if out:
            return out
    msg = template_message(trip)
    if llm.last_error:
        msg += ("\n\n_I can't read detailed change requests right now. Use **Plan this route**, or write the exact "
                "cities you want (e.g. \"Barcelona, Paris, Florence\")._")
    return msg


def apply_proposal(trip: TripState) -> None:
    """The traveller accepted: the proposed bases become the trip's destinations."""
    d = trip.draft
    pr = d.route_proposal
    assert pr is not None and pr.stops
    d.route_confirmed = True
    d.redesign = False
    refs = [s.ref for s in pr.stops if s.ref]
    d.destinations = [r.name for r in refs]
    d.destination_refs = refs
    d.stop_nights = [s.nights for s in pr.stops]
    d.destination, d.destination_ref = refs[0].name, refs[0]
    if len(refs) == 1:
        d.destinations, d.destination_refs, d.stop_nights = [], [], []
    if d.start_date and not d.end_date:
        d.end_date = d.start_date + timedelta(days=sum(s.nights for s in pr.stops))
