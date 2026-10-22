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
    PLANNING_MODES,
    Budget,
    FeedbackItem,
    RequirementDraft,
    TripContract,
    TripPlan,
    TripState,
)
from .nlu import Action, FeedbackNote, Requirements, RouteStop
from . import preferences
from .journey import build_stops
from .providers.geo import country_code
from .utils import matches_ref, place_key, same_place

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


def names_place(text: str | None, name: str | None, ref=None) -> bool:
    """Does `text` (as the model wrote it: 'City', 'City, Country' or a country) name this place of the trip? Once
    the place is resolved, a stated country must agree ('Bali, Indonesia' is not the Bali in Taiwan), and a country
    alone names it when it is that place's country (an echoed 'Italy' on a trip to Rome)."""
    if not (text or "").strip():
        return False
    if ref is not None:
        cc = country_code(text)
        if matches_ref(text, ref) or (cc is not None and cc == (ref.country_code or "").upper()):
            return True
        # The draft's own words for it ("Sharm El Sheikh, Egypt" resolved as "Sharm el-Sheikh"), unless they now
        # state another country.
        parts = [x.strip() for x in text.split(",")]
        stated = country_code(parts[-1]) if len(parts) > 1 else None
        return same_place(text, name) and stated in (None, (ref.country_code or "").upper())
    return same_place(text, name)


def _forget_route_places(trip: TripState, keep: bool) -> None:
    """A new set of places: sights named for the old one belong to it ("the Colosseum" is not in Istanbul) unless
    some places stay (`keep`), and the expert review's picks always belong to the plan it reviewed."""
    d = trip.draft
    expert = {n.lower() for n in trip.metadata.pop("expert_added", [])}
    if not keep:
        d.must_visit, d.wish_list = [], []
        trip.metadata.pop("must_visit_day", None)
    d.must_visit = [n for n in d.must_visit if n.lower() not in expert]


def set_route(trip: TripState, stops: list[RouteStop]) -> bool:
    """The traveller said exactly which places the trip covers ("only Bali", "drop Taipei", "Rome 3 nights then
    Florence 2"). The draft takes that list as it is and any route proposal or redesign is closed - a country in the
    list still gets its cities designed with the traveller. Returns False when nothing changes."""
    d, c = trip.draft, trip.trip_contract
    wanted = [(s.place.strip(), s.nights if s.nights and s.nights > 0 else None) for s in stops if (s.place or "").strip()]
    if not wanted:
        return False
    pending = d.route_proposal if d.route_proposal and d.route_proposal.stops and not d.route_confirmed else None
    known = [r for r in (list(d.destination_refs) + [d.destination_ref] + [s.ref for s in (pending.stops if pending else [])]
                         + ([s.ref for s in c.stops] + [c.destination_ref] if c else [])) if r is not None]
    refs = [next((r for r in known if names_place(text, None, r) and not country_code(text)), None) for text, _ in wanted]
    nights = [n for _, n in wanted]
    if c and not pending and not d.redesign:
        current = [s.ref for s in c.stops] if c.stops else [c.destination_ref]
        cur_nights = [s.nights for s in c.stops] if c.stops else [c.nights]
        if len(current) == len(wanted) and all(r is not None and _place_id(r) == _place_id(x) for r, x in zip(refs, current)) \
                and all(n is None or n == m for n, m in zip(nights, cur_nights)):
            return False  # the same route, said again
    before = {place_key(r.name) for r in known} | {place_key(x) for x in d.destinations + [d.destination or ""] if x}
    if before or d.region:
        # Places named before any destination was given ("I want to see Hagia Sophia") are kept.
        _forget_route_places(trip, keep=bool(before & {place_key(t) for t, _ in wanted}))
    d.route_proposal, d.route_feedback, d.redesign, d.region = None, [], False, None
    d.countries = [t for t, _ in wanted if country_code(t)]
    d.route_confirmed = not d.countries
    if len(wanted) == 1:
        d.destination, d.destination_ref = wanted[0][0], refs[0]
        d.destinations, d.destination_refs, d.stop_nights = [], [], []
    else:
        d.destinations = [t for t, _ in wanted]
        d.destination_refs = list(refs) if all(refs) else []
        d.destination, d.destination_ref = wanted[0][0], (refs[0] if all(refs) else None)
        d.stop_nights = list(nights) if all(nights) else []
    if all(nights):
        d.duration_days = sum(nights) + 1  # kept for a start date that comes later
        d.end_date = d.start_date + timedelta(days=sum(nights)) if d.start_date else None
    return True


