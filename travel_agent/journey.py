"""Multi-city journeys: several cities (and countries) in one trip.

A journey is a chain of stops: origin -> stop 1 -> stop 2 -> ... -> origin.
Every stop is researched like a normal destination (its own hotels, sights,
restaurants, weather, prices and airport transfers) and every leg between two
stops gets real options: a one-way Google Flights search when the cities are far
apart, and a train / coach (Google Maps travel time) when they are close.

Planning reuses the single-city engine for each stop, in order: the journey
chosen to leave stop i is the one arriving at stop i+1, and the day you move
between two cities is merged into a single travel day. Validation, repair and
scoring then run on the merged plan against the whole-trip budget.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from datetime import date, timedelta

from .mcp_hub import MCPHub, MCPToolError
from .models import (
    FlightOption,
    GeoPoint,
    PlaceRef,
    ResearchBundle,
    StopPlan,
    TravelerProfile,
    TripContract,
    TripPlan,
    TripStop,
)
from .utils import haversine_km

log = logging.getLogger(__name__)

FLY_ABOVE_KM = 350     # consider flights between stops further apart than this
GROUND_BELOW_KM = 700  # consider trains / coaches between stops closer than this
SERPAPI_PER_EXTRA_STOP = 11  # rough live-search cost of researching one more city (hotel, food, sights, leg)


# ---------------------------------------------------------------------------
# Contract helpers
# ---------------------------------------------------------------------------


def split_nights(total: int, k: int, requested: list[int] | None = None) -> list[int]:
    """Nights per stop: the user's split when it fits, else as even as possible (earlier stops get the extra)."""
    if requested and len(requested) == k and all(n > 0 for n in requested) and sum(requested) == total:
        return list(requested)
    if requested and len(requested) == k and all(n > 0 for n in requested):
        # Scale a requested split that doesn't add up to the trip length, keeping its proportions.
        scaled = [max(1, round(n * total / sum(requested))) for n in requested]
        while sum(scaled) > total:
            scaled[scaled.index(max(scaled))] -= 1
        while sum(scaled) < total:
            scaled[scaled.index(min(scaled))] += 1
        return scaled
    base, extra = divmod(total, k)
    return [base + (1 if i < extra else 0) for i in range(k)]


def build_stops(refs: list[PlaceRef], start: date, end: date, requested: list[int] | None = None
                ) -> tuple[list[TripStop], date, list[str]]:
    """Returns (stops, possibly extended end date, assumptions)."""
    notes: list[str] = []
    k = len(refs)
    total = (end - start).days
    if requested and len(requested) == k and all(n > 0 for n in requested) and total < sum(requested):
        total = sum(requested)
        end = start + timedelta(days=total)
    if total < k:
        total = k
        end = start + timedelta(days=total)
        notes.append(f"A {k}-city trip needs at least one night per city, so I extended it to {total} nights.")
    nights = split_nights(total, k, requested)
    if not requested:
        notes.append("I split the nights between the cities: "
                     + ", ".join(f"{r.name} {n}" for r, n in zip(refs, nights)) + " - tell me if you want a different split.")
    if min(nights) < 2:
        notes.append("Some cities get a single night - a longer trip or fewer cities would feel less rushed.")
    stops, day = [], start
    for ref, n in zip(refs, nights):
        stops.append(TripStop(ref=ref, nights=n, start_date=day, end_date=day + timedelta(days=n)))
        day += timedelta(days=n)
    return stops, end, notes


def stop_contract(c: TripContract, i: int, budget_amount: float | None = None) -> TripContract:
    """The single-city contract of stop i (its own dates; the whole trip's travelers and preferences)."""
    s = c.stops[i]
    update = {"destination": s.name, "destination_name": s.name, "destination_ref": s.ref,
              "start_date": s.start_date, "end_date": s.end_date, "stops": [],
              "arrive_by": c.arrive_by if i == 0 else None}  # "arrive on the 1st" is about the first city
    if budget_amount is not None:
        update["budget"] = c.budget.model_copy(update={"amount": round(budget_amount, 2)})
    return c.model_copy(update=update)


