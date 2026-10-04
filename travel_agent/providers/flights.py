"""Flights: Google Flights, Google Flights Deals and Google Travel Explore via SerpApi.

Each direction is searched as a one-way trip with adults=1, so every option carries a
real per-person price and the planner can combine any outbound with any return.
(A round-trip ticket can be cheaper; the Google Flights link is kept for comparison.)
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .. import net
from ..config import settings
from ..models import FlightOption, Metadata, Money

PROVIDER = "Google Flights (SerpApi)"


def _dt(value: str, tz: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tz))


def _parse_itinerary(it: dict, direction: str, dep_tz: str, arr_tz: str, currency: str, url: str | None) -> FlightOption | None:
    segs = it.get("flights") or []
    if not segs or it.get("price") is None:
        return None
    first, last = segs[0], segs[-1]
    numbers = [s.get("flight_number", "?") for s in segs]
    airlines = []
    for s in segs:
        if s.get("airline") and s["airline"] not in airlines:
            airlines.append(s["airline"])
    layovers = [f"{l.get('name', l.get('id'))} ({l.get('id')}), {l.get('duration', 0)} min" + (" overnight" if l.get("overnight") else "")
                for l in it.get("layovers") or []]
    extras = [e for s in segs for e in s.get("extensions", [])] + list(it.get("extensions") or [])
    baggage = next((e for e in extras if "bag" in e.lower()), "See the airline's fare rules for baggage")
    dep_date = first["departure_airport"]["time"][:10]
    fid = "fl_" + hashlib.sha1(f"{'|'.join(numbers)}|{dep_date}".encode()).hexdigest()[:12]
    carbon = (it.get("carbon_emissions") or {}).get("this_flight")
    return FlightOption(
        id=fid,
        direction=direction,  # type: ignore[arg-type]
        airline=" + ".join(airlines),
        flight_number=" / ".join(numbers),
        origin=first["departure_airport"]["id"],
        destination=last["arrival_airport"]["id"],
        depart_at=_dt(first["departure_airport"]["time"], dep_tz),
        arrive_at=_dt(last["arrival_airport"]["time"], arr_tz),
        duration_minutes=int(it.get("total_duration") or sum(s.get("duration", 0) for s in segs)),
        stops=len(segs) - 1,
        via=", ".join(l.get("id", "") for l in it.get("layovers") or []) or None,
        price_per_person=Money(amount=float(it["price"]), currency=currency, price_type="known"),
        baggage=baggage,
        cabin=(first.get("travel_class") or "Economy").lower(),
        segments=[f"{s.get('flight_number')} {s['departure_airport']['id']} {s['departure_airport']['time'][11:]} -> "
                  f"{s['arrival_airport']['id']} {s['arrival_airport']['time'][11:]} ({s.get('airplane', 'aircraft n/a')})" for s in segs],
        layovers=layovers,
        carbon_kg=round(carbon / 1000, 1) if carbon else None,
        booking_url=url,
        metadata=Metadata(source="flight_mcp", provider=PROVIDER, confidence=0.9, source_url=url,
                          notes="Fare found on Google Flights at search time; fares change - confirm before booking."),
    )


async def search_one_way(departure_id: str, arrival_id: str, on: date, currency: str, direction: str,
                         dep_tz: str, arr_tz: str, travel_class: int = 1) -> tuple[list[FlightOption], dict]:
    data = await net.serpapi(
        "google_flights", 6 * net.HOUR, departure_id=departure_id, arrival_id=arrival_id,
        outbound_date=on.isoformat(), type="2", adults=1, currency=currency.upper(), hl=settings.language,
        travel_class=travel_class,
    )
    url = (data.get("search_metadata") or {}).get("google_flights_url")
    options = []
    for it in (data.get("best_flights") or []) + (data.get("other_flights") or []):
        f = _parse_itinerary(it, direction, dep_tz, arr_tz, currency.upper(), url)
        if f and all(x.id != f.id for x in options):
            options.append(f)
    insights = data.get("price_insights") or {}
    return options, {k: insights.get(k) for k in ("lowest_price", "price_level", "typical_price_range")}


async def search_round_trip(departure_id: str, arrival_id: str, out_date: date, back_date: date, currency: str,
                            dep_tz: str, arr_tz: str, travel_class: int = 1) -> list[tuple[FlightOption, FlightOption, float]]:
    """The cheapest round-trip ticket Google Flights sells (2 searches: outbound list, then the return options of the
    cheapest outbound via its departure_token). Returns [(outbound, inbound, total price per person)] with each leg
    priced at half the ticket, or [] when nothing is found."""
    common = dict(departure_id=departure_id, arrival_id=arrival_id, outbound_date=out_date.isoformat(),
                  return_date=back_date.isoformat(), type="1", adults=1, currency=currency.upper(), hl=settings.language,
                  travel_class=travel_class)
    data = await net.serpapi("google_flights", 6 * net.HOUR, **common)
    url = (data.get("search_metadata") or {}).get("google_flights_url")
    its = [it for it in (data.get("best_flights") or []) + (data.get("other_flights") or [])
           if it.get("price") and it.get("departure_token")]
    if not its:
        return []
    first = min(its, key=lambda it: it["price"])
    back_data = await net.serpapi("google_flights", 6 * net.HOUR, departure_token=first["departure_token"], **common)
    backs = [it for it in (back_data.get("best_flights") or []) + (back_data.get("other_flights") or []) if it.get("price")]
    if not backs:
        return []
    second = min(backs, key=lambda it: it["price"])
    total = float(second["price"])  # the return list is priced as the whole round trip
    out = _parse_itinerary({**first, "price": total / 2}, "outbound", dep_tz, arr_tz, currency.upper(), url)
    back = _parse_itinerary({**second, "price": total / 2}, "return", arr_tz, dep_tz, currency.upper(),
                            (back_data.get("search_metadata") or {}).get("google_flights_url") or url)
    if out is None or back is None:
        return []
    note = (f"Part of a round-trip ticket: {total:,.0f} {currency.upper()} per person for both flights "
            "(Google Flights). Book both legs together as one round trip.")
    for f in (out, back):
        f.id += "_rt"
        f.metadata.notes = note
    return [(out, back, total)]


async def deals(departure_id: str, currency: str = "USD") -> list[dict]:
    data = await net.serpapi("google_flights_deals", 12 * net.HOUR, departure_id=departure_id,
                             currency=currency.upper(), hl=settings.language)
    return [{k: d.get(k) for k in ("name", "country", "price", "average_price", "discount_percentage", "start_date",
                                   "end_date", "arrival_airport_code", "airline", "stops", "flight_duration", "flight_link")}
            for d in data.get("deals", [])]


async def explore(departure_id: str, currency: str = "USD", month: int | None = None,
                  travel_duration: int | None = None, interest: str | None = None,
                  outbound_date: str | None = None, return_date: str | None = None, adults: int | None = None,
                  stops: int | None = None, max_duration: int | None = None, arrival_id: str | None = None,
                  arrival_area_id: str | None = None) -> list[dict]:
    """Exact dates (outbound + return) replace month / travel_duration; stops=1 means nonstop only;
    max_duration is the longest acceptable flight in minutes. arrival_area_id limits the ideas to a country /
    region, arrival_id to one city (Google ids from the flights autocomplete)."""
    exact = bool(outbound_date and return_date)
    data = await net.serpapi("google_travel_explore", 12 * net.HOUR, departure_id=departure_id,
                             currency=currency.upper(), hl=settings.language,
                             arrival_id=arrival_id or None, arrival_area_id=None if arrival_id else arrival_area_id,
                             month=None if exact else month, travel_duration=None if exact else travel_duration,
                             outbound_date=outbound_date if exact else None, return_date=return_date if exact else None,
                             adults=adults if adults and adults > 1 else None, stops=stops or None,
                             max_duration=max_duration or None, interest=interest)
    if not data.get("destinations") and data.get("flights"):
        # One city (arrival_id): Google answers with its cheapest flights for suggested dates - no hotel price.
        best = min((f for f in data["flights"] if f.get("price")), key=lambda f: f["price"], default=None)
        if best is None:
            return []
        return [{"destination_id": arrival_id, "name": None, "country": None, "start_date": data.get("start_date"),
                 "end_date": data.get("end_date"), "flight_price": best["price"], "hotel_price": None,
                 "flight_duration": best.get("duration"), "number_of_stops": best.get("number_of_stops"),
                 "airline": best.get("airline"), "link": data.get("google_flights_link"), "thumbnail": None,
                 "airport": (best.get("arrival_airport") or {}).get("id"), "lat": None, "lon": None, "flights_only": True}]
    return [{**{k: d.get(k) for k in ("destination_id", "name", "country", "start_date", "end_date", "flight_price",
                                      "hotel_price", "flight_duration", "number_of_stops", "airline", "link", "thumbnail")},
             "airport": (d.get("destination_airport") or {}).get("code"),
             "lat": (d.get("gps_coordinates") or {}).get("latitude"), "lon": (d.get("gps_coordinates") or {}).get("longitude")}
            for d in data.get("destinations", [])]
