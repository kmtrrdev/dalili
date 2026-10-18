"""Structured data contracts shared by every node, MCP server, validator and the API.

The Trip State (TripState) is the single source of truth for a planning session.
Nodes never pass paragraphs to each other; they pass these models.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field

from .engine.knobs import PlanKnobs
from .utils import SERVED_STALE, fetch_time

# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

# known: published by a provider (Google fares/rates, Wikivoyage listing, official tariff quote)
# range: a published per-person range (e.g. Google's "€10–20")
# calculated: an official published tariff applied to a real distance (e.g. taxi flag fall + per-km x ORS km)
# estimated: no published price - an estimate, always labelled as such
PriceType = Literal["known", "estimated", "range", "calculated"]
TravelStyle = Literal["relaxed", "moderate", "active", "very_active"]
Level = Literal["low", "medium", "high"]
PlanningMode = Literal["balanced", "budget", "comfort", "experience"]
Popularity = Literal["must_see", "popular", "local_favorite", "hidden_gem", "alternative"]
MealType = Literal["breakfast", "lunch", "coffee", "dinner", "dessert"]
CheckStatus = Literal["PASS", "WARN", "FAIL"]

PLANNING_MODES: tuple[PlanningMode, ...] = ("balanced", "budget", "comfort", "experience")


def _web_url(v: Any) -> str | None:
    """Links shown to travellers come from third-party data: only http(s) ever passes (no javascript:, data:, file:)."""
    if not isinstance(v, str) or not v.strip():
        return None
    v = v.strip()
    return v if v.lower().startswith(("http://", "https://")) else None


WebUrl = Annotated[str | None, BeforeValidator(_web_url)]


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Money(BaseModel):
    amount: float
    currency: str = "USD"
    price_type: PriceType = "estimated"
    source: str | None = None  # where a verified price comes from, e.g. "Wikivoyage · updated 2025-03"

    def rounded(self) -> "Money":
        return Money(amount=round(self.amount, 2), currency=self.currency, price_type=self.price_type,
                     source=self.source)


TrustClass = Literal["verified", "calculated", "estimated", "unknown"]


def trust_class(m: "Money") -> TrustClass:
    """One vocabulary for how much a price can be trusted (never shows an estimate as verified):
    verified   - published by a provider (a fare, a nightly rate, a listed or quoted price, a published range);
    calculated - computed from published inputs (an official tariff x a real distance, a meal from menu prices);
    estimated  - an informed estimate with a stated basis (AI estimate for this place, an older published price);
    unknown    - no information about this place: a generic default for its category."""
    if m.price_type in ("known", "range"):
        return "verified"
    if m.price_type == "calculated":
        return "calculated"
    return "estimated" if m.source else "unknown"


class GeoPoint(BaseModel):
    lat: float
    lon: float


class Metadata(BaseModel):
    """Provenance attached to every externally sourced entity."""

    source: str
    provider: str
    # When the provider really answered (a cached response keeps its original time - never "now").
    retrieved_at: datetime = Field(default_factory=lambda: fetch_time().replace(microsecond=0))
    stale: bool = Field(default_factory=lambda: SERVED_STALE.get())  # served from an expired cache (provider down)
    confidence: float = 1.0
    source_url: WebUrl = None
    is_demo_data: bool = False
    notes: str | None = None


# ---------------------------------------------------------------------------
# Traveler + contract
# ---------------------------------------------------------------------------


class LearnedPreference(BaseModel):
    """One remembered preference (see preferences.py for how confidence is computed)."""
    value: Any
    confidence: float = 0.5           # last computed confidence (preferences.confidence() recomputes it with decay)
    evidence: list[str] = Field(default_factory=list)  # the most recent supporting observations
    source: Literal["stated", "inferred"] = "inferred"
    support: float = 0.0              # weighted observations for this value
    against: float = 0.0              # weighted observations contradicting it
    updated_at: datetime | None = None


class TravelerProfile(BaseModel):
    travel_style: TravelStyle = "moderate"
    food_preferences: list[str] = Field(default_factory=list)
    dietary_restrictions: list[str] = Field(default_factory=list)
    activity_preferences: list[str] = Field(default_factory=list)
    walking_tolerance: Level = "medium"
    transport_preference: Literal["walk", "mixed", "public_transport", "taxi"] | None = None
    preferred_wake_up_time: str = "08:30"
    hotel_style: str | None = None
    hotel_rating_preference: float = 4.0
    flight_preference: Literal["direct", "any"] = "any"
    avoid_early_flights: bool = False
    nightlife_interest: Level = "low"
    noise_tolerance: Level = "medium"
    prefer_hidden_gems: bool = False
    avoid_categories: list[str] = Field(default_factory=list)
    # Preferences inferred from feedback. Lower priority than the explicit fields above.
    learned: dict[str, LearnedPreference] = Field(default_factory=dict)
    # Which explicit fields the user actually stated (vs. defaults).
    explicit_fields: list[str] = Field(default_factory=list)


class Budget(BaseModel):
    amount: float
    currency: str = "USD"
    hard_limit: bool = True


class PlaceRef(BaseModel):
    """A resolved city: coordinates, timezone and airports (Google Flights autocomplete + Geoapify)."""

    name: str
    country: str = ""
    country_code: str = ""
    lat: float
    lon: float
    timezone: str = "UTC"
    city_id: str | None = None          # Google knowledge-graph id, accepted by Google Flights
    airports: list[str] = Field(default_factory=list)
    airport_names: dict[str, str] = Field(default_factory=dict)

    @property
    def flight_id(self) -> str:
        return self.city_id or (self.airports[0] if self.airports else self.name)


class TripStop(BaseModel):
    """One city of a multi-city journey: arrives on start_date, leaves on end_date."""

    ref: PlaceRef
    nights: int
    start_date: date
    end_date: date

    @property
    def name(self) -> str:
        return self.ref.name


ConstraintPriority = Literal["hard", "soft", "preference", "nice_to_have"]
ConstraintSource = Literal["explicit", "inferred", "learned", "default"]


class Constraint(BaseModel):
    """One requirement of the trip, with where it came from and how firmly it holds (see constraints.py).

    hard: must hold - never relaxed without the traveller's consent. soft: kept unless it conflicts with something
    harder. preference: ranks options. nice_to_have: lowest priority. Explicit statements outrank inferred or learned
    ones; nothing the traveller didn't say becomes hard."""

    id: str
    type: str                      # budget_max, must_visit, wish, avoid_category, dietary, direct_flights, ...
    value: Any
    unit: str | None = None
    priority: ConstraintPriority
    source: ConstraintSource
    confidence: float = 1.0
    flexibility: Literal["fixed", "negotiable", "flexible"] = "negotiable"
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)  # what the traveller said / the behaviour it was learned from
    created_from: str = ""         # requirements | profile | learned_preferences | defaults
    last_updated: datetime = Field(default_factory=utcnow)


