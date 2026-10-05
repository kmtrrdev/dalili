"""Deterministic validation layer.

Validators never trust the planner: they re-derive facts from the research
data (opening hours, prices, distances, forecasts) and check the plan against
the Trip Contract and the traveler profile. Only a PASS plan is final.
"""

from __future__ import annotations

from ..models import (
    CheckResult,
    ResearchBundle,
    TravelerProfile,
    TripContract,
    TripPlan,
    ValidationReport,
    Violation,
)
from ..providers.routing import WALK_LIMITS
from ..utils import is_open_for, to_min
from .budget import compute_budget
from .planner import AIRPORT_BEFORE_DEPARTURE, STYLE_CAPACITY, day_load
from .ranking import dietary_ok, expand_interests, must_have_terms


def _check(name: str, violations: list[Violation]) -> CheckResult:
    mine = [v for v in violations if v.check == name]
    status = "FAIL" if any(v.severity == "error" for v in mine) else ("WARN" if mine else "PASS")
    return CheckResult(name=name, status=status, messages=[v.message for v in mine])  # type: ignore[arg-type]


def validate_budget(plan: TripPlan, contract: TripContract, research: ResearchBundle, buffer_ratio: float) -> list[Violation]:
    out = []
    recomputed = compute_budget(plan.model_copy(deep=True), contract, research.fx_rates, buffer_ratio)
    if plan.budget is None or abs(recomputed.total - plan.budget.total) > max(1.0, 0.01 * recomputed.total):
        out.append(Violation(check="budget", severity="error", message="Budget total does not match its line items."))
    over = recomputed.total - contract.budget.amount
    if over > 0:
        sev = "error" if contract.budget.hard_limit else "warning"
        parts = {k: getattr(recomputed, k) for k in ("flights", "hotel", "food", "activities", "transport")}
        biggest = max(parts, key=parts.get)  # type: ignore[arg-type]
        out.append(Violation(check="budget", severity=sev,
                             message=f"Over budget by {over:,.0f} {contract.budget.currency} (largest component: {biggest}).",
                             fix_hint=biggest))
    if plan.outbound_flight is None or plan.return_flight is None or plan.hotel is None:
        out.append(Violation(check="budget", severity="error", message="Plan is missing flights or a hotel, so cost is incomplete."))
    return out


def validate_schedule(plan: TripPlan, contract: TripContract, profile: TravelerProfile) -> list[Violation]:
    out = []
    wake = to_min(profile.preferred_wake_up_time)
    for day in plan.days:
        prev_end = None
        for idx, item in enumerate(day.items):
            s, e = to_min(item.start), to_min(item.end)
            if item.kind != "flight" and e < s:
                out.append(Violation(check="schedule", severity="error", day=day.day, item_title=item.title,
                                     message=f"Day {day.day}: '{item.title}' ends before it starts."))
            if prev_end is not None:
                # A transfer item *is* the journey, so its travel time is inside the item.
                leg = item.transport_from_previous
                travel = leg.minutes if leg and item.kind != "transfer" else 0
                if s + 2 < prev_end + travel:
                    out.append(Violation(check="schedule", severity="error", day=day.day, item_title=item.title,
                                         place_id=item.place_id,
                                         message=f"Day {day.day}: '{item.title}' at {item.start} overlaps the previous item "
                                                 f"(ends {prev_end // 60:02d}:{prev_end % 60:02d} + {travel} min travel)."))
            if item.kind != "flight":
                prev_end = max(prev_end or 0, e)
            elif idx == 0:
                prev_end = e
            if (0 < day.day < contract.num_days and day.day != 1 and item.kind in ("activity", "meal")
                    and s < wake - 5):
                out.append(Violation(check="schedule", severity="error", day=day.day, item_title=item.title,
                                     message=f"Day {day.day}: '{item.title}' starts at {item.start}, before your wake-up time "
                                             f"{profile.preferred_wake_up_time}."))
        # Every full day must feed the traveler (a food tour / cooking class counts as lunch).
        if 1 < day.day < contract.num_days and not day.travel_day:
            meals = {i.meal_type for i in day.items if i.kind == "meal"}
            food_exp = any(i.kind == "activity" and "Lunch is part" in i.notes for i in day.items)
            for m in ("lunch", "dinner"):
                if m not in meals and not (m == "lunch" and food_exp):
                    out.append(Violation(check="schedule", severity="error", day=day.day,
                                         message=f"Day {day.day} has no {m} planned."))
        # Departure: at the airport early enough.
        flights = [i for i in day.items if i.kind == "flight"]
        transfers = [i for i in day.items if i.kind == "transfer" and "airport" in i.title.lower()]
        if day.day == contract.num_days and flights and transfers:
            if to_min(flights[-1].start) - to_min(transfers[-1].end) < AIRPORT_BEFORE_DEPARTURE - 10:
                out.append(Violation(check="schedule", severity="error", day=day.day,
                                     message=f"Day {day.day}: arriving at the airport less than "
                                             f"{AIRPORT_BEFORE_DEPARTURE // 60}h30 before departure."))
    return out


