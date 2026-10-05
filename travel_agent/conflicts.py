"""Constraint conflict resolution: when the plan cannot satisfy every requirement, find the smallest meaningful
relaxations, price them, and let the traveller choose. Nothing here changes the plan.

1. Detect: the selected plan breaks a constraint (over the budget, a requested place that couldn't fit).
2. Generate atomic relaxations from the research already done - real prices, no new searches:
     another plan that fits, a cheaper comparable hotel, cheaper flights, fewer paid tickets, fewer nights,
     raising the budget, (other dates: impact unknown until searched).
3. Search: single relaxations and combinations of the combinable ones, keeping those that close the gap.
4. Rank by how much each costs THIS traveller: experience lost + the priority of every constraint it relaxes
   (hard >> soft > preference) + what they said matters most (a traveller who said "cost" pays more for raising
   the budget; "comfort" protects the hotel; "time in the city" protects nights and flight hours).
5. Explain each option with its saving and impact; the traveller confirms before anything is applied.
The weights below are ranking heuristics (tunable), not travel rules: every number they combine is computed.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any

from pydantic import BaseModel, Field

from .constraints import by_type
from .models import TripState

RELAX_COST = {"hard": 1.0, "soft": 0.35, "preference": 0.1, "nice_to_have": 0.05}
COMBINABLE = {"cheaper_hotel", "cheaper_flights", "fewer_paid_tickets"}


class Relaxation(BaseModel):
    kind: str
    label: str
    saving: float | None = None          # in the budget currency; None = unknown until searched
    impact: str = ""
    degradation: float = 0.0             # 0 = nothing lost .. 1 = a lot of the experience lost
    relaxes: list[str] = Field(default_factory=list)  # constraint ids this would bend
    action: dict[str, Any] = Field(default_factory=dict)  # how to apply it if the traveller agrees
    penalty: float = 0.0                 # how much it costs this traveller (see _penalty)


class Option(BaseModel):
    steps: list[Relaxation]
    saving: float | None
    closes_gap: bool
    penalty: float
    summary: str


class Conflict(BaseModel):
    kind: str
    constraint_ids: list[str]
    explanation: str
    gap: float | None = None
    currency: str | None = None
    options: list[Option] = Field(default_factory=list)
    needs_confirmation: bool = True


def _money(v: float, cur: str) -> str:
    return f"{v:,.0f} {cur}"


def _penalty(r: Relaxation, trip: TripState) -> float:
    c = trip.trip_contract
    pri = {x.id: x.priority for x in (c.constraints if c else [])}
    p = r.degradation + sum(RELAX_COST.get(pri.get(cid, "soft"), 0.35) for cid in r.relaxes)
    said = c.priorities if c else []
    weight = {name: 1.0 - i * 0.15 for i, name in enumerate(said)}  # earlier = more important
    if r.kind == "raise_budget":
        p += 0.5 * weight.get("cost", 0)
    if r.kind in ("cheaper_hotel", "cheaper_flights", "switch_plan"):
        p += 0.3 * weight.get("comfort", 0)
    if r.kind == "fewer_nights" or (r.kind == "cheaper_flights" and "fewer hours" in r.impact):
        p += 0.3 * weight.get("time_in_city", 0)
    if r.kind == "fewer_paid_tickets":
        p += 0.3 * weight.get("sights", 0)
    return round(p, 3)


def _budget_relaxations(trip: TripState, gap: float) -> list[Relaxation]:
    plan, r, c = trip.selected_plan, trip.research, trip.trip_contract
    cur = c.budget.currency.upper()

    def u(m) -> float:
        return m.amount * (1.0 if m.currency.upper() == cur else r.fx_rates.get(m.currency.upper(), 1.0))

    b = plan.budget
    out: list[Relaxation] = []
    # Another plan that already fits.
    for m, p in trip.plans.items():
        if m != plan.mode and p.budget and p.budget.total <= c.budget.amount:
            drop = max(0.0, ((plan.score.total if plan.score else 0) - (p.score.total if p.score else 0)) / 100)
            out.append(Relaxation(kind="switch_plan", label=f"Switch to the {m} plan", saving=b.total - p.budget.total,
                                  impact=f"{p.pitch or m} - fits the budget", degradation=0.05 + drop,
                                  action={"action": "select_mode", "text": m}))
    # A cheaper hotel of comparable quality (single-city: multi-city hotels are chosen per city by the planner).
    if plan.hotel and not plan.stops:
        cur_night, cur_rating = u(plan.hotel.price_per_night), plan.hotel.rating or 0
        stars = by_type(c, "hotel_min_stars")
        cheaper = [h for h in r.hotels if u(h.price_per_night) < cur_night]
        # Comparable first; if none, a somewhat lower-rated one (its rating drop is counted as lost experience).
        options = [h for h in cheaper if (h.rating or 0) >= cur_rating - 0.4] or \
            [h for h in cheaper if (h.rating or 0) >= cur_rating - 1.0]
        if options:
            h = min(options, key=lambda x: u(x.price_per_night))
            relaxes = [s.id for s in stars if h.stars and h.stars < float(s.value)]
            out.append(Relaxation(
                kind="cheaper_hotel", label=f"Stay at {h.name} ({h.rating}/5)",
                saving=(cur_night - u(h.price_per_night)) * c.nights * c.rooms,
                impact=f"instead of {plan.hotel.name} ({cur_rating}/5)",
                degradation=0.05 + 0.3 * max(0.0, cur_rating - (h.rating or 0)), relaxes=relaxes,
                action={"action": "change_hotel", "text": h.name}))
    # Cheaper flights (same days), unless the traveller requires direct flights and only connections are cheaper.
    if plan.outbound_flight and plan.return_flight and not plan.stops:
        chosen = u(plan.outbound_flight.price_per_person) + u(plan.return_flight.price_per_person)
        direct = by_type(c, "direct_flights")
        pairs = [(o, x, u(o.price_per_person) + u(x.price_per_person)) for o in r.flights_outbound
                 for x in r.flights_return if x.depart_at > o.arrive_at]
        if direct:
            pairs = [p for p in pairs if p[0].stops == 0 and p[1].stops == 0] or pairs
        cheap = min(pairs, key=lambda p: p[2], default=None)
        if cheap and cheap[2] < chosen - 1:
            o, x, fare = cheap
            hours = ((plan.return_flight.depart_at - plan.outbound_flight.arrive_at)
                     - (x.depart_at - o.arrive_at)).total_seconds() / 3600
            impact = f"{o.airline} {o.flight_number} + {x.airline} {x.flight_number}"
            if hours > 1:
                impact += f", {hours:.0f} fewer hours in the city"
            relaxes = [d.id for d in direct if o.stops or x.stops]
            out.append(Relaxation(kind="cheaper_flights", label="Take the cheapest flights",
                                  saving=(chosen - fare) * c.travelers, impact=impact,
                                  degradation=0.05 + max(0.0, hours) / max(24 * c.num_days, 1) + 0.05 * (o.stops + x.stops),
                                  relaxes=relaxes, action={"action": "change_flight"}))
    # Fewer paid tickets: the priciest optional ones (never a requested place or the city's icons).
    from .engine.ranking import icon_ids

    protected = set(trip.user_knobs.must_include) | set(icon_ids(r.attractions))
    paid = sorted(((i, u(i.cost)) for d in plan.days for i in d.items
                   if i.kind == "activity" and i.place_id not in protected and i.cost.amount > 0),
                  key=lambda x: -x[1])
    if paid:
        chosen_items, total = [], 0.0
        for item, cost in paid:
            chosen_items.append(item.title)
            total += cost
            if total >= gap:
                break
        n_acts = max(1, sum(d.activity_count for d in plan.days))
        out.append(Relaxation(kind="fewer_paid_tickets", label=f"Skip {len(chosen_items)} paid visit(s)",
                              saving=total, impact=", ".join(chosen_items[:4]),
                              degradation=0.6 * len(chosen_items) / n_acts,
                              relaxes=["interests"] if by_type(c, "interests") else [],
                              action={"action": "cheaper"}))
    # Fewer nights: what one night really costs in this plan (room + a day of spending).
    if c.nights > 1:
        per_night = (b.hotel / max(c.nights, 1)) + (b.food + b.activities + b.transport) / max(c.num_days, 1)
        k = math.ceil(gap / max(per_night, 1))
        if k < c.nights:
            out.append(Relaxation(kind="fewer_nights", label=f"Shorten the trip by {k} night(s)", saving=k * per_night,
                                  impact=f"{c.nights - k} nights instead of {c.nights}",
                                  degradation=k / c.nights, relaxes=[x.id for x in by_type(c, "dates")],
                                  action={"action": "shorten_trip", "amount": k}))
    # Raise the budget to what this plan really costs (rounded to a friendly amount).
    from .replanner import nice_amount

    out.append(Relaxation(kind="raise_budget", label=f"Raise the budget to {_money(nice_amount(b.total), cur)}",
                          saving=gap, impact="keeps this plan exactly as it is", degradation=0.0,
                          relaxes=[x.id for x in by_type(c, "budget_max")],
                          action={"action": "set_budget", "amount": nice_amount(b.total)}))
    # Other dates can be cheaper, but only a new search can say by how much: offered without a made-up number.
    out.append(Relaxation(kind="other_dates", label="Check other dates", saving=None,
                          impact="flights and hotels may be cheaper on other days - needs a new search",
                          degradation=0.1, relaxes=[x.id for x in by_type(c, "dates")]))
    return out


def _search(relax: list[Relaxation], gap: float, trip: TripState, cur: str, top: int = 4) -> list[Option]:
    for r in relax:
        r.penalty = _penalty(r, trip)
    candidates: list[list[Relaxation]] = [[r] for r in relax]
    combinable = [r for r in relax if r.kind in COMBINABLE and r.saving]
    for n in (2, 3):
        candidates += [list(c) for c in combinations(combinable, n)]
    options = []
    for steps in candidates:
        known = [s.saving for s in steps if s.saving is not None]
        saving = sum(known) if len(known) == len(steps) else None
        closes = saving is not None and saving >= gap - 0.5
        penalty = round(sum(s.penalty for s in steps), 3)
        summary = " + ".join(s.label for s in steps)
        if saving is not None:
            summary += f" (saves about {_money(saving, cur)})"
        options.append(Option(steps=steps, saving=saving, closes_gap=closes, penalty=penalty, summary=summary))
    closing = sorted((o for o in options if o.closes_gap), key=lambda o: (o.penalty, -(o.saving or 0)))
    # Prefer the smallest set of changes: drop combinations that a subset already achieves.
    minimal = []
    for o in closing:
        kinds = {s.kind for s in o.steps}
        if not any({s.kind for s in m.steps} <= kinds for m in minimal):
            minimal.append(o)
    chosen = minimal[:top]
    if len(chosen) < 2:
        # Few complete ways out: also show the biggest partial saving, honestly marked as not enough on its own.
        partial = max((o for o in options if not o.closes_gap and o.saving and o.saving > 0
                       and o.steps[0].kind != "raise_budget"), key=lambda o: o.saving, default=None)
        if partial:
            chosen.append(partial)
    unknown = [o for o in options if o.saving is None]
    return chosen + unknown[:1]


def analyze(trip: TripState) -> list[Conflict]:
    """Conflicts of the selected plan with the traveller's constraints, each with ranked ways out."""
    plan, c, r = trip.selected_plan, trip.trip_contract, trip.research
    if not plan or not c or not r:
        return []
    out: list[Conflict] = []
    budget = by_type(c, "budget_max")
    if budget and plan.budget and not plan.within_budget and not (trip.draft.find_cheapest and not trip.draft.budget_amount):
        cur = c.budget.currency.upper()
        gap = plan.budget.total - c.budget.amount
        relax = _budget_relaxations(trip, gap)
        out.append(Conflict(
            kind="budget", constraint_ids=[b.id for b in budget], gap=round(gap, 2), currency=cur,
            explanation=f"The {plan.mode} plan costs {_money(plan.budget.total, cur)}, {_money(gap, cur)} over the "
                        f"{budget[0].priority} budget of {_money(c.budget.amount, cur)}.",
            options=_search(relax, gap, trip, cur)))
    # Places the traveller firmly asked for that could not be scheduled.
    unmet = [name for name, day in plan.requested.items() if day is None
             and any(x.type == "must_visit" and str(x.value).lower() == name.lower() for x in c.constraints)]
    if unmet and plan.budget:
        b = plan.budget
        per_day = (b.hotel / max(c.nights, 1)) + (b.food + b.activities + b.transport) / max(c.num_days, 1)
        steps = [Relaxation(kind="extend_trip", label="Add a day to the trip", saving=-per_day,
                            impact=f"about {_money(per_day, b.currency)} more", degradation=0.0,
                            relaxes=[x.id for x in by_type(c, "dates")], action={"action": "extend_trip", "amount": 1}),
                 Relaxation(kind="lighter_elsewhere", label="Drop a lower-priority stop to make room", saving=0.0,
                            impact="one of the plan's own picks gives way", degradation=0.1,
                            action={"action": "increase_density"})]
        for s in steps:
            s.penalty = _penalty(s, trip)
        out.append(Conflict(
            kind="must_visit", constraint_ids=[f"visit:{n.lower()}" for n in unmet],
            explanation="Couldn't fit: " + ", ".join(unmet) + " (closed on your dates or no room left).",
            options=[Option(steps=[s], saving=s.saving, closes_gap=True, penalty=s.penalty, summary=s.label)
                     for s in sorted(steps, key=lambda s: s.penalty)]))
    return out


def facts(trip: TripState) -> list[dict[str, Any]]:
    """For the reply: each conflict with its ranked options (labels, savings, impact)."""
    return [{"conflict": x.explanation,
             "options_best_first": [{"option": o.summary, "impact": "; ".join(s.impact for s in o.steps if s.impact),
                                     "bends": sorted({cid for s in o.steps for cid in s.relaxes}),
                                     "closes_the_gap": o.closes_gap} for o in x.options]}
            for x in (Conflict.model_validate(c) for c in trip.metadata.get("conflicts", []))]
