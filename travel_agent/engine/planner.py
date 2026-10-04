"""Plan builder: turns research + contract + profile into a complete TripPlan.

Pure function of its inputs (contract, profile, research, mode, knobs, pins).
The optimizer orders each day; this module selects flights and the hotel under
the budget, assigns activities to days, and assembles a realistic timeline
with meals, transport legs, rest and evening plans.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import timedelta
from zoneinfo import ZoneInfo

from ..models import (
    DayPlan,
    FlightOption,
    GeoPoint,
    HotelOption,
    ItineraryItem,
    Metadata,
    Money,
    Place,
    PlanningMode,
    ResearchBundle,
    TransferOption,
    TransportLeg,
    TravelerProfile,
    TripContract,
    TripPlan,
)
from ..providers import routing
from ..utils import haversine_km
from ..utils import is_open_for, open_windows, round_up, to_hhmm, to_min
from .budget import compute_budget, estimate_daily_user
from .knobs import PlanKnobs
from .optimizer import LUNCH_DURATION, Stop, optimize_day
from .ranking import (
    Ranked,
    dietary_ok,
    expand_interests,
    icon_ids,
    must_have_terms,
    score_attraction,
    score_flight,
    score_hotel,
    score_restaurant,
)

MEAL_DURATION = {"breakfast": 45, "lunch": LUNCH_DURATION, "coffee": 30, "dinner": 90, "dessert": 25}
# (max activities per day, max activity minutes, latest end of daytime activities)
STYLE_CAPACITY = {
    "relaxed": (2, 300, "18:00"),
    "moderate": (3, 390, "18:30"),
    "active": (4, 480, "19:00"),
    "very_active": (5, 560, "19:30"),
}

AIRPORT_BEFORE_DEPARTURE = 150  # minutes at the airport before an international departure
ARRIVAL_PROCESSING = 45         # immigration + baggage
STATION_BEFORE_DEPARTURE = 30   # trains / coaches between the cities of a multi-city trip
MAX_HOTEL_KM_FROM_SIGHTS = 10   # average distance to the top sights beyond which a hotel is a last resort
CHECK_IN_FROM = "14:00"


def before_departure(f: FlightOption) -> int:
    return AIRPORT_BEFORE_DEPARTURE if f.mode == "flight" else STATION_BEFORE_DEPARTURE


def arrival_processing(f: FlightOption) -> int:
    return ARRIVAL_PROCESSING if f.mode == "flight" else 10


def _hub(f: FlightOption | None) -> str:
    return "airport" if f is None or f.mode == "flight" else "station"


@dataclass
class PlanContext:
    contract: TripContract
    profile: TravelerProfile
    research: ResearchBundle
    mode: PlanningMode
    knobs: PlanKnobs
    buffer_ratio: float = 0.05
    pinned_days: dict[int, list[str]] = field(default_factory=dict)
    auto_picks: list[str] = field(default_factory=list)  # guaranteed from an interest (a beach day), not named by the user
    # What this mode means for this trip (agents.strategist.ModeStrategy), designed by the model. None = defaults.
    strategy: object | None = None

    @property
    def dest(self) -> str:
        return self.contract.destination

    @property
    def cur(self) -> str:
        return self.contract.budget.currency

    @property
    def local_cur(self) -> str:
        return self.research.destination_info.get("currency", "EUR")

    @property
    def walking(self) -> str:
        return self.knobs.walk_tolerance_override or self.profile.walking_tolerance

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.research.destination_info.get("timezone", "UTC"))

    def fx(self, currency: str) -> float:
        if currency.upper() == self.cur.upper():
            return 1.0
        return self.research.fx_rates.get(currency.upper(), 1.0)

    def leg(self, a: GeoPoint, b: GeoPoint, prefer_taxi: bool = False) -> TransportLeg:
        return routing.best_leg(a, b, self.walking, self.contract.travelers, self.research.fares, self.cur,
                                prefer_taxi=prefer_taxi or self.knobs.prefer_taxi)


def _style(ctx: PlanContext) -> str:
    return ctx.profile.travel_style or ctx.contract.travel_style


def capacity(ctx: PlanContext) -> tuple[int, int, int]:
    count, minutes, end = STYLE_CAPACITY[_style(ctx)]
    if ctx.mode == "experience":
        count, minutes = count + 1, minutes + 60
    elif ctx.mode == "comfort":
        minutes -= 30
    count = max(1, count + ctx.knobs.density_delta)
    minutes = max(120, minutes + 75 * ctx.knobs.density_delta)
    if ctx.knobs.extra_rest:
        minutes -= 60
    return count, minutes, to_min(end)


# ---------------------------------------------------------------------------
# Flights + hotel selection
# ---------------------------------------------------------------------------


def _rank_flights(pool: list[FlightOption], ctx: PlanContext, leaving: bool = False) -> list[Ranked]:
    fprefs = ctx.strategy.flights if ctx.strategy is not None else None
    picked = [f for f in pool if f.id in ctx.knobs.flight_pins]
    if picked:  # the traveller chose this flight: no filter overrides that
        return [score_flight(f, pool, ctx.profile, ctx.mode, fprefs) for f in picked]
    red_eye_ok = bool(fprefs and fprefs.allow_red_eye) and not ctx.profile.avoid_early_flights
    # Exclusions (repairs, "change my flight") must never leave a leg with no way to travel at all.
    pool = [f for f in pool if f.id not in ctx.knobs.flight_exclude] or pool
    flights = [f for f in pool if f.mode == "flight"]
    if flights:
        # A ground leg that costs most of a day (Cairo -> Luxor by train: ~9 h vs a 1 h flight) is not a
        # real saving: keep trains / coaches only when they are within ~4 h of the fastest flight.
        fastest = min(f.duration_minutes for f in flights)
        pool = [f for f in pool if f.mode == "flight" or f.duration_minutes <= fastest + 240]
    if red_eye_ok:
        pass  # this plan takes night / dawn flights when they're cheaper (the price weight decides)
    elif leaving:
        # A pre-07:00 departure means checking out in the middle of the night: only if nothing else exists.
        civil = [f for f in pool if f.depart_at.hour >= 7]
        pool = civil or pool
    elif pool and pool[0].direction == "outbound":
        # Landing after 23:00 (or after midnight) wastes day one; avoid when possible.
        same_day = [f for f in pool if f.arrive_at.astimezone(ctx.tz).date() == ctx.contract.start_date
                    and f.arrive_at.astimezone(ctx.tz).hour < 23]
        pool = same_day or pool
        if fprefs is not None:
            # This plan said no red-eyes: a 02:50 departure means a sleepless night before the trip.
            daytime = [f for f in pool if f.depart_at.hour >= 6]
            pool = daytime or pool
    if ctx.profile.avoid_early_flights:
        late = [f for f in pool if f.depart_at.hour >= 8]
        pool = late or pool
    if ctx.profile.flight_preference == "direct":
        direct = [f for f in pool if f.stops == 0]
        pool = direct or pool
    ranked = [score_flight(f, pool, ctx.profile, ctx.mode, fprefs) for f in pool]
    return sorted(ranked, key=lambda r: -r.score)


def _anchor_points(ctx: PlanContext) -> list[GeoPoint]:
    # In-city sights only: a day trip or an overnight idea (Milan from Rome) would drag the "centre" out of town.
    city_sights = [a for a in ctx.research.attractions if not a.day_trip and "overnight_trip" not in a.categories]
    ranked = sorted((score_attraction(a, ctx.profile, ctx.contract, ctx.mode) for a in city_sights),
                    key=lambda r: -r.score)
    return [r.item.location for r in ranked[:6]] or [GeoPoint(**ctx.research.destination_info["center"])]


def select_core(ctx: PlanContext) -> tuple[Ranked | None, Ranked | None, Ranked | None, list[str], dict[str, list[str]]]:
    """Joint flight + hotel choice under the budget. Returns (out, ret, hotel, notes, alternatives)."""
    notes: list[str] = []
    fprefs = ctx.strategy.flights if ctx.strategy is not None else None
    outs = _rank_flights(ctx.research.flights_outbound, ctx)
    rets = _rank_flights(ctx.research.flights_return, ctx, leaving=True)
    c = ctx.contract
    count, _, _ = capacity(ctx)
    daily_user = estimate_daily_user(ctx.research.restaurants, ctx.research.attractions, ctx.mode, c.travelers,
                                     count, ctx.research.fares.get("transit", 2.0), ctx.fx)
    budget = c.budget.amount

    def fare(f: FlightOption) -> float:
        return f.price_per_person.amount * ctx.fx(f.price_per_person.currency)

    # Nightly budget share used to judge hotel prices (in the user's currency).
    flight_guess = ((fare(outs[0].item) if outs else 0) + (fare(rets[0].item) if rets else 0)) * c.travelers
    nightly_user = max(budget - flight_guess - daily_user * c.num_days, budget * 0.15) / (c.nights * c.rooms)

    hotels = [h for h in ctx.research.hotels if h.id not in ctx.knobs.hotel_exclude]
    if ctx.profile.noise_tolerance == "low":
        hotels = [h for h in hotels if h.noise_level != "noisy"] or hotels
    if ctx.knobs.hotel_max_price_local is not None:
        hotels = [h for h in hotels if h.price_per_night.amount * ctx.fx(h.price_per_night.currency)
                  <= ctx.knobs.hotel_max_price_local] or hotels  # caps are in the budget currency
    anchors = _anchor_points(ctx)

    def avg_km(h: HotelOption) -> float:
        return sum(haversine_km(h.location.lat, h.location.lon, a.lat, a.lon) for a in anchors) / max(len(anchors), 1)

    # More than ~10 km from the sights means hours of commuting a day: only if nothing closer exists.
    hotels = [h for h in hotels if avg_km(h) <= MAX_HOTEL_KM_FROM_SIGHTS] or hotels
    hprefs = ctx.strategy.hotel if ctx.strategy is not None else None
    if hprefs is not None:
        # The plan's quality bar (e.g. comfort: 4.4+ rating, 4+ stars), kept only if enough hotels clear it.
        good = [h for h in hotels if (h.rating or 0) >= hprefs.min_rating and (not hprefs.min_stars or h.stars >= hprefs.min_stars)]
        if len(good) < 3:
            good = [h for h in hotels if (h.rating or 0) >= hprefs.min_rating]
        hotels = good if len(good) >= 3 else hotels
    hranked = sorted((score_hotel(h, anchors, ctx.profile, ctx.mode, nightly_user / max(ctx.fx(h.price_per_night.currency), 1e-9),
                                  hprefs) for h in hotels), key=lambda r: -r.score)
    if not (outs and rets and hranked):
        notes.append("Missing flight or hotel candidates - the plan is partial.")
        return (outs[0] if outs else None, rets[0] if rets else None, hranked[0] if hranked else None, notes, {})

    weights = {"balanced": (1.0, 1.4, 1.0), "budget": (0.6, 0.8, 2.2), "comfort": (1.0, 2.0, 0.3), "experience": (0.8, 1.2, 0.8)}[ctx.mode]
    if ctx.strategy is not None:
        # How much the total price weighs against flight and hotel quality, as the strategist set it for this plan.
        pw = (ctx.strategy.flights.price_weight + ctx.strategy.hotel.price_weight) / 2
        weights = (weights[0], weights[1], 0.2 + 2.2 * pw)
    # How much an extra hour on the ground is worth: a short trip lives or dies by its arrival and departure times.
    hour_weight = {"balanced": 0.5, "budget": 0.25, "comfort": 0.5, "experience": 0.8}[ctx.mode] / max(c.num_days, 1)
    best, best_obj, cheapest, cheapest_total = None, -math.inf, None, math.inf
    pressure_share = 1.0 - 0.06 * ctx.knobs.price_pressure
    # Best-scored hotels plus the cheapest ones, so a tight budget can always reach them.
    by_price = sorted(hranked, key=lambda x: x.item.price_per_night.amount * ctx.fx(x.item.price_per_night.currency))
    hotel_pool = list({id(x): x for x in hranked[:7] + by_price[:3]}.values())
    if hprefs is not None and hprefs.shortlist and getattr(ctx.strategy, "budget_stretch", 0) > 0:
        # An upgrade stays in the hotels the strategist picked by name for it (checked to exist and be near the
        # sights) - a "hostel" listed as 4-star never becomes the comfort hotel.
        names = {n.strip().lower() for n in hprefs.shortlist}
        picked = [x for x in hranked if x.item.name.strip().lower() in names]
        hotel_pool = picked or hotel_pool
    # Same for flights: the best-scored ones plus the cheapest, so "cheapest" really is the cheapest fare found.
    out_pool = list({x.item.id: x for x in outs[:4] + sorted(outs, key=lambda x: fare(x.item))[:3]}.values())
    ret_pool = list({x.item.id: x for x in rets[:4] + sorted(rets, key=lambda x: fare(x.item))[:3]}.values())

    def ground_hours(o: FlightOption, r: FlightOption) -> float:
        """Usable hours in the destination: from landing (+ arrival formalities) to leaving for the airport."""
        start = o.arrive_at + timedelta(minutes=arrival_processing(o))
        end = r.depart_at - timedelta(minutes=before_departure(r))
        return max(0.0, (end - start).total_seconds() / 3600)

    # Flights the traveller picked ("take the direct one") are the only candidates for their direction.
    pins = set(ctx.knobs.flight_pins)
    out_pool = [x for x in outs if x.item.id in pins] or out_pool
    ret_pool = [x for x in rets if x.item.id in pins] or ret_pool
    pinned_rt = [rt for rt in ctx.research.round_trips if {rt.outbound.id, rt.inbound.id} <= pins]

    # Round-trip tickets: both legs together or not at all (each leg carries half the ticket price).
    pairs = [] if pinned_rt else [(o, r) for o in out_pool for r in ret_pool]
    for rt in pinned_rt or ctx.research.round_trips:
        if rt.outbound.id in ctx.knobs.flight_exclude or rt.inbound.id in ctx.knobs.flight_exclude:
            continue
        if pins and not pinned_rt and (pins & {x.item.id for x in outs + rets}):
            continue  # one-way flights were picked: no round-trip ticket replaces them
        o = score_flight(rt.outbound, [x.item for x in outs] + [rt.outbound], ctx.profile, ctx.mode, fprefs)
        r = score_flight(rt.inbound, [x.item for x in rets] + [rt.inbound], ctx.profile, ctx.mode, fprefs)
        o.reasons.append("Round-trip ticket: cheaper than two one-way fares")
        pairs.append((o, r))

    combos = []
    for o, r in pairs:
        hours = ground_hours(o.item, r.item)
        for h in hotel_pool:
            total = ((fare(o.item) + fare(r.item)) * c.travelers
                     + h.item.price_per_night.amount * c.nights * c.rooms * ctx.fx(h.item.price_per_night.currency)
                     + daily_user * c.num_days) * (1 + ctx.buffer_ratio)
            obj = (weights[0] * (o.score + r.score) + weights[1] * h.score - weights[2] * total / max(budget, 1)
                   + hour_weight * hours / 24 * 4)
            combos.append((total, obj, (o, r, h)))
            if total < cheapest_total:
                cheapest, cheapest_total = (o, r, h), total
            # `total` already carries the safety buffer: a combination that fits it fits the budget.
            if total <= budget * pressure_share and obj > best_obj:
                best, best_obj = (o, r, h), obj
    if ctx.mode == "budget" and combos:
        # The budget plan is the cheapest flights + hotel, full stop; quality only breaks near-ties (within 3%).
        near = [x for x in combos if x[0] <= cheapest_total * 1.03]
        best = max(near, key=lambda x: x[1])[2]
        if cheapest_total > budget * pressure_share:
            notes.append("No flight + hotel combination fits the budget comfortably; picked the cheapest combination.")
    elif best is None and ctx.strategy is not None and getattr(ctx.strategy, "budget_stretch", 0) > 0:
        # An upgrade (comfort / experience) keeps its promise when the budget is tight - the price still weighs in
        # the objective, and the card shows honestly how much more it costs. A copy of the budget plan helps no one.
        # Its promise at the lowest extra cost: the cheapest of its own candidates, quality breaking near-ties (10%).
        near = [x for x in combos if x[0] <= cheapest_total * 1.10]
        best = max(near, key=lambda x: x[1])[2]
        notes.append("Upgrade plan: costs more than your budget to deliver what this plan promises.")
    elif best is None:
        # Nothing fits: stay close to the cheapest, but don't throw away a much better trip for a few percent
        # (a direct flight that lands at 07:10 instead of 11:30 for +3% is the smarter "cheapest").
        slack = cheapest_total + max(0.02 * cheapest_total, 0.01 * budget) if ctx.knobs.price_pressure < 2 else cheapest_total
        best = max((x for x in combos if x[0] <= slack), key=lambda x: x[1])[2]
        notes.append("No flight + hotel combination fits the budget comfortably; picked the cheapest combination.")
    o, r, h = best
    alternatives = {
        "hotels": [x.item.id for x in hranked if x.item.id != h.item.id][:3],
        "outbound_flights": [x.item.id for x in outs if x.item.id != o.item.id][:3],
        "return_flights": [x.item.id for x in rets if x.item.id != r.item.id][:3],
    }
    return o, r, h, notes, alternatives


def choose_transfer(ctx: PlanContext, airport: str | None = None) -> TransferOption | None:
    options = [o for o in ctx.research.airport_transfers if airport is None or o.airport in (None, airport)]
    options = options or ctx.research.airport_transfers
    if not options:
        return None
    t = ctx.contract.travelers

    def group_cost(o: TransferOption) -> float:
        if o.cost_per_vehicle:
            return o.cost_per_vehicle.amount * max(1, math.ceil(t / 4))
        return (o.cost_per_person.amount if o.cost_per_person else 0) * t

    if ctx.knobs.transfer_mode:
        wanted = {"bus": ("bus", "transit", "train"), "train": ("train", "transit")}.get(ctx.knobs.transfer_mode,
                                                                                            (ctx.knobs.transfer_mode,))
        forced = [o for o in options if o.mode in wanted]
        if forced:
            return min(forced, key=group_cost)
    taxis = [o for o in options if o.mode == "taxi"]
    if ctx.mode == "comfort" and taxis and ctx.knobs.price_pressure == 0:
        return taxis[0]
    if ctx.mode == "budget" or ctx.knobs.price_pressure >= 2:
        return min(options, key=group_cost)
    if ctx.walking == "low" or t >= 3:
        # Door-to-door is worth it when luggage + walking is a problem, if not much pricier.
        cheapest = min(options, key=group_cost)
        if taxis and group_cost(taxis[0]) <= group_cost(cheapest) * 2.2:
            return taxis[0]
        return cheapest
    public = [o for o in options if o.mode in ("train", "transit", "bus")]
    return min(public, key=group_cost) if public else min(options, key=group_cost)


def station_transfer(ctx: PlanContext, hotel: HotelOption | None, arriving: bool) -> TransferOption | None:
    """Main station <-> hotel on a train / coach day (station assumed near the city centre)."""
    if hotel is None:
        return None
    center = GeoPoint(**ctx.research.destination_info["center"])
    leg = ctx.leg(center, hotel.location) if arriving else ctx.leg(hotel.location, center)
    how = {"walk": "on foot", "transit": "by public transport", "taxi": "by taxi"}.get(leg.mode, leg.mode)
    return TransferOption(
        id="station_in" if arriving else "station_out", mode="taxi" if leg.mode == "taxi" else "transit",
        name=("Station -> hotel " if arriving else "Hotel -> station ") + how, minutes=leg.minutes + 10,
        cost_per_person=Money(amount=round(leg.cost.amount / max(ctx.contract.travelers, 1), 2), currency=leg.cost.currency,
                              price_type=leg.cost.price_type, source=leg.cost.source),
        notes="Main station assumed near the city centre; confirm which station your train or coach uses.",
        metadata=Metadata(source="planner", provider="openrouteservice / distance estimate", confidence=0.6))


def _towards_airport(name: str) -> str:
    """Transfer options are researched airport -> city; on departure day show them the other way round."""
    if " -> " not in name:
        return name
    head, tail = name.split(" -> ", 1)
    how, _, airport = head.rpartition(" ")
    place, sep, via = tail.partition(" via ")
    return f"{how} {place} -> {airport}".strip() + (f" via {via}" if sep else "")


def transfer_cost(o: TransferOption, travelers: int) -> Money:
    """The group cost, keeping how sure the fare is (published / tariff / estimate) and its source."""
    if o.cost_per_vehicle:
        m, n = o.cost_per_vehicle, max(1, math.ceil(travelers / 4))
    else:
        assert o.cost_per_person is not None
        m, n = o.cost_per_person, travelers
    return Money(amount=m.amount * n, currency=m.currency, price_type=m.price_type, source=m.source)


# ---------------------------------------------------------------------------
# Day skeleton + activity assignment
# ---------------------------------------------------------------------------


@dataclass
class DaySlot:
    index: int
    date: object
    kind: str                # arrival | full | departure
    start: int               # earliest activity start (minutes)
    end: int                 # latest activity end
    max_count: int
    max_minutes: int
    high_rain: bool
    activities: list[Ranked] = field(default_factory=list)
    evening: Ranked | None = None


def build_slots(ctx: PlanContext, out: FlightOption | None, ret: FlightOption | None,
                t_in: TransferOption | None, t_out: TransferOption | None) -> list[DaySlot]:
    c = ctx.contract
    count, minutes, act_end = capacity(ctx)
    wake = to_min(ctx.profile.preferred_wake_up_time)
    weather = {w.date: w for w in ctx.research.weather}
    tmin_in = t_in.minutes if t_in else 60
    tmin_out = t_out.minutes if t_out else 60
    slots = []
    for i in range(c.num_days):
        d = c.start_date + timedelta(days=i)
        w = weather.get(d)
        high_rain = bool(w and w.risk == "high") or (i + 1) in ctx.knobs.avoid_outdoor_days
        kind = "arrival" if i == 0 else ("departure" if i == c.num_days - 1 else "full")
        start, end, cnt, mins = wake + 60, act_end, count, minutes
        # Arrival / departure days: every free hour counts. A slot is ~100 min of visit + travel (short stops such
        # as a fountain weigh half), so an afternoon in Rome holds the Colosseum and two or three nearby sights.
        if kind == "arrival" and out is not None:
            arr = out.arrive_at.astimezone(ctx.tz)
            at_hotel = arr.hour * 60 + arr.minute + arrival_processing(out) + tmin_in + 30
            if arr.date() > d:
                at_hotel = end  # lands after midnight: day one has no free time (nothing assigned, nothing lost)
            start = max(start, at_hotel)
            avail = end - start
            cnt = min(count, max(0, avail // 100))
            mins = min(minutes, max(0, avail - 20))
        if kind == "departure" and ret is not None:
            start = wake + 45  # right after breakfast: the morning is all there is
            dep = ret.depart_at.astimezone(ctx.tz)
            leave_hotel = dep.hour * 60 + dep.minute - before_departure(ret) - tmin_out - 20
            end = min(end, leave_hotel - 30)
            avail = end - start
            cnt = min(count, max(0, avail // 100))
            mins = min(minutes, max(0, avail - 20))
        override = ctx.knobs.day_capacity_override.get(i + 1)
        if override is not None:
            if override > cnt:  # "pack more into day 2"
                mins = min(max(0, end - start), mins + 90 * (override - cnt))
            cnt = override
        slots.append(DaySlot(i, d, kind, start, end, max(0, cnt), max(0, mins), high_rain))
    return slots


def activity_weight(minutes: int) -> float:
    """Short stops (a fountain, a square) cost half a 'slot' of the day's energy budget."""
    return 0.5 if minutes <= 45 else 1.0