def apply_requirements(trip: TripState, req: Requirements) -> list[str]:
    """Merge newly extracted requirements into the draft and the profile. Returns change notes."""
    d, p = trip.draft, trip.traveler_profile
    notes: list[str] = []

    def setd(field: str, value) -> None:
        if value not in (None, [], ""):
            setattr(d, field, value)

    wanted = [x.strip() for x in req.destinations if x and x.strip()]
    proposal = d.route_proposal.stops if d.route_proposal else []
    proposed = [place_key(s.city) for s in proposal]
    had_route = bool(d.destination or d.destinations or d.region)

    def new_route() -> None:
        # This message's own must-visit / wish places are added below. Places named before any destination was given
        # are kept.
        if had_route:
            _forget_route_places(trip, keep=False)

    def in_tour(text: str) -> bool:
        return any(same_place(text, x) for x in d.destinations) or any(names_place(text, r.name, r) for r in d.destination_refs)

    if req.region and not wanted and not req.destination:
        if (d.region or "").lower() != req.region.lower():
            d.region = req.region
            d.destinations, d.destination_refs, d.destination, d.destination_ref = [], [], None, None
            d.route_proposal, d.route_confirmed, d.route_feedback, d.countries = None, False, [], []
            new_route()
    if len(wanted) >= 2:
        # Multi-city / multi-country journey, in visit order.
        if [place_key(w) for w in wanted] == proposed and d.route_proposal:
            pass  # the model echoed the pending proposal: the traveller's decision is handled separately
        else:
            changed = [place_key(w) for w in wanted] != [place_key(x) for x in d.destinations]
            if changed:
                d.destinations, d.destination_refs = wanted, []
                d.destination, d.destination_ref = wanted[0], None
                d.route_proposal, d.route_confirmed, d.route_feedback = None, False, []
                d.stop_nights = []  # the old split belongs to the old city list
                new_route()
            if len(req.nights_per_destination) == len(wanted):
                d.stop_nights = [int(n) for n in req.nights_per_destination if n]
    elif req.destination and in_tour(req.destination):
        pass  # the model echoed one of the tour's cities: keep the journey
    elif req.destination and any(names_place(req.destination, s.city, s.ref) for s in proposal):
        pass  # one of the proposed cities ("more nights in Rome"): the answer to the proposal is handled separately
    elif req.destination and not names_place(req.destination, d.destination, d.destination_ref):
        # A new place - or the same name in another country ("Bali, Indonesia" when Bali resolved to Taiwan).
        d.destination, d.destination_ref = req.destination.strip(), None  # resolved against real geocoding later
        d.destinations, d.destination_refs, d.stop_nights = [], [], []
        d.route_proposal, d.route_confirmed, d.route_feedback = None, False, []
        new_route()
    if req.origin_city and not names_place(req.origin_city, d.origin_city, d.origin_ref):
        d.origin_city, d.origin_ref = req.origin_city.strip(), None
        d.origin = None  # the old city's airport must not survive a new city (set below when one was named)
    elif req.origin_city and not d.origin_city:
        d.origin_city = req.origin_city.strip()  # the assumed home city, now stated
    if req.return_to:
        back = req.return_to.strip()
        if names_place(back, d.origin_city, d.origin_ref) and not country_code(back):
            d.return_to, d.return_ref = None, None  # "back home" is the default, not an open-jaw trip
        elif not names_place(back, d.return_to, d.return_ref):
            d.return_to, d.return_ref = back, None  # resolved against real geocoding later
    if req.rooms and req.rooms > 0:
        d.rooms = int(req.rooms)
    setd("origin", req.origin_airport.upper() if req.origin_airport else None)
    if req.nights and req.nights > 0:
        # Stated in nights ("3 nights"): the code does the arithmetic - N nights = N + 1 days, and it overrides an
        # echoed old end date (the length is what the traveller just said).
        req.duration_days, req.end_date = int(req.nights) + 1, None
    if req.travel_month and not req.start_date and not (d.start_date and d.start_date.month == req.travel_month):
        # "Rome in November": a concrete start date (mid-month), stated as an assumption the traveller can correct.
        from .nlu import _next_date
        from .config import today

        req.start_date = _next_date(req.travel_month, 10, today()).isoformat()
        notes.append(f"No exact dates given, so I started the trip on {date.fromisoformat(req.start_date):%d %B} - "
                     "tell me if you prefer other days.")
    # The trip's current length (what was planned, else what was said), kept when only the start moves.
    c = trip.trip_contract
    length = c.num_days if c else ((d.end_date - d.start_date).days + 1 if d.start_date and d.end_date
                                   else d.duration_days)
    if req.start_date:
        d.start_date = date.fromisoformat(req.start_date)
        if not req.end_date and not req.duration_days and length:
            d.end_date = d.start_date + timedelta(days=length - 1)
    if req.end_date:
        d.end_date = date.fromisoformat(req.end_date)
    if req.duration_days:
        d.duration_days = req.duration_days
        if d.start_date and not req.end_date:
            d.end_date = d.start_date + timedelta(days=req.duration_days - 1)
    elif d.start_date and d.end_date:
        d.duration_days = (d.end_date - d.start_date).days + 1  # never left stale next to explicit dates
    if (req.duration_days or req.end_date) and len(d.destinations) >= 2 and d.stop_nights \
            and d.start_date and d.end_date and not req.nights_per_destination:
        # A tour that got longer or shorter: the extra nights go to the last city, removed ones come off the
        # longest stays (each city keeps at least one night) - the cities' split is never silently reset.
        d.stop_nights = resize_nights(d.stop_nights, (d.end_date - d.start_date).days)
    if req.arrive_on_start is not None:
        d.arrive_by = d.start_date if req.arrive_on_start else None
    elif d.arrive_by and d.start_date and d.start_date != d.arrive_by and d.start_date != d.arrive_by - timedelta(days=1):
        # The trip moved: the arrival day moves with it - unless they now leave the day before, to land on time.
        d.arrive_by = d.start_date
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
    firm = {x.lower() for x in d.must_visit}
    for name in req.wish_list:  # softly mentioned places: planned when they fit, never forced
        if name.strip() and name.lower() not in firm and name.lower() not in {w.lower() for w in d.wish_list}:
            d.wish_list.append(name.strip())
    if req.priorities:
        d.priorities = list(dict.fromkeys(req.priorities))
    d.avoid = sorted(set(d.avoid) | set(req.avoid))
    setd("planning_mode", req.planning_mode)
    # Evidence for every requirement this message set (shown when explaining a constraint or a choice).
    said = next((m.content for m in reversed(trip.conversation) if m.role == "user"), "")[:200]
    if said:
        for field, value in req.model_dump(exclude_none=True).items():
            if value not in ([], "", False):
                d.stated[field] = said

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