def leg_endpoints(c: TripContract) -> list[tuple[PlaceRef, PlaceRef, date]]:
    assert c.origin_ref is not None
    points = [c.origin_ref] + [s.ref for s in c.stops] + [c.end_ref]  # home, or another city (open-jaw)
    dates = [c.start_date] + [s.end_date for s in c.stops]
    return [(points[i], points[i + 1], dates[i]) for i in range(len(points) - 1)]


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------


async def _leg_options(hub: MCPHub, a: PlaceRef, b: PlaceRef, on: date, currency: str, direction: str,
                       origin_code: str | None = None) -> tuple[list[FlightOption], list[str]]:
    """origin_code: the airport the traveller named, for the first leg (from it) or the last one (to it)."""
    km = haversine_km(a.lat, a.lon, b.lat, b.lon)
    options: list[FlightOption] = []
    errors: list[str] = []
    fly = km >= FLY_ABOVE_KM and bool(a.airports or a.city_id) and bool(b.airports or b.city_id)
    ground = km <= GROUND_BELOW_KM
    if fly:
        try:
            res = await hub.call("flights", "search_one_way_flights", {
                "origin": origin_code if origin_code and direction == "outbound" else a.flight_id,
                "destination": origin_code if origin_code and direction == "return" else b.flight_id,
                "departure_date": on.isoformat(), "currency": currency, "origin_timezone": a.timezone,
                "destination_timezone": b.timezone, "direction": direction,
                "origin_name": f"{a.name}, {a.country}", "destination_name": f"{b.name}, {b.country}"})
            options += [FlightOption.model_validate(f) for f in res["results"]]
        except MCPToolError as exc:
            errors.append(f"flights {a.name} -> {b.name}: {exc}")
    if ground or (fly and not options and km <= 1200):
        try:
            res = await hub.call("transport", "get_intercity_journeys", {
                "from_city": f"{a.name}, {a.country}".strip(", "), "from_lat": a.lat, "from_lon": a.lon,
                "to_city": f"{b.name}, {b.country}".strip(", "), "to_lat": b.lat, "to_lon": b.lon,
                "travel_date": on.isoformat(), "from_timezone": a.timezone, "to_timezone": b.timezone})
            ground_opts = [FlightOption.model_validate(f) for f in res["results"]]
            for g in ground_opts:  # short city names read better in the timeline
                g.origin, g.destination = a.name, b.name
                g.direction = direction  # type: ignore[assignment]
            options += ground_opts
        except MCPToolError as exc:
            errors.append(f"ground transport {a.name} -> {b.name}: {exc}")
    return options, errors


async def research_legs(hub: MCPHub, c: TripContract) -> dict:
    """Journey options for every leg, searched in parallel."""
    ends = leg_endpoints(c)
    origin_code = c.origin if len(c.origin) == 3 else None
    # The last leg flies to the return city's airport when the trip ends elsewhere (open-jaw).
    end_code = (c.return_to if c.return_to and len(c.return_to) == 3 else None) if c.return_ref else origin_code
    results = await asyncio.gather(*(
        _leg_options(hub, a, b, on, c.budget.currency, "return" if i == len(ends) - 1 else "outbound",
                     origin_code if i == 0 else (end_code if i == len(ends) - 1 else None))
        for i, (a, b, on) in enumerate(ends)))
    legs = [r[0] for r in results]
    errors = [e for r in results for e in r[1]]
    return {"outbound": legs[0], "return": legs[-1], "insights": {}, "legs": legs, "errors": errors}


async def per_stop(c: TripContract, infos: list[dict], fn) -> list:
    """Run a single-city research call for every stop (in parallel); a failing stop yields []."""
    async def one(i: int):
        try:
            return await fn(stop_contract(c, i), infos[i])
        except (MCPToolError, KeyError, ValueError) as exc:
            log.warning("research for stop %s failed: %s", c.stops[i].name, exc)
            return []
    return list(await asyncio.gather(*(one(i) for i in range(len(c.stops)))))


