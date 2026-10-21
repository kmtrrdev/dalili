"""AI knowledge fallback: when a live source fails (quota used up, outage), the LLM fills in.

The live providers (SerpApi's Google Flights / Hotels / Maps, openrouteservice, ...) stay the source of
truth. When one of them raises (e.g. SerpApi "Your account has run out of searches"), the MCP tool asks
the language model for what it knows instead, so the agent can still plan:

- flights: airlines that really fly the route, typical departure times and durations, estimated fares;
- hotels, attractions, restaurants: well-known real places with typical hours and estimated prices;
- airports of a city.

Everything produced here is labelled: metadata.source = "ai_knowledge", price_type = "estimated",
hours_verified = False, low confidence, and a note to verify before booking. Coordinates suggested by
the model are checked with Geoapify geocoding (a separate free service) whenever it is available.
Results are cached for the session so re-planning is stable.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from typing import Literal

from pydantic import BaseModel, Field

from .. import llm, net
from ..config import today
from ..models import FlightOption, GeoPoint, HotelOption, Metadata, Money, Place
from ..utils import haversine_km


SOURCE = "ai_knowledge"
NOTE = "Live search was unavailable - generated from the AI model's knowledge. Verify before booking."
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
CATEGORIES = ["history", "museums", "art", "architecture", "culture", "nature", "food", "shopping", "nightlife",
              "photography", "relaxation", "family", "romantic", "music", "beach"]

_memo: dict[str, object] = {}


def available() -> bool:
    return llm.available()


def _meta(conf: float = 0.35, url: str | None = None) -> Metadata:
    # Generated now, not fetched: never inherits the time / stale flag of an HTTP response parsed earlier in this task.
    return Metadata(source=SOURCE, provider="AI estimate (live search unavailable)", confidence=conf,
                    source_url=url, notes=NOTE, retrieved_at=datetime.now(timezone.utc).replace(microsecond=0), stale=False)


def _key(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, default=str, sort_keys=True).encode()).hexdigest()[:12]


async def _ask(system: str, user: dict, schema):
    k = _key(system[:40], user, schema.__name__)
    if k in _memo:
        return _memo[k]
    out = await llm.parse(system, json.dumps(user, default=str, ensure_ascii=False), schema)
    if out is not None:
        _memo[k] = out
    return out


async def _geocode(text: str, near: GeoPoint, max_km: float) -> GeoPoint | None:
    """Real coordinates for a named place (Geoapify), accepted only if near the expected area."""
    from . import geo  # local import: geo imports nothing from here, but keep the module graph flat

    try:
        hit = await geo.geocode(text, city_only=False)
    except net.ProviderError:
        return None
    if not hit:
        return None
    p = GeoPoint(lat=float(hit["lat"]), lon=float(hit["lon"]))
    return p if haversine_km(p.lat, p.lon, near.lat, near.lon) <= max_km else None


async def _locate(name: str, city: str, center: GeoPoint, lat: float | None, lon: float | None,
                  max_km: float = 40) -> tuple[GeoPoint, bool]:
    """(location, verified). Geoapify first; the model's own coordinates if plausible; else the centre."""
    real = await _geocode(f"{name}, {city}", center, max_km)
    if real:
        return real, True
    if lat is not None and lon is not None and haversine_km(lat, lon, center.lat, center.lon) <= max_km:
        return GeoPoint(lat=lat, lon=lon), False
    return center, False


# ---------------------------------------------------------------------------
# Flights
# ---------------------------------------------------------------------------


class AIFlight(BaseModel):
    airline: str
    flight_number: str = Field(description="Typical flight number if you know it, else airline code + '?'")
    origin_airport: str = Field(description="IATA code")
    destination_airport: str = Field(description="IATA code")
    depart_time: str = Field(description="HH:MM local time at the origin")
    duration_minutes: int
    stops: int = 0
    via: str | None = None
    typical_economy_fare_usd: float


class AIFlights(BaseModel):
    flights: list[AIFlight]


FLIGHTS_SYSTEM = """You are an airline schedule expert. List 3-5 realistic one-way economy options for the route and date:
airlines that actually operate it (direct first, then common one-stop connections), typical departure times,
realistic durations and typical fares in USD for that season. Never invent airlines that don't fly the route.
Spread the departures across the day (morning, afternoon, evening) when such flights exist."""