def resize_nights(nights: list[int], total: int) -> list[int]:
    """A tour's nights per city after the trip got longer or shorter: extra nights go to the last city, removed
    ones come off the longest stays first, and every city keeps at least one night."""
    out = list(nights)
    total = max(total, len(out))
    while sum(out) < total:
        out[-1] += 1
    while sum(out) > total:
        i = max(range(len(out)), key=lambda j: (out[j], j))
        out[i] -= 1
    return out


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


def _home_currency(d: RequirementDraft) -> str | None:
    """The currency of the country the traveller flies from (EGP for Cairo). For a stated budget only when they said
    where they fly from; "the cheapest trip" is always priced in the home currency."""
    if not (d.origin_city or d.origin or d.find_cheapest) or not (d.origin_ref and d.origin_ref.country_code):
        return None
    from babel.numbers import get_territory_currencies

    return (get_territory_currencies(d.origin_ref.country_code) or [None])[0]


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
    # The currency the traveller named, else the one this trip already uses, else their home country's.
    currency = (d.budget_currency or (trip.trip_contract.budget.currency if trip.trip_contract else None)
                or trip.metadata.get("home_currency") or _home_currency(d) or "USD").upper()
    if not d.budget_currency:
        d.budget_currency = currency  # kept, so a later change never flips it back silently
        if d.budget_amount:
            assumptions.append(f"I assumed your budget is in {currency} - tell me if you meant another currency.")
    amount = float(d.budget_amount or 0)
    if not d.budget_amount and d.find_cheapest:
        # No budget given: the planner finds the cheapest good trip and sets the budget to its cost (workflow.plan).
        amount = FIND_CHEAPEST_PLACEHOLDER
    stops = []
    if len(d.destination_refs) >= 2:
        stops, end, notes = build_stops(d.destination_refs, d.start_date, end, d.stop_nights or None)
        assumptions += notes
    contract = TripContract(
        origin=origin, origin_city=origin_city, origin_ref=d.origin_ref,
        return_to=return_to, return_city=back.name if back else None, return_ref=back, room_count=d.rooms,
        destination=d.destination_ref.name, destination_name=d.destination_ref.name, destination_ref=d.destination_ref,
        start_date=d.start_date, end_date=end, arrive_by=d.arrive_by,
        travelers=travelers,
        budget=Budget(amount=amount, currency=currency,
                      hard_limit=False if d.find_cheapest else (True if d.budget_hard_limit is None else d.budget_hard_limit)),
        must_have=d.must_have, avoid=d.avoid, travel_style=p.travel_style,
        planning_mode=d.planning_mode or "balanced", stops=stops,
    )
    if stops:
        contract.destination_name = contract.route_name
    from .constraints import derive

    contract.priorities = list(d.priorities)
    contract.constraints = derive(trip, contract)
    return contract, assumptions