def merge_research(stops: list[ResearchBundle], legs: list[list[FlightOption]], errors: list[str]) -> ResearchBundle:
    """One bundle over every stop, so validators and scoring can check the whole journey."""
    def uniq(items):
        seen, out = set(), []
        for x in items:
            if x.id not in seen:
                seen.add(x.id)
                out.append(x)
        return out

    fx: dict[str, float] = {}
    for s in stops:
        fx.update(s.fx_rates)
    first = stops[0]
    info = dict(first.destination_info)
    info["stops"] = [s.destination_info for s in stops]
    return ResearchBundle(
        flights_outbound=uniq([f for leg in legs[:-1] for f in leg]),
        flights_return=list(legs[-1]) if legs else [],
        hotels=uniq([h for s in stops for h in s.hotels]),
        restaurants=uniq([p for s in stops for p in s.restaurants]),
        attractions=uniq([p for s in stops for p in s.attractions]),
        weather=sorted({w.date: w for s in reversed(stops) for w in s.weather}.values(), key=lambda w: w.date),
        airport_transfers=[t for s in stops for t in s.airport_transfers],
        fx_rates=fx, fx_metadata=first.fx_metadata, destination_info=info,
        cost_factor=round(statistics.mean(s.cost_factor for s in stops), 2),
        fares=dict(first.fares),
        errors=list(errors) + [e for s in stops for e in s.errors],
        stops=stops, legs=legs,
    )


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def _localize_knobs(knobs, first_day: int, num_days: int, hotel_scale: float):
    """Repair / replan knobs are keyed by trip day; each stop plans with its own day numbers."""
    k = knobs.model_copy(deep=True)
    last = first_day + num_days - 1

    def local(d: int) -> int | None:
        return d - first_day + 1 if first_day <= d <= last else None

    k.exclude_on_day = {local(d): ids for d, ids in knobs.exclude_on_day.items() if local(d)}
    k.day_capacity_override = {local(d): v for d, v in knobs.day_capacity_override.items() if local(d)}
    k.avoid_outdoor_days = [local(d) for d in knobs.avoid_outdoor_days if local(d)]
    if knobs.hotel_max_price_local is not None:
        # The cap was set from the first city's hotel: scale it to this city's price level.
        k.hotel_max_price_local = knobs.hotel_max_price_local * hotel_scale
    return k


def _median_hotel(b: ResearchBundle) -> float:
    # In the traveller's currency: cities can price hotels in different currencies.
    prices = [h.price_per_night.amount * b.fx_rates.get(h.price_per_night.currency.upper(), 1.0)
              for h in b.hotels if h.price_per_night.amount > 0]
    return statistics.median(prices) if prices else 0.0