async def flights(departure: str, arrival: str, on: date, direction: str, dep_tz: str, arr_tz: str,
                  departure_name: str = "", arrival_name: str = "") -> list[FlightOption]:
    res = await _ask(FLIGHTS_SYSTEM, {"from": f"{departure_name} ({departure})".strip(), "to": f"{arrival_name} ({arrival})".strip(),
                                      "date": on.isoformat()}, AIFlights)
    if res is None:
        return []
    url = (f"https://www.google.com/travel/flights?q={quote_plus(f'Flights from {departure_name or departure} '
                                                                 f'to {arrival_name or arrival} on {on.isoformat()}')}")
    out = []
    for f in res.flights[:5]:
        try:
            dep = datetime.combine(on, datetime.strptime(f.depart_time[:5], "%H:%M").time()).replace(tzinfo=ZoneInfo(dep_tz))
        except ValueError:
            continue
        arr = (dep + timedelta(minutes=max(30, f.duration_minutes))).astimezone(ZoneInfo(arr_tz))
        out.append(FlightOption(
            id="fl_ai_" + _key(f.airline, f.flight_number, on, f.depart_time), direction=direction,  # type: ignore[arg-type]
            airline=f.airline, flight_number=f.flight_number, origin=f.origin_airport.upper()[:3] or departure,
            destination=f.destination_airport.upper()[:3] or arrival, depart_at=dep, arrive_at=arr,
            duration_minutes=f.duration_minutes, stops=max(0, f.stops), via=f.via,
            price_per_person=Money(amount=round(f.typical_economy_fare_usd), currency="USD", price_type="estimated"),
            baggage="Check the airline's fare rules", segments=[], booking_url=url, metadata=_meta(0.3, url)))
    return out


# ---------------------------------------------------------------------------
# Hotels
# ---------------------------------------------------------------------------


class AIHotel(BaseModel):
    name: str
    neighborhood: str
    stars: int = 3
    guest_rating_out_of_5: float = 4.2
    typical_price_per_night_usd: float
    breakfast_included: bool = False
    lat: float | None = None
    lon: float | None = None


class AIHotels(BaseModel):
    hotels: list[AIHotel]


HOTELS_SYSTEM = """You are a hotel expert. Suggest 8 real, currently operating hotels in the city for the dates, across price
levels (budget to upscale), in well-located areas for tourists. Give typical nightly prices in USD for that season and
approximate coordinates. Only hotels you are confident exist. 'name' is the hotel's exact name only (no comments)."""


async def hotels(city: str, check_in: date, check_out: date, adults: int, center: GeoPoint) -> list[HotelOption]:
    res = await _ask(HOTELS_SYSTEM, {"city": city, "check_in": check_in, "check_out": check_out, "adults": adults}, AIHotels)
    if res is None:
        return []
    nights = max((check_out - check_in).days, 1)
    out = []
    for h in res.hotels[:8]:
        loc, verified = await _locate(h.name, city, center, h.lat, h.lon, 30)
        url = f"https://www.google.com/travel/hotels?q={quote_plus(f'{h.name} {city}')}"
        km = haversine_km(loc.lat, loc.lon, center.lat, center.lon)
        out.append(HotelOption(
            id="h_ai_" + _key(h.name, city), name=h.name, neighborhood=h.neighborhood or f"{km:.1f} km from the centre",
            location=loc, rating=min(5.0, max(1.0, h.guest_rating_out_of_5)), stars=max(0, min(5, h.stars)),
            price_per_night=Money(amount=round(h.typical_price_per_night_usd), currency="USD", price_type="estimated"),
            total_price=Money(amount=round(h.typical_price_per_night_usd * nights), currency="USD", price_type="estimated"),
            breakfast_included=h.breakfast_included, link=url,
            cancellation_policy="Check the cancellation policy when booking",
            metadata=_meta(0.4 if verified else 0.3, url)))
    return out


# ---------------------------------------------------------------------------
# Attractions + restaurants
# ---------------------------------------------------------------------------


