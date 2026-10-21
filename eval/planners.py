"""Planners compared by the benchmark and the ablation (random, greedy, OR-Tools, LLM, Dalili) - see benchmark.py.

Import after harness.setup_env(): the travel_agent modules read their settings at import time.
"""

from __future__ import annotations

import json
import random
from datetime import timedelta

import harness

from travel_agent.engine.optimizer import Stop, optimize_day
from travel_agent.engine.planner import build_plan, capacity
from travel_agent.engine.ranking import score_attraction, score_hotel
from travel_agent.engine.repair import repair
from travel_agent.engine.validators import validate_plan
from travel_agent.utils import haversine_km, open_windows, to_min

def _per_day(ctx) -> int:
    return max(1, capacity(ctx)[0])


def _same_day_flights(ctx):
    c, r = ctx.contract, ctx.research
    outs = [f for f in r.flights_outbound if f.arrive_at.astimezone(ctx.tz).date() == c.start_date] or r.flights_outbound
    rets = [f for f in r.flights_return if f.depart_at.astimezone(ctx.tz).date() == c.end_date] or r.flights_return
    return outs, rets


def plan_random(sc, seed: int):
    rnd = random.Random(seed)
    ctx = harness.ctx_for(sc)
    r = ctx.research
    hotel = rnd.choice(r.hotels)
    out, ret = rnd.choice(r.flights_outbound), rnd.choice(r.flights_return)
    pool = harness.city_attractions(r)
    rnd.shuffle(pool)
    k = _per_day(ctx)
    days = [pool[i * k:(i + 1) * k] for i in range(ctx.contract.num_days)]
    return harness.schedule(ctx, hotel, out, ret, days)


def _greedy_choice(ctx):
    r, p, c = ctx.research, ctx.profile, ctx.contract
    anchors = [a.location for a in sorted(harness.city_attractions(r), key=lambda a: -(a.reviews_count or 0))[:6]]
    nightly = c.budget.amount * 0.35 / max(c.nights * c.rooms, 1)  # a reasonable share of the budget per night
    affordable = [h for h in r.hotels if h.price_per_night.amount * ctx.fx(h.price_per_night.currency) <= nightly] \
        or [min(r.hotels, key=lambda h: h.price_per_night.amount * ctx.fx(h.price_per_night.currency))]
    hotel = max(affordable, key=lambda h: score_hotel(h, anchors, p, ctx.mode, nightly).score)
    outs, rets = _same_day_flights(ctx)

    def ok(f):  # the traveller's stated flight preferences
        return (not p.avoid_early_flights or f.depart_at.astimezone(ctx.tz).hour >= 8) and \
            (p.flight_preference != "direct" or f.stops == 0)

    out = min([f for f in outs if ok(f)] or outs, key=lambda f: f.price_per_person.amount)
    ret = min([f for f in rets if ok(f)] or rets, key=lambda f: f.price_per_person.amount)
    ranked = sorted(harness.city_attractions(r), key=lambda a: -score_attraction(a, p, c, ctx.mode).score)
    k = _per_day(ctx)
    days: list[list] = [[] for _ in range(c.num_days)]
    for i, a in enumerate(ranked[:k * c.num_days]):
        days[i % c.num_days].append(a)
    return hotel, out, ret, days


def _nearest_neighbour(start, stops):
    order, here, left = [], start, list(stops)
    while left:
        nxt = min(left, key=lambda s: haversine_km(here.lat, here.lon, s.location.lat, s.location.lon))
        order.append(nxt)
        left.remove(nxt)
        here = nxt.location
    return order


def plan_greedy(sc):
    ctx = harness.ctx_for(sc)
    hotel, out, ret, days = _greedy_choice(ctx)
    return harness.schedule(ctx, hotel, out, ret, [_nearest_neighbour(hotel.location, d) for d in days])


def _optimize_days(ctx, hotel, days):
    """Each day's stops ordered and timed by the OR-Tools time-window router (Dalili's optimizer)."""
    wake = to_min(ctx.profile.preferred_wake_up_time)
    ordered, starts = [], []
    for i, stops in enumerate(days):
        d = ctx.contract.start_date + timedelta(days=i)
        st = [Stop(id=a.id, location=a.location, duration=a.duration_minutes,
                   windows=open_windows(a.opening_hours, d) or [(0, 24 * 60)], priority=0.5) for a in stops]
        res = optimize_day(hotel.location, st, wake + 60, 21 * 60, lambda a, b: ctx.leg(a, b).minutes)
        by_id = {a.id: a for a in stops}
        ordered.append([by_id[s.id] for s, _ in res.ordered])
        starts.append([t for _, t in res.ordered])
    return ordered, starts


