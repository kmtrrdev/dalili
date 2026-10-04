"""Candidate scoring with explainable reason codes.

Every scorer returns (score in [0, 1], reasons, trade_offs) so the UI and the
Trip Book can say *why* something was picked.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..models import FlightOption, GeoPoint, HotelOption, Place, PlanningMode, TravelerProfile, TripContract
from ..utils import haversine_km


def distance_km(a: GeoPoint, b: GeoPoint) -> float:
    return haversine_km(a.lat, a.lon, b.lat, b.lon)

INTEREST_SYNONYMS = {
    "museums": {"museums", "art"},
    "art": {"art", "museums"},
    "history": {"history", "architecture", "culture"},
    "culture": {"culture", "history"},
    "food": {"food", "experience"},
    "photography": {"photography"},
    "relaxation": {"relaxation", "nature", "beach"},
    "beach": {"beach", "relaxation"},
    "nature": {"nature", "relaxation"},
    "shopping": {"shopping"},
    "nightlife": {"nightlife", "music"},
    "romantic": {"romantic"},
    "architecture": {"architecture"},
    "adventure": {"adventure", "experience"},
    "family": {"family"},
    "music": {"music", "nightlife"},
}

POPULARITY_BASE = {"must_see": 0.30, "popular": 0.18, "local_favorite": 0.16, "hidden_gem": 0.10, "alternative": 0.05}


@dataclass
class Ranked:
    item: object
    score: float
    reasons: list[str] = field(default_factory=list)
    tradeoffs: list[str] = field(default_factory=list)


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def expand_interests(interests: list[str]) -> set[str]:
    out: set[str] = set()
    for i in interests:
        out |= INTEREST_SYNONYMS.get(i.lower(), {i.lower()})
    return out


# ---------------------------------------------------------------------------
# Flights
# ---------------------------------------------------------------------------


def score_flight(f: FlightOption, pool: list[FlightOption], profile: TravelerProfile, mode: PlanningMode) -> Ranked:
    prices = [p.price_per_person.amount for p in pool] or [f.price_per_person.amount]
    durations = [p.duration_minutes for p in pool] or [f.duration_minutes]
    lo, hi = min(prices), max(prices)
    price_s = 1.0 if hi == lo else 1 - (f.price_per_person.amount - lo) / (hi - lo)
    dur_s = 1.0 if max(durations) == min(durations) else 1 - (f.duration_minutes - min(durations)) / (max(durations) - min(durations))
    reasons, trade = [], []
    dep_h = f.depart_at.hour + f.depart_at.minute / 60
    arr_h = f.arrive_at.hour + f.arrive_at.minute / 60

    time_s = 1.0
    wake_h = int(profile.preferred_wake_up_time.split(":")[0])
    dislikes_early = profile.avoid_early_flights or wake_h >= 9  # late risers dislike dawn departures too
    if dep_h < 8:
        time_s -= 0.6 if dislikes_early else 0.2
        trade.append(f"Early departure ({f.depart_at:%H:%M})")
    elif 9 <= dep_h <= 16:
        reasons.append(f"Comfortable departure time ({f.depart_at:%H:%M})")
    if arr_h >= 23 or arr_h < 5:
        time_s -= 0.45
        trade.append(f"Very late arrival ({f.arrive_at:%H:%M})")
    elif arr_h >= 21 and f.direction == "outbound":
        time_s -= 0.2
        trade.append(f"Evening arrival ({f.arrive_at:%H:%M}) - day one is short")

    direct_s = 1.0 if f.stops == 0 else (0.2 if profile.flight_preference == "direct" else 0.6)
    if f.stops == 0:
        reasons.append("Direct flight")
    else:
        trade.append(f"{f.stops} stop via {f.via}")

    w = {"balanced": (0.35, 0.2, 0.2, 0.25), "budget": (0.6, 0.1, 0.1, 0.2),
         "comfort": (0.15, 0.25, 0.3, 0.3), "experience": (0.3, 0.25, 0.2, 0.25)}[mode]
    score = w[0] * price_s + w[1] * dur_s + w[2] * direct_s + w[3] * clamp(time_s)
    if price_s > 0.85:
        reasons.append("Among the cheapest fares")
    return Ranked(f, round(score, 4), reasons, trade)


# ---------------------------------------------------------------------------
# Hotels
# ---------------------------------------------------------------------------


def score_hotel(h: HotelOption, anchors: list[GeoPoint], profile: TravelerProfile, mode: PlanningMode,
                nightly_budget_local: float) -> Ranked:
    reasons, trade = [], []
    rating_s = clamp((h.rating - 3.4) / 1.5)
    avg_km = sum(distance_km(h.location, a) for a in anchors) / max(len(anchors), 1)
    loc_s = clamp(1 - (avg_km - 1.0) / 4.0)
    if avg_km <= 2.0:
        reasons.append(f"Central: about {avg_km:.1f} km from your top sights")
    elif avg_km > 3.5:
        trade.append(f"Farther from the main sights (~{avg_km:.1f} km)")
    price = h.price_per_night.amount
    price_ratio = price / max(nightly_budget_local, 1)
    price_s = clamp(1.25 - price_ratio * 0.75) if price_ratio <= 1.6 else 0.0
    if price_ratio <= 0.8:
        reasons.append("Comfortably within the hotel budget")
    elif price_ratio > 1.0:
        trade.append("Above the typical nightly budget share")
    extras = 0.0
    if h.breakfast_included:
        extras += 0.5
        reasons.append("Breakfast included")
    if h.free_cancellation:
        extras += 0.3
        reasons.append("Free cancellation available")
    noise_pen = 0.0
    if h.noise_level == "noisy":
        noise_pen = {"low": 0.35, "medium": 0.1, "high": 0.0}[profile.noise_tolerance]
        trade.append("Guests mention noise in recent reviews")
    elif h.noise_level == "quiet":
        reasons.append("Guests describe it as quiet")
    style_s = 0.0
    if profile.hotel_style and profile.hotel_style.lower() in h.style.lower():
        style_s = 0.15
        reasons.append(f"Matches your {profile.hotel_style} style")
    if 0 < h.stars and h.stars + 0.5 < profile.hotel_rating_preference and mode != "budget":
        trade.append(f"{h.stars}-star (you prefer {profile.hotel_rating_preference:g}+)")
        style_s -= 0.1
    if h.rating >= 4.5:
        reasons.append(f"Highly rated ({h.rating}/5)")

    w = {"balanced": (0.3, 0.3, 0.3), "budget": (0.2, 0.25, 0.55),
         "comfort": (0.45, 0.35, 0.1), "experience": (0.3, 0.4, 0.25)}[mode]
    score = w[0] * rating_s + w[1] * loc_s + w[2] * price_s + 0.08 * extras + style_s - noise_pen
    return Ranked(h, round(score, 4), reasons, trade)


# ---------------------------------------------------------------------------
# Attractions / activities
# ---------------------------------------------------------------------------


def must_have_terms(contract: TripContract | None) -> set[str]:
    if contract is None:
        return set()
    terms = set()
    for m in contract.must_have:
        low = m.lower()
        for key in INTEREST_SYNONYMS:
            if key in low:
                terms.add(key)
        if "food" in low or "culinary" in low or "cooking" in low:
            terms.add("food")
        if "historic" in low:
            terms.add("history")
    return terms


def fame(a: Place) -> float:
    """0..1 from the number of Google reviews (log scale): ~1k reviews -> 0, ~500k (the Colosseum) -> 1.
    Review volume is the best public signal of what visitors actually come to a city for."""
    n = a.reviews_count or 0
    return clamp((math.log10(n) - 3.0) / 2.7) if n > 0 else 0.0


def score_attraction(a: Place, profile: TravelerProfile, contract: TripContract | None, mode: PlanningMode,
                     boosts: dict[str, float] | None = None) -> Ranked:
    reasons, trade = [], []
    interests = expand_interests(profile.activity_preferences)
    cats = set(a.categories)
    match = cats & interests
    interest_s = clamp(len(match) / 2)
    if match:
        reasons.append("Matches your interests: " + ", ".join(sorted(match)))
    score = 0.45 * interest_s + POPULARITY_BASE.get(a.popularity, 0.1) + 0.25 * clamp((a.rating - 4.0) / 1.0)
    # First-time visitors come for the icons: a city's most-visited landmarks lead unless the traveller avoids crowds.
    f = fame(a)
    score += (0.15 if profile.prefer_hidden_gems else 0.45) * f
    if f >= 0.85:
        reasons.insert(0, f"One of the city's most visited landmarks ({a.reviews_count:,} Google reviews)")
    elif a.popularity == "must_see":
        reasons.append("Must-see landmark")
    if a.popularity == "hidden_gem":
        if profile.prefer_hidden_gems:
            score += 0.2
            reasons.append("Hidden gem, away from the crowds")
        else:
            reasons.append("Less-touristy local gem")
    if a.popularity == "local_favorite":
        reasons.append("Local favourite")

    mh = must_have_terms(contract) & expand_interests(list(cats))
    if mh:
        score += 0.25
        reasons.append("Covers a must-have: " + ", ".join(sorted(mh)))

    avoided = cats & {c.lower() for c in profile.avoid_categories}
    if avoided:
        score -= 0.6
        trade.append("Category you asked to avoid: " + ", ".join(sorted(avoided)))

    if "nightlife" in cats:
        score += {"low": -0.25, "medium": 0.0, "high": 0.25}[profile.nightlife_interest]
    if "walking" in cats and profile.walking_tolerance == "low":
        score -= 0.15
        trade.append("Involves a fair amount of walking")

    for cat, b in (boosts or {}).items():
        if cat in cats or (cat == "must_see" and (a.popularity == "must_see" or f >= 0.6)):
            score += b

    cost = a.cost_per_person.amount
    if cost == 0:
        reasons.append("Free entry")
    if mode == "budget" and cost > 0:
        score -= 0.1
    if mode == "experience" and a.kind == "activity":
        score += 0.12
    if a.requires_reservation:
        trade.append("Reserve tickets in advance")
    return Ranked(a, round(score, 4), reasons, trade)


# ---------------------------------------------------------------------------
# Restaurants
# ---------------------------------------------------------------------------


def dietary_ok(p: Place, profile: TravelerProfile) -> bool:
    for d in profile.dietary_restrictions:
        d = d.lower()
        if d in ("vegetarian", "vegan") and d not in p.dietary:
            return False
    return True


def score_restaurant(r: Place, profile: TravelerProfile, mode: PlanningMode, price_pressure: int = 0) -> Ranked:
    reasons, trade = [], []
    prefs = {c.lower() for c in profile.food_preferences}
    match = prefs & set(r.cuisine)
    score = 0.35 * clamp((r.rating - 3.8) / 1.0)
    if match:
        score += 0.35
        reasons.append("Cuisine you like: " + ", ".join(sorted(match)))
    if r.popularity in ("local_favorite", "hidden_gem"):
        score += 0.05
    if r.rating >= 4.5:
        reasons.append(f"Highly rated ({r.rating}/5)")
    level_pen = {"budget": 0.12, "balanced": 0.05, "comfort": 0.0, "experience": 0.0}[mode] + 0.06 * price_pressure
    score -= level_pen * (r.price_level - 1)
    if mode in ("experience", "comfort") and r.price_level >= 3:
        score += 0.08
    if r.price_level <= 1:
        reasons.append("Budget-friendly")
    if r.requires_reservation:
        trade.append("Reservation recommended")
    return Ranked(r, round(score, 4), reasons, trade)
