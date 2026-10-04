"""Compact views of a trip that agents reason over (kept small: every token is context the model reads)."""

from __future__ import annotations

from typing import Any

from ..models import GeoPoint, TripState
from ..utils import haversine_km


def plan_summary(trip: TripState, day: int | None = None) -> dict[str, Any]:
    c, p = trip.trip_contract, trip.selected_plan
    if c is None:
        return {"status": "no trip yet"}
    out: dict[str, Any] = {
        "destination": c.route_name, "dates": f"{c.start_date} to {c.end_date}", "travellers": c.travelers,
        "budget": f"{c.budget.amount:.0f} {c.budget.currency}", "origin": c.origin_city,
    }
    if p is None:
        return out
    out["plan_mode"] = trip.selected_mode
    if p.budget:
        out["plan_total"] = f"{p.budget.total:.0f} {p.budget.currency}"
    if p.hotel:
        h = p.hotel
        out["hotel"] = f"{h.name} ({h.neighborhood}), rating {h.rating}, {h.price_per_night.amount:.0f} " \
                       f"{h.price_per_night.currency}/night"
    for key, f in (("outbound_flight", p.outbound_flight), ("return_flight", p.return_flight)):
        if f:
            out[key] = f"{f.airline} {f.flight_number} {f.origin}->{f.destination} {f.depart_at:%a %d %b %H:%M}"
    days = []
    for d in p.days:
        if day and d.day != day:
            continue
        w = d.weather
        days.append({
            "day": d.day, "date": f"{d.date:%a %d %b}", "city": d.city or None, "title": d.title,
            "travel_day": d.travel_day or None,
            "weather": f"{w.condition}, {w.temp_min_c:.0f}-{w.temp_max_c:.0f}C, {w.precipitation_probability}% rain"
            if w else None,
            "walking_km": round(d.walking_km, 1),
            "items": [f"{i.start}-{i.end} {i.kind}{'/' + i.meal_type if i.meal_type else ''}: {i.title}"
                      + (" [outdoor]" if i.indoor is False else "") for i in d.items],
        })
    out["days"] = days
    return out


def profile_summary(trip: TripState) -> dict[str, Any]:
    pr = trip.traveler_profile
    return {"style": pr.travel_style, "interests": pr.activity_preferences, "food": pr.food_preferences,
            "dietary": pr.dietary_restrictions, "walking_tolerance": pr.walking_tolerance,
            "wake_up": pr.preferred_wake_up_time, "nightlife": pr.nightlife_interest,
            "hidden_gems": pr.prefer_hidden_gems, "avoid": pr.avoid_categories}


def anchor(trip: TripState, near: str | None) -> tuple[GeoPoint | None, str]:
    """Where a "near X" question is about: the hotel, a place in the plan, or the city centre."""
    c, p = trip.trip_contract, trip.selected_plan
    text = (near or "").strip().lower()
    if p and (not text or text in ("hotel", "my hotel", "the hotel", "الفندق")) and p.hotel:
        return p.hotel.location, p.hotel.name
    if p and text:
        for d in p.days:
            for i in d.items:
                if i.location and text in i.title.lower():
                    return i.location, i.title
    if trip.research and text:
        for pl in trip.research.attractions + trip.research.restaurants:
            if text in pl.name.lower():
                return pl.location, pl.name
    ref = c.destination_ref if c else None
    return (GeoPoint(lat=ref.lat, lon=ref.lon), ref.name) if ref else (None, "")


def km(a: GeoPoint, lat: float, lon: float) -> float:
    return round(haversine_km(a.lat, a.lon, lat, lon), 2)