def day_load(durations: list[int]) -> float:
    return sum(activity_weight(m) for m in durations)


def _is_evening(a: Place) -> bool:
    windows = [w for day in a.opening_hours.values() for w in day]
    return bool(windows) and min(to_min(w[0]) for w in windows) >= 17 * 60


def _fits_day(a: Place, slot: DaySlot) -> bool:
    if a.dates and slot.date not in a.dates:
        return False  # one-off event on another day
    return any(max(o, slot.start) + a.duration_minutes <= min(c, slot.end) for o, c in open_windows(a.opening_hours, slot.date))


def _fill(pool: list[Ranked], slots: list[DaySlot], used: set[str], allowed, take, hotel: HotelOption | None,
          allow_wet: bool) -> None:
    for r in pool:
        a = r.item
        if a.id in used or _is_evening(a) or r.score < 0.12:
            continue
        best, best_cost = None, math.inf
        for slot in slots:
            wet = slot.high_rain and not a.indoor
            if (wet and not allow_wet) or not allowed(slot, r):
                continue
            pts = [x.item.location for x in slot.activities] or ([hotel.location] if hotel else [])
            spread = sum(haversine_km(a.location.lat, a.location.lon, p.lat, p.lon) for p in pts) / max(len(pts), 1)
            cost = 0.15 * spread + 0.25 * len(slot.activities) / max(slot.max_count, 1)
            if wet:
                cost += 1.5
            if slot.kind != "full":
                cost += 0.1
            if cost < best_cost:
                best, best_cost = slot, cost
        if best is not None:
            take(best, r)