class AIAttraction(BaseModel):
    name: str
    categories: list[str] = Field(description=f"From: {', '.join(CATEGORIES)}")
    visit_minutes: int = 90
    indoor: bool = False
    opens: str = Field(default="09:00", description="HH:MM typical opening")
    closes: str = Field(default="17:00", description="HH:MM typical closing")
    closed_days: list[str] = Field(default_factory=list, description="mon..sun")
    ticket_usd: float = 0
    world_famous: bool = False
    needs_booking: bool = False
    short_description: str = ""
    lat: float | None = None
    lon: float | None = None


class AIAttractions(BaseModel):
    places: list[AIAttraction]


ATTRACTIONS_SYSTEM = """You are a destination expert. List the 15 best real sights and experiences in and around the city
(the most famous first, then a few local favourites; famous places within ~150 km count as day trips), with typical
opening hours, visit length, ticket price in USD and approximate coordinates. Prefer the traveller's interests; if they
include 'beach', add the best real beaches / snorkelling spots within ~150 km (a beach visit is ~180 minutes)."""


def _hours(opens: str, closes: str, closed: list[str]) -> dict[str, list[list[str]]]:
    closed = {c.lower()[:3] for c in closed}
    return {d: [[opens[:5], closes[:5]]] for d in WEEKDAYS if d not in closed}


async def attractions(city: str, center: GeoPoint, interests: list[str], country: str | None = None) -> list[Place]:
    res = await _ask(ATTRACTIONS_SYSTEM, {"city": city, "country": country, "interests": interests}, AIAttractions)
    if res is None:
        return []
    from .places import tag_distance

    out = []
    for a in res.places[:15]:
        loc, verified = await _locate(a.name, city, center, a.lat, a.lon, 200)
        cats = [c for c in a.categories if c in CATEGORIES] or ["culture"]
        p = Place(
            id="a_ai_" + _key(a.name, city), name=a.name, kind="attraction", categories=cats, location=loc,
            rating=4.6 if a.world_famous else 4.4, price_level=1 if not a.ticket_usd else 2,
            cost_per_person=Money(amount=round(a.ticket_usd, 2), currency="USD", price_type="estimated"),
            opening_hours=_hours(a.opens, a.closes, a.closed_days), hours_verified=False,
            duration_minutes=max(30, min(a.visit_minutes, 360)), indoor=a.indoor,
            popularity="must_see" if a.world_famous else "popular", requires_reservation=a.needs_booking,
            description=a.short_description, reviews_count=20000 if a.world_famous else 3000,
            notes="Hours and price are typical values from the AI model - check before going." if verified
            else "Location, hours and price are AI estimates - check before going.",
            metadata=_meta(0.4 if verified else 0.25))
        out.append(tag_distance(p, center, city))
    return out


FIND_SYSTEM = """You are a destination expert. The traveller named one specific place. Return that real place (its usual
English name, typical hours, visit length, ticket price in USD, coordinates). If it is a whole city or resort town,
still return it with its centre coordinates."""


async def find_place(name: str, city: str, center: GeoPoint) -> Place | None:
    """One named place: the model identifies it, Geoapify confirms where it is."""
    from .places import tag_distance

    a = await _ask(FIND_SYSTEM, {"place": name, "near": city or None}, AIAttraction)
    if a is None:
        return None
    # A named place can be far from the search centre (multi-city trips search a whole region).
    loc, verified = await _locate(a.name, city, center, a.lat, a.lon, 3000 if not city else 400)
    if not verified and loc == center and (a.lat is None or a.lon is None):
        return None
    cats = [c for c in a.categories if c in CATEGORIES] or ["culture"]
    p = Place(
        id="a_ai_" + _key(a.name, city or "region"), name=a.name, kind="attraction", categories=cats, location=loc,
        rating=4.6, cost_per_person=Money(amount=round(a.ticket_usd, 2), currency="USD", price_type="estimated"),
        opening_hours=_hours(a.opens, a.closes, a.closed_days), hours_verified=False,
        duration_minutes=max(30, min(a.visit_minutes, 360)), indoor=a.indoor, popularity="must_see",
        requires_reservation=a.needs_booking, description=a.short_description, reviews_count=20000,
        notes="Hours and price are AI estimates - check before going.", metadata=_meta(0.4 if verified else 0.25))
    return tag_distance(p, center, city or "the city")