def validate_distance(plan: TripPlan, profile: TravelerProfile, tolerance: str | None = None) -> list[Violation]:
    out = []
    max_leg, max_day = WALK_LIMITS[tolerance or profile.walking_tolerance]
    for day in plan.days:
        for item in day.items:
            leg = item.transport_from_previous
            if leg and leg.mode == "walk" and leg.distance_km > max_leg + 0.3:
                out.append(Violation(check="distance", severity="error", day=day.day, item_title=item.title,
                                     message=f"Day {day.day}: {leg.distance_km:.1f} km walk to '{item.title}' exceeds your "
                                             f"{max_leg:.1f} km comfort limit."))
        if day.walking_km > max_day * 1.3:
            out.append(Violation(check="distance", severity="error", day=day.day,
                                 message=f"Day {day.day}: {day.walking_km:.1f} km of walking is far above your {max_day:.0f} km/day."))
        elif day.walking_km > max_day:
            out.append(Violation(check="distance", severity="warning", day=day.day,
                                 message=f"Day {day.day}: {day.walking_km:.1f} km of walking is above your {max_day:.0f} km/day."))
    return out


def validate_opening_hours(plan: TripPlan, research: ResearchBundle) -> list[Violation]:
    out = []
    unverified: set[str] = set()
    for day in plan.days:
        for item in day.items:
            if not item.place_id:
                continue
            place = research.place(item.place_id)
            if place is None:
                continue  # reported by the reality check
            if place.dates and day.date not in place.dates:
                out.append(Violation(check="opening_hours", severity="error", day=day.day, item_title=item.title,
                                     place_id=item.place_id,
                                     message=f"Day {day.day}: {place.name} does not take place on {day.date:%a %d %b}."))
            elif not is_open_for(place.opening_hours, day.date, to_min(item.start), to_min(item.end)):
                out.append(Violation(check="opening_hours", severity="error" if place.hours_verified else "warning",
                                     day=day.day, item_title=item.title, place_id=item.place_id,
                                     message=f"Day {day.day}: {place.name} is not open {item.start}-{item.end} on "
                                             f"{day.date:%A}" + ("." if place.hours_verified else " (assumed hours).")))
            elif not place.hours_verified:
                unverified.add(place.name)
    if unverified:
        out.append(Violation(check="opening_hours", severity="warning",
                             message=f"Hours not published for {len(unverified)} place(s) ({', '.join(sorted(unverified)[:4])}"
                                     f"{'...' if len(unverified) > 4 else ''}); typical hours were assumed - check before going."))
    return out