def assign_activities(ctx: PlanContext, slots: list[DaySlot], hotel: HotelOption | None) -> tuple[list[Ranked], dict[str, int]]:
    """Greedy geographic assignment of ranked activities to days. Returns (unused pool, category counts)."""
    excluded = set(ctx.knobs.exclude_ids)
    avoid = {c.lower() for c in ctx.profile.avoid_categories}
    boosts = dict(ctx.knobs.category_boost)
    if ctx.knobs.food_focus:
        boosts["food"] = boosts.get("food", 0) + 0.3
    pool: list[Ranked] = []
    must_terms = must_have_terms(ctx.contract)
    signature = set(ctx.knobs.signature_picks)
    must_ids = set(ctx.knobs.must_include) | signature
    icons = icon_ids(ctx.research.attractions)
    act_prefs = ctx.strategy.activities if ctx.strategy is not None else None
    for a in ctx.research.attractions:
        forced = a.id in must_ids  # named by the traveller (or a signature experience): no category / price filters
        if a.id in excluded or (set(a.categories) & avoid and not forced):
            continue
        over_cap = ctx.knobs.activity_cost_cap_local is not None and \
            a.cost_per_person.amount * ctx.fx(a.cost_per_person.currency) > ctx.knobs.activity_cost_cap_local
        # Must-have experiences and the city's icons (nobody goes to Rome to skip the Colosseum) survive the price cap.
        if over_cap and not forced and not (must_terms & expand_interests(a.categories)) and a.id not in icons:
            continue
        if "overnight_trip" in a.categories:
            continue  # suggested in the reply / Trip Book, never squeezed into a day
        ranked = score_attraction(a, ctx.profile, ctx.contract, ctx.mode, boosts)
        if a.day_trip:
            # Worth the journey only if it is famous; the further, the more it must earn its day.
            if a.popularity != "must_see":
                ranked.score -= 0.1 * a.distance_km / 60
            ranked.reasons.append(f"Day trip ~{a.distance_km:.0f} km from the city")
        if act_prefs is not None and not act_prefs.paid_ok and a.cost_per_person.amount > 0 and a.id not in icons \
                and not forced:
            ranked.score -= 0.2  # this plan favours free sights; the city's icons are worth their ticket
            ranked.tradeoffs.append("Paid entry (this plan favours free sights)")
        if a.id in signature:
            ranked.score += 0.9
            city = ctx.research.destination_info.get("name", ctx.dest)
            ranked.reasons.insert(0, f"Signature experience of {city}")
        elif forced and a.id in ctx.knobs.expert_picks:
            ranked.score += 0.1  # the critic's idea: welcome if it fits, never at the cost of a better stop
            ranked.reasons.insert(0, "You asked to visit this place")  # relabelled as an expert pick after planning
        elif forced:
            ranked.score += 1.0  # the day optimizer drops low-value stops first; never this one
            ranked.reasons.insert(0, "Because you love the sea" if a.id in ctx.auto_picks else "You asked to visit this place")
        pool.append(ranked)
    pool.sort(key=lambda r: -r.score)
    by_id = {r.item.id: r for r in pool}
    cat_counts: dict[str, int] = {}
    used: set[str] = set()

    # Balance: a sea lover gets beach time, not a whole trip of beaches - at most about half the full days.
    limits = dict(ctx.knobs.category_limits)
    full_days = sum(1 for s in slots if s.kind == "full")
    limits.setdefault("beach", max(1, math.ceil(full_days / 2)))

    def limit_ok(a: Place) -> bool:
        return all(cat_counts.get(cat, 0) < lim for cat, lim in limits.items() if cat in a.categories)

    def take(slot: DaySlot, r: Ranked) -> None:
        slot.activities.append(r)
        used.add(r.item.id)
        for cat in r.item.categories:
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

    base_point = hotel.location if hotel else GeoPoint(**ctx.research.destination_info["center"])

    def trip_overhead(a: Place) -> int:
        """Round-trip travel minutes to a day-trip site (real ORS drive time when available)."""
        return 2 * ctx.leg(base_point, a.location).minutes if a.day_trip else 0

    def minutes_used(slot: DaySlot) -> int:
        anchors = [x.item for x in slot.activities if x.item.day_trip]
        return sum(x.item.duration_minutes + 20 for x in slot.activities) + (trip_overhead(anchors[0]) if anchors else 0)

    def day_trip_ok(slot: DaySlot, a: Place) -> bool:
        """A day-trip site owns its day: only places near it may share that day."""
        anchor = next((x.item for x in slot.activities if x.item.day_trip), None)
        near = lambda p, q: haversine_km(p.location.lat, p.location.lon, q.location.lat, q.location.lon) <= 20  # noqa: E731
        if a.day_trip:
            if slot.kind != "full":
                return False
            if anchor is not None:
                return near(a, anchor)
            if any(not near(a, x.item) for x in slot.activities):
                return False
            one_way = ctx.leg(base_point, a.location).minutes
            # A short stay only affords short day trips - unless the traveller asked for this place.
            limit = 180 if ctx.contract.num_days >= 4 or a.id in must_ids else 90
            return one_way <= limit and minutes_used(slot) + a.duration_minutes + 2 * one_way <= slot.max_minutes + 120
        return anchor is None or near(a, anchor)

    def allowed(slot: DaySlot, r: Ranked) -> bool:
        a = r.item
        if "beach" in a.categories and any("beach" in x.item.categories for x in slot.activities):
            return False  # one beach a day is a beach day; two is a lost day
        return (a.id not in used and a.id not in ctx.knobs.exclude_on_day.get(slot.index + 1, []) and day_trip_ok(slot, a)
                and day_load([x.item.duration_minutes for x in slot.activities]) + activity_weight(a.duration_minutes) <= slot.max_count
                and (minutes_used(slot) + a.duration_minutes <= slot.max_minutes or (a.day_trip and not slot.activities))
                and _fits_day(a, slot) and limit_ok(a) and not (slot.high_rain and not a.indoor and (slot.index + 1) in ctx.knobs.avoid_outdoor_days))

    # 1) Keep pinned assignments stable across replans.
    for slot in slots:
        for pid in ctx.pinned_days.get(slot.index + 1, []):
            r = by_id.get(pid)
            if r and not _is_evening(r.item) and allowed(slot, r):
                take(slot, r)

    # 1b) Places the traveller asked for by name: always in the plan. Pick the best day that has room;
    #     if none has, free a day by dropping its weakest (not requested) activities.
    def spread_cost(slot: DaySlot, a: Place) -> float:
        pts = [x.item.location for x in slot.activities] or ([hotel.location] if hotel else [])
        km = sum(haversine_km(a.location.lat, a.location.lon, p.lat, p.lon) for p in pts) / max(len(pts), 1)
        return 0.15 * km + 0.25 * len(slot.activities) / max(slot.max_count, 1) + (0.5 if slot.kind != "full" else 0) \
            + (1.5 if slot.high_rain and not a.indoor else 0)

    for pid in list(dict.fromkeys(ctx.knobs.must_include + ctx.knobs.signature_picks)):
        r = by_id.get(pid)
        if r is None or pid in used:
            continue
        a = r.item
        if _is_evening(a):
            night = next((s for s in slots if s.kind == "full" and s.evening is None and open_windows(a.opening_hours, s.date)
                          and (not a.dates or s.date in a.dates)), None)
            if night:
                night.evening = r
                used.add(pid)
            continue
        options = [s for s in slots if allowed(s, r)]
        if not options and pid not in ctx.knobs.expert_picks:  # only the traveller's own requests clear room
            for slot in sorted(slots, key=lambda s: (s.kind != "full", spread_cost(s, a))):
                if not _fits_day(a, slot) or (a.day_trip and slot.kind != "full"):
                    continue
                removed = []
                while not allowed(slot, r):
                    weakest = min((x for x in slot.activities if x.item.id not in must_ids), key=lambda x: x.score, default=None)
                    if weakest is None:
                        break
                    slot.activities.remove(weakest)
                    used.discard(weakest.item.id)
                    removed.append(weakest)
                if allowed(slot, r):
                    options = [slot]
                    break
                for x in removed:  # could not make room here: put them back
                    slot.activities.append(x)
                    used.add(x.item.id)
        if options:
            take(min(options, key=lambda s: spread_cost(s, a)), r)

    # 2) Fill remaining capacity: best activity first, placed on the most cohesive day.
    #    Pass one never puts outdoor plans on rainy days; pass two may, but only
    #    for capacity still left after every weather-safe option was used.
    # Days the traveller already has (pinned) keep exactly their stops: only the other days are filled / rebalanced.
    open_slots = [s for s in slots if (s.index + 1) not in ctx.pinned_days]
    for allow_wet in (False, True):
        _fill(pool, open_slots, used, allowed, take, hotel, allow_wet)

    # 3) Redistribute: no full day should stay empty while another day has 2+ activities.
    full_days = [s for s in open_slots if s.kind == "full"]
    for _ in range(len(full_days)):
        empties = [s for s in full_days if not s.activities]
        donors = sorted((s for s in open_slots if len(s.activities) >= 2), key=lambda s: -len(s.activities))
        moved = False
        for empty in empties:
            for donor in donors:
                if len(donor.activities) < 2:
                    continue
                # The weakest stop that the empty day really accepts - the same rules as any placement, so a
                # repair (a stop excluded that day, a day capped at zero, no outdoor plans in the rain) is never undone.
                for r in sorted(donor.activities, key=lambda x: x.score):
                    if r.item.id in must_ids or not _fits_day(r.item, empty):
                        continue
                    donor.activities.remove(r)
                    used.discard(r.item.id)
                    ok = allowed(empty, r) and not (empty.high_rain and not r.item.indoor)
                    used.add(r.item.id)
                    if ok:
                        empty.activities.append(r)
                        moved = True
                        break
                    donor.activities.append(r)
                if moved:
                    break
        if not moved:
            break

    # 4) Evening plans (nightlife / shows) for travellers who want them.
    interest = ctx.profile.nightlife_interest
    if ctx.mode == "experience" and interest == "low":
        interest = "medium"
    if interest != "low":
        evenings = [r for r in pool if _is_evening(r.item) and r.item.id not in used and limit_ok(r.item)]
        step = 1 if interest == "high" else 2
        for slot in [s for s in slots if s.kind == "full" and s.evening is None][::step]:  # never replace a requested one
            for r in evenings:
                if r.item.id not in used and open_windows(r.item.opening_hours, slot.date) and (not r.item.dates or slot.date in r.item.dates):
                    slot.evening = r
                    used.add(r.item.id)
                    break
    unused = [r for r in pool if r.item.id not in used]
    return unused, cat_counts