class AIRestaurant(BaseModel):
    name: str
    cuisine: list[str] = Field(default_factory=list)
    kind: str = Field(default="restaurant", description="restaurant or cafe")
    meals: list[str] = Field(default_factory=list, description="breakfast, lunch, coffee, dinner, dessert")
    price_level: int = Field(default=2, description="1 cheap .. 4 fine dining")
    vegetarian_friendly: bool = False
    opens: str = "12:00"
    closes: str = "23:00"
    lat: float | None = None
    lon: float | None = None


class AIRestaurants(BaseModel):
    restaurants: list[AIRestaurant]


RESTAURANTS_SYSTEM = """You are a food expert. List 14 real, well-reviewed places to eat in the city centre: local classics,
a few cafes/bakeries for breakfast and coffee, and a range of prices. Typical hours and approximate coordinates."""

PRICE_LEVEL_USD = {1: 10.0, 2: 22.0, 3: 40.0, 4: 80.0}


async def restaurants(city: str, center: GeoPoint, dietary: list[str]) -> list[Place]:
    res = await _ask(RESTAURANTS_SYSTEM, {"city": city, "dietary": dietary}, AIRestaurants)
    if res is None:
        return []
    out = []
    for r in res.restaurants[:14]:
        loc, verified = await _locate(r.name, city, center, r.lat, r.lon, 15)
        cafe = r.kind.lower().startswith("cafe")
        meals = [m for m in r.meals if m in ("breakfast", "lunch", "coffee", "dinner", "dessert")] or (
            ["breakfast", "coffee"] if cafe else ["lunch", "dinner"])
        level = max(1, min(4, r.price_level))
        out.append(Place(
            id="r_ai_" + _key(r.name, city), name=r.name, kind="cafe" if cafe else "restaurant", categories=["food"],
            cuisine=[c.lower().replace(" ", "_") for c in r.cuisine], dietary=["vegetarian"] if r.vegetarian_friendly else [],
            meal_types=meals, location=loc, rating=4.4, price_level=level,  # type: ignore[arg-type]
            cost_per_person=Money(amount=8.0 if cafe else PRICE_LEVEL_USD[level], currency="USD", price_type="estimated"),
            opening_hours=_hours(r.opens, r.closes, []), hours_verified=False, duration_minutes=30 if cafe else 75,
            indoor=True, popularity="popular", reviews_count=500,
            notes="Suggested by the AI model (live search unavailable) - check it's open.",
            metadata=_meta(0.4 if verified else 0.25)))
    return out


# ---------------------------------------------------------------------------
# Airports
# ---------------------------------------------------------------------------


class AIIdea(BaseModel):
    name: str
    country: str
    typical_round_trip_fare_usd: float
    typical_hotel_night_usd: float
    lat: float | None = None
    lon: float | None = None


class AIIdeas(BaseModel):
    ideas: list[AIIdea]


async def destination_ideas(origin: str, country: str, currency: str, nights: int, month: int | None,
                            prefs: dict | None = None) -> list[dict]:
    """Destinations from the origin with typical prices (live explore unavailable), chosen for the
    traveller's interests, company, wishes and dates when given."""
    res = await _ask("You are a travel expert. Suggest 12 varied destinations reachable by air from the origin that "
                     "best suit the traveller (their interests, who is travelling, wishes, dates/season, flight limits), "
                     "with typical economy round-trip fares and a typical mid-range hotel night in USD for that season, "
                     "and city-centre coordinates. Real places only. If the traveller named a 'destination' (a country "
                     "or a city), suggest ONLY places in that country (the city itself first).",
                     {"origin": f"{origin}, {country}", "month": month, "nights": nights, "traveller": prefs or {}},
                     AIIdeas)
    if res is None:
        return []
    usd_only = currency.upper() == "USD"
    return [{"name": i.name, "country": i.country, "flight_price": round(i.typical_round_trip_fare_usd),
             "hotel_price": round(i.typical_hotel_night_usd), "lat": i.lat, "lon": i.lon, "estimated": True,
             "currency_note": None if usd_only else "USD"} for i in res.ideas[:12]]