def validate_preferences(plan: TripPlan, contract: TripContract, profile: TravelerProfile,
                         research: ResearchBundle) -> list[Violation]:
    out = []
    avoid = {c.lower() for c in profile.avoid_categories}
    covered: set[str] = set()
    for day in plan.days:
        for item in day.items:
            place = research.place(item.place_id) if item.place_id else None
            if place is None:
                continue
            covered |= expand_interests(place.categories)
            if item.kind == "meal" and not dietary_ok(place, profile):
                out.append(Violation(check="preferences", severity="error", day=day.day, place_id=place.id,
                                     message=f"Day {day.day}: {place.name} may not suit your dietary needs "
                                             f"({', '.join(profile.dietary_restrictions)})."))
            hit = set(place.categories) & avoid
            if item.kind == "activity" and hit:
                out.append(Violation(check="preferences", severity="error", day=day.day, place_id=place.id,
                                     message=f"Day {day.day}: {place.name} is in a category you want to avoid ({', '.join(hit)})."))
    for f in (plan.outbound_flight, plan.return_flight):
        if f is None:
            continue
        pool = research.flights_outbound if f.direction == "outbound" else research.flights_return
        if profile.avoid_early_flights and f.depart_at.hour < 8:
            has_alt = any(x.depart_at.hour >= 8 for x in pool)
            out.append(Violation(check="preferences", severity="error" if has_alt else "warning",
                                 message=f"{f.flight_number} departs at {f.depart_at:%H:%M}, but you prefer no early flights.",
                                 place_id=f.id))
        if profile.flight_preference == "direct" and f.stops > 0 and any(x.stops == 0 for x in pool):
            out.append(Violation(check="preferences", severity="warning",
                                 message=f"{f.flight_number} has a connection although direct flights exist."))
    if plan.hotel and profile.noise_tolerance == "low" and plan.hotel.noise_level == "noisy":
        out.append(Violation(check="preferences", severity="warning",
                             message=f"{plan.hotel.name} is in a lively area; you prefer quiet.", place_id=plan.hotel.id))
    for name, day in plan.requested.items():
        if day is None:
            out.append(Violation(check="preferences", severity="warning",
                                 message=f"Couldn't fit '{name}' into the schedule (opening hours, distance or a full day) - "
                                         "try freeing a day or extending the trip."))
    missing = must_have_terms(contract) - covered
    if missing:
        out.append(Violation(check="preferences", severity="warning",
                             message="Must-have not covered yet: " + ", ".join(sorted(missing))))
    # Restrictions the data can't confirm (only vegetarian / vegan are tagged by the providers): never passed
    # silently - each meal place that doesn't list it is named so the traveller can check.
    unverifiable = [d for d in profile.dietary_restrictions if d.lower() not in ("vegetarian", "vegan")]
    for d in unverifiable:
        places = sorted({p.name for day in plan.days for i in day.items if i.kind == "meal" and i.place_id
                         and (p := research.place(i.place_id)) and d.lower() not in {x.lower() for x in p.dietary}})
        if places:
            out.append(Violation(check="preferences", severity="warning",
                                 message=f"{d.title()} options couldn't be verified for: " + ", ".join(places[:6]) +
                                         " - please check with the restaurant."))
    return out


def validate_freshness(plan: TripPlan) -> list[Violation]:
    """Prices the plan rests on that are old or came from an expired cache (the provider was unavailable)."""
    from datetime import datetime, timezone

    out = []
    now = datetime.now(timezone.utc)
    for label, x in [("hotel", plan.hotel)] + [("hotel", s.hotel) for s in plan.stops] + \
            [("flight", f) for f in [plan.outbound_flight, plan.return_flight] + list(plan.legs)]:
        if x is None:
            continue
        age_h = (now - x.metadata.retrieved_at).total_seconds() / 3600
        name = getattr(x, "name", None) or getattr(x, "flight_number", "")
        if x.metadata.stale:
            out.append(Violation(check="freshness", severity="warning",
                                 message=f"The {label} price for {name} comes from an earlier search (the provider was "
                                         "unavailable) - check it before booking."))
        elif age_h > 48:
            out.append(Violation(check="freshness", severity="warning",
                                 message=f"The {label} price for {name} was found {age_h / 24:.0f} days ago - prices "
                                         "may have changed."))
    return list({v.message: v for v in out}.values())  # one line per item (a multi-city hotel may repeat)


