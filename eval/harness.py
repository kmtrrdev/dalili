"""Shared evaluation harness: scenarios on recorded real data, a naive scheduler for baseline planners, and the
metrics every planner is judged by (the same deterministic validators and scorer Dalili uses).

Scenarios replay real API responses recorded in tests/fixtures/http_cache.sqlite, so every planner sees exactly
the same flights, hotels, places, opening hours, prices and travel times - only the planning differs.
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def setup_env(llm: bool) -> None:
    """Replay the recorded data (offline, identical inputs); the model only when an experiment needs it."""
    os.environ["TRAVEL_AGENT_LLM"] = "1" if llm else "0"
    os.environ["TRAVEL_AGENT_RULES_FALLBACK"] = "1"  # scenario setup parses the requests the same way every run
    os.environ["TRAVEL_AGENT_HTTP_MODE"] = "replay"
    os.environ["TRAVEL_AGENT_HTTP_CACHE"] = str(ROOT / "tests" / "fixtures" / "http_cache.sqlite")
    os.environ["TRAVEL_AGENT_TODAY"] = "2026-09-27"
    os.environ["TRAVEL_AGENT_DB"] = ":memory:"
    for key in ("SERPAPI_API_KEY", "ORS_API_KEY", "OPENTRIPMAP_API_KEY", "GEOAPIFY_API_KEY"):
        os.environ.setdefault(key, "replay-placeholder")


ROME = "7 days in Rome from October 12 for two, budget $3,500. We love food, history and photography."
ISTANBUL = ("Relaxed 7-day trip to Istanbul from Cairo, November 3, budget $2,000, vegetarian, "
            "no early flights, I don't like walking much")


@dataclass
class Scenario:
    name: str
    trip: object          # TripState with contract, research and profile
    request: str


async def scenarios() -> list[Scenario]:
    """Six scenarios: two real cities x (as asked, a faster pace, a tight budget)."""
    from travel_agent import research
    from travel_agent.models import TripState
    from travel_agent.workflow import run_turn

    out = []
    for city, req in (("rome", ROME), ("istanbul", ISTANBUL)):
        base, _ = await run_turn(TripState(), req)
        await research.prepare_routing(base.research)
        out.append(Scenario(f"{city}-as-asked", base, req))
        fast = base.model_copy(deep=True)
        fast.traveler_profile.travel_style = "active"
        out.append(Scenario(f"{city}-active-pace", fast, req + " We like full days."))
        tight = base.model_copy(deep=True)
        tight.trip_contract.budget.amount = round(base.trip_contract.budget.amount * 0.55)
        out.append(Scenario(f"{city}-tight-budget", tight, req.replace(
            f"${int(base.trip_contract.budget.amount):,}", f"${int(tight.trip_contract.budget.amount):,}")))
    return out


def ctx_for(sc: Scenario, mode: str = "balanced", knobs=None):
    from travel_agent.agents.strategist import DEFAULTS
    from travel_agent.engine.knobs import PlanKnobs
    from travel_agent.engine.planner import PlanContext

    t = sc.trip
    return PlanContext(contract=t.trip_contract, profile=t.traveler_profile, research=t.research, mode=mode,
                       knobs=knobs or PlanKnobs(), buffer_ratio=0.05, strategy=getattr(DEFAULTS, mode))


def city_attractions(research) -> list:
    return [a for a in research.attractions if not a.day_trip and "overnight_trip" not in a.categories]


def icons(research, n: int = 5) -> set[str]:
    return {a.id for a in sorted(city_attractions(research), key=lambda a: -(a.reviews_count or 0))[:n]}


# ---------------------------------------------------------------------------
# Naive scheduler (baselines): visits in the given order, a lunch and a dinner at the nearest restaurant
# ---------------------------------------------------------------------------


def schedule(ctx, hotel, out, ret, day_stops: list[list], starts: list[list[int | None]] | None = None,
             mode: str = "balanced"):
    from travel_agent.engine.budget import compute_budget
    from travel_agent.models import DayPlan, GeoPoint, ItineraryItem, Money, TripPlan
    from travel_agent.utils import haversine_km, is_open_for, round_up, to_hhmm, to_min

    c, r, p = ctx.contract, ctx.research, ctx.profile
    tz = ctx.tz
    wake = to_min(p.preferred_wake_up_time)
    days = []

    from travel_agent.engine.ranking import dietary_ok

    def meal(here, t, kind, day):
        fit = [x for x in r.restaurants if dietary_ok(x, p)] or r.restaurants  # dietary needs, for every planner
        options = [x for x in fit if kind in x.meal_types and is_open_for(x.opening_hours, day, t, t + 75)] or \
            [x for x in fit if kind in x.meal_types] or fit
        if not options:
            return None
        x = min(options, key=lambda x: haversine_km(here.lat, here.lon, x.location.lat, x.location.lon))
        return x

    for i in range(c.num_days):
        d = c.start_date + timedelta(days=i)
        items: list = []
        here = hotel.location if hotel else GeoPoint(**r.destination_info["center"])
        t = wake + 60
        end = 21 * 60
        if i == 0 and out:
            arr = out.arrive_at.astimezone(tz)
            items.append(ItineraryItem(start=to_hhmm(out.depart_at.astimezone(tz).hour * 60), end=to_hhmm(arr.hour * 60 + arr.minute),
                                       kind="flight", title=f"Flight {out.flight_number}"))
            t = max(t, arr.hour * 60 + arr.minute + 120) if arr.date() == d else end
        if i == c.num_days - 1 and ret:
            dep = ret.depart_at.astimezone(tz)
            end = min(end, dep.hour * 60 + dep.minute - 210)
        stops = day_stops[i] if i < len(day_stops) else []
        given = (starts[i] if starts and i < len(starts) else None) or [None] * len(stops)
        lunch_done = dinner_done = False
        for stop, s0 in zip(stops, given):
            if not lunch_done and t >= 12 * 60 + 30 and here:
                x = meal(here, t, "lunch", d)
                if x:
                    leg = ctx.leg(here, x.location)
                    t += leg.minutes
                    items.append(ItineraryItem(start=to_hhmm(t), end=to_hhmm(t + 75), kind="meal", meal_type="lunch",
                                               title=f"Lunch - {x.name}", place_id=x.id, location=x.location,
                                               transport_from_previous=leg,
                                               cost=Money(amount=x.cost_per_person.amount * c.travelers,
                                                          currency=x.cost_per_person.currency,
                                                          price_type=x.cost_per_person.price_type,
                                                          source=x.cost_per_person.source)))
                    t, here, lunch_done = t + 75, x.location, True
            leg = ctx.leg(here, stop.location) if here else None
            t += leg.minutes if leg else 0
            start = round_up(max(t, s0 or 0))
            items.append(ItineraryItem(start=to_hhmm(start), end=to_hhmm(start + stop.duration_minutes), kind="activity",
                                       title=stop.name, place_id=stop.id, location=stop.location, indoor=stop.indoor,
                                       cost=Money(amount=stop.cost_per_person.amount * c.travelers,
                                                  currency=stop.cost_per_person.currency,
                                                  price_type=stop.cost_per_person.price_type,
                                                  source=stop.cost_per_person.source),
                                       transport_from_previous=leg))
            t, here = start + stop.duration_minutes, stop.location
        if 0 < i < c.num_days - 1 and here:
            if not lunch_done:
                x = meal(here, max(t, 12 * 60 + 30), "lunch", d)
                if x:
                    leg = ctx.leg(here, x.location)
                    s = max(t + leg.minutes, 12 * 60 + 30)
                    items.append(ItineraryItem(start=to_hhmm(s), end=to_hhmm(s + 75), kind="meal", meal_type="lunch",
                                               title=f"Lunch - {x.name}", place_id=x.id, location=x.location,
                                               transport_from_previous=leg,
                                               cost=Money(amount=x.cost_per_person.amount * c.travelers,
                                                          currency=x.cost_per_person.currency,
                                                          price_type=x.cost_per_person.price_type)))
                    t = s + 75
            x = meal(here, max(t, 19 * 60 + 30), "dinner", d)
            if x and not dinner_done:
                leg = ctx.leg(here, x.location)
                s = max(t + leg.minutes, 19 * 60 + 30)
                items.append(ItineraryItem(start=to_hhmm(s), end=to_hhmm(s + 90), kind="meal", meal_type="dinner",
                                           title=f"Dinner - {x.name}", place_id=x.id, location=x.location,
                                           transport_from_previous=leg,
                                           cost=Money(amount=x.cost_per_person.amount * c.travelers,
                                                      currency=x.cost_per_person.currency,
                                                      price_type=x.cost_per_person.price_type)))
        if i == c.num_days - 1 and ret:
            dep = ret.depart_at.astimezone(tz)
            arr = ret.arrive_at.astimezone(tz)
            items.append(ItineraryItem(start=to_hhmm(dep.hour * 60 + dep.minute), end=to_hhmm(min(arr.hour * 60 + arr.minute + (24 * 60 if arr.date() > dep.date() else 0), 24 * 60 - 1)),
                                       kind="flight", title=f"Flight {ret.flight_number}"))
        items.sort(key=lambda x: x.start)
        days.append(DayPlan(day=i + 1, date=d, title=f"Day {i + 1}", items=items,
                            activity_count=sum(1 for x in items if x.kind == "activity"),
                            walking_km=round(sum(x.transport_from_previous.distance_km for x in items
                                                 if x.transport_from_previous and x.transport_from_previous.mode == "walk"), 2)))
    plan = TripPlan(mode=mode, outbound_flight=out, return_flight=ret, hotel=hotel, days=days)
    plan.budget = compute_budget(plan, c, r.fx_rates, 0.05)
    plan.within_budget = plan.budget.total <= c.budget.amount
    return plan


def match_hotel(name: str, hotels: list):
    import re

    def toks(s: str) -> set[str]:
        return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in {"hotel", "the", "by", "and", "&"}}

    want = toks(name)
    best, score = None, 0.0
    for h in hotels:
        have = toks(h.name)
        if want and have:
            s = len(want & have) / len(want | have)
            if s > score:
                best, score = h, s
    return best if score >= 0.5 else None


def _meal_type(it: dict) -> str | None:
    t = (it.get("meal_type") or "").lower()
    if t in ("breakfast", "lunch", "coffee", "dinner", "dessert"):
        return t
    return "coffee" if t in ("snack", "cafe", "tea") else None


def assemble(ctx, hotel, out, ret, days: list[list[dict]], mode: str = "balanced"):
    """A plan from a model's itinerary as written (its own times). Items it named that match researched places get
    their real data; the rest stay unmatched (no place id) - counted as ungrounded."""
    from travel_agent.engine.budget import compute_budget
    from travel_agent.models import DayPlan, ItineraryItem, Money, TripPlan
    from travel_agent.utils import to_hhmm, to_min

    c = ctx.contract
    plan_days = []
    for i in range(c.num_days):
        d = c.start_date + timedelta(days=i)
        items, here = [], hotel.location if hotel else None
        for it in (days[i] if i < len(days) else []):
            place = it.get("place")
            try:
                start = to_min(it["start"])
            except (KeyError, ValueError, AttributeError):
                continue
            dur = place.duration_minutes if place else (75 if it.get("kind") == "meal" else 60)
            leg = ctx.leg(here, place.location) if (place and here) else None
            cost = place.cost_per_person if place else Money(amount=float(it.get("cost") or 0), currency=c.budget.currency)
            items.append(ItineraryItem(
                start=to_hhmm(start), end=to_hhmm(start + dur), kind="meal" if it.get("kind") == "meal" else "activity",
                meal_type=_meal_type(it) if it.get("kind") == "meal" else None, title=it.get("name") or "?",
                place_id=place.id if place else None, location=place.location if place else None,
                indoor=place.indoor if place else None,
                cost=Money(amount=cost.amount * c.travelers, currency=cost.currency, price_type=cost.price_type,
                           source=cost.source), transport_from_previous=leg))
            if place:
                here = place.location
        items.sort(key=lambda x: x.start)
        plan_days.append(DayPlan(day=i + 1, date=d, title=f"Day {i + 1}", items=items,
                                 activity_count=sum(1 for x in items if x.kind == "activity")))
    plan = TripPlan(mode=mode, outbound_flight=out, return_flight=ret, hotel=hotel, days=plan_days)
    plan.budget = compute_budget(plan, c, ctx.research.fx_rates, 0.05)
    plan.within_budget = plan.budget.total <= c.budget.amount
    return plan


# ---------------------------------------------------------------------------
# Metrics (identical for every planner)
# ---------------------------------------------------------------------------


def evaluate(plan, sc: Scenario, ms: float, extra: dict | None = None) -> dict:
    from travel_agent.engine.ranking import expand_interests
    from travel_agent.engine.scoring import score_plan
    from travel_agent.engine.validators import validate_plan

    t = sc.trip
    c, r, p = t.trip_contract, t.research, t.traveler_profile
    plan.validation = validate_plan(plan, c, p, r, 0.05)
    plan.score = score_plan(plan, c, p, r, plan.mode)
    # Travel between the day's stops (sights and meals) - airport transfers and returns to the hotel are left out, so
    # every planner is measured on the same legs.
    legs = [i.transport_from_previous for d in plan.days for i in d.items
            if i.transport_from_previous and i.kind in ("activity", "meal")]
    acts = [r.place(i.place_id) for d in plan.days for i in d.items if i.kind == "activity" and i.place_id]
    acts = [a for a in acts if a]
    interests = expand_interests(p.activity_preferences)
    errors = plan.validation.errors
    by_check: dict[str, int] = {}
    for v in errors:
        by_check[v.check] = by_check.get(v.check, 0) + 1
    hops = [l.distance_km for l in legs]
    return {
        "hard_violations": len(errors), "feasible": not errors, "violations_by_check": by_check,
        "travel_minutes": sum(l.minutes for l in legs), "travel_km": round(sum(hops), 1),
        "km_per_hop": round(statistics.fmean(hops), 2) if hops else 0.0,
        "cost": round(plan.budget.total), "within_budget": plan.within_budget,
        "activities": len(acts),
        "landmark_coverage": round(len(icons(r) & {a.id for a in acts}) / max(len(icons(r)), 1), 2),
        "preference_satisfaction": round(sum(1 for a in acts if interests & set(a.categories)) / len(acts), 2)
        if acts and interests else None,
        "tripscore": plan.score.total, "quality": plan.score.quality,
        "requirements_met": plan.score.constraint_satisfaction,
        "compute_ms": round(ms, 1), **(extra or {}),
    }


def timed(fn, *a, **k):
    t0 = time.perf_counter()
    out = fn(*a, **k)
    return out, (time.perf_counter() - t0) * 1000


def summarize(rows: list[dict], keys: list[str]) -> dict:
    out = {}
    for k in keys:
        vals = [r[k] for r in rows if r.get(k) is not None]
        if not vals:
            continue
        if isinstance(vals[0], bool):
            out[k] = round(sum(vals) / len(vals), 3)
        else:
            out[k] = round(statistics.fmean(vals), 2)
    return out


def tz_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