class PriceGuess(BaseModel):
    name: str = Field(description="Exactly as given")
    amount: float = Field(description="Typical price per person in the local currency (0 if normally free)")
    basis: str = Field(description="What it is: 'adult ticket', 'main + drink', 'free public space'...")
    confidence: Literal["high", "medium", "low"] = "medium"


class CityPriceGuess(BaseModel):
    currency: str = Field(description="ISO code of the local currency")
    places: list[PriceGuess] = Field(default_factory=list)
    transit_single_ticket: float | None = None
    taxi_flag_fall: float | None = None
    taxi_per_km: float | None = None


async def estimate_prices(city: str, country: str, local_currency: str, places: list[dict],
                          need_transit: bool, need_taxi: bool) -> CityPriceGuess | None:
    """The model's knowledge of typical local prices, for what no source publishes. One call per city.
    Always labelled 'AI estimate' - never shown as verified."""
    if not places and not need_transit and not need_taxi:
        return None
    res = await _ask(
        "You are a travel pricing expert. Give TYPICAL current prices per person in the LOCAL currency for each "
        "place: attractions -> the standard adult ticket (0 if entry is normally free, e.g. squares, viewpoints, most "
        "churches); restaurants/cafes -> a typical main course plus a soft drink (cafes: coffee and a pastry). Use "
        "the given price level and cuisine as hints. Also give the city's single public-transport ticket and taxi "
        "flag fall / per-km tariff when asked. Prices must be for TODAY's date: your knowledge may be a few years old, "
        "so in high-inflation currencies (e.g. TRY, EGP, ARS, NGN) raise older prices for the inflation since then - "
        "a taxi or a meal is never cheaper today than it was years ago. Rate your confidence honestly; use 'low' "
        "when unsure.",
        {"city": f"{city}, {country}", "today": today().isoformat(), "local_currency": local_currency,
         "places": places[:70],
         "need_transit_ticket": need_transit, "need_taxi_tariff": need_taxi}, CityPriceGuess)
    return res


class TimedPlace(BaseModel):
    name: str = Field(description="Exactly as given")
    best_time: Literal["sunrise", "sunset", "night", "any"]
    only_then: bool = Field(default=False, description=(
        "True only if the experience itself takes place solely at that time (a performance, a tour or trek that "
        "starts then, a market that opens at night); false if the place is open all day and merely nicer then"))


class TimedPlaces(BaseModel):
    places: list[TimedPlace] = Field(default_factory=list)


async def best_times(city: str, country: str, names: list[str]) -> dict[str, str]:
    """Which sights and activities happen at a set time of day (a Kecak dance at sunset, a Batur trek at sunrise, a
    night market), from the model's knowledge of the places - their names alone rarely say so. One call per city."""
    if not names:
        return {}
    res = await _ask(
        "You are a local travel expert. For each place, when is it normally visited or performed? 'sunrise' (dawn treks "
        "and viewpoints people go to for the sunrise), 'sunset' (sunset shows and places famous for the sunset), "
        "'night' (night markets, evening shows, night tours), else 'any'. Mark a time only when the experience itself "
        "happens then - a show's performance time, a trek timed for the sunrise, a market that opens at night. A sight "
        "that is open all day and merely prettier at sunset is 'any'.",
        {"city": f"{city}, {country}", "places": names[:80]}, TimedPlaces)
    # Only fixed times constrain the schedule: a temple that is merely prettier at sunset stays free to move.
    return {p.name.strip().lower(): p.best_time for p in (res.places if res else []) if p.best_time != "any" and p.only_then}


class AIAirport(BaseModel):
    iata: str
    name: str


class AIAirports(BaseModel):
    airports: list[AIAirport]


async def airports(city: str, country: str) -> list[AIAirport]:
    res = await _ask("List the commercial airports (IATA codes) that serve the city, main one first. Real airports only.",
                     {"city": city, "country": country}, AIAirports)
    return [a for a in (res.airports if res else []) if len(a.iata) == 3][:3]