def plan_journey(contract: TripContract, profile: TravelerProfile, research: ResearchBundle, mode, knobs,
                 buffer_ratio: float, pinned_days: dict[int, list[str]], strategy=None) -> TripPlan:
    from .engine.budget import compute_budget
    from .agents.strategist import for_city
    from .engine.planner import PlanContext, build_plan

    stops = contract.stops
    legs = research.legs
    cur = contract.budget.currency.upper()
    fx = research.fx_rates

    def user(f: FlightOption) -> float:
        m = f.price_per_person
        return m.amount * (1.0 if m.currency.upper() == cur else fx.get(m.currency.upper(), 1.0))

    # Budget share of each stop: its days' share of the non-transport budget + the legs it touches.
    # Each stop plans nights + 1 days, so the travel days are counted twice across stops: the shares
    # sum to rest * (N + k) / (N + 1), which covers exactly that double count.
    leg_guess = [min((user(f) for f in leg), default=0.0) * contract.travelers for leg in legs]
    rest = max(contract.budget.amount - sum(leg_guess), contract.budget.amount * 0.3)
    base_median = _median_hotel(research.stops[0]) or 1.0

    subs: list[tuple[PlanContext, TripPlan]] = []
    first_day = 1
    inbound: FlightOption | None = None
    for i, stop in enumerate(stops):
        sb = research.stops[i].model_copy(update={
            "flights_outbound": [inbound] if inbound else (legs[i] if i < len(legs) else []),
            "flights_return": legs[i + 1] if i + 1 < len(legs) else [],
            # A round-trip ticket is origin <-> one city: never a candidate for the legs of a multi-city journey.
            "round_trips": []})
        share = rest * (stop.nights + 1) / (contract.nights + 1) + leg_guess[i] + leg_guess[i + 1]
        scale = (_median_hotel(sb) / base_median) if base_median else 1.0
        ctx = PlanContext(
            contract=stop_contract(contract, i, share), profile=profile, research=sb, mode=mode,
            knobs=_localize_knobs(knobs, first_day, stop.nights + 1, scale or 1.0), buffer_ratio=buffer_ratio,
            pinned_days={d - first_day + 1: ids for d, ids in pinned_days.items()
                         if first_day <= d <= first_day + stop.nights},
            strategy=for_city(strategy, stop.name) if strategy is not None else None,
        )
        p = build_plan(ctx)
        subs.append((ctx, p))
        inbound = p.return_flight
        first_day += stop.nights

    plan = TripPlan(mode=mode)
    plan.outbound_flight = subs[0][1].outbound_flight
    plan.return_flight = subs[-1][1].return_flight
    plan.hotel = subs[0][1].hotel
    plan.legs = [f for f in [subs[0][1].outbound_flight] + [p.return_flight for _, p in subs] if f is not None]
    plan.explanations = {"outbound_flight": subs[0][1].explanations.get("outbound_flight", []),
                         "return_flight": subs[-1][1].explanations.get("return_flight", []),
                         "hotel": subs[0][1].explanations.get("hotel", [])}
    plan.alternatives = {"hotels": [h for _, p in subs for h in p.alternatives.get("hotels", [])],
                         "outbound_flights": subs[0][1].alternatives.get("outbound_flights", []),
                         "return_flights": subs[-1][1].alternatives.get("return_flights", [])}
    for _, p in subs:
        for line in p.repair_log:
            if line not in plan.repair_log:
                plan.repair_log.append(line)

    first_day = 1
    for i, ((ctx, p), stop) in enumerate(zip(subs, stops)):
        plan.stops.append(StopPlan(
            index=i, name=stop.name, country=stop.ref.country, country_code=stop.ref.country_code,
            location=GeoPoint(lat=stop.ref.lat, lon=stop.ref.lon), start_date=stop.start_date,
            end_date=stop.end_date, nights=stop.nights, first_day=first_day, last_day=first_day + stop.nights,
            hotel=p.hotel, arrival=p.outbound_flight, explanations=p.explanations.get("hotel", []),
            check_in=p.hotel_check_in, check_out=p.hotel_check_out))  # the nights this city's journeys need
        for name, local_day in p.requested.items():  # requested places: stop day -> trip day
            if plan.requested.get(name) is None:
                plan.requested[name] = first_day + local_day - 1 if local_day else None
        for j, day in enumerate(p.days):
            d = day.model_copy(deep=True)
            d.day, d.city = first_day + j, stop.name
            if j == 0 and i > 0 and plan.days:
                _merge_travel_day(plan.days[-1], d, stops[i - 1].name, stop.name)
                continue
            plan.days.append(d)
        first_day += stop.nights

    plan.budget = compute_budget(plan, contract, fx, buffer_ratio)
    plan.within_budget = plan.budget.total <= contract.budget.amount
    return plan


def _merge_travel_day(morning, arrival, from_city: str, to_city: str) -> None:
    """Departure half (breakfast, sights, check-out, the journey) + arrival half in the new city."""
    items = list(arrival.items)
    if items and items[0].kind == "flight":
        items = items[1:]  # the same journey already closes the morning half
    morning.items += items
    morning.travel_day = True
    morning.city = to_city
    morning.title = f"{from_city} → {to_city}"
    morning.walking_km = round(morning.walking_km + arrival.walking_km, 2)
    morning.activity_count += arrival.activity_count
    morning.notes += [n for n in arrival.notes if n not in morning.notes]
    if arrival.weather and (morning.weather is None or arrival.weather.risk != "low"):
        if morning.weather and morning.weather.risk != "low":
            morning.notes.append(f"{from_city} weather: {morning.weather.condition}.")
        morning.weather = arrival.weather