class TripContract(BaseModel):
    origin: str = "CAI"                 # airport code or city id used for flight searches
    origin_city: str = "Cairo"
    origin_ref: PlaceRef | None = None
    # Open-jaw: the trip ends somewhere else than it started (Riyadh -> Istanbul -> home to Cairo). None = back to origin.
    return_to: str | None = None        # airport code or city id for the last flight
    return_city: str | None = None
    return_ref: PlaceRef | None = None
    destination: str                    # city name, e.g. "Rome"
    destination_name: str = ""
    destination_ref: PlaceRef | None = None
    start_date: date
    end_date: date
    arrive_by: date | None = None       # the traveller wants to BE there on this date (not just leave home on it)
    travelers: int = 1
    budget: Budget
    must_have: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    travel_style: TravelStyle = "moderate"
    planning_mode: PlanningMode = "balanced"
    # Multi-city journey (2+ stops, in visit order). Empty for a classic single-destination trip;
    # when set, destination/destination_ref mirror the first stop.
    stops: list[TripStop] = Field(default_factory=list)
    room_count: int | None = None       # rooms the traveller asked for ("all three in one room"); None = 2 per room
    constraints: list[Constraint] = Field(default_factory=list)  # typed view of every requirement (constraints.py)
    priorities: list[str] = Field(default_factory=list)          # what the traveller said matters most, in order

    @property
    def end_ref(self) -> PlaceRef | None:
        """Where the trip ends: the return city if the traveller named one, else home."""
        return self.return_ref or self.origin_ref

    @property
    def is_multi(self) -> bool:
        return len(self.stops) > 1

    @property
    def route_name(self) -> str:
        return " → ".join(s.name for s in self.stops) if self.is_multi else (self.destination_name or self.destination)

    @property
    def nights(self) -> int:
        return max((self.end_date - self.start_date).days, 1)

    @property
    def num_days(self) -> int:
        return self.nights + 1

    @property
    def rooms(self) -> int:
        return self.room_count or max(1, (self.travelers + 1) // 2)


class ProposedStop(BaseModel):
    city: str
    country: str = ""
    nights: int = 1
    why: str = ""
    covers: list[str] = Field(default_factory=list)      # places the traveller named that this base covers
    day_trips: list[str] = Field(default_factory=list)   # e.g. "Leaning Tower of Pisa (~80 km)"
    ref: PlaceRef | None = None


class RouteProposal(BaseModel):
    """A multi-city route the agent suggests (and the traveller confirms or changes) before planning."""

    stops: list[ProposedStop] = Field(default_factory=list)
    summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    travel_km: float = 0.0            # origin -> stops -> origin, straight-line
    typed_order_km: float | None = None  # same, in the order the traveller typed (when it differs)
    version: int = 1


class RequirementDraft(BaseModel):
    """What the requirement-understanding step extracted so far (all optional)."""

    origin: str | None = None
    origin_city: str | None = None
    origin_ref: PlaceRef | None = None
    destination: str | None = None
    destination_ref: PlaceRef | None = None
    # Multi-city: every stop in visit order (destination mirrors the first one).
    destinations: list[str] = Field(default_factory=list)
    destination_refs: list[PlaceRef] = Field(default_factory=list)
    stop_nights: list[int] = Field(default_factory=list)   # requested nights per stop (optional)
    countries: list[str] = Field(default_factory=list)     # destinations the traveller gave as countries
    region: str | None = None                              # "Europe": let the agent choose countries and cities
    route_proposal: RouteProposal | None = None            # suggested route awaiting the traveller's answer
    route_confirmed: bool = False
    redesign: bool = False          # the traveller asked to change the route of an existing plan
    route_feedback: list[str] = Field(default_factory=list)  # what the traveller said about earlier proposals
    start_date: date | None = None
    end_date: date | None = None
    arrive_by: date | None = None   # "I want to arrive on the 1st": the day to land, not just to leave home
    duration_days: int | None = None
    travelers: int | None = None
    budget_amount: float | None = None
    budget_currency: str | None = None
    budget_hard_limit: bool | None = None
    find_cheapest: bool = False     # "the cheapest trip possible": the planner finds the budget instead of asking
    return_to: str | None = None     # end the trip in another city than the origin (open-jaw), as the traveller said it
    return_ref: PlaceRef | None = None
    rooms: int | None = None         # hotel rooms the traveller asked for
    must_have: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    must_visit: list[str] = Field(default_factory=list)  # specific places named by the traveller, kept in the plan
    wish_list: list[str] = Field(default_factory=list)   # places mentioned softly ("if there's time"): planned when they fit
    priorities: list[str] = Field(default_factory=list)  # what the traveller said matters most, most important first
    # Evidence: the words each requirement came from (field -> the traveller's message), for explanations.
    stated: dict[str, str] = Field(default_factory=dict)
    profile_updates: dict[str, Any] = Field(default_factory=dict)
    planning_mode: PlanningMode | None = None


# ---------------------------------------------------------------------------
# Research entities (MCP outputs)
# ---------------------------------------------------------------------------


class FlightOption(BaseModel):
    """A journey between cities. Usually a flight; between nearby stops of a multi-city
    trip it can be a train / coach / drive (mode != "flight", times and fare estimated)."""

    id: str
    direction: Literal["outbound", "return"]
    mode: Literal["flight", "train", "coach", "car"] = "flight"
    airline: str
    flight_number: str
    origin: str
    destination: str
    depart_at: datetime
    arrive_at: datetime
    duration_minutes: int
    stops: int
    via: str | None = None
    price_per_person: Money
    baggage: str = "See airline fare rules"
    cabin: str = "economy"
    segments: list[str] = Field(default_factory=list)
    layovers: list[str] = Field(default_factory=list)
    carbon_kg: float | None = None
    booking_url: WebUrl = None
    metadata: Metadata


class ReviewInsights(BaseModel):
    """What real guests say about a hotel, distilled by the review-analyst agent (aspect-based sentiment)."""

    summary: str = Field(description="One sentence: the overall guest verdict, in English")
    summary_ar: str = Field(default="", description="The same sentence in Egyptian Arabic")
    pros: list[str] = Field(default_factory=list, description="2-4 short strengths guests repeat, in English")
    pros_ar: list[str] = Field(default_factory=list, description="The same strengths in Egyptian Arabic")
    cons: list[str] = Field(default_factory=list, description="0-3 short recurring complaints, in English")
    cons_ar: list[str] = Field(default_factory=list, description="The same complaints in Egyptian Arabic")
    aspects: dict[str, float] = Field(default_factory=dict, description=(
        "Score 1-5 for each aspect the reviews actually discuss: cleanliness, location, staff, comfort, quietness, "
        "value, breakfast. Leave out aspects nobody mentions."))
    noise_level: Literal["quiet", "moderate", "noisy", "unknown"] = "unknown"
    noise_evidence: list[str] = Field(default_factory=list, description="Up to 2 short quotes about noise, verbatim")
    reviews_read: int = 0


class HotelOption(BaseModel):
    id: str
    name: str
    neighborhood: str
    location: GeoPoint
    rating: float
    stars: int = 0
    price_per_night: Money
    total_price: Money | None = None
    breakfast_included: bool = False
    cancellation_policy: str = "Check the cancellation policy with the provider"
    free_cancellation: bool | None = None
    noise_level: Literal["quiet", "moderate", "noisy", "unknown"] = "unknown"
    noise_evidence: list[str] = Field(default_factory=list)
    review_insights: ReviewInsights | None = None
    style: str = "hotel"
    reviews_count: int = 0
    location_rating: float | None = None
    check_in_time: str | None = None
    check_out_time: str | None = None
    property_token: str | None = None
    link: WebUrl = None
    images: list[str] = Field(default_factory=list)
    room_types: list[str] = Field(default_factory=list)
    amenities: list[str] = Field(default_factory=list)
    metadata: Metadata


class Place(BaseModel):
    """A restaurant, cafe, attraction or bookable activity."""

    id: str
    name: str
    kind: Literal["restaurant", "cafe", "attraction", "activity"]
    categories: list[str] = Field(default_factory=list)
    cuisine: list[str] = Field(default_factory=list)
    dietary: list[str] = Field(default_factory=list)
    meal_types: list[MealType] = Field(default_factory=list)
    location: GeoPoint
    neighborhood: str = ""
    rating: float = 4.0
    price_level: int = 2
    cost_per_person: Money
    opening_hours: dict[str, list[list[str]]] = Field(default_factory=dict)
    duration_minutes: int = 60
    indoor: bool = True
    popularity: Popularity = "popular"
    requires_reservation: bool = False
    combo_with: str | None = None  # shares a ticket with this place id (pay once)
    description: str = ""
    notes: str | None = None
    # Provenance / quality of the facts above
    hours_verified: bool = False    # True only when the provider published the hours (else typical hours assumed)
    # The time of day the experience happens at (a sunset dance show, a sunrise trek, a night market): from the name
    # or the AI's knowledge of the place; None for anything visited at any hour.
    best_time: Literal["sunrise", "sunset", "night"] | None = None
    price_known: bool = False       # True only when the provider published a price
    price_checked: bool = False     # the price cascade already ran for this place (never repeated on later turns)
    dates: list[date] = Field(default_factory=list)  # events: only happens on these dates
    distance_km: float = 0.0        # straight-line distance from the city centre
    day_trip: bool = False          # outside the city: needs a dedicated (half) day and real travel time
    reviews_count: int = 0
    address: str = ""
    website: WebUrl = None
    booking_url: WebUrl = None   # reserve a table / buy tickets, when the provider lists one
    menu_url: WebUrl = None      # the restaurant's menu (found by web search) - where its meal price comes from
    google_place_id: str | None = None
    google_data_id: str | None = None
    thumbnail: str | None = None
    metadata: Metadata


class WeatherDay(BaseModel):
    date: date
    condition: str
    temp_min_c: float
    temp_max_c: float
    precipitation_probability: int
    precipitation_mm: float = 0.0
    risk: Level = "low"
    metadata: Metadata


class TransportLeg(BaseModel):
    mode: Literal["walk", "transit", "taxi", "train", "bus"]
    minutes: int
    distance_km: float
    cost: Money
    description: str = ""


class TransferOption(BaseModel):
    id: str
    mode: Literal["train", "taxi", "bus", "transit"]
    name: str
    minutes: int
    cost_per_person: Money | None = None
    cost_per_vehicle: Money | None = None
    airport: str | None = None
    notes: str = ""
    metadata: Metadata


class RoundTrip(BaseModel):
    """A round-trip ticket (often cheaper than two one-ways). Each leg carries half the ticket price, so the pair is
    only ever chosen together; mixing one leg with a one-way fare would misprice it."""

    outbound: FlightOption
    inbound: FlightOption
    total_per_person: Money


class ResearchBundle(BaseModel):
    flights_outbound: list[FlightOption] = Field(default_factory=list)
    flights_return: list[FlightOption] = Field(default_factory=list)
    round_trips: list[RoundTrip] = Field(default_factory=list)
    hotels: list[HotelOption] = Field(default_factory=list)
    restaurants: list[Place] = Field(default_factory=list)
    attractions: list[Place] = Field(default_factory=list)
    weather: list[WeatherDay] = Field(default_factory=list)
    airport_transfers: list[TransferOption] = Field(default_factory=list)
    fx_rates: dict[str, float] = Field(default_factory=dict)  # currency -> user-currency multiplier
    fx_metadata: Metadata | None = None
    destination_info: dict[str, Any] = Field(default_factory=dict)
    # Local price level relative to a mid-priced city (from real hotel prices); scales estimates.
    cost_factor: float = 1.0
    # Estimated local transport prices in the user's currency (no free API publishes fares).
    fares: dict[str, float] = Field(default_factory=dict)
    # Where verified fares came from: {"transit": 'Wikivoyage: "A single ticket costs €1.20"', ...}
    fare_sources: dict[str, str] = Field(default_factory=dict)
    # How many researched prices are verified (for transparency in the UI).
    price_coverage: dict[str, Any] = Field(default_factory=dict)
    flight_insights: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    # Multi-city: one bundle per stop, and the journey options for every leg
    # (leg 0: origin -> stop 1, leg i: stop i -> stop i+1, last: final stop -> origin).
    stops: list["ResearchBundle"] = Field(default_factory=list)
    legs: list[list[FlightOption]] = Field(default_factory=list)

    def place(self, place_id: str) -> Place | None:
        for p in self.attractions + self.restaurants:
            if p.id == place_id:
                return p
        return None


# ---------------------------------------------------------------------------
# Itinerary
# ---------------------------------------------------------------------------


class ItineraryItem(BaseModel):
    start: str  # "HH:MM"
    end: str
    kind: Literal["meal", "activity", "transfer", "flight", "hotel", "rest", "free"]
    title: str
    place_id: str | None = None
    location: GeoPoint | None = None
    meal_type: MealType | None = None
    cost: Money = Field(default_factory=lambda: Money(amount=0.0))
    indoor: bool | None = None
    notes: str = ""
    transport_from_previous: TransportLeg | None = None
    alternatives: list[str] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)
    optional: bool = False
    link: WebUrl = None  # e.g. the restaurant's menu


