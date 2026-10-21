"""Travel times: openrouteservice matrices (walk / drive) + Google Maps Directions for airport transfers.

`prepare()` fetches real walking and driving matrices for every point the planner may
use (hotels, attractions, restaurants) in a few ORS calls; the synchronous planner then
looks legs up instantly. Pairs outside the matrix fall back to a distance-based estimate.
Public transport time inside the city is estimated from driving time (ORS has no transit).
"""

from __future__ import annotations

import hashlib
import logging
import math
import re

from .. import net
from ..config import settings
from ..models import GeoPoint, Metadata, Money, TransferOption, TransportLeg
from ..utils import haversine_km

log = logging.getLogger(__name__)
ORS_MATRIX = "https://api.openrouteservice.org/v2/matrix/{profile}"
MAX_ELEMENTS = 3500  # ORS limit per matrix request

# Max single walking leg (km) and max walking per day (km) for each tolerance.
WALK_LIMITS = {"low": (1.0, 5.0), "medium": (2.0, 9.0), "high": (3.5, 15.0)}

# (from_key, to_key) -> (walk_min, walk_km, drive_min, drive_km)
_matrix: dict[tuple[str, str], tuple[float, float, float, float]] = {}


def key(p: GeoPoint) -> str:
    return f"{p.lat:.5f},{p.lon:.5f}"


async def _ors(profile: str, points: list[GeoPoint], sources: list[int]) -> dict:
    if not settings.ors_key:
        raise net.ProviderError("ORS_API_KEY is not configured")
    body = {"locations": [[p.lon, p.lat] for p in points], "sources": sources, "metrics": ["duration", "distance"], "units": "km"}
    return await net.fetch_json("ors", ORS_MATRIX.format(profile=profile), ttl_s=180 * net.DAY, method="POST",
                                json_body=body, headers={"Authorization": settings.ors_key})


