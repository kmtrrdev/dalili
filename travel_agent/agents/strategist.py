"""Strategist agent: designs what each of the four plans means for THIS trip.

The four modes used to differ by a few hard-coded weights, so they came out similar. Now, once research is in, the
model looks at the real options (airlines and fares found, hotel prices and ratings, restaurant levels, the top sights)
and the traveller, and writes one strategy per mode:

- budget     : the least money for a good trip - cheapest fares (red-eyes and low-cost carriers fine), a clean, decent
               and central cheap hotel, street food and markets, free sights plus the icons, public transport.
- balanced   : the best value - good flight times, a well-rated central hotel at a fair price, good local restaurants.
- comfort    : ease and quality - full-service airlines and direct, sensible times, highly rated 4-5 star hotels,
               excellent restaurants, taxis, a calmer pace.
- experience : the most memorable trip - the destination's signature experiences (found for real on Google Maps),
               famous local food, a fuller pace.

The deterministic planner applies the strategy (filters, weights, knobs) and still verifies every time, price and
opening hour. Without a model, sensible defaults are used.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

from .. import llm
from ..models import TripState
from . import trace

log = logging.getLogger(__name__)


class FlightPrefs(BaseModel):
    price_weight: float = Field(0.5, description="0-1: how much the fare matters vs comfort (directness, duration, times)")
    allow_red_eye: bool = Field(False, description="True if night / very early flights are fine when cheaper")
    preferred_airlines: list[str] = Field(default_factory=list, description=(
        "Airlines from 'airlines_found' this plan should prefer (e.g. full-service carriers for comfort), exact names"))


class HotelPrefs(BaseModel):
    min_rating: float = Field(3.8, description="Minimum guest rating out of 5 (from the ratings available)")
    min_stars: int = Field(0, description="Minimum hotel class 0-5 (0 = any)")
    rating_weight: float = Field(0.4, description="0-1: how much guest rating / quality matters")
    price_weight: float = Field(0.4, description="0-1: how much the nightly price matters")
    location_weight: float = Field(0.4, description="0-1: how much being central matters")
    shortlist: list[str] = Field(default_factory=list, description=(
        "Up to 5 exact names from 'hotels_list' that best deliver this plan's promise (e.g. comfort: real 4-5 star "
        "hotels and trusted brands - never a hostel; budget: clean cheap places). Different plans should "
        "shortlist different hotels where the data allows"))


class FoodPrefs(BaseModel):
    min_price_level: int = Field(1, description="1 street food/cheap ... 4 fine dining")
    max_price_level: int = Field(3, description="1-4")
    min_rating: float = Field(4.0, description="Minimum restaurant rating out of 5")
    price_weight: float = Field(0.3, description="0-1: how much a cheaper meal matters vs a better one")


class ActivityPrefs(BaseModel):
    paid_ok: bool = Field(True, description="False = prefer free sights (the city's icons always stay)")
    pace_delta: int = Field(0, description="-1 calmer, 0 as the traveller likes, +1 fuller days")
    signature_experiences: list[str] = Field(default_factory=list, description=(
        "Only for experience (empty for the other plans): 2-4 real, famous, bookable experiences that define this "
        "destination (e.g. 'Desert safari Dubai', 'Bosphorus dinner cruise Istanbul'), named so Google Maps finds them"))


class CityPicks(BaseModel):
    city: str = Field(description="The city, exactly as in 'cities'")
    hotel_shortlist: list[str] = Field(default_factory=list, description="Up to 4 exact hotel names from that city's list")
    signature_experiences: list[str] = Field(default_factory=list, description=(
        "Experience plan only (empty for the others): 1-3 real, famous, bookable experiences that define THIS city"))


class ModeStrategy(BaseModel):
    headline: str = Field(description="One short English sentence: what this plan optimises for this traveller")
    headline_ar: str = Field(description="The same sentence in natural Egyptian Arabic")
    flights: FlightPrefs = Field(default_factory=FlightPrefs)
    hotel: HotelPrefs = Field(default_factory=HotelPrefs)
    food: FoodPrefs = Field(default_factory=FoodPrefs)
    activities: ActivityPrefs = Field(default_factory=ActivityPrefs)
    transport: Literal["public", "mixed", "taxi"] = "mixed"
    cities: list[CityPicks] = Field(default_factory=list, description=(
        "Multi-city trips only: one entry per city in 'cities' with this plan's hotel shortlist (and, for "
        "experience, signature experiences) for that city. Empty for a single-city trip"))
    budget_stretch: float = Field(0.0, description=(
        "0-0.5: how far over the traveller's budget this plan may go to deliver its promise (an upgrade shown with "
        "its real extra cost). Always 0 for budget and balanced."))


class Strategies(BaseModel):
    budget: ModeStrategy
    balanced: ModeStrategy
    comfort: ModeStrategy
    experience: ModeStrategy


SYSTEM = """You are the strategist of an AI travel planner. Design what each of four plans means for THIS trip and
traveller, using only the real options in the data (airlines found with their cheapest fares, hotel ratings and prices,
restaurant price levels, top sights). Make the four plans clearly DIFFERENT:
- budget: the least money for a good trip. Cheapest fares (red-eyes and low-cost carriers fine: allow_red_eye true,
  price_weight ~0.9), a clean decent cheap hotel that is still central (min_rating ~3.8, price_weight high, rating
  and location moderate), street food and cheap local places (food levels 1-2, food price_weight ~0.9), free sights
  (paid_ok false - icons stay anyway), public transport, budget_stretch 0.
