"""Repair strategies: turn validation failures into planner knob changes."""

from __future__ import annotations

from ..models import ResearchBundle, TravelerProfile, TripPlan, ValidationReport
from .knobs import PlanKnobs

BUDGET_LADDER = [
    "cheaper_restaurants",
    "cheaper_flights",
    "cheaper_hotel",
    "cap_activity_prices",
    "cheapest_transfers",
    "street_food",
    "fewer_paid_activities",
    "skip_snacks",
    "free_sights_only",
]
# Rungs that save money without taking anything the traveller would miss.
PAINLESS_STEPS = ("cheaper_flights", "cheaper_hotel", "cheaper_restaurants", "cheapest_transfers", "skip_snacks")
# Which rung to try first, given the largest cost component.
FIRST_RUNG = {"flights": "cheaper_flights", "hotel": "cheaper_hotel", "food": "cheaper_restaurants",
              "activities": "cap_activity_prices", "transport": "cheapest_transfers"}


def repair(plan: TripPlan, report: ValidationReport, knobs: PlanKnobs, research: ResearchBundle,
           iteration: int, profile: TravelerProfile | None = None) -> tuple[PlanKnobs, list[str]]:
    k = knobs.model_copy(deep=True)
    log: list[str] = []
    errors = report.errors
    checks = {v.check for v in errors}

    if "budget" in checks and plan.budget:
        over = plan.budget.total - plan.budget.limit
        # The further over budget, the more rungs we climb at once.
        rungs = 1 + int(over / max(plan.budget.limit, 1) / 0.06)
        hint = next((v.fix_hint for v in errors if v.check == "budget" and v.fix_hint), None)
        ladder = list(BUDGET_LADDER)
        if hint in FIRST_RUNG:
            ladder.remove(FIRST_RUNG[hint])
            ladder.insert(0, FIRST_RUNG[hint])
        floor = travel_floor(plan, research)
        b = plan.budget
        # What cutting the experience could save at most: every ticket, half the food, half the local transport.
        cuttable = b.activities + 0.5 * b.food + 0.5 * b.transport
        if (floor is not None and floor > b.limit) or b.total - cuttable > b.limit:
            # Stripping meals and sights would ruin the trip and still not fit (the gap is flights / hotel).
            # Keep the experience, trim only the painless extras, and say so.
            ladder = [s for s in ladder if s in PAINLESS_STEPS]
            marker = "floor_noted"
            if marker not in k.budget_steps:
                k.budget_steps.append(marker)
                if floor is not None and floor > b.limit:
                    log.append(f"Budget: the cheapest flights and hotel alone cost about {floor:,.0f} {b.currency}, "
                               f"more than the {b.limit:,.0f} budget - kept the sights instead of stripping the trip.")
                else:
                    log.append("Budget: the gap is in flights and hotel, so cutting sights or meals wouldn't close it - "
                               "kept the experience.")
        for step in ladder:
            if rungs <= 0:
                break
            if step in k.budget_steps and step not in ("cheaper_hotel", "cheaper_flights"):
                continue
            msg = _apply_budget_step(step, plan, k, research, profile)
            if msg:
                k.budget_steps.append(step)
                log.append(msg)
                rungs -= 1

    for v in errors:
        if v.check == "opening_hours" and v.place_id and v.day:
            k.exclude_on_day.setdefault(v.day, [])
            if v.place_id not in k.exclude_on_day[v.day]:
                k.exclude_on_day[v.day].append(v.place_id)
                log.append(f"Moved '{v.item_title}' off day {v.day} (closed at that time).")
        elif v.check == "schedule" and v.place_id and v.day:
            k.exclude_on_day.setdefault(v.day, []).append(v.place_id)
            log.append(f"Removed '{v.item_title}' from day {v.day} to fix a timing conflict.")
        elif v.check == "schedule" and v.day:
            k.day_capacity_override[v.day] = max(0, k.day_capacity_override.get(v.day, 2) - 1)
            log.append(f"Freed up time on day {v.day} to keep the schedule feasible.")
        elif v.check == "distance":
            if k.walk_tolerance_override != "low":
                k.walk_tolerance_override = "low"
                log.append("Switched long walks to public transport.")
            elif not k.prefer_taxi:
                k.prefer_taxi = True
                log.append("Using taxis for longer hops to cut walking.")
        elif v.check == "weather" and v.day and v.day not in k.avoid_outdoor_days:
            k.avoid_outdoor_days.append(v.day)
            log.append(f"Swapped outdoor plans on day {v.day} for indoor ones (rain forecast).")
        elif v.check == "energy" and v.day:
            k.day_capacity_override[v.day] = max(1, k.day_capacity_override.get(v.day, 3) - 1)
            log.append(f"Lightened day {v.day}.")
        elif v.check == "preferences" and v.place_id:
            if v.place_id.startswith("fl_"):
                k.flight_exclude.append(v.place_id)
                log.append("Replaced a flight that conflicts with your preferences.")
            elif v.place_id not in k.exclude_ids:
                k.exclude_ids.append(v.place_id)
                log.append("Removed an item that conflicts with your preferences.")
        elif v.check == "reality" and v.place_id and v.place_id not in k.exclude_ids:
            k.exclude_ids.append(v.place_id)
            log.append("Removed an ungrounded recommendation.")
    return k, [m for m in log if m]


