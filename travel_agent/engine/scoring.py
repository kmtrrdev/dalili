"""TripScore: one comparable 0-100 score per complete plan."""

from __future__ import annotations

import statistics

from ..models import PlanningMode, ResearchBundle, TravelerProfile, TripContract, TripPlan, TripScore
from ..providers.routing import WALK_LIMITS
from ..utils import to_min
from .planner import STYLE_CAPACITY, day_load
from .ranking import expand_interests, must_have_terms

WEIGHTS = {
    "balanced":   {"budget_fit": 0.18, "comfort": 0.14, "food": 0.14, "activities": 0.16, "transportation": 0.1, "personal_fit": 0.16, "schedule_quality": 0.12},
    "budget":     {"budget_fit": 0.3, "comfort": 0.08, "food": 0.12, "activities": 0.14, "transportation": 0.1, "personal_fit": 0.14, "schedule_quality": 0.12},
    "comfort":    {"budget_fit": 0.12, "comfort": 0.26, "food": 0.12, "activities": 0.12, "transportation": 0.12, "personal_fit": 0.14, "schedule_quality": 0.12},
    "experience": {"budget_fit": 0.12, "comfort": 0.1, "food": 0.18, "activities": 0.22, "transportation": 0.08, "personal_fit": 0.16, "schedule_quality": 0.14},
}


def _c(x: float) -> int:
    return int(round(max(0.0, min(100.0, x))))


def score_plan(plan: TripPlan, contract: TripContract, profile: TravelerProfile, research: ResearchBundle,
               mode: PlanningMode) -> TripScore:
    b = plan.budget
    # Budget fit: full marks with some headroom, sharp drop once over the limit.
    if b and b.limit > 0:
        u = b.total / b.limit
        budget_fit = 100 - max(0.0, u - 0.7) * 60 if u <= 1 else 80 - (u - 1) * 300
    else:
        budget_fit = 50

    comfort = 55.0
    if plan.hotel:
        comfort = 40 + (plan.hotel.rating - 3.5) * 25 + (8 if plan.hotel.breakfast_included else 0)
        comfort += {"quiet": 8, "moderate": 2, "noisy": -8, "unknown": 0}[plan.hotel.noise_level]
    for f in (plan.outbound_flight, plan.return_flight):
        if f:
            comfort += 4 if f.stops == 0 else -6
            comfort -= 6 if f.depart_at.hour < 7 else 0
    rest_blocks = sum(1 for d in plan.days for i in d.items if i.kind in ("rest", "free"))
    comfort += min(rest_blocks * 2, 10)

    meals = [i for d in plan.days for i in d.items if i.kind == "meal" and i.place_id]
    places = [research.place(i.place_id) for i in meals]
    places = [p for p in places if p]
    prefs = {f.lower() for f in profile.food_preferences}
    if places:
        food = 30 + (statistics.mean(p.rating for p in places) - 3.8) * 40
        match = sum(1 for p in places if prefs & set(p.cuisine)) / len(places) if prefs else 0.5
        variety = len({p.id for p in places}) / len(places)
        food += match * 20 + variety * 15
    else:
        food = 40

    acts = [research.place(i.place_id) for d in plan.days for i in d.items if i.kind == "activity" and i.place_id]
    acts = [a for a in acts if a]
    interests = expand_interests(profile.activity_preferences)
    if acts:
        avg_rating = statistics.mean(a.rating for a in acts)
        hit = sum(1 for a in acts if interests & set(a.categories)) / len(acts) if interests else 0.6
        must_see = sum(1 for a in acts if a.popularity == "must_see")
        activities = 25 + (avg_rating - 4.0) * 40 + hit * 30 + min(must_see, 4) * 4
        full_days = max(contract.num_days - 2, 1)
        activities += min(len(acts) / full_days, 2.5) * 4
    else:
        activities = 30

    legs = [i.transport_from_previous for d in plan.days for i in d.items if i.transport_from_previous]
    per_day_minutes = sum(l.minutes for l in legs) / max(len(plan.days), 1)
    max_day_walk = WALK_LIMITS[profile.walking_tolerance][1]
    walk_over = sum(max(0.0, d.walking_km - max_day_walk) for d in plan.days)
    transportation = 100 - max(0.0, per_day_minutes - 30) * 0.8 - walk_over * 8

    v = plan.validation
    warnings = len([x for x in v.violations if x.severity == "warning"]) if v else 0
    errors = len(v.errors) if v else 0
    covered = set()
    for a in acts:
        covered |= expand_interests(a.categories)
    mh = must_have_terms(contract)
    personal = 70 + (20 * len(mh & covered) / len(mh) if mh else 10)
    personal += 10 * (sum(1 for a in acts if interests & set(a.categories)) / len(acts) if acts and interests else 0.5)
    personal -= 5 * sum(1 for x in (v.violations if v else []) if x.check == "preferences")

    cap = STYLE_CAPACITY[profile.travel_style][0]
    density_pen = sum(max(0.0, day_load([to_min(i.end) - to_min(i.start) for i in d.items if i.kind == "activity"]) - cap)
                      for d in plan.days) * 6
    late_pen = sum(1 for d in plan.days if d.items and to_min(d.items[-1].end) > 23 * 60 + 30) * 3
    schedule_quality = 100 - errors * 15 - warnings * 4 - density_pen - late_pen

    parts = {
        "budget_fit": _c(budget_fit), "comfort": _c(comfort), "food": _c(food), "activities": _c(activities),
        "transportation": _c(transportation), "personal_fit": _c(personal), "schedule_quality": _c(schedule_quality),
    }
    total = sum(parts[k] * w for k, w in WEIGHTS[mode].items())
    return TripScore(total=_c(total), **parts)