def validate_energy(plan: TripPlan, profile: TravelerProfile) -> list[Violation]:
    """Each day is checked against the capacity the planner agreed for it (pace, mode, the traveller's own "pack more
    into day 2"), so a day the traveller filled on purpose is never flagged and then emptied again by repair."""
    out = []
    count, minutes, _ = STYLE_CAPACITY[profile.travel_style]
    for day in plan.days:
        acts = [i for i in day.items if i.kind == "activity"]
        if day_load([to_min(i.end) - to_min(i.start) for i in acts]) > max(count, day.capacity or 0) + 1:
            out.append(Violation(check="energy", severity="error", day=day.day,
                                 message=f"Day {day.day}: {len(acts)} activities is too dense for a {profile.travel_style} pace."))
        busy = sum(to_min(i.end) - to_min(i.start) for i in acts)
        if busy > minutes * 1.2 + 60:
            out.append(Violation(check="energy", severity="warning", day=day.day,
                                 message=f"Day {day.day}: {busy // 60}h{busy % 60:02d} of sightseeing is a long day."))
        ground = [i for i in day.items if i.kind != "flight"]
        if profile.travel_style == "relaxed" and ground and to_min(ground[-1].end) > 23 * 60 + 15:
            out.append(Violation(check="energy", severity="warning", day=day.day,
                                 message=f"Day {day.day} ends late for a relaxed pace."))
    return out


def validate_weather(plan: TripPlan, research: ResearchBundle) -> list[Violation]:
    out = []
    indoor_exists = any(a.indoor for a in research.attractions)
    for day in plan.days:
        w = day.weather
        if not w or w.risk != "high":
            continue
        for item in day.items:
            if item.kind == "activity" and item.indoor is False:
                reliable = w.metadata.confidence >= 0.6
                out.append(Violation(check="weather", severity="error" if (reliable and indoor_exists) else "warning",
                                     day=day.day, item_title=item.title, place_id=item.place_id,
                                     message=f"Day {day.day}: outdoor '{item.title}' during forecast {w.condition.lower()} "
                                             f"({w.precipitation_probability}%)."))
    return out


def validate_reality(plan: TripPlan, research: ResearchBundle) -> list[Violation]:
    """Grounding: every recommended entity must come from a tool result with provenance."""
    out = []
    hotel_ids = {h.id for h in research.hotels}
    flight_ids = {f.id for f in research.flights_outbound + research.flights_return}
    flight_ids |= {f.id for rt in research.round_trips for f in (rt.outbound, rt.inbound)}
    # Every city's hotel on a multi-city journey, not only the first one.
    for h in {h.id: h for h in [plan.hotel] + [s.hotel for s in plan.stops] if h}.values():
        if h.id not in hotel_ids:
            out.append(Violation(check="reality", severity="error", message=f"Hotel {h.name} is not in the research data."))
    for f in {f.id: f for f in [plan.outbound_flight, plan.return_flight] + list(plan.legs) if f}.values():
        if f and f.id not in flight_ids:
            out.append(Violation(check="reality", severity="error", message=f"Flight {f.flight_number} is not in the research data."))
    for day in plan.days:
        for item in day.items:
            if item.place_id:
                place = research.place(item.place_id)
                if place is None:
                    out.append(Violation(check="reality", severity="error", day=day.day, place_id=item.place_id,
                                         message=f"Day {day.day}: '{item.title}' is not backed by any tool result."))
                elif not place.metadata.source:
                    out.append(Violation(check="reality", severity="error", day=day.day, place_id=item.place_id,
                                         message=f"Day {day.day}: '{item.title}' has no source metadata."))
    return out


CHECK_ORDER = ["budget", "schedule", "distance", "opening_hours", "preferences", "energy", "weather", "reality",
               "freshness"]


def validate_plan(plan: TripPlan, contract: TripContract, profile: TravelerProfile, research: ResearchBundle,
                  buffer_ratio: float, walking_tolerance: str | None = None) -> ValidationReport:
    violations = (
        validate_budget(plan, contract, research, buffer_ratio)
        + validate_schedule(plan, contract, profile)
        + validate_distance(plan, profile, walking_tolerance)
        + validate_opening_hours(plan, research)
        + validate_preferences(plan, contract, profile, research)
        + validate_energy(plan, profile)
        + validate_weather(plan, research)
        + validate_reality(plan, research)
        + validate_freshness(plan)
    )
    checks = [_check(name, violations) for name in CHECK_ORDER]
    result = "FAIL" if any(v.severity == "error" for v in violations) else "PASS"
    return ValidationReport(result=result, checks=checks, violations=violations)  # type: ignore[arg-type]