# ---------------------------------------------------------------------------
# Timeline assembly
# ---------------------------------------------------------------------------


class DayBuilder:
    def __init__(self, ctx: PlanContext, slot: DaySlot, hotel: HotelOption | None, used_restaurants: dict[str, int],
                 restaurant_rank: dict[str, Ranked], spare: list[Ranked] | None = None, taken: set[str] | None = None,
                 later: list[DaySlot] | None = None):
        self.ctx = ctx
        self.slot = slot
        self.hotel = hotel
        self.spare = spare or []          # ranked sights no day was given (best first)
        self.taken = taken if taken is not None else set()  # place ids already somewhere in the trip
        self.later = later or []          # days not built yet: idle hours today may borrow their sights
        self.hard_end: int | None = None  # departure day: the latest any stop may end (bags, then the airport)
        self.items: list[ItineraryItem] = []
        self.here: GeoPoint = hotel.location if hotel else GeoPoint(**ctx.research.destination_info["center"])
        self.t = 0
        self.used_restaurants = used_restaurants
        self.restaurant_rank = restaurant_rank
        self.lunch_done = False
        self.walk_km = 0.0
        self.dropped: list[str] = []
        self.combo_paid: set[str] = set()

    # -- helpers -------------------------------------------------------------
    def leg_to(self, loc: GeoPoint) -> TransportLeg | None:
        if haversine_km(self.here.lat, self.here.lon, loc.lat, loc.lon) < 0.05:
            return None
        # The plan's transport choice (taxi for a comfort strategy) comes from its knobs - the same legs the stop order
        # was optimised on, so the schedule matches the route.
        return self.ctx.leg(self.here, loc)

    def add(self, item: ItineraryItem, leg: TransportLeg | None, loc: GeoPoint | None) -> None:
        item.transport_from_previous = leg
        if leg and leg.mode == "walk":
            self.walk_km += leg.distance_km
        self.items.append(item)
        if loc is not None:
            self.here = loc
        self.t = to_min(item.end)

    def pick_restaurant(self, meal: str, earliest: int) -> tuple[Place, int, TransportLeg | None, list[Place]] | None:
        # A price cap must never make a meal disappear: relax it step by step if nothing qualifies.
        base = self.ctx.knobs.max_price_level if meal in ("lunch", "dinner") else 2
        for level in range(base, 5):
            found = self._pick_restaurant(meal, earliest, level)
            if found:
                return found
        return None

    def _pick_restaurant(self, meal: str, earliest: int, max_level: int) -> tuple[Place, int, TransportLeg | None, list[Place]] | None:
        ctx = self.ctx
        dur = MEAL_DURATION[meal]
        today = {i.place_id for i in self.items if i.kind == "meal"}
        cands = []
        for r in ctx.research.restaurants:
            if meal not in r.meal_types or r.price_level > max_level or r.id in ctx.knobs.exclude_ids:
                continue
            if r.id in today and meal not in ("coffee", "dessert"):
                continue
            if not dietary_ok(r, ctx.profile):
                continue
            leg = self.leg_to(r.location)
            start = round_up(max(earliest, self.t + (leg.minutes if leg else 0)))
            if not is_open_for(r.opening_hours, self.slot.date, start, start + dur):
                # Try the next opening window the same day (e.g. dinner service at 19:00).
                later = [o for o, c in open_windows(r.opening_hours, self.slot.date) if o >= start and o + dur <= c]
                if not later or later[0] - start > 60:
                    continue
                start = later[0]
            ranked = self.restaurant_rank[r.id]
            km = haversine_km(self.here.lat, self.here.lon, r.location.lat, r.location.lon)
            dist_pen = {"low": 0.2, "medium": 0.12, "high": 0.07}[ctx.walking] * km
            if meal == "breakfast":
                dist_pen *= 2  # breakfast should be around the corner
            reuse_pen = 0.45 * self.used_restaurants.get(r.id, 0)
            # A restaurant the traveller asked for wins its meal (on its day, if they named one), once.
            wanted = ctx.knobs.meal_requests.get(r.id)
            ask_bonus = 3.0 if (wanted is not None and wanted in (0, self.slot.index + 1)
                                and not self.used_restaurants.get(r.id) and meal in ("lunch", "dinner")) else 0.0
            cands.append((ranked.score + ask_bonus - dist_pen - reuse_pen - 0.002 * (start - earliest), r, start, leg))
        if not cands:
            return None
        cands.sort(key=lambda x: -x[0])
        _, r, start, leg = cands[0]
        return r, start, leg, [c[1] for c in cands[1:3]]

    def away_from_city(self) -> bool:
        c = self.ctx.research.destination_info["center"]
        return haversine_km(self.here.lat, self.here.lon, c["lat"], c["lon"]) > 25

    def local_meal(self, meal: str, earliest: int) -> bool:
        """On a day trip the researched restaurants are back in the city: eat near the site instead."""
        prices = sorted(p.cost_per_person.amount * self.ctx.fx(p.cost_per_person.currency)
                        for p in self.ctx.research.restaurants if meal in p.meal_types)
        per_person = prices[len(prices) // 2] if prices else 15.0
        start = round_up(max(earliest, self.t))
        site = next((i.title for i in reversed(self.items) if i.kind == "activity"), "the site")
        self.add(ItineraryItem(
            start=to_hhmm(start), end=to_hhmm(start + MEAL_DURATION[meal]), kind="meal", meal_type=meal,  # type: ignore[arg-type]
            title=f"{meal.capitalize()} near {site}", location=self.here,
            cost=Money(amount=round(per_person * self.ctx.contract.travelers, 2), currency=self.ctx.cur, price_type="estimated"),
            notes="Day trip: pick a local place near the site (not researched); price estimated from city restaurants.",
            explanation=["Saves the journey back to the city for lunch"]), None, None)
        return True

    def meal(self, meal: str, earliest: int, title_prefix: str | None = None) -> bool:
        if meal in ("lunch", "coffee", "dessert") and self.away_from_city():
            return self.local_meal(meal, earliest)
        pick = self.pick_restaurant(meal, earliest)
        if pick is None:
            return False
        r, start, leg, alts = pick
        if self.hard_end is not None and start + MEAL_DURATION[meal] > self.hard_end:
            return False  # no time left before the airport run
        tr = self.ctx.contract.travelers
        ranked = self.restaurant_rank[r.id]
        why = list(ranked.reasons)
        if leg:
            why.append(f"{leg.minutes} min {leg.mode} from your previous stop")
        else:
            why.append("Right where you are")
        self.used_restaurants[r.id] = self.used_restaurants.get(r.id, 0) + 1
        self.add(ItineraryItem(
            start=to_hhmm(start), end=to_hhmm(start + MEAL_DURATION[meal]), kind="meal", meal_type=meal,  # type: ignore[arg-type]
            title=f"{title_prefix or meal.capitalize()} - {r.name}", place_id=r.id, location=r.location,
            cost=Money(amount=r.cost_per_person.amount * tr, currency=r.cost_per_person.currency,
                       price_type=r.cost_per_person.price_type, source=r.cost_per_person.source),
            indoor=r.indoor, notes=r.description + (" Reservation recommended." if r.requires_reservation else ""),
            alternatives=[a.name for a in alts], explanation=why, link=r.menu_url,
        ), leg, r.location)
        return True

    def activity(self, r: Ranked, start_hint: int | None = None, deadline: int | None = None) -> bool:
        a: Place = r.item
        leg = self.leg_to(a.location)
        arrive = self.t + (leg.minutes if leg else 0)
        start = None
        for o, c in open_windows(a.opening_hours, self.slot.date):
            s = round_up(max(arrive, o, start_hint or 0))
            if s + a.duration_minutes <= c:
                start = s
                break
        if start is None or (deadline is not None and start + a.duration_minutes > deadline):
            self.dropped.append(a.id)
            return False
        tr = self.ctx.contract.travelers
        cost = a.cost_per_person.amount * tr
        notes = a.description
        if a.id in self.combo_paid or (a.combo_with and a.combo_with in self.combo_paid):
            cost = 0.0
            notes += " Covered by the combo ticket already counted today."
        else:
            self.combo_paid.add(a.id)
            if a.combo_with:
                self.combo_paid.add(a.combo_with)
        why = list(r.reasons)
        if leg:
            why.append(f"{leg.minutes} min {leg.mode} from the previous stop")
        w = self.slot_weather()
        if w and w.risk == "high" and a.indoor:
            why.append(f"Indoor pick for a rainy day ({w.condition})")
        if a.notes:
            notes += f" {a.notes}"
        if not a.hours_verified:
            notes += " Opening hours are not published online - typical hours assumed; check before going."
        if a.dates:
            notes += f" Happens only on {a.dates[0]:%a %d %b}."
        if a.requires_reservation:
            notes += " Book a timed ticket in advance."
        self.add(ItineraryItem(
            start=to_hhmm(start), end=to_hhmm(start + a.duration_minutes), kind="activity", title=a.name,
            place_id=a.id, location=a.location,
            cost=Money(amount=cost, currency=a.cost_per_person.currency, price_type=a.cost_per_person.price_type,
                       source=a.cost_per_person.source),
            indoor=a.indoor, notes=notes.strip(), explanation=why + [f"Trade-off: {t}" for t in r.tradeoffs],
        ), leg, a.location)
        return True

    def fill_gap(self, until: int, back_to: GeoPoint | None = None) -> int:
        """Use idle time for nearby sights instead of leaving 'free time' while famous places sit unvisited.

        Picks, one at a time, the best unplanned sight within ~3 km that is open, fits before `until` (including the
        way back to `back_to`) and keeps the day within the traveller's pace. Returns how many were added."""
        ctx = self.ctx
        style = _style(ctx)
        if style == "relaxed" or ctx.knobs.extra_rest or not (self.spare or self.later):
            return 0
        if (self.slot.index + 1) in ctx.pinned_days:
            return 0  # a day the traveller already has stays exactly as it was (stable replans)
        # Same ceiling the energy check uses: the style's capacity (+1 for active travellers, + "pack more" requests).
        base = STYLE_CAPACITY[ctx.profile.travel_style][0]
        cap = min(capacity(ctx)[0] + (1 if style in ("active", "very_active") else 0), base + 1)
        max_km = {"low": 1.5, "medium": 3.0, "high": 4.0}[ctx.walking]
        day_excluded = set(ctx.knobs.exclude_on_day.get(self.slot.index + 1, []))
        # A moderate traveller still wants breathing room: one extra stop per gap; active travellers want them all.
        per_gap = {"moderate": 1, "active": 3, "very_active": 6}.get(style, 1) + max(0, ctx.knobs.density_delta)
        must = set(ctx.knobs.must_include) | set(ctx.knobs.signature_picks)
        added = 0
        while until - self.t >= 30 and added < per_gap:
            load = day_load([to_min(i.end) - to_min(i.start) for i in self.items if i.kind == "activity"])
            # Unassigned sights, plus sights of later days that can spare one (a free afternoon today beats a
            # crowded day later). Places the traveller asked for stay where they were put.
            candidates = [(r, None) for r in self.spare if r.item.id not in self.taken]
            candidates += [(r, s) for s in self.later if len(s.activities) > 2 and (s.index + 1) not in ctx.pinned_days
                           for r in s.activities if r.item.id not in must and not r.item.day_trip]
            best = None
            for r, source in candidates:
                a = r.item
                if (a.id in day_excluded or _is_evening(a) or a.day_trip or r.score < 0.12
                        or a.duration_minutes > 150 or (a.dates and self.slot.date not in a.dates)
                        or (self.slot.high_rain and not a.indoor)
                        or load + activity_weight(a.duration_minutes) > cap):
                    continue
                km = haversine_km(self.here.lat, self.here.lon, a.location.lat, a.location.lon)
                if km > max_km:
                    continue
                leg = self.leg_to(a.location)
                arrive = self.t + (leg.minutes if leg else 0)
                start = next((round_up(max(arrive, o)) for o, c in open_windows(a.opening_hours, self.slot.date)
                              if round_up(max(arrive, o)) + a.duration_minutes <= c), None)
                if start is None or start - arrive > 45:
                    continue
                back = ctx.leg(a.location, back_to).minutes if back_to else 0
                if start + a.duration_minutes + back > until:
                    continue
                value = r.score - 0.08 * km - 0.003 * (start - self.t)
                if best is None or value > best[0]:
                    best = (value, r, start, source)
            if best is None:
                break
            _, r, start, source = best
            self.taken.add(r.item.id)
            if source is not None:
                source.activities.remove(r)
            if not self.activity(r, start_hint=start, deadline=until):
                self.dropped.remove(r.item.id)  # just a candidate, not a planned stop that failed
                if source is not None:
                    source.activities.append(r)  # give it back to its day
                continue
            self.items[-1].explanation.insert(0, "Close by and open now: a good use of the free time")
            added += 1
        return added

    def slot_weather(self):
        return next((w for w in self.ctx.research.weather if w.date == self.slot.date), None)

    def back_to_hotel(self, title: str = "Return to hotel") -> None:
        if not self.hotel:
            return
        leg = self.leg_to(self.hotel.location)
        if leg is None:
            return
        self.add(ItineraryItem(start=to_hhmm(self.t), end=to_hhmm(self.t + leg.minutes), kind="transfer", title=title,
                               location=self.hotel.location, notes=leg.description), leg, self.hotel.location)

    # -- day sections ----------------------------------------------------------
    def breakfast(self, at: int) -> None:
        self.t = at
        if self.hotel and self.hotel.breakfast_included:
            self.add(ItineraryItem(start=to_hhmm(at), end=to_hhmm(at + 45), kind="meal", meal_type="breakfast",
                                   title=f"Breakfast at {self.hotel.name}", location=self.hotel.location,
                                   explanation=["Included in your room rate"]), None, None)
        else:
            self.meal("breakfast", at)

    def daytime(self, activities: list[Ranked], start: int, end: int) -> None:
        ctx = self.ctx
        if not activities:
            lunch_start = max(self.t, 12 * 60 + 30)
            if not self.lunch_done and lunch_start <= 14 * 60 + 30 and lunch_start + LUNCH_DURATION <= end + 30:
                self.lunch_done = self.meal("lunch", lunch_start)
            return
        depot = self.here
        stops = [Stop(r.item.id, r.item.location, r.item.duration_minutes, open_windows(r.item.opening_hours, self.slot.date),
                      max(r.score, 0.05)) for r in activities]
        # A long food experience (cooking class, food tour) doubles as lunch.
        meal_experience = any(r.item.kind == "activity" and "food" in r.item.categories and r.item.duration_minutes >= 120
                              for r in activities)
        lunch_window = None if (self.lunch_done or meal_experience) else (12 * 60, 13 * 60 + 45)

        def travel(a: GeoPoint, b: GeoPoint) -> int:
            return ctx.leg(a, b).minutes

        res = optimize_day(depot, stops, max(start, self.t), end, travel, lunch_window)
        by_id = {r.item.id: r for r in activities}
        self.dropped += [s.id for s in res.dropped]
        lunch_at = res.lunch_start
        for stop, planned_start in res.ordered:
            r = by_id[stop.id]
            if (not self.lunch_done and lunch_at is not None and planned_start >= lunch_at
                    and max(self.t, lunch_at) + LUNCH_DURATION <= end + 30):
                self.lunch_done = self.meal("lunch", max(self.t, lunch_at))
            # Real travel times can differ from the optimizer's; never run past the window.
            ok = self.activity(r, deadline=end + 20)
            if ok and "food" in r.item.categories and r.item.kind == "activity":
                s, e = to_min(self.items[-1].start), to_min(self.items[-1].end)
                if s <= 13 * 60 + 30 and e >= 12 * 60 + 30:
                    self.lunch_done = True
                    self.items[-1].notes += " Lunch is part of this experience."
        lunch_start = max(self.t, 12 * 60 + 15)
        if not self.lunch_done and lunch_start <= 14 * 60 + 30 and lunch_start + LUNCH_DURATION <= end + 30:
            self.lunch_done = self.meal("lunch", lunch_start)

    def afternoon_and_evening(self, evening: Ranked | None, allow_extras: bool = True) -> None:
        ctx = self.ctx
        style = _style(ctx)
        dinner_at = to_min(ctx.research.destination_info.get("dinner_time", "19:30"))
        relaxed = style == "relaxed" or ctx.knobs.extra_rest
        if self.away_from_city() and self.hotel:
            self.back_to_hotel(f"Return to {ctx.research.destination_info.get('name', 'the city')}")
            allow_extras = False  # a long day out: straight to dinner
        if allow_extras and relaxed and self.hotel and self.t < 17 * 60 + 30:
            leg = self.leg_to(self.hotel.location)
            if leg is None or leg.minutes <= 30:
                rest_start = self.t + (leg.minutes if leg else 0)
                rest_end = min(rest_start + 90, dinner_at - 45)
                if rest_end - rest_start >= 45:
                    self.add(ItineraryItem(start=to_hhmm(rest_start), end=to_hhmm(rest_end), kind="rest",
                                           title=f"Rest at {self.hotel.name}", location=self.hotel.location,
                                           explanation=["Relaxed pace: a recharge break before the evening"]),
                             leg, self.hotel.location)
        if allow_extras and not relaxed:
            self.fill_gap(dinner_at - 20)  # sights before free time
        food_prefs = [f.lower() for f in ctx.profile.food_preferences]
        wants_coffee = not ctx.knobs.skip_snacks and (
            ctx.knobs.food_focus or "coffee" in food_prefs or style in ("relaxed", "moderate"))
        wants_dessert = not ctx.knobs.skip_snacks and (
            ctx.knobs.food_focus or "dessert" in food_prefs or "gelato" in food_prefs)
        if allow_extras and wants_coffee and 15 * 60 <= self.t + 20 and self.t <= dinner_at - 90:
            self.meal("coffee", self.t, "Coffee break")
        if evening is not None:
            ev = evening.item
            windows = open_windows(ev.opening_hours, self.slot.date)
            if windows and windows[0][0] + ev.duration_minutes <= dinner_at + 30 and self.t <= windows[0][0]:
                self.activity(evening, start_hint=windows[0][0])
                evening = None
        gap = dinner_at - self.t
        # Relaxed days show their spare time too (after the rest), so the traveller sees the breathing room.
        if allow_extras and gap >= (90 if relaxed else 120):
            area = self.items[-1].title if self.items else "the neighbourhood"
            self.add(ItineraryItem(start=to_hhmm(self.t), end=to_hhmm(dinner_at - 30), kind="free",
                                   title="Free time", notes=f"Explore around {area.split(' - ')[-1]} at your own pace.",
                                   explanation=["Unscheduled time keeps the day flexible"]), None, None)
        self.meal("dinner", max(self.t, dinner_at))
        if evening is not None:
            self.activity(evening, start_hint=self.t)
        elif allow_extras and style in ("active", "very_active") and self.hotel:
            # Squares and fountains are at their best after dark: an evening stroll for travellers who want full days.
            self.fill_gap(22 * 60 + 30, back_to=self.hotel.location)
        if allow_extras and wants_dessert:
            if self.t <= 22 * 60 + 15:
                self.meal("dessert", self.t, "Dessert")
        self.back_to_hotel()


def _flight_item(f: FlightOption, tz: ZoneInfo, outbound: bool) -> ItineraryItem:
    """Timeline times are in destination local time; the title shows each airport's local time."""
    dep_local = f.depart_at.astimezone(tz)
    arr_local = f.arrive_at.astimezone(tz)
    if outbound:
        # An overnight flight that left "yesterday" in destination time starts the day at 00:00.
        start = dep_local.strftime("%H:%M") if dep_local.date() == arr_local.date() else "00:00"
        end = arr_local.strftime("%H:%M")
    else:
        start = dep_local.strftime("%H:%M")
        end = arr_local.strftime("%H:%M") if arr_local.date() == dep_local.date() else "23:59"
    if f.mode != "flight":
        return ItineraryItem(start=start, end=end, kind="flight",
                             title=f"{f.airline} {f.origin} {f.depart_at:%H:%M} -> {f.destination} {f.arrive_at:%H:%M}",
                             cost=Money(amount=0.0),
                             notes=f"{f.metadata.notes or ''} Fare ~{f.price_per_person.amount:.0f} "
                                   f"{f.price_per_person.currency} per person (estimate, counted in transport).".strip(),
                             explanation=[f"{f.duration_minutes // 60}h{f.duration_minutes % 60:02d} between the cities",
                                          "Ground transport: city centre to city centre, no airport time"])
    title = (f"Flight {f.flight_number} {f.origin} {f.depart_at:%H:%M} -> {f.destination} {f.arrive_at:%H:%M} "
             f"({f.airline}, {'direct' if f.stops == 0 else f'{f.stops} stop'})")
    return ItineraryItem(start=start, end=end, kind="flight", title=title,
                         notes=f"Times in the title are local to each airport. Baggage: {f.baggage}.",
                         explanation=[f"{f.duration_minutes // 60}h{f.duration_minutes % 60:02d} total travel time"])


def build_day(ctx: PlanContext, slot: DaySlot, hotel: HotelOption | None, out: FlightOption | None,
              ret: FlightOption | None, transfers: tuple[TransferOption | None, TransferOption | None], used_restaurants: dict[str, int],
              restaurant_rank: dict[str, Ranked], spare: list[Ranked] | None = None,
              taken: set[str] | None = None, later: list[DaySlot] | None = None) -> tuple[DayPlan, list[str]]:
    b = DayBuilder(ctx, slot, hotel, used_restaurants, restaurant_rank, spare, taken, later)
    wake = to_min(ctx.profile.preferred_wake_up_time)
    tr = ctx.contract.travelers
    name = ctx.research.destination_info.get("name", ctx.dest.title())
    title = f"Explore {name}"

    transfer = transfers[0]
    if slot.kind == "arrival" and out is not None:
        title = f"Arrival in {name}"
        b.items.append(_flight_item(out, ctx.tz, True))
        arr = out.arrive_at.astimezone(ctx.tz)
        b.t = arr.hour * 60 + arr.minute + arrival_processing(out)
        if arr.date() != slot.date:
            # Lands after midnight: the transfer and check-in belong to the night, not to this day's timeline.
            b.items.append(ItineraryItem(
                start="23:59", end="23:59", kind="free", title="Overnight arrival",
                cost=transfer_cost(transfer, tr) if transfer else Money(amount=0.0),
                notes=f"Lands {arr:%a %H:%M}; {_hub(out)} transfer"
                      + (f" ({transfer.name}, ~{transfer.minutes} min)" if transfer else "")
                      + " and check-in happen after midnight - tell the hotel you'll arrive late."))
            return DayPlan(day=slot.index + 1, date=slot.date, title=title, items=b.items,
                           notes=["Late arrival: the first full day starts after a short night."]), []
        if transfer:
            b.items.append(ItineraryItem(
                start=to_hhmm(b.t), end=to_hhmm(b.t + transfer.minutes), kind="transfer",
                title=f"{_hub(out).capitalize()} transfer: {transfer.name}", cost=transfer_cost(transfer, tr), notes=transfer.notes,
                location=hotel.location if hotel else None,
                explanation=[f"Chosen for your {ctx.mode} plan", f"About {transfer.minutes} min door to door"]))
            b.t += transfer.minutes
        at_hotel = b.t
        if arr.date() != slot.date or at_hotel >= 23 * 60 + 45:
            b.items.append(ItineraryItem(start="23:59", end="23:59", kind="free", title="Overnight arrival",
                                         notes=f"Lands {arr:%a %H:%M}; transfer and check-in happen after midnight."))
            return DayPlan(day=1, date=slot.date, title=title, items=b.items,
                           notes=["Overnight flight: the first full day starts after a short night."]), []
        if hotel:
            early = b.t < to_min(CHECK_IN_FROM)
            b.items.append(ItineraryItem(
                start=to_hhmm(b.t), end=to_hhmm(b.t + 30), kind="hotel", title=f"Check in at {hotel.name}",
                location=hotel.location,
                notes=("Early arrival: leave your bags; official check-in from " + CHECK_IN_FROM) if early else "Check-in",
            ))
            b.t += 30
        b.daytime(slot.activities, slot.start, slot.end)
        if b.t < 22 * 60:
            b.afternoon_and_evening(None, allow_extras=b.t < 17 * 60)
    elif slot.kind == "departure" and ret is not None:
        title = f"Departure from {name}"
        transfer = transfers[1]
        dep = ret.depart_at.astimezone(ctx.tz)
        tmin = transfer.minutes if transfer else 60
        leave = dep.hour * 60 + dep.minute - before_departure(ret) - tmin
        if leave - 45 >= wake:
            b.breakfast(wake)
        else:
            b.t = max(0, leave - 30)
            slot.activities = []
        # Leave room to get back to the hotel for the bags before the transfer - measured from the city centre to
        # this hotel (a hotel out of town is a long ride back), with 15 minutes to collect the bags.
        center = GeoPoint(**ctx.research.destination_info["center"])
        back_min = ctx.leg(center, hotel.location).minutes if hotel else 0
        b.hard_end = leave - 15 - back_min  # nothing (sight or meal) may run past this
        b.daytime(slot.activities, slot.start, min(slot.end, b.hard_end - 20))
        if leave - b.t >= 150 and b.t >= 13 * 60 and b.t < 16 * 60 and not ctx.knobs.skip_snacks:
            b.meal("coffee", b.t, "Coffee break")
        if hotel:
            b.fill_gap(leave - 15, back_to=hotel.location)  # one more sight before the bags, if it fits
        back = b.leg_to(hotel.location) if hotel else None
        spare = leave - 15 - (back.minutes if back else 0) - b.t
        if spare >= 75:
            b.add(ItineraryItem(start=to_hhmm(b.t), end=to_hhmm(b.t + spare), kind="free", title="Free time",
                                notes="Last wander, souvenir shopping or a final coffee before heading home.",
                                explanation=["Buffer before the airport run"]), None, None)
        if hotel:
            b.back_to_hotel("Head back to the hotel")
            checkout = max(b.t, leave - 15)
            b.items.append(ItineraryItem(start=to_hhmm(checkout), end=to_hhmm(checkout + 15),
                                         kind="hotel", title=f"Check out / collect bags at {hotel.name}",
                                         location=hotel.location, notes="Most hotels store luggage after check-out."))
            b.t = checkout + 15
        if transfer:
            b.items.append(ItineraryItem(
                start=to_hhmm(b.t), end=to_hhmm(b.t + transfer.minutes), kind="transfer",
                title=f"Transfer to {_hub(ret)}: {_towards_airport(transfer.name)}", cost=transfer_cost(transfer, tr),
                notes=transfer.notes,
                explanation=[f"Arrive about {before_departure(ret) // 60}h{before_departure(ret) % 60:02d} before departure"]))
            b.t += transfer.minutes
        b.items.append(_flight_item(ret, ctx.tz, False))
    else:
        b.breakfast(wake)
        if not slot.activities and b.t < 12 * 60:
            # Nothing scheduled (e.g. a beach resort with few sights): say so, it's a free day by design.
            b.add(ItineraryItem(start=to_hhmm(b.t), end=to_hhmm(12 * 60 + 30), kind="free", title=f"Free day in {name}",
                                notes="Beach, pool, a spa or wandering at your own pace - nothing booked.",
                                explanation=["Unscheduled time: every sight that fits your trip is on another day"]),
                  None, None)
            title = f"Free day in {name}"
        b.daytime(slot.activities, slot.start, slot.end)
        b.afternoon_and_evening(slot.evening)

    weather = b.slot_weather()
    notes = []
    if weather and weather.risk == "high":
        notes.append(f"Weather risk: {weather.condition} ({weather.precipitation_probability}% rain). Indoor options prioritised.")
    if b.dropped:
        names = [p.name for p in ctx.research.attractions if p.id in set(b.dropped)]
        if names:
            notes.append("Did not fit today: " + ", ".join(names))
    day = DayPlan(day=slot.index + 1, date=slot.date, title=title, items=b.items, weather=weather,
                  walking_km=round(b.walk_km, 2), activity_count=sum(1 for i in b.items if i.kind == "activity"),
                  notes=notes, capacity=slot.max_count)
    if day.activity_count:
        top = [i.title for i in b.items if i.kind == "activity"][:2]
        day.title = f"{title}: " + " & ".join(top) if slot.kind == "full" else day.title
    return day, b.dropped


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _with_beach_day(ctx: PlanContext) -> PlanContext:
    """A traveller who loves the sea gets (at least) one real beach in the plan, like a place they named."""
    if "beach" not in expand_interests(ctx.profile.activity_preferences) or ctx.contract.num_days < 3:
        return ctx
    beaches = [a for a in ctx.research.attractions if "beach" in a.categories and "overnight_trip" not in a.categories
               and a.id not in ctx.knobs.exclude_ids]
    if not beaches or any(b.id in ctx.knobs.must_include for b in beaches):
        return ctx
    best = max(beaches, key=lambda a: score_attraction(a, ctx.profile, ctx.contract, ctx.mode).score)
    knobs = ctx.knobs.model_copy(update={"must_include": ctx.knobs.must_include + [best.id]})
    return replace(ctx, knobs=knobs, auto_picks=[best.id])


def build_plan(ctx: PlanContext) -> TripPlan:
    ctx = _with_beach_day(ctx)
    plan = TripPlan(mode=ctx.mode)
    o, r, h, notes, alternatives = select_core(ctx)
    plan.outbound_flight = o.item if o else None
    plan.return_flight = r.item if r else None
    plan.hotel = h.item if h else None
    plan.alternatives = alternatives
    plan.repair_log.extend(notes)
    if o:
        plan.explanations["outbound_flight"] = o.reasons + [f"Trade-off: {t}" for t in o.tradeoffs]
    if r:
        plan.explanations["return_flight"] = r.reasons + [f"Trade-off: {t}" for t in r.tradeoffs]
    if h:
        plan.explanations["hotel"] = h.reasons + [f"Trade-off: {t}" for t in h.tradeoffs]

    o_f, r_f = plan.outbound_flight, plan.return_flight
    t_in = (station_transfer(ctx, plan.hotel, True) if o_f and o_f.mode != "flight"
            else choose_transfer(ctx, o_f.destination if o_f else None))
    t_out = (station_transfer(ctx, plan.hotel, False) if r_f and r_f.mode != "flight"
             else choose_transfer(ctx, r_f.origin if r_f else None))
    slots = build_slots(ctx, plan.outbound_flight, plan.return_flight, t_in, t_out)
    unused, _ = assign_activities(ctx, slots, plan.hotel)
    food_prefs = ctx.strategy.food if ctx.strategy is not None else None
    # The city's typical meal price (per currency), so "cheap" and "upscale" are judged against this city.
    by_cur: dict[str, list[float]] = {}
    for x in ctx.research.restaurants:
        if x.cost_per_person.amount > 0 and x.kind == "restaurant":
            by_cur.setdefault(x.cost_per_person.currency, []).append(x.cost_per_person.amount)
    typical = {cur: sorted(v)[len(v) // 2] for cur, v in by_cur.items()}
    restaurant_rank = {x.id: score_restaurant(x, ctx.profile, ctx.mode, ctx.knobs.price_pressure, food_prefs,
                                              typical.get(x.cost_per_person.currency, 0.0))
                       for x in ctx.research.restaurants}
    used_restaurants: dict[str, int] = {}
    # The traveller's requests and the plan's signature experiences survive the timeline; the critic's picks never evict.
    must_ids = (set(ctx.knobs.must_include) - set(ctx.knobs.expert_picks)) | set(ctx.knobs.signature_picks)
    # Everything already given a day; the rest can fill idle hours (gap filling) on any day.
    taken = {r.item.id for s in slots for r in s.activities} | {s.evening.item.id for s in slots if s.evening}
    for n, slot in enumerate(slots):
        later = [s for s in slots[n + 1:] if s.kind != "departure"]
        # A place the traveller asked for must survive the real timeline (travel times, closing hours):
        # if it gets squeezed out, drop the day's weakest other activity and rebuild the day. If even an emptied
        # day can't hold it (closed that day, too far), give the day its stops back: never lose everything for nothing.
        original = list(slot.activities)
        start_state = (dict(used_restaurants), set(taken), [list(s.activities) for s in later])
        gave_back = False
        while True:
            before = dict(used_restaurants)
            taken_before = set(taken)
            later_before = [list(s.activities) for s in later]
            planned = list(slot.activities)
            day, dropped = build_day(ctx, slot, plan.hotel, plan.outbound_flight, plan.return_flight, (t_in, t_out),
                                     used_restaurants, restaurant_rank, unused, taken, later)
            lost = [r for r in planned if r.item.id in must_ids and r.item.id in dropped]
            others = [r for r in planned if r.item.id not in must_ids]
            if lost and not others and len(original) > len(planned) and not gave_back:
                lost_ids = {r.item.id for r in lost}
                slot.activities = [r for r in original if r.item.id not in lost_ids]
                gave_back, (before, taken_before, later_before) = True, start_state
            elif not lost or not others:
                break
            else:
                planned.remove(min(others, key=lambda r: r.score))
                slot.activities = planned
            used_restaurants.clear()
            used_restaurants.update(before)
            taken.clear()
            taken.update(taken_before)
            for s, acts in zip(later, later_before):
                s.activities = list(acts)
        plan.days.append(day)
    unused = [u for u in unused if u.item.id not in taken]

    # Alternatives for each chosen activity: best unused ones sharing a category.
    for day in plan.days:
        for item in day.items:
            if item.kind == "activity" and item.place_id:
                place = ctx.research.place(item.place_id)
                cats = set(place.categories) if place else set()
                item.alternatives = [u.item.name for u in unused if cats & set(u.item.categories)][:2]

    # Where did each requested place end up?
    placed = {i.place_id: d.day for d in plan.days for i in d.items if i.place_id}
    for pid in ctx.knobs.must_include:
        place = ctx.research.place(pid)
        if pid in ctx.auto_picks:
            continue  # not something the traveller named
        if place is not None and "overnight_trip" not in place.categories:  # too far: explained in the reply instead
            plan.requested[place.name] = placed.get(pid)
    for pid in ctx.knobs.meal_requests:  # restaurants asked for by name: on which day they're a meal
        place = ctx.research.place(pid)
        if place is not None:
            plan.requested[place.name] = placed.get(pid)

    plan.budget = compute_budget(plan, ctx.contract, {k: v for k, v in ctx.research.fx_rates.items()}, ctx.buffer_ratio)
    plan.within_budget = plan.budget.total <= ctx.contract.budget.amount
    return plan


def plan_activity_ids(plan: TripPlan) -> dict[int, list[str]]:
    return {d.day: [i.place_id for i in d.items if i.kind == "activity" and i.place_id] for d in plan.days}
