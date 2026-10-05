"""Data quality gate for research results: bad external data never reaches the itinerary silently.

Checks every researched entity for impossible coordinates, duplicates (the same place under two ids or listings)
and implausible prices relative to the rest of the same search; what is dropped is reported in the research errors
so the reply and the Trip Book can say so. Thresholds are statistical (relative to the city's own data), not travel
rules.
"""

from __future__ import annotations

import re
import statistics

from .models import ResearchBundle
from .utils import haversine_km

DUPLICATE_KM = 0.15       # two listings with the same name this close are one place
PRICE_OUTLIER_X = 15.0    # a nightly price 15x the city's median (or 1/15th) is a data error, not a deal


def _valid_point(p) -> bool:
    return p is not None and -90 <= p.lat <= 90 and -180 <= p.lon <= 180 and not (abs(p.lat) < 1e-6 and abs(p.lon) < 1e-6)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _dedupe(items: list, label: str, notes: list[str]) -> list:
    kept: list = []
    for x in items:
        twin = next((k for k in kept if _norm(k.name) == _norm(x.name)
                     and haversine_km(k.location.lat, k.location.lon, x.location.lat, x.location.lon) <= DUPLICATE_KM), None)
        if twin is None:
            kept.append(x)
        elif (getattr(x, "reviews_count", 0) or 0) > (getattr(twin, "reviews_count", 0) or 0):
            kept[kept.index(twin)] = x  # keep the better-documented listing
    if len(kept) < len(items):
        notes.append(f"data quality: merged {len(items) - len(kept)} duplicate {label} listing(s)")
    return kept


def check(bundle: ResearchBundle) -> list[str]:
    """Clean the bundle in place; returns what was removed or merged (also appended to bundle.errors)."""
    notes: list[str] = []
    for attr, label in (("attractions", "place"), ("restaurants", "restaurant"), ("hotels", "hotel")):
        items = getattr(bundle, attr)
        valid = [x for x in items if _valid_point(x.location)]
        if len(valid) < len(items):
            notes.append(f"data quality: dropped {len(items) - len(valid)} {label}(s) with invalid coordinates")
        setattr(bundle, attr, _dedupe(valid, label, notes))
    prices = [h.price_per_night.amount for h in bundle.hotels if h.price_per_night.amount > 0]
    if len(prices) >= 5:
        med = statistics.median(prices)
        sane = [h for h in bundle.hotels
                if h.price_per_night.amount <= 0 or med / PRICE_OUTLIER_X <= h.price_per_night.amount <= med * PRICE_OUTLIER_X]
        if len(sane) < len(bundle.hotels):
            notes.append(f"data quality: dropped {len(bundle.hotels) - len(sane)} hotel(s) with an implausible price")
            bundle.hotels = sane
    for f in bundle.flights_outbound + bundle.flights_return:
        if f.arrive_at <= f.depart_at:
            notes.append(f"data quality: flight {f.flight_number} arrives before it departs - dropped")
    bundle.flights_outbound = [f for f in bundle.flights_outbound if f.arrive_at > f.depart_at]
    bundle.flights_return = [f for f in bundle.flights_return if f.arrive_at > f.depart_at]
    bundle.errors.extend(n for n in notes if n not in bundle.errors)
    return notes