class DayPlan(BaseModel):
    day: int
    date: date
    title: str
    items: list[ItineraryItem] = Field(default_factory=list)
    weather: WeatherDay | None = None
    walking_km: float = 0.0
    estimated_cost: Money = Field(default_factory=lambda: Money(amount=0.0))
    activity_count: int = 0
    notes: list[str] = Field(default_factory=list)
    city: str = ""              # multi-city: where the day ends (the new city on a travel day)
    travel_day: bool = False    # a flying day: between two stops, or a long-haul flight there / home
    capacity: int | None = None  # activities the plan agreed for this day (pace, mode, the traveller's own changes)


class BudgetBreakdown(BaseModel):
    currency: str
    flights: float = 0.0
    hotel: float = 0.0
    food: float = 0.0
    activities: float = 0.0
    transport: float = 0.0
    buffer: float = 0.0
    total: float = 0.0
    limit: float = 0.0
    remaining: float = 0.0
    hard_limit: bool = True
    status: CheckStatus = "PASS"
    daily_spending: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    # How much of the cost rests on what (trust_class), and the resulting confidence in the total (see budget.py).
    by_trust: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = None
    stale_sources: int = 0     # flights / hotels served from an expired cache (provider unavailable)


class Violation(BaseModel):
    check: str
    severity: Literal["warning", "error"]
    message: str
    day: int | None = None
    item_title: str | None = None
    place_id: str | None = None
    fix_hint: str | None = None