def plan_ortools(sc):
    ctx = harness.ctx_for(sc)
    hotel, out, ret, days = _greedy_choice(ctx)
    ordered, starts = _optimize_days(ctx, hotel, days)
    return harness.schedule(ctx, hotel, out, ret, ordered, starts)


def plan_dalili(sc):
    from travel_agent.engine.knobs import PlanKnobs

    knobs = PlanKnobs()
    plan = None
    for i in range(6):
        ctx = harness.ctx_for(sc, knobs=knobs)
        plan = build_plan(ctx)
        plan.validation = validate_plan(plan, ctx.contract, ctx.profile, ctx.research, 0.05)
        if plan.validation.result == "PASS":
            break
        knobs, _ = repair(plan, plan.validation, knobs, ctx.research, ctx.profile)
    return plan


async def plan_llm(sc, optimize: bool = False):
    """The model plans from the same candidate lists (ids); the naive scheduler times it in the model's order, or
    (optimize=True) the OR-Tools optimizer orders and times each day."""
    from pydantic import BaseModel

    from travel_agent import llm

    class DayPick(BaseModel):
        day: int
        place_ids: list[str]

    class LLMPlan(BaseModel):
        hotel_id: str
        outbound_flight_id: str
        return_flight_id: str
        days: list[DayPick]

    ctx = harness.ctx_for(sc)
    r, c = ctx.research, ctx.contract
    data = {
        "trip": {"city": c.destination_name, "start": str(c.start_date), "end": str(c.end_date), "days": c.num_days,
                 "travellers": c.travelers, "budget": f"{c.budget.amount:.0f} {c.budget.currency}",
                 "pace_activities_per_day": _per_day(ctx), "interests": ctx.profile.activity_preferences,
                 "walking": ctx.profile.walking_tolerance},
        "hotels": [{"id": h.id, "name": h.name, "rating": h.rating, "per_night": h.price_per_night.amount} for h in r.hotels],
        "outbound_flights": [{"id": f.id, "dep": f.depart_at.isoformat(), "arr": f.arrive_at.isoformat(),
                              "price": f.price_per_person.amount} for f in r.flights_outbound[:15]],
        "return_flights": [{"id": f.id, "dep": f.depart_at.isoformat(), "arr": f.arrive_at.isoformat(),
                            "price": f.price_per_person.amount} for f in r.flights_return[:15]],
        "places": [{"id": a.id, "name": a.name, "categories": a.categories[:3], "minutes": a.duration_minutes,
                    "hours": a.opening_hours, "lat": round(a.location.lat, 4), "lon": round(a.location.lon, 4),
                    "price": a.cost_per_person.amount} for a in harness.city_attractions(r)[:45]],
    }
    system = ("You are a travel planner. Using ONLY the ids given, choose a hotel, an outbound and a return flight, "
              "and for each day the places to visit in visiting order (respect opening hours, keep each day "
              "geographically compact, about pace_activities_per_day places, stay within the budget).")
    out = await llm.parse(system, json.dumps(data, default=str), LLMPlan, effort="low")
    if out is None:
        return None
    hotels = {h.id: h for h in r.hotels}
    flights = {f.id: f for f in r.flights_outbound + r.flights_return}
    places = {a.id: a for a in r.attractions}
    hotel = hotels.get(out.hotel_id) or r.hotels[0]
    o = flights.get(out.outbound_flight_id) or r.flights_outbound[0]
    b = flights.get(out.return_flight_id) or r.flights_return[0]
    days = [[places[pid] for pid in d.place_ids if pid in places] for d in sorted(out.days, key=lambda d: d.day)]
    invented = sum(1 for d in out.days for pid in d.place_ids if pid not in places)
    if optimize:
        ordered, starts = _optimize_days(ctx, hotel, days)
        return harness.schedule(ctx, hotel, o, b, ordered, starts), invented
    return harness.schedule(ctx, hotel, o, b, days), invented




async def llm_select_then_optimize(sc):
    """Ablation E: the model picks hotel, flights and each day's places; Dalili's OR-Tools optimizer orders and
    times every day."""
    res = await plan_llm(sc, optimize=True)
    if res is None:
        return None
    plan, invented = res
    return plan, {"ungrounded_rate": None, "invented_ids": invented, "claimed_total": None}


def dalili(sc):
    return plan_dalili(sc)