def _place_id(ref) -> tuple | None:
    # Same name is not same place: a corrected "Bali, Indonesia" keeps the name "Bali" of the Bali it replaces.
    return (ref.name, (ref.country_code or "").upper(), round(ref.lat, 2), round(ref.lon, 2)) if ref else None


def contract_dirty_domains(old: TripContract | None, new: TripContract) -> set[str]:
    """Which research domains must be refreshed after a contract change."""
    if old is None or _place_id(old.destination_ref) != _place_id(new.destination_ref) \
            or old.budget.currency != new.budget.currency:
        return set(RESEARCH_DOMAINS)
    if [_place_id(s.ref) for s in old.stops] != [_place_id(s.ref) for s in new.stops]:
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
    for n in notes:
        trip.feedback.append(FeedbackItem(feedback_type=n.feedback_type, sentiment=n.sentiment,
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
    every = r.flights_outbound + r.flights_return + [f for rt in r.round_trips for f in (rt.outbound, rt.inbound)] \
        + [f for leg in r.legs for f in leg]  # a tour's middle legs too
    return list({f.id: f for f in every}.values())


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
    legs_of = {x.id: f"leg{i}" for i, leg in enumerate(trip.research.legs if trip.research else []) for x in leg}
    for f in sorted(matches, key=lambda f: f.price_per_person.amount):
        picked.setdefault(legs_of.get(f.id, f.direction), f)  # one per leg of a tour, else per direction
    tickets = trip.research.round_trips if trip.research else []
    # A round-trip leg brings its own partner: the ticket holding the picked outbound first (two tickets can share a
    # return flight), else one holding any picked flight.
    out_id = picked["outbound"].id if "outbound" in picked else None
    rt = next((t for t in tickets if t.outbound.id == out_id), None) \
        or next((t for t in tickets if {t.outbound.id, t.inbound.id} & {f.id for f in picked.values()}), None)
    if rt is not None:
        picked = {"outbound": rt.outbound, "return": rt.inbound}
    return list(picked.values())


def _same_slot(trip: TripState, f) -> set[str]:
    """Flights that compete with `f` for one place in the plan: the same leg of a tour, else the same direction."""
    r = trip.research
    for leg in (r.legs if r else []):
        if any(x.id == f.id for x in leg):
            return {x.id for x in leg}
    return {x.id for x in _all_flights(trip) if x.direction == f.direction}


def _target_hotels(plan: TripPlan, a: Action) -> list:
    """The hotels a 'change the hotel' request means: the city named (or the day's city) on a tour, else all."""
    if not plan.stops:
        return plan.hotels
    hay = f"{a.text or ''} {a.category or ''}".lower()
    named = [s for s in plan.stops if s.hotel and s.name.lower() in hay]
    if not named and a.day:
        named = [s for s in plan.stops if s.hotel and s.first_day <= a.day <= s.last_day]
    return [s.hotel for s in named] or plan.hotels


def _resolve_item(trip: TripState, plan: TripPlan | None, text: str) -> str | None:
    """The place a replace_item request means: a place id, an item title in the plan ("Lunch - Roscioli" too), or a
    researched place's name. None when nothing matches."""
    r, low = trip.research, text.strip().lower()
    if r and r.place(text.strip()):
        return text.strip()
    items = [i for d in (plan.days if plan else []) for i in d.items if i.place_id]
    hit = next((i for i in items if i.title.lower() == low), None) \
        or next((i for i in items if low.endswith(" - " + i.title.lower()) or i.title.lower().endswith(" - " + low)), None)
    if hit:
        return hit.place_id
    if r:
        place = next((x for x in r.attractions + r.restaurants if x.name.lower() == low), None) \
            or next((x for x in r.attractions + r.restaurants
                     if len(x.name) >= 4 and low.endswith(" " + x.name.lower())), None)
        if place:
            return place.id
    return None


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
                explicit.add("travel_style")
                notes.append(f"Switched to a {p.travel_style.replace('_', ' ')} pace with more sights per day.")
            k.extra_rest = False
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
            notes.append("Upgraded towards the comfort plan.")
        elif name == "more_food":
            k.food_focus = True
            if "food" not in p.activity_preferences:
                p.activity_preferences.append("food")
            notes.append("Added more food experiences, coffee and dessert stops.")
        elif name == "fewer_category" and a.category:
            current = _count_category(plan, a.category, trip)
            k.category_limits[a.category] = max(0, current - int(a.amount or 1))
            notes.append(f"Reduced {a.category} from {current} to {k.category_limits[a.category]}.")
        elif name == "more_category" and a.category and a.category.lower() in LANDMARK_WORDS:
            k.category_boost["must_see"] = k.category_boost.get("must_see", 0) + 0.4
            notes.append("Prioritising the city's most famous landmarks.")
        elif name == "more_category" and a.category:
            k.category_boost[a.category] = k.category_boost.get(a.category, 0) + 0.35
            k.category_limits.pop(a.category, None)
            if a.category not in p.activity_preferences:
                p.activity_preferences.append(a.category)
            notes.append(f"Added more {a.category}.")
        elif name == "avoid_noise":
            p.noise_tolerance = "low"
            explicit.add("noise_tolerance")
            if plan and plan.hotel and plan.hotel.noise_level == "noisy":
                k.hotel_exclude.append(plan.hotel.id)
                notes.append(f"Replacing {plan.hotel.name} with a quieter hotel.")
            else:
                notes.append("Will prefer quiet areas for hotels.")
        elif name == "change_hotel" and plan and plan.hotels:
            targets = _target_hotels(plan, a)
            k.hotel_exclude += [h.id for h in targets]
            notes.append("Looking for an alternative to " + " and ".join(h.name for h in targets) + ".")
        elif name == "choose_flight" and a.text and trip.research:
            chosen = resolve_flights(trip, a.text)
            for f in chosen:
                # One pin per flight slot (direction, or leg of a tour); a round-trip ticket pins both of its legs.
                same_slot = _same_slot(trip, f)
                k.flight_pins = [x for x in k.flight_pins if x not in same_slot] + [f.id]
                k.flight_exclude = [x for x in k.flight_exclude if x != f.id]
                notes.append(f"Switched to {f.airline} {f.flight_number} ({f.depart_at:%a %d %b %H:%M}).")
            if not chosen:
                notes.append("I couldn't find that flight among the options I researched.")
        elif name == "change_flight" and plan:
            k.flight_pins = []  # "a different flight": the planner picks again
            flights = plan.legs if plan.legs else [plan.outbound_flight, plan.return_flight]
            if plan.legs and a.day:
                # "A different flight on day 5": the leg that departs that day (every other leg stays).
                day_date = c.start_date + timedelta(days=a.day - 1) if c else None
                flights = [f for f in plan.legs if day_date and f.depart_at.date() == day_date] or flights
            k.flight_exclude += [f.id for f in flights if f]
            notes.append("Looking for different flights.")
        elif name in ("extend_trip", "shorten_trip") and c:
            n = int(a.amount or 1)
            new_end = c.end_date + timedelta(days=n if name == "extend_trip" else -n)
            new_end = max(new_end, c.start_date + timedelta(days=max(1, len(c.stops))))
            if c.is_multi:
                # The cities' nights follow the new length (extra nights to the last city), and every stop moves.
                nights = resize_nights([s.nights for s in c.stops], (new_end - c.start_date).days)
                c.stops, new_end, _ = build_stops([s.ref for s in c.stops], c.start_date, new_end, nights)
                trip.draft.stop_nights = nights
                dirty |= {"activities"}
            c.end_date = new_end
            trip.draft.end_date = c.end_date
            trip.draft.duration_days = c.num_days
            dirty |= {"flights", "hotels", "weather"}
            notes.append(f"Trip is now {c.num_days} days ({c.start_date:%b %d} - {c.end_date:%b %d}).")
        elif name in ("set_budget", "adjust_budget") and c and a.amount:
            d = trip.draft
            if name == "set_budget":
                c.budget.amount = float(a.amount)
            else:
                # Relative to the found budget in "cheapest trip" mode - never to the no-limit placeholder.
                base = c.budget.amount if c.budget.amount < FIND_CHEAPEST_PLACEHOLDER \
                    else float(trip.metadata.get("found_budget") or 0)
                c.budget.amount = max(0.0, base + float(a.amount))
                if a.amount > 0:  # more money lifts any earlier "cheaper" pressure
                    k.price_pressure, k.max_price_level = 0, 4
            if d.find_cheapest:
                # A real budget replaces "find the cheapest": it is a limit again, as for any stated budget.
                d.find_cheapest = False
                c.budget.hard_limit = True if d.budget_hard_limit is None else d.budget_hard_limit
            d.budget_amount, d.budget_currency = c.budget.amount, c.budget.currency
            notes.append(f"Budget {'set to' if name == 'set_budget' else 'is now'} {c.budget.amount:,.0f} {c.budget.currency}.")
        elif name == "less_walking":
            p.walking_tolerance = LEVELS[max(0, LEVELS.index(p.walking_tolerance) - 1)]  # type: ignore[assignment]
            explicit.add("walking_tolerance")
            notes.append(f"Walking tolerance set to {p.walking_tolerance}; longer hops use transport.")
        elif name == "more_nightlife":
            p.nightlife_interest = "high"
            explicit.add("nightlife_interest")
            notes.append("Added evening plans.")
        elif name == "prefer_hidden_gems":
            p.prefer_hidden_gems = True
            explicit.add("prefer_hidden_gems")
            notes.append("Favouring hidden gems over the busiest sights.")
        elif name == "add_place" and a.text:
            if a.day:  # "for dinner on day 1": remembered for restaurants (and as the preferred day)
                trip.metadata.setdefault("must_visit_day", {})[a.text] = a.day
            if add_must_visit(trip, [a.text]):
                notes.append(f"Adding {a.text} to your plan.")
            else:
                notes.append(f"{a.text} is already on your list.")
        elif name == "replace_item" and a.text:
            pid = _resolve_item(trip, plan, a.text)
            if pid is None:
                notes.append(f"I couldn't find '{a.text}' in your plan.")
                continue
            k.exclude_ids.append(pid)
            trip.excluded_ids.append(pid)
            if by_traveller and (pid in k.must_include or pid in k.meal_requests):
                # They changed their mind about a place they asked for (the critic never overrides such a request).
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
        elif name == "select_mode" and a.text in PLANNING_MODES:
            trip.selected_mode = a.text  # type: ignore[assignment]
            notes.append(f"Switched to the {a.text} plan.")
    if by_traveller:
        p.explicit_fields = sorted(explicit)

    # Stability: keep previous activity assignments unless the change needs a reshuffle.
    if plan and needs_replan:
        pins = plan_activity_ids(plan)
        if {x.action for x in actions} & RESHUFFLE_ACTIONS:
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
    if old.stops and new.stops:
        # Multi-city: each city's hotel and every leg between them.
        olds = {s.name: s for s in old.stops}
        for s in new.stops:
            o = olds.get(s.name)
            if o and o.hotel and s.hotel and o.hotel.id != s.hotel.id:
                out.append(f"Hotel in {s.name}: {o.hotel.name} -> {s.hotel.name}")
        for i, (a, b) in enumerate(zip(old.legs, new.legs)):
            if a.id != b.id:
                out.append(f"Leg {i + 1} ({b.origin} -> {b.destination}): {a.flight_number} -> {b.flight_number}")
    elif old.hotel and new.hotel and old.hotel.id != new.hotel.id:
        out.append(f"Hotel: {old.hotel.name} -> {new.hotel.name}")
    for label, a, b in (("Outbound flight", old.outbound_flight, new.outbound_flight),
                        ("Return flight", old.return_flight, new.return_flight)):
        if a and b and a.id != b.id and not (old.stops and new.stops):
            if a.flight_number == b.flight_number:  # the same flight on another day (new dates)
                out.append(f"{label}: {a.flight_number} now on {b.depart_at:%a %d %b} (was {a.depart_at:%a %d %b})")
            else:
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
    if old.budget and new.budget and old.budget.currency.upper() != new.budget.currency.upper():
        out.append(f"Prices now in {new.budget.currency}: total {new.budget.total:,.0f} {new.budget.currency} "
                   f"(was {old.budget.total:,.0f} {old.budget.currency})")
    elif old.budget and new.budget:
        delta = new.budget.total - old.budget.total
        if abs(delta) >= 1:
            out.append(f"Total cost {'+' if delta > 0 else '-'}{abs(delta):,.0f} {new.budget.currency} "
                       f"(now {new.budget.total:,.0f})")
    if old.score and new.score and old.score.total != new.score.total:
        out.append(f"TripScore {old.score.total} -> {new.score.total}")
    return out