- balanced: best value. Good flight times at a fair price (price_weight ~0.5), well-rated central hotel
  (min_rating ~4.1, weights balanced), good local restaurants (levels 1-3, food price_weight ~0.4), mixed transport,
  budget_stretch 0.
- comfort: ease and quality over price. Full-service airlines from airlines_found in preferred_airlines (e.g. the
  national carriers, not low-cost ones), flight price_weight ~0.2, highly rated hotels (min_rating ~4.5, min_stars 4
  if such hotels exist in the data, hotel rating_weight ~0.9, price_weight ~0.15), the best restaurants (the highest
  levels in the data, min_rating ~4.5, food price_weight ~0.05), taxis, pace_delta -1, budget_stretch 0.2-0.5 (enough to afford the shortlisted hotels).
- experience: the most memorable trip. 2-4 signature_experiences that truly define this destination (real, famous,
  bookable - e.g. a desert safari in Dubai, a Bosphorus cruise in Istanbul, a cooking class in Rome), a characterful
  well-rated hotel in the most atmospheric area (rating_weight ~0.6, location_weight ~0.8), famous local food
  (levels 1-3, min_rating ~4.5, food price_weight ~0.2), pace_delta +1, mixed transport, budget_stretch 0.15-0.4.
Multi-city trip ('cities' present): fill 'cities' in every plan - for each city its own hotel shortlist from that
city's hotels_list and, for experience, 1-3 signature experiences of THAT city (e.g. a gondola ride in Venice, a
Florence cooking class) - and leave the top-level shortlist and signature_experiences empty.
For every plan also shortlist the hotels (by exact name from hotels_list) that truly fit it - judge by name, brand,
type and rating, not only the numbers (a "hostel" is never a comfort hotel, even if listed as 4-star). Comfort and
experience are upgrades: they keep their promise even when the traveller's budget is tight - the traveller sees
exactly how much more they cost and decides. Make each plan's hotel and flights differ from budget's whenever the
data offers a real alternative. For comfort and experience, include in each shortlist at least one hotel that
keeps the plan within the budget plus its budget_stretch when the data has one, so the upgrade stays reachable.
Respect the traveller: never contradict their stated preferences (e.g. 'direct flights only', dietary needs, a
low walking tolerance). Keep thresholds achievable with the options in the data. Headlines are short and concrete."""


DEFAULTS = Strategies(
    budget=ModeStrategy(headline="The least money for a good trip", headline_ar="أقل فلوس لرحلة كويسة",
                        flights=FlightPrefs(price_weight=0.9, allow_red_eye=True),
                        hotel=HotelPrefs(min_rating=3.6, rating_weight=0.25, price_weight=0.7, location_weight=0.3),
                        food=FoodPrefs(min_price_level=1, max_price_level=2, min_rating=3.8, price_weight=0.9),
                        activities=ActivityPrefs(paid_ok=False), transport="public"),
    balanced=ModeStrategy(headline="The best value for your money", headline_ar="أحسن قيمة مقابل فلوسك",
                          flights=FlightPrefs(price_weight=0.5), hotel=HotelPrefs(min_rating=4.0),
                          food=FoodPrefs(max_price_level=3, min_rating=4.0, price_weight=0.4)),
    comfort=ModeStrategy(headline="Comfort first: better flights, hotel and restaurants",
                         headline_ar="الراحة أولاً: طيران وفندق ومطاعم أحسن",
                         flights=FlightPrefs(price_weight=0.2),
                         hotel=HotelPrefs(min_rating=4.4, min_stars=4, rating_weight=0.9, price_weight=0.15,
                                          location_weight=0.45),
                         food=FoodPrefs(min_price_level=2, max_price_level=4, min_rating=4.4, price_weight=0.05),
                         activities=ActivityPrefs(pace_delta=-1), transport="taxi", budget_stretch=0.35),
    experience=ModeStrategy(headline="The most memorable trip: signature experiences",
                            headline_ar="أمتع رحلة: أشهر التجارب المميزة",
                            flights=FlightPrefs(price_weight=0.4),
                            hotel=HotelPrefs(min_rating=4.2, rating_weight=0.6, location_weight=0.6),
                            food=FoodPrefs(max_price_level=3, min_rating=4.3, price_weight=0.2),
                            activities=ActivityPrefs(pace_delta=1), budget_stretch=0.25),
)


def _research_summary(trip: TripState) -> dict:
    r, c = trip.research, trip.trip_contract
    airlines: dict[str, float] = {}
    for f in r.flights_outbound + r.flights_return:
        for name in f.airline.split(" + "):
            airlines[name] = min(airlines.get(name, 1e12), f.price_per_person.amount)
    def city(b, limit: int) -> dict:
        hotels = sorted(b.hotels, key=lambda h: h.price_per_night.amount)
        half = limit // 2
        return {
            "hotels": {"count": len(hotels),
                       "nightly_price_range": [round(hotels[0].price_per_night.amount), round(hotels[-1].price_per_night.amount)] if hotels else None,
                       "ratings": sorted({round(h.rating, 1) for h in hotels if h.rating})[-8:],
                       "stars_available": sorted({h.stars for h in hotels if h.stars})},
            "hotels_list": [{"name": h.name, "rating": h.rating, "stars": h.stars, "per_night": round(h.price_per_night.amount),
                             "type": h.style or None} for h in (hotels if len(hotels) <= limit else hotels[:half + 1] + hotels[-half:])],
            "restaurant_price_levels": sorted({p.price_level for p in b.restaurants}),
            "top_sights": [a.name for a in sorted(b.attractions, key=lambda a: -(a.reviews_count or 0))[:10]],
        }

    base = {
        "destination": c.destination_name, "nights": c.nights, "travelers": c.travelers,
        "budget": f"{c.budget.amount:,.0f} {c.budget.currency}",
        "airlines_found": [{"airline": a, "cheapest_fare": round(p)} for a, p in sorted(airlines.items(), key=lambda x: x[1])][:12],
    }
    if c.is_multi and r.stops:
        # Each city with its own hotels and sights: the plans shortlist hotels and experiences city by city.
        base["cities"] = [{"city": s.name, "nights": s.nights, **city(b, 16)} for s, b in zip(c.stops, r.stops)]
        return base
    return {**base, **city(r, 25)}


def for_city(strategy: ModeStrategy, city: str) -> ModeStrategy:
    """One plan's strategy for one city of a multi-city trip: that city's hotel shortlist and signature experiences."""
    name = city.strip().lower()
    picks = next((p for p in strategy.cities if p.city.strip().lower() in name or name in p.city.strip().lower()), None)
    if picks is None:
        return strategy
    return strategy.model_copy(update={
        "hotel": strategy.hotel.model_copy(update={"shortlist": picks.hotel_shortlist}),
        "activities": strategy.activities.model_copy(update={"signature_experiences": picks.signature_experiences})})


async def design(trip: TripState) -> Strategies:
    """The four strategies for this trip (cached on the trip until the destination, dates or profile change)."""
    c, r, p = trip.trip_contract, trip.research, trip.traveler_profile
    if c is None or r is None:
        return DEFAULTS
    key = f"{c.route_name}|{c.start_date}|{c.end_date}|{c.travelers}|{c.budget.currency}|{p.model_dump_json(exclude={'learned'})}"
    cached = trip.metadata.get("strategies")
    if cached and cached.get("key") == key:
        try:
            return Strategies.model_validate(cached["value"])
        except ValueError:
            pass
    if not llm.available():
        return DEFAULTS
    payload = {"trip": _research_summary(trip),
               "traveller": p.model_dump(include={"travel_style", "walking_tolerance", "transport_preference",
                                                   "activity_preferences", "food_preferences", "dietary_restrictions",
                                                   "flight_preference", "avoid_early_flights", "hotel_style"})}
    out = await llm.parse(SYSTEM, json.dumps(payload, ensure_ascii=False, default=str), Strategies, effort="low")
    if out is None:
        return DEFAULTS
    # The traveller's budget is a promise for the budget and balanced plans; upgrades stretch it by at most 50%.
    for mode in ("budget", "balanced", "comfort", "experience"):
        s = getattr(out, mode)
        s.budget_stretch = 0.0 if mode in ("budget", "balanced") else min(max(s.budget_stretch, 0.0), 0.5)
    trip.metadata["strategies"] = {"key": key, "value": out.model_dump()}
    trace.step(trip, "strategist", "decision", " | ".join(f"{m}: {getattr(out, m).headline}" for m in
                                                         ("budget", "balanced", "comfort", "experience")))
    return out