class CheckResult(BaseModel):
    name: str
    status: CheckStatus
    messages: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    result: Literal["PASS", "FAIL"]
    checks: list[CheckResult] = Field(default_factory=list)
    violations: list[Violation] = Field(default_factory=list)

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "error"]


class TripScore(BaseModel):
    """Hierarchical: feasibility, then the traveller's hard requirements, then preferences, then quality.
    A plan that breaks a hard requirement never outranks one that doesn't, however good it is otherwise."""
    total: int
    budget_fit: int
    comfort: int
    food: int
    activities: int
    transportation: int
    personal_fit: int
    schedule_quality: int
    feasible: bool = True               # no hard validation errors
    hard_violations: int = 0
    constraint_satisfaction: int = 100  # share of the traveller's hard requirements met
    preference_satisfaction: int = 100  # share of their preferences met
    quality: int = 0                    # the weighted experience parts (weights follow the plan and the traveller)
    unmet: list[str] = Field(default_factory=list)  # requirements / preferences this plan does not meet
    weights: dict[str, float] = Field(default_factory=dict)

    def rank_key(self) -> tuple:
        return (self.feasible, self.constraint_satisfaction, self.preference_satisfaction, self.quality)


def stay_nights(check_in: date | None, check_out: date | None, default: int) -> int:
    return max(1, (check_out - check_in).days) if check_in and check_out else default