def travel_floor(plan: TripPlan, research: ResearchBundle) -> float | None:
    """The least the trip can cost in the budget currency: cheapest outbound + return (or round-trip ticket) for
    everyone, plus the cheapest hotel for every night. None for multi-city trips or missing data."""
    b = plan.budget
    if b is None or plan.stops or not research.flights_outbound or not research.flights_return or not research.hotels:
        return None

    def user(m) -> float:
        return m.amount * (1.0 if m.currency.upper() == b.currency.upper() else research.fx_rates.get(m.currency.upper(), 1.0))

    one_ways = min(user(f.price_per_person) for f in research.flights_outbound) + \
        min(user(f.price_per_person) for f in research.flights_return)
    tickets = min([one_ways] + [user(rt.total_per_person) for rt in research.round_trips])
    travelers = max(1, round(b.flights / max(user(plan.outbound_flight.price_per_person) + user(plan.return_flight.price_per_person), 1))) \
        if plan.outbound_flight and plan.return_flight and b.flights else 1
    nights = max(1, len(plan.days) - 1)
    hotel = min(user(h.price_per_night) for h in research.hotels) * nights
    return tickets * travelers + hotel


def _apply_budget_step(step: str, plan: TripPlan, k: PlanKnobs, research: ResearchBundle,
                       profile: TravelerProfile | None) -> str:
    if step == "cheaper_restaurants":
        if k.max_price_level <= 2:
            return ""
        k.max_price_level = min(k.max_price_level, 2)
        k.price_pressure = max(k.price_pressure, 1)
        return "Budget: switched to more affordable restaurants."
    if step == "cap_activity_prices":
        paid = sorted(a.cost_per_person.amount for a in research.attractions if a.cost_per_person.amount > 0)
        if paid:
            cap = paid[int(len(paid) * 0.6)]
            k.activity_cost_cap_local = cap if k.activity_cost_cap_local is None else min(cap, k.activity_cost_cap_local)
        return "Budget: skipped the priciest tours and tickets."
    if step == "cheaper_hotel" and plan.hotel:
        price = plan.hotel.price_per_night.amount
        marker = f"hotel_tried:{plan.hotel.id}"
        if marker in k.budget_steps or not any(h.price_per_night.amount < price for h in research.hotels):
            return ""  # already tried from this hotel, or nothing cheaper exists
        k.budget_steps.append(marker)
        k.hotel_max_price_local = price * 0.85
        k.price_pressure = max(k.price_pressure, 2)
        return f"Budget: looking for a hotel cheaper than {plan.hotel.name}."
    if step == "cheaper_flights":
        changed = False
        for f in (plan.outbound_flight, plan.return_flight):
            if f is None:
                continue
            pool = research.flights_outbound if f.direction == "outbound" else research.flights_return
            # Same journey only: a multi-city pool also holds the other legs (a cheap domestic hop must
            # never count as a "cheaper alternative" to the international flight).
            pool = [x for x in pool if x.depart_at.date() == f.depart_at.date() and x.destination == f.destination]
            # Only drop the current flight if a cheaper one that respects the traveler's
            # preferences exists; otherwise we would cascade into early/connecting flights.
            acceptable = [x for x in pool if x.id not in k.flight_exclude and x.id != f.id
                          and (x.depart_at.hour >= 7 or f.depart_at.hour < 7)  # never trade into a red-eye to save money
                          and (profile is None or not profile.avoid_early_flights or x.depart_at.hour >= 8)
                          and (profile is None or profile.flight_preference != "direct" or x.stops == 0)]
            if any(x.price_per_person.amount < f.price_per_person.amount for x in acceptable):
                k.flight_exclude.append(f.id)
                changed = True
        if not changed:
            return ""
        k.price_pressure = max(k.price_pressure, 3)
        return "Budget: choosing cheaper flights."
    if step == "cheapest_transfers":
        if k.transfer_mode == "bus":
            return ""
        k.transfer_mode = "bus"
        return "Budget: cheapest airport transfers."
    if step == "street_food":
        k.max_price_level = 1
        return "Budget: casual, street-food level meals."
    if step == "fewer_paid_activities":
        k.density_delta -= 1
        return "Budget: one fewer paid activity per day."
    if step == "skip_snacks":
        k.skip_snacks = True
        return "Budget: dropped optional coffee and dessert stops."
    if step == "free_sights_only":
        k.activity_cost_cap_local = 0.0
        return "Budget: free sights only (must-have experiences kept)."
    return ""