async def prepare(points: list[GeoPoint]) -> int:
    """Load real walking/driving times between all points. Returns number of pairs known."""
    uniq: dict[str, GeoPoint] = {}
    for p in points:
        uniq.setdefault(key(p), p)
    pts = list(uniq.values())
    if len(pts) < 2:
        return 0
    todo = [i for i in range(len(pts)) if (key(pts[i]), key(pts[-1])) not in _matrix]
    if not todo:
        return len(_matrix)
    chunk = max(1, MAX_ELEMENTS // len(pts))
    for start in range(0, len(pts), chunk):
        sources = list(range(start, min(start + chunk, len(pts))))
        try:
            walk = await _ors("foot-walking", pts, sources)
            drive = await _ors("driving-car", pts, sources)
        except net.ProviderError as exc:
            log.warning("openrouteservice unavailable, using distance estimates: %s", exc)
            return len(_matrix)
        for si, src in enumerate(sources):
            for dj in range(len(pts)):
                wm, wk = (walk["durations"][si][dj], walk["distances"][si][dj])
                dm, dk = (drive["durations"][si][dj], drive["distances"][si][dj])
                if None in (wm, wk, dm, dk):
                    continue
                _matrix[(key(pts[src]), key(pts[dj]))] = (wm / 60, wk, dm / 60, dk)
    return len(_matrix)


def lookup(a: GeoPoint, b: GeoPoint) -> tuple[float, float, float, float, bool]:
    """(walk_min, walk_km, drive_min, drive_km, measured)."""
    hit = _matrix.get((key(a), key(b)))
    if hit:
        return (*hit, True)
    km = haversine_km(a.lat, a.lon, b.lat, b.lon)
    road = km * 1.35
    # City traffic averages ~22 km/h for the first ~12 km; the rest of a longer drive is on faster roads (~70 km/h).
    drive = 4 + min(road, 12) / 22 * 60 + max(road - 12, 0) / 70 * 60
    return km * 1.3 / 4.5 * 60, km * 1.3, drive, road, False


def options(a: GeoPoint, b: GeoPoint, travelers: int, fares: dict[str, float], currency: str) -> list[TransportLeg]:
    wmin, wkm, dmin, dkm, measured = lookup(a, b)
    src = "openrouteservice" if measured else "distance estimate"
    taxis = max(1, math.ceil(travelers / 4))
    taxi_cost = (fares.get("taxi_base", 4.0) + fares.get("taxi_per_km", 1.6) * dkm) * taxis
    transit_min = int(round(max(dmin * 1.5, 8) + 8))  # waiting + slower than a car; ORS has no transit
    # Fares are verified when they come from the city's published ticket price / official taxi tariff.
    transit_known, taxi_tariff = fares.get("transit_verified"), fares.get("taxi_verified")
    transit_src = "Single ticket price (Wikivoyage)" if transit_known else \
        "AI estimate · typical single ticket" if fares.get("transit_ai") else None
    taxi_src = f"Official taxi tariff (Wikivoyage) x {dkm:.1f} km by road" if taxi_tariff else \
        f"AI estimate · typical tariff x {dkm:.1f} km" if fares.get("taxi_ai") else None
    return [
        TransportLeg(mode="walk", minutes=max(1, int(round(wmin))), distance_km=round(wkm, 2),
                     cost=Money(amount=0, currency=currency, price_type="known"), description=f"Walk {wkm:.1f} km ({src})"),
        TransportLeg(mode="transit", minutes=transit_min, distance_km=round(dkm, 2),
                     cost=Money(amount=fares.get("transit", 2.0) * travelers, currency=currency,
                                price_type="known" if transit_known else "estimated", source=transit_src),
                     description="Public transport (time estimated; " + ("official single-ticket fare)" if transit_known
                                                                         else "fare estimated)")),
        TransportLeg(mode="taxi", minutes=int(round(dmin + 4)), distance_km=round(dkm, 2),
                     cost=Money(amount=round(taxi_cost, 2), currency=currency,
                                price_type="calculated" if taxi_tariff else "estimated", source=taxi_src),
                     description=f"Taxi (drive time {src}, " + ("fare from the official tariff)" if taxi_tariff
                                                                  else "fare estimated)")),
    ]


INTERCITY_KM = 50  # beyond this, city transit is the wrong model: use train/coach or a private driver


def intercity_options(a: GeoPoint, b: GeoPoint, travelers: int, fares: dict[str, float], currency: str) -> list[TransportLeg]:
    _, _, dmin, dkm, measured = lookup(a, b)
    src = "openrouteservice" if measured else "distance estimate"
    per_person = fares.get("intercity_base", 3.0) + fares.get("intercity_per_km", 0.06) * dkm
    driver = (fares.get("taxi_base", 4.0) + fares.get("taxi_per_km", 1.6) * dkm * 0.8) * max(1, math.ceil(travelers / 4))
    return [
        # Regional trains run about as fast as the drive, plus getting to / waiting at the station.
        TransportLeg(mode="train", minutes=int(round(min(dmin * 1.2, dkm / 85 * 60) + 25)), distance_km=round(dkm, 1),
                     cost=Money(amount=round(per_person * travelers, 2), currency=currency),
                     description=f"Train / coach between cities ({dkm:.0f} km by road, {src}; time and fare estimated)"),
        TransportLeg(mode="taxi", minutes=int(round(dmin + 10)), distance_km=round(dkm, 1),
                     cost=Money(amount=round(driver, 2), currency=currency),
                     description=f"Private driver ({dkm:.0f} km, {src}; fare estimated)"),
    ]


def best_leg(a: GeoPoint, b: GeoPoint, walking_tolerance: str, travelers: int, fares: dict[str, float],
             currency: str, prefer_taxi: bool = False) -> TransportLeg:
    if haversine_km(a.lat, a.lon, b.lat, b.lon) > INTERCITY_KM:
        train, driver = intercity_options(a, b, travelers, fares, currency)
        return driver if prefer_taxi else train
    walk, transit, taxi = options(a, b, travelers, fares, currency)
    max_leg, _ = WALK_LIMITS.get(walking_tolerance, WALK_LIMITS["medium"])
    if walk.distance_km <= max_leg:
        return walk
    if prefer_taxi or transit.minutes > taxi.minutes * 2.2:
        return taxi
    return transit


# ---------------------------------------------------------------------------
# Google Maps Directions (SerpApi): airport <-> city centre
# ---------------------------------------------------------------------------


async def directions(start: str, end: GeoPoint | str, travel_mode: int = 6) -> list[dict]:
    params = {"start_addr": start, "travel_mode": travel_mode, "hl": settings.language}
    if isinstance(end, GeoPoint):
        params["end_coords"] = f"{end.lat},{end.lon}"
    else:
        params["end_addr"] = end
    data = await net.serpapi("google_maps_directions", 30 * net.DAY, **params)
    # Google publishes the transit fare ("cost" + "currency") for many routes: real, not estimated.
    return [{k: d.get(k) for k in ("travel_mode", "via", "distance", "duration", "formatted_duration",
                                   "formatted_distance", "start_time", "end_time", "extensions", "cost", "currency")}
            for d in data.get("directions", [])]


def google_fare(route: dict | None) -> Money | None:
    """The fare Google Maps shows for a transit route, per person, in the local currency (None if not shown)."""
    if not route or route.get("cost") in (None, "") or not route.get("currency"):
        return None
    try:
        amount = float(route["cost"])
    except (TypeError, ValueError):
        return None
    return Money(amount=amount, currency=str(route["currency"]).upper(), price_type="known",
                 source="Google Maps transit fare") if amount > 0 else None


GROUND_FARE_USD = {"train": (8.0, 0.12), "coach": (4.0, 0.06)}  # per person: base + per road km (estimate)
GROUND_DEPARTURES = ("09:30", "14:00")                            # typical departures offered to the planner


async def intercity_journeys(from_name: str, from_pt: GeoPoint, to_name: str, to_pt: GeoPoint, on, dep_tz: str,
                             arr_tz: str) -> list:
    """Train / coach between two stops of a multi-city trip.

    Travel time comes from Google Maps Directions (transit) when available; fares are estimates
    (no free API publishes rail fares) and departures are offered at typical times.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from ..models import FlightOption

    try:
        routes = await directions(from_name, to_pt)
    except net.ProviderError as exc:
        log.warning("intercity directions unavailable: %s", exc)
        routes = []
    transit = next((r for r in routes if (r.get("travel_mode") or "").lower() == "transit" and r.get("duration")), None)
    drive = next((r for r in routes if (r.get("travel_mode") or "").lower() == "driving" and r.get("duration")), None)
    straight = haversine_km(from_pt.lat, from_pt.lon, to_pt.lat, to_pt.lon)
    road_km = (drive.get("distance") or 0) / 1000 if drive and drive.get("distance") else straight * 1.25
    candidates = []
    if transit:
        text = " ".join([str(transit.get("via") or "")] + [str(e) for e in transit.get("extensions") or []]).lower()
        mode = "coach" if ("bus" in text and "train" not in text and "rail" not in text) else "train"
        candidates.append((mode, int(transit["duration"] / 60), "Google Maps Directions (SerpApi)", 0.8,
                           f"{transit.get('formatted_duration')} by public transport on Google Maps"
                           + (f" via {transit['via']}" if transit.get("via") else "")))
    elif drive and road_km <= 750:
        candidates.append(("coach", int(drive["duration"] / 60 * 1.15) + 20, "Google Maps Directions (SerpApi)", 0.6,
                           f"Coach estimated from a {drive.get('formatted_duration')} drive on Google Maps"))
    elif not routes and road_km <= 750:
        # No live directions: don't promise a railway that may not exist - a coach (bus) runs almost everywhere.
        candidates.append(("coach", int(road_km / 65 * 60) + 30, "distance estimate", 0.4,
                           f"About {road_km:.0f} km by road; coach time estimated from distance"))
    out = []
    real = google_fare(transit)
    for mode, minutes, provider, conf, note in candidates:
        base, per_km = GROUND_FARE_USD[mode]
        # Google's own fare for this public-transport route when it shows one; otherwise a labelled estimate.
        price = real if (real and transit and provider.startswith("Google") and conf >= 0.8) else \
            Money(amount=round(base + per_km * road_km, 0), currency="USD", price_type="estimated")
        fare_note = (f"the fare ({price.amount:g} {price.currency}) is the one Google Maps shows for this route"
                     if price.price_type == "known" else "the fare is an estimate")
        for hhmm in GROUND_DEPARTURES:
            dep = datetime.combine(on, datetime.strptime(hhmm, "%H:%M").time()).replace(tzinfo=ZoneInfo(dep_tz))
            arr = (dep + timedelta(minutes=minutes)).astimezone(ZoneInfo(arr_tz))
            label = "Train" if mode == "train" else "Coach"
            fid = f"fl_{mode}_" + hashlib.sha1(f"{from_name}|{to_name}|{on.isoformat()}|{hhmm}".encode()).hexdigest()[:10]
            out.append(FlightOption(
                id=fid, direction="outbound", mode=mode, airline=label, flight_number=f"{label} {hhmm}",
                origin=from_name, destination=to_name, depart_at=dep, arrive_at=arr, duration_minutes=minutes, stops=0,
                price_per_person=price, baggage="Luggage travels with you", cabin="standard",
                segments=[f"{label} {from_name} {hhmm} -> {to_name} {arr:%H:%M} (~{road_km:.0f} km)"],
                metadata=Metadata(source="transport_mcp", provider=provider, confidence=conf,
                                  notes=f"{note}. Departure time is a typical slot and {fare_note} - "
                                        "check the operator for exact schedules and prices.")))
    return out


async def _estimated_transfers(airport_code: str, airport_name: str, center: GeoPoint, fares: dict[str, float],
                               currency: str, live_error: Exception) -> list[TransferOption]:
    """Google Maps Directions unavailable: locate the airport (Geoapify) and estimate from the distance."""
    from . import geo

    try:
        hit = await geo.geocode(airport_name, city_only=False)
    except net.ProviderError:
        hit = None
    if not hit:
        raise live_error if isinstance(live_error, net.ProviderError) else net.ProviderError(str(live_error))
    ap = GeoPoint(lat=float(hit["lat"]), lon=float(hit["lon"]))
    _, _, dmin, dkm, _ = lookup(ap, center)
    meta = Metadata(source="transport_mcp", provider="distance estimate (live directions unavailable)", confidence=0.4,
                    notes="Airport located with Geoapify; time and fare estimated from the distance.")
    return [
        TransferOption(id=f"{airport_code}_taxi", mode="taxi", airport=airport_code, name=f"Taxi {airport_code} -> hotel",
                       minutes=int(dmin) + 10,
                       cost_per_vehicle=Money(amount=round(fares.get("taxi_base", 4.0) + fares.get("taxi_per_km", 1.6) * dkm, 2),
                                              currency=currency),
                       notes=f"About {dkm:.0f} km by road (estimate).", metadata=meta),
        TransferOption(id=f"{airport_code}_transit", mode="transit", airport=airport_code,
                       name=f"Public transport {airport_code} -> city centre", minutes=int(dmin * 1.6) + 20,
                       cost_per_person=Money(amount=round(fares.get("airport_transit", 10.0), 2), currency=currency),
                       notes="Time and fare estimated - check the airport's official transport page.", metadata=meta),
    ]


def _fixed_fare(fixed: list[dict], airport_code: str, airport_name: str, modes: set[str]) -> dict | None:
    """A fixed airport fare quoted in the city guide for this airport (by code or a distinctive name word)."""
    words = {w for w in re.findall(r"[a-z]{4,}", airport_name.lower()) if w not in ("airport", "international", "aeroport")}
    for f in fixed:
        if f.get("mode") not in modes:
            continue
        text = f"{f.get('airport', '')} {f.get('quote', '')}".lower()
        if airport_code.lower() in re.findall(r"[a-z]{3}", text) or any(w in text for w in words):
            return f
    return None


async def airport_transfers(airport_code: str, airport_name: str, center: GeoPoint, fares: dict[str, float],
                            currency: str, fixed_fares: list[dict] | None = None) -> list[TransferOption]:
    try:
        routes = await directions(airport_name, center)
    except net.ProviderError as exc:
        return await _estimated_transfers(airport_code, airport_name, center, fares, currency, exc)
    fixed = fixed_fares or []
    out: list[TransferOption] = []
    drive = next((r for r in routes if (r.get("travel_mode") or "").lower() == "driving"), None)
    transit = next((r for r in routes if (r.get("travel_mode") or "").lower() == "transit"), None)
    meta = Metadata(source="transport_mcp", provider="Google Maps Directions (SerpApi)", confidence=0.8,
                    notes="Travel time from Google Maps.")
    if transit and transit.get("duration"):
        # 1) Google's own fare for the route  2) a fixed fare quoted in the city guide  3) a labelled estimate
        price = google_fare(transit)
        fare_note = "Fare shown by Google Maps."
        if price is None and (f := _fixed_fare(fixed, airport_code, airport_name, {"bus", "train", "metro", "shuttle"})):
            price = Money(amount=f["amount"], currency=f["currency"], price_type="known", source=f'Wikivoyage: "{f["quote"]}"')
            fare_note = f'Fare quoted in the city guide: "{f["quote"]}".'
        if price is None:
            price = Money(amount=round(fares.get("airport_transit", 10.0), 2), currency=currency)
            fare_note = "Fare not published - estimated."
        out.append(TransferOption(
            id=f"{airport_code}_transit", mode="transit", airport=airport_code,
            name=f"Public transport {airport_code} -> city centre" + (
                f" via {transit['via']}" if transit.get("via") and not str(transit["via"]).lower().startswith("every") else ""),
            minutes=int(transit["duration"] / 60) + 15, cost_per_person=price,
            notes=f"{transit.get('formatted_duration')} on Google Maps + ~15 min to the hotel. {fare_note}", metadata=meta))
    if drive and drive.get("duration"):
        km = (drive.get("distance") or 0) / 1000
        f = _fixed_fare(fixed, airport_code, airport_name, {"taxi"})
        if f:
            price = Money(amount=f["amount"], currency=f["currency"], price_type="known", source=f'Wikivoyage: "{f["quote"]}"')
            fare_note = f'Fixed taxi fare quoted in the city guide: "{f["quote"]}".'
        elif fares.get("taxi_verified"):
            price = Money(amount=round(fares["taxi_base"] + fares["taxi_per_km"] * km, 2), currency=currency,
                          price_type="calculated", source=f"Official taxi tariff (Wikivoyage) x {km:.1f} km by road")
            fare_note = "Fare calculated from the official taxi tariff and the road distance."
        else:
            price = Money(amount=round(fares.get("taxi_base", 4.0) + fares.get("taxi_per_km", 1.6) * km, 2), currency=currency,
                          source=f"AI estimate · typical tariff x {km:.1f} km" if fares.get("taxi_ai") else None)
            fare_note = "Fare not published - estimated; many airports have fixed taxi fares."
        out.append(TransferOption(
            id=f"{airport_code}_taxi", mode="taxi", airport=airport_code, name=f"Taxi {airport_code} -> hotel",
            minutes=int(drive["duration"] / 60) + 10, cost_per_vehicle=price,
            notes=f"{drive.get('formatted_duration')} / {drive.get('formatted_distance')} by road on Google Maps. {fare_note}",
            metadata=meta))
    return out