class StopPlan(BaseModel):
    """The part of a multi-city plan spent in one city."""

    index: int
    name: str
    country: str = ""
    country_code: str = ""
    location: GeoPoint
    start_date: date
    end_date: date
    nights: int
    first_day: int
    last_day: int
    hotel: HotelOption | None = None
    arrival: FlightOption | None = None     # how you get here (flight / train)
    explanations: list[str] = Field(default_factory=list)
    # The nights the hotel is really needed (see TripPlan.hotel_check_in); None = the stop's own dates.
    check_in: date | None = None
    check_out: date | None = None

    @property
    def hotel_nights(self) -> int:
        return stay_nights(self.check_in, self.check_out, self.nights)


class TripPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: new_id("plan"))
    mode: PlanningMode = "balanced"
    pitch: str = ""       # what this plan optimises for this trip (from the strategist), English
    pitch_ar: str = ""    # the same in Arabic
    outbound_flight: FlightOption | None = None
    return_flight: FlightOption | None = None
    hotel: HotelOption | None = None
    # The nights the flights really need the hotel: a landing on the next local evening leaves the first night
    # unused, a flight home just after midnight checks out the day before. None = the trip's own dates.
    hotel_check_in: date | None = None
    hotel_check_out: date | None = None
    days: list[DayPlan] = Field(default_factory=list)
    budget: BudgetBreakdown | None = None
    score: TripScore | None = None
    validation: ValidationReport | None = None
    explanations: dict[str, list[str]] = Field(default_factory=dict)
    alternatives: dict[str, list[str]] = Field(default_factory=dict)
    repair_log: list[str] = Field(default_factory=list)
    within_budget: bool = True
    generated_at: datetime = Field(default_factory=utcnow)
    # Places the traveller asked for by name -> the day they are on (None: could not be fitted).
    requested: dict[str, int | None] = Field(default_factory=dict)
    # Multi-city: the cities in order and the chosen journey for every leg (first = outbound, last = return).
    stops: list[StopPlan] = Field(default_factory=list)
    legs: list[FlightOption] = Field(default_factory=list)

    @property
    def hotels(self) -> list[HotelOption]:
        """Every city's hotel on a multi-city trip, else the one hotel."""
        return [s.hotel for s in self.stops if s.hotel] if self.stops else ([self.hotel] if self.hotel else [])

    def hotel_nights(self, default: int) -> int:
        """Nights the (single-city) hotel is paid for: its check-in to check-out, else `default` (the trip's)."""
        return stay_nights(self.hotel_check_in, self.hotel_check_out, default)


