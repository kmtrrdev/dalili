"""State updates: requirements -> profile/contract, feedback -> replan actions, plan diffs.

Replanning is targeted: each action changes specific profile fields, contract
fields or planner knobs, and reports which research domains became stale.
Activity assignments of unaffected days are pinned so they stay stable.
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta

from .engine.planner import plan_activity_ids
from .models import (
    Budget,
    FeedbackItem,
    RequirementDraft,
    TravelerProfile,
    TripContract,
    TripPlan,
    TripState,
)
from .nlu import Action, FeedbackNote, Requirements
from . import preferences
from .config import settings
from .journey import build_stops

STYLES = ["relaxed", "moderate", "active", "very_active"]
LEVELS = ["low", "medium", "high"]
RESEARCH_DOMAINS = {"flights", "hotels", "restaurants", "activities", "weather", "destination"}

# Facts about the traveller (not about one trip): remembered across trips once stated.
DURABLE_PREFERENCES = {"travel_style", "food_preferences", "dietary_restrictions", "activity_preferences",
                       "avoid_categories", "walking_tolerance", "transport_preference", "preferred_wake_up_time",
                       "hotel_style", "flight_preference", "avoid_early_flights", "nightlife_interest", "noise_tolerance",
                       "prefer_hidden_gems"}

LANDMARK_WORDS = {"landmarks", "landmark", "sights", "sightseeing", "attractions", "highlights", "must_see", "must-see",
                  "top sights", "famous places", "monuments"}

# Actions whose effect should be allowed to reshuffle every day's activities.
RESHUFFLE_ACTIONS = {"more_food", "more_category", "prefer_hidden_gems", "more_nightlife", "increase_density", "upgrade"}


# ---------------------------------------------------------------------------
# Requirements -> draft + profile
# ---------------------------------------------------------------------------


def apply_requirements(trip: TripState, req: Requirements) -> list[str]:
    """Merge newly extracted requirements into the draft and the profile. Returns change notes."""
    d, p = trip.draft, trip.traveler_profile
    notes: list[str] = []

    def setd(field: str, value) -> None:
        if value not in (None, [], ""):
            setattr(d, field, value)

    wanted = [x.strip() for x in req.destinations if x and x.strip()]
    proposed = [s.city.lower() for s in d.route_proposal.stops] if d.route_proposal else []
    if req.region and not wanted and not req.destination:
        if (d.region or "").lower() != req.region.lower():
            d.region = req.region
            d.destinations, d.destination_refs, d.destination, d.destination_ref = [], [], None, None
            d.route_proposal, d.route_confirmed, d.route_feedback, d.countries = None, False, [], []
    if len(wanted) >= 2:
        # Multi-city / multi-country journey, in visit order.
        if [w.lower() for w in wanted] == proposed and d.route_proposal:
            pass  # the model echoed the pending proposal: the traveller's decision is handled separately
        else:
            if [w.lower() for w in wanted] != [x.lower() for x in d.destinations]:
                d.destinations, d.destination_refs = wanted, []
                d.destination, d.destination_ref = wanted[0], None
                d.route_proposal, d.route_confirmed, d.route_feedback = None, False, []
            d.stop_nights = [int(n) for n in req.nights_per_destination if n] if len(req.nights_per_destination) == len(wanted) else []
    elif req.destination and req.destination.strip().lower() in (
            {x.lower() for x in d.destinations} | {r.name.lower() for r in d.destination_refs}):
        pass  # the model echoed one of the tour's cities: keep the journey
    elif req.destination and req.destination.strip().lower() in proposed:
        pass
    elif req.destination and req.destination.strip().lower() != (d.destination or "").lower():
        d.destination, d.destination_ref = req.destination.strip(), None  # resolved against real geocoding later
        d.destinations, d.destination_refs, d.stop_nights = [], [], []
        d.route_proposal, d.route_confirmed, d.route_feedback = None, False, []
    if req.origin_city and req.origin_city.strip().lower() != (d.origin_city or "").lower():
        d.origin_city, d.origin_ref = req.origin_city.strip(), None
    if req.return_to:
        back = req.return_to.strip()
        home = {(d.origin_city or "").lower(), (d.origin_ref.name.lower() if d.origin_ref else "")}
        if back.lower() in home:
            d.return_to, d.return_ref = None, None  # "back home" is the default, not an open-jaw trip
        elif back.lower() != (d.return_to or "").lower():
            d.return_to, d.return_ref = back, None  # resolved against real geocoding later
    if req.rooms and req.rooms > 0:
        d.rooms = int(req.rooms)
    setd("origin", req.origin_airport.upper() if req.origin_airport else None)
    if req.start_date:
        d.start_date = date.fromisoformat(req.start_date)
        if not req.end_date and not req.duration_days and d.duration_days:
            d.end_date = d.start_date + timedelta(days=d.duration_days - 1)
    if req.end_date:
        d.end_date = date.fromisoformat(req.end_date)
    if req.duration_days:
        d.duration_days = req.duration_days
        if d.start_date and not req.end_date:
            d.end_date = d.start_date + timedelta(days=req.duration_days - 1)
    setd("travelers", req.travelers)
    setd("budget_amount", req.budget_amount)
    setd("budget_currency", req.budget_currency)
    if req.wants_cheapest and not req.budget_amount:
        d.find_cheapest, d.planning_mode = True, "budget"
        d.budget_amount = None  # the planner finds it
    elif req.budget_amount:
        d.find_cheapest = False  # a real budget replaces "find the cheapest"
    if req.budget_is_hard_limit is not None:
        d.budget_hard_limit = req.budget_is_hard_limit
    d.must_have = sorted(set(d.must_have) | set(req.must_have))
    add_must_visit(trip, req.must_visit)
    d.avoid = sorted(set(d.avoid) | set(req.avoid))
    setd("planning_mode", req.planning_mode)

    explicit = set(p.explicit_fields)

    def setp(field: str, value) -> None:
        if value in (None, [], ""):
            return
        if isinstance(value, list):
            value = sorted(set(getattr(p, field)) | {v.lower() for v in value})
        setattr(p, field, value)
        explicit.add(field)
        if field in DURABLE_PREFERENCES:
            # Long-term memory: what the traveller says about themselves carries over to their next trips.
            preferences.state(p, field, value)

    setp("travel_style", req.travel_style)
    setp("food_preferences", req.food_preferences)
    setp("dietary_restrictions", req.dietary_restrictions)
    setp("activity_preferences", [a for a in req.activity_preferences if a not in req.avoid_categories])
    setp("avoid_categories", req.avoid_categories)
    setp("walking_tolerance", req.walking_tolerance)
    if req.transport_preference:
        # Routing already walks short hops and rides longer ones; the preference moves where that line is.
        setp("transport_preference", req.transport_preference)
        level = {"walk": "high", "mixed": "medium", "public_transport": "low", "taxi": "low"}[req.transport_preference]
        if not req.walking_tolerance:
            setp("walking_tolerance", level)
        trip.user_knobs.prefer_taxi = req.transport_preference == "taxi"
        notes.append({"walk": "Walking between sights wherever it's reasonable.",
                      "mixed": "Walking between nearby sights, public transport for the longer hops.",
                      "public_transport": "Public transport for anything beyond a short walk.",
                      "taxi": "Taxis for anything beyond a short walk."}[req.transport_preference])
    setp("preferred_wake_up_time", req.preferred_wake_up_time)
    setp("hotel_style", req.hotel_style)
    setp("hotel_rating_preference", req.min_hotel_stars)
    if req.direct_flights_only:
        setp("flight_preference", "direct")
    setp("avoid_early_flights", req.avoid_early_flights)
    setp("nightlife_interest", req.nightlife_interest)
    setp("noise_tolerance", req.noise_tolerance)
    setp("prefer_hidden_gems", req.prefer_hidden_gems)
    p.activity_preferences = [a for a in p.activity_preferences if a not in p.avoid_categories]
    p.explicit_fields = sorted(explicit)
    return notes


def add_must_visit(trip: TripState, names: list[str]) -> list[str]:
    """Remember places the traveller named; returns the ones that are new."""
    known = {x.lower() for x in trip.draft.must_visit}
    new = []
    for n in names:
        n = (n or "").strip()
        if n and n.lower() not in known:
            trip.draft.must_visit.append(n)
            known.add(n.lower())
            new.append(n)
    return new


FIND_CHEAPEST_PLACEHOLDER = 1e9  # "no limit" while the cheapest plan is being found


def nice_amount(x: float) -> float:
    """Round a found cost up to a friendly budget: 25,730 -> 26,000; 1,240 -> 1,250; 830 -> 830."""
    digits = len(str(int(max(x, 1))))
    step = max(1, 10 ** max(0, digits - 2) // 2)
    return float(math.ceil(x / step) * step)


REQUIRED_QUESTIONS = {
    "destination": "Where would you like to go? Any city with an airport works.",
    "dates": "When do you want to travel (start date and number of days, or exact dates)?",
    "budget": ("What's your total budget, and in which currency? Or tell me to find the cheapest possible trip and "
               "I'll work out the minimum for you."),
}


def missing_requirements(d: RequirementDraft) -> list[str]:
    missing = []
    if not d.destination and not d.region:
        missing.append("destination")
    if not d.start_date or not (d.end_date or d.duration_days):
        missing.append("dates")
    if not d.budget_amount and not d.find_cheapest:
        missing.append("budget")
    return missing


def build_contract(trip: TripState) -> tuple[TripContract, list[str]]:
    d, p = trip.draft, trip.traveler_profile
    assumptions = []
    end = d.end_date or (d.start_date + timedelta(days=(d.duration_days or 7) - 1))
    if end <= d.start_date:
        end = d.start_date + timedelta(days=1)
        assumptions.append("A trip needs at least one night, so I planned two days.")
    assert d.destination_ref is not None and d.origin_ref is not None
    origin_city = d.origin_ref.name
    origin = d.origin or (d.origin_ref.airports[0] if len(d.origin_ref.airports) == 1 else d.origin_ref.flight_id)
    back = d.return_ref
    return_to = (back.airports[0] if len(back.airports) == 1 else back.flight_id) if back else None
    if not d.origin_city:
        assumptions.append(f"I assumed you're flying from {origin_city} - tell me if you're leaving from somewhere else.")
    travelers = d.travelers or 1
    if not d.travelers:
        assumptions.append("I planned for 1 traveler - tell me if more people are coming.")
    currency = (d.budget_currency or "USD").upper()
    amount = float(d.budget_amount or 0)
    if not d.budget_amount and d.find_cheapest:
        # No budget given: the planner finds the cheapest good trip and sets the budget to its cost (workflow.plan).
        # Prices are shown in the traveller's home currency unless they named one.
        if not d.budget_currency and d.origin_ref and d.origin_ref.country_code:
            from babel.numbers import get_territory_currencies

            currency = (get_territory_currencies(d.origin_ref.country_code) or ["USD"])[0]
        amount = FIND_CHEAPEST_PLACEHOLDER
    stops = []
    if len(d.destination_refs) >= 2:
        stops, end, notes = build_stops(d.destination_refs, d.start_date, end, d.stop_nights or None)
        assumptions += notes
    contract = TripContract(
        origin=origin, origin_city=origin_city, origin_ref=d.origin_ref,
        return_to=return_to, return_city=back.name if back else None, return_ref=back, room_count=d.rooms,
        destination=d.destination_ref.name, destination_name=d.destination_ref.name, destination_ref=d.destination_ref,
        start_date=d.start_date, end_date=end, travelers=travelers,
        budget=Budget(amount=amount, currency=currency,
                      hard_limit=False if d.find_cheapest else (True if d.budget_hard_limit is None else d.budget_hard_limit)),
        must_have=d.must_have, avoid=d.avoid, travel_style=p.travel_style,
        planning_mode=d.planning_mode or "balanced", stops=stops,
    )
    if stops:
        contract.destination_name = contract.route_name
    return contract, assumptions


def contract_dirty_domains(old: TripContract | None, new: TripContract) -> set[str]:
    """Which research domains must be refreshed after a contract change."""
    if old is None or old.destination != new.destination or old.budget.currency != new.budget.currency:
        return set(RESEARCH_DOMAINS)
    if [s.name for s in old.stops] != [s.name for s in new.stops]:
        return set(RESEARCH_DOMAINS)
    if [(s.start_date, s.end_date) for s in old.stops] != [(s.start_date, s.end_date) for s in new.stops]:
        return {"flights", "hotels", "weather", "activities"}  # events depend on each city's dates
    dirty: set[str] = set()
    if (old.start_date, old.end_date, old.origin) != (new.start_date, new.end_date, new.origin):
        dirty |= {"flights", "hotels", "weather"}
    if old.travelers != new.travelers:
        dirty |= {"flights", "hotels"}
    if old.return_to != new.return_to:
        dirty |= {"flights"}  # a new last flight (open-jaw); the stay is unchanged
    if old.room_count != new.room_count:
        dirty |= {"hotels"}
    return dirty


# ---------------------------------------------------------------------------
# Feedback -> learning + actions
# ---------------------------------------------------------------------------


def learn_from_feedback(trip: TripState, notes: list[FeedbackNote], raw: str) -> None:
    """Store structured feedback and update learned preferences (explicit prefs always win)."""
    p = trip.traveler_profile
    plan = trip.selected_plan
    for n in notes:
        entity = None
        if n.feedback_type == "hotel" and plan and plan.hotel:
            entity = plan.hotel.id
        trip.feedback.append(FeedbackItem(feedback_type=n.feedback_type, entity_id=entity, sentiment=n.sentiment,
                                          attribute=n.attribute, severity=n.severity, raw_text=raw))
        key = None
        value = None
        if n.attribute == "noise" and n.sentiment == "negative":
            key, value = "noise_tolerance", "low"
        # (pace complaints are learned once, by apply_actions' reduce_density - not here a second time)
        elif n.attribute == "walking" and n.sentiment == "negative":
            key, value = "walking_tolerance", "low"
        if key:
            # Evidence, not a verdict: a severe complaint weighs a full observation, a mild one half.
            preferences.observe(p, key, value, raw, weight=0.5 + 0.5 * min(max(n.severity, 0.0), 1.0))
    preferences.apply(p)


def _all_flights(trip: TripState) -> list:
    r = trip.research
    if r is None:
        return []
    return r.flights_outbound + r.flights_return + [f for rt in r.round_trips for f in (rt.outbound, rt.inbound)]


def resolve_flights(trip: TripState, text: str) -> list:
    """The flights a choose_flight request means: an exact id, or flight numbers ("AZ 895 / AZ 894", "VF248").
    At most one per direction (the cheapest match); a round-trip leg brings its partner along."""
    pool = _all_flights(trip)
    exact = [f for f in pool if f.id == text.strip()]
    if exact:
        matches = exact
    else:
        wanted = re.sub(r"\s+", "", text.upper())
        matches = [f for f in pool if all(seg.replace(" ", "") in wanted for seg in f.flight_number.upper().split(" / "))]
    picked: dict[str, object] = {}
    for f in sorted(matches, key=lambda f: f.price_per_person.amount):
        picked.setdefault(f.direction, f)
    for rt in (trip.research.round_trips if trip.research else []):
        legs = {rt.outbound.id, rt.inbound.id}
        if any(f.id in legs for f in picked.values()):
            picked = {"outbound": rt.outbound, "return": rt.inbound}
    return list(picked.values())


def _count_category(plan: TripPlan | None, category: str, trip: TripState) -> int:
    if plan is None or trip.research is None:
        return 0
    n = 0
    for day in plan.days:
        for item in day.items:
            place = trip.research.place(item.place_id) if item.place_id else None
            if item.kind == "activity" and place and category in place.categories:
                n += 1
    return n


def apply_actions(trip: TripState, actions: list[Action], by_traveller: bool = True) -> tuple[set[str], list[str], bool]:
    """Apply replan actions. Returns (dirty research domains, notes, needs_replan).
    by_traveller=False (the critic's fixes): the plan changes, but nothing is learned about the traveller and no
    field is marked as their explicit choice."""
    p, k, c = trip.traveler_profile, trip.user_knobs, trip.trip_contract
    plan = trip.selected_plan
    dirty: set[str] = set()
    notes: list[str] = []
    needs_replan = False
    unpin_all = False
    unpin_days: set[int] = set()
    explicit = set(p.explicit_fields)

    for a in actions:
        name = a.action
        needs_replan = needs_replan or name != "select_mode"
        if name == "reduce_density":
            if a.day and plan:
                current = next((d.activity_count for d in plan.days if d.day == a.day), 2)
                k.day_capacity_override[a.day] = max(0, current - 1)
                unpin_days.add(a.day)
                notes.append(f"Lightened day {a.day}.")
            elif p.travel_style == "relaxed":
                k.density_delta -= 1  # already the slowest style: drop one more activity per day
                notes.append("Removed one activity per day.")
            else:
                p.travel_style = STYLES[STYLES.index(p.travel_style) - 1]  # type: ignore[assignment]
                explicit.add("travel_style")
                notes.append(f"Switched to a {p.travel_style.replace('_', ' ')} pace with fewer activities per day.")
                if by_traveller:
                    preferences.observe(p, "travel_style", p.travel_style, "asked for fewer activities")
        elif name == "increase_density":
            if a.day and plan:
                current = next((d.activity_count for d in plan.days if d.day == a.day), 2)
                k.day_capacity_override[a.day] = current + 2
                unpin_days.add(a.day)
                notes.append(f"Packed more into day {a.day}.")
            elif p.travel_style == "very_active":
                k.density_delta += 1  # already the fastest style: one more stop per day
                notes.append("Added more stops to every day.")
            else:
                p.travel_style = STYLES[min(len(STYLES) - 1, STYLES.index(p.travel_style) + 1)]  # type: ignore[assignment]
                notes.append(f"Switched to a {p.travel_style.replace('_', ' ')} pace with more sights per day.")
            explicit.add("travel_style")
            k.extra_rest = False
            unpin_all = True
            if by_traveller and not a.day:
                # Long-term memory: this traveller likes full days (inherited by their next trips).
                preferences.observe(p, "travel_style", p.travel_style, "asked for more activities")
        elif name == "more_free_time":
            k.extra_rest = True
            notes.append("Added more rest and free time.")
        elif name == "later_start":
            p.preferred_wake_up_time = a.text or "10:00"
            explicit.add("preferred_wake_up_time")
            notes.append(f"Days now start after {p.preferred_wake_up_time}.")
        elif name == "cheaper":
            k.price_pressure = min(3, k.price_pressure + 1)
            k.max_price_level = min(k.max_price_level, 3 if k.price_pressure == 1 else 2)
            notes.append("Looking for cheaper options across hotel, food and activities.")
        elif name == "upgrade":
            k.price_pressure = 0
            k.max_price_level = 4
            trip.selected_mode = "comfort"
            unpin_all = True
            notes.append("Upgraded towards the comfort plan.")
        elif name == "more_food":
            k.food_focus = True
            if "food" not in p.activity_preferences:
                p.activity_preferences.append("food")
            unpin_all = True
            notes.append("Added more food experiences, coffee and dessert stops.")
        elif name == "fewer_category" and a.category:
            current = _count_category(plan, a.category, trip)
            k.category_limits[a.category] = max(0, current - int(a.amount or 1))
            notes.append(f"Reduced {a.category} from {current} to {k.category_limits[a.category]}.")
        elif name == "more_category" and a.category and a.category.lower() in LANDMARK_WORDS:
            k.category_boost["must_see"] = k.category_boost.get("must_see", 0) + 0.4
            unpin_all = True
            notes.append("Prioritising the city's most famous landmarks.")
        elif name == "more_category" and a.category:
            k.category_boost[a.category] = k.category_boost.get(a.category, 0) + 0.35
            k.category_limits.pop(a.category, None)
            if a.category not in p.activity_preferences:
                p.activity_preferences.append(a.category)
            unpin_all = True
            notes.append(f"Added more {a.category}.")
        elif name == "avoid_noise":
            p.noise_tolerance = "low"
            explicit.add("noise_tolerance")
            if plan and plan.hotel and plan.hotel.noise_level == "noisy":
                k.hotel_exclude.append(plan.hotel.id)
                notes.append(f"Replacing {plan.hotel.name} with a quieter hotel.")
            else:
                notes.append("Will prefer quiet areas for hotels.")
        elif name == "change_hotel" and plan and plan.hotel:
            k.hotel_exclude.append(plan.hotel.id)
            notes.append(f"Looking for an alternative to {plan.hotel.name}.")
        elif name == "choose_flight" and a.text and trip.research:
            chosen = resolve_flights(trip, a.text)
            for f in chosen:
                # One pin per direction; a round-trip ticket pins both of its legs.
                same_dir = {x.id for x in _all_flights(trip) if x.direction == f.direction}
                k.flight_pins = [x for x in k.flight_pins if x not in same_dir] + [f.id]
                k.flight_exclude = [x for x in k.flight_exclude if x != f.id]
                notes.append(f"Switched to {f.airline} {f.flight_number} ({f.depart_at:%a %d %b %H:%M}).")
            if not chosen:
                notes.append("I couldn't find that flight among the options I researched.")
        elif name == "change_flight" and plan:
            k.flight_pins = []  # "a different flight": the planner picks again
            for f in (plan.outbound_flight, plan.return_flight):
                if f:
                    k.flight_exclude.append(f.id)
            notes.append("Looking for different flights.")
        elif name in ("extend_trip", "shorten_trip") and c:
            n = int(a.amount or 1)
            new_end = c.end_date + timedelta(days=n if name == "extend_trip" else -n)
            c.end_date = max(new_end, c.start_date + timedelta(days=1))
            trip.draft.end_date = c.end_date
            trip.draft.duration_days = c.num_days
            dirty |= {"flights", "hotels", "weather"}
            notes.append(f"Trip is now {c.num_days} days ({c.start_date:%b %d} - {c.end_date:%b %d}).")
        elif name == "set_budget" and c and a.amount:
            c.budget.amount = float(a.amount)
            trip.draft.budget_amount = c.budget.amount
            trip.draft.find_cheapest = False
            notes.append(f"Budget set to {c.budget.amount:,.0f} {c.budget.currency}.")
        elif name == "adjust_budget" and c and a.amount:
            c.budget.amount = max(0.0, c.budget.amount + float(a.amount))  # relative to the found budget, too
            trip.draft.budget_amount = c.budget.amount
            trip.draft.find_cheapest = False
            k.price_pressure = 0 if a.amount > 0 else k.price_pressure
            if a.amount > 0:
                k.max_price_level = 4
            notes.append(f"Budget is now {c.budget.amount:,.0f} {c.budget.currency}.")
        elif name == "less_walking":
            p.walking_tolerance = LEVELS[max(0, LEVELS.index(p.walking_tolerance) - 1)]  # type: ignore[assignment]
            explicit.add("walking_tolerance")
            notes.append(f"Walking tolerance set to {p.walking_tolerance}; longer hops use transport.")
        elif name == "more_nightlife":
            p.nightlife_interest = "high"
            explicit.add("nightlife_interest")
            unpin_all = True
            notes.append("Added evening plans.")
        elif name == "prefer_hidden_gems":
            p.prefer_hidden_gems = True
            explicit.add("prefer_hidden_gems")
            unpin_all = True
            notes.append("Favouring hidden gems over the busiest sights.")
        elif name == "add_place" and a.text:
            if a.day:  # "for dinner on day 1": remembered for restaurants (and as the preferred day)
                trip.metadata.setdefault("must_visit_day", {})[a.text] = a.day
            if add_must_visit(trip, [a.text]):
                notes.append(f"Adding {a.text} to your plan.")
            else:
                notes.append(f"{a.text} is already on your list.")
        elif name == "replace_item" and a.text:
            pid = a.text
            if trip.research and not trip.research.place(pid):
                match = [x for x in trip.research.attractions + trip.research.restaurants if x.name.lower() == pid.lower()]
                pid = match[0].id if match else pid
            k.exclude_ids.append(pid)
            trip.excluded_ids.append(pid)
            if pid in k.must_include or pid in k.meal_requests:  # they changed their mind about a place they asked for
                k.meal_requests.pop(pid, None)
                if pid in k.must_include:
                    k.must_include.remove(pid)
                resolved = trip.metadata.get("must_visit", {})  # keys are "<route>|<name as asked>"
                gone = {key.split("|", 1)[-1].lower() for key, i in resolved.items() if i == pid}
                trip.draft.must_visit = [n for n in trip.draft.must_visit if n.lower() not in gone]
            if plan:
                for d in plan.days:
                    if any(i.place_id == pid for i in d.items):
                        unpin_days.add(d.day)
            notes.append("Removed it and found a replacement.")
        elif name == "weather_adjust":
            dirty.add("weather")
            notes.append("Refreshed the forecast and re-checked outdoor plans.")
        elif name == "select_mode" and a.text in ("balanced", "budget", "comfort", "experience"):
            trip.selected_mode = a.text  # type: ignore[assignment]
            notes.append(f"Switched to the {a.text} plan.")
    if by_traveller:
        p.explicit_fields = sorted(explicit)

    # Stability: keep previous activity assignments unless the change needs a reshuffle.
    if plan and needs_replan:
        pins = plan_activity_ids(plan)
        if unpin_all or {x.action for x in actions} & RESHUFFLE_ACTIONS:
            pins = {}
        for d in unpin_days:
            pins.pop(d, None)
        trip.pinned_days = pins
    return dirty, notes, needs_replan


# ---------------------------------------------------------------------------
# Plan diff
# ---------------------------------------------------------------------------


def diff_plans(old: TripPlan | None, new: TripPlan | None) -> list[str]:
    if old is None or new is None:
        return []
    out: list[str] = []
    if old.hotel and new.hotel and old.hotel.id != new.hotel.id:
        out.append(f"Hotel: {old.hotel.name} -> {new.hotel.name}")
    for label, a, b in (("Outbound flight", old.outbound_flight, new.outbound_flight),
                        ("Return flight", old.return_flight, new.return_flight)):
        if a and b and a.id != b.id:
            out.append(f"{label}: {a.flight_number} -> {b.flight_number}")
    old_days = {d.day: d for d in old.days}
    for d in new.days:
        od = old_days.get(d.day)
        if od is None:
            out.append(f"Day {d.day}: new day added")
            continue
        before = [i.title for i in od.items if i.kind == "activity"]
        after = [i.title for i in d.items if i.kind == "activity"]
        removed = [x for x in before if x not in after]
        added = [x for x in after if x not in before]
        parts = []
        if removed:
            parts.append("removed " + ", ".join(removed))
        if added:
            parts.append("added " + ", ".join(added))
        first_old = next((i.start for i in od.items if i.kind in ("meal", "activity")), None)
        first_new = next((i.start for i in d.items if i.kind in ("meal", "activity")), None)
        if first_old and first_new and first_old != first_new and d.day not in (1, len(new.days)):
            parts.append(f"starts {first_new} instead of {first_old}")
        if parts:
            out.append(f"Day {d.day}: " + "; ".join(parts))
    for day in range(len(new.days) + 1, len(old.days) + 1):
        out.append(f"Day {day}: removed (shorter trip)")
    if old.budget and new.budget:
        delta = new.budget.total - old.budget.total
        if abs(delta) >= 1:
            out.append(f"Total cost {'+' if delta > 0 else '-'}{abs(delta):,.0f} {new.budget.currency} "
                       f"(now {new.budget.total:,.0f})")
    if old.score and new.score and old.score.total != new.score.total:
        out.append(f"TripScore {old.score.total} -> {new.score.total}")
    return out