# ---------------------------------------------------------------------------
# Feedback, events, state
# ---------------------------------------------------------------------------

class FeedbackItem(BaseModel):
    feedback_type: Literal["hotel", "flight", "restaurant", "activity", "itinerary", "budget", "general"]
    entity_id: str | None = None
    sentiment: Literal["positive", "negative", "neutral"] = "neutral"
    attribute: str | None = None
    severity: float = 0.5
    raw_text: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class Event(BaseModel):
    type: str
    at: datetime = Field(default_factory=utcnow)
    data: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    at: datetime = Field(default_factory=utcnow)


class TripState(BaseModel):
    trip_id: str = Field(default_factory=lambda: new_id("trip"))
    user_id: str = "default"
    status: Literal["collecting", "planned", "needs_input", "error"] = "collecting"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    traveler_profile: TravelerProfile = Field(default_factory=TravelerProfile)
    draft: RequirementDraft = Field(default_factory=RequirementDraft)
    trip_contract: TripContract | None = None
    research: ResearchBundle | None = None
    plans: dict[str, TripPlan] = Field(default_factory=dict)
    selected_mode: PlanningMode = "balanced"
    pinned_days: dict[int, list[str]] = Field(default_factory=dict)  # day -> activity ids kept on replan
    excluded_ids: list[str] = Field(default_factory=list)
    feedback: list[FeedbackItem] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    conversation: list[ChatMessage] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)
    user_knobs: PlanKnobs = Field(default_factory=PlanKnobs)  # adjustments requested by the user
    assumptions: list[str] = Field(default_factory=list)
    last_changes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def selected_plan(self) -> TripPlan | None:
        return self.plans.get(self.selected_mode)

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append(Event(type=event_type, data=data))
        self.updated_at = utcnow()
