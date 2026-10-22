"""Hotels: Google Hotels search, reviews, photos and autocomplete via SerpApi."""

from __future__ import annotations

import re
from datetime import date

from .. import net
from ..config import settings
from ..models import GeoPoint, HotelOption, Metadata, Money
from ..utils import haversine_km

PROVIDER = "Google Hotels (SerpApi)"
NOISY = re.compile(r"\b(noisy|noise|loud|thin walls|street noise|traffic noise|couldn'?t sleep|hard to sleep|party|nightclub)\b", re.I)
QUIET = re.compile(r"\b(quiet|peaceful|calm|silent|slept well|good sleep)\b", re.I)


def _style(p: dict, stars: int) -> str:
    kind = (p.get("type") or "hotel").lower()
    if kind != "hotel":
        return kind
    if stars >= 5:
        return "luxury"
    if 0 < stars <= 2:
        return "budget"
    return "boutique" if "boutique" in p.get("name", "").lower() else "hotel"


def _to_option(p: dict, currency: str, nights: int, center: GeoPoint) -> HotelOption | None:
    gps = p.get("gps_coordinates") or {}
    rate = (p.get("rate_per_night") or {}).get("extracted_lowest")
    if not gps or rate is None:
        return None
    loc = GeoPoint(lat=gps["latitude"], lon=gps["longitude"])
    stars = int(p.get("extracted_hotel_class") or 0)
    amenities = p.get("amenities") or []
    breakfast = any("breakfast" in a.lower() and "paid" not in a.lower() for a in amenities)
    free_cxl = bool(p.get("free_cancellation")) or any(x.get("free_cancellation") for x in p.get("prices") or [])
    total = (p.get("total_rate") or {}).get("extracted_lowest")
    km = haversine_km(center.lat, center.lon, loc.lat, loc.lon)
    return HotelOption(
        id="h_" + (p.get("property_token") or p["name"])[:40],
        name=p["name"],
        neighborhood=f"{km:.1f} km from the centre",
        location=loc,
        rating=float(p.get("overall_rating") or 0),
        stars=stars,
        price_per_night=Money(amount=float(rate), currency=currency, price_type="known"),
        total_price=Money(amount=float(total), currency=currency, price_type="known") if total else None,
        breakfast_included=breakfast,
        cancellation_policy="Free cancellation available" if free_cxl else "Check the cancellation policy when booking",
        free_cancellation=free_cxl,
        style=_style(p, stars),
        reviews_count=int(p.get("reviews") or 0),
        check_in_time=p.get("check_in_time"),
        check_out_time=p.get("check_out_time"),
        property_token=p.get("property_token"),
        link=p.get("link"),
        images=[i.get("thumbnail") for i in (p.get("images") or [])[:6] if i.get("thumbnail")],
        amenities=amenities,
        metadata=Metadata(source="hotel_mcp", provider=PROVIDER, confidence=0.9, source_url=p.get("link"),
                          notes=f"Lowest rate found on Google Hotels for {nights} nights at search time."),
    )


async def search(city: str, check_in: date, check_out: date, adults: int, currency: str, center: GeoPoint,
                 query: str | None = None) -> list[HotelOption]:
    data = await net.serpapi(
        "google_hotels", 6 * net.HOUR, q=query or f"Hotels in {city}", check_in_date=check_in.isoformat(),
        check_out_date=check_out.isoformat(), adults=max(1, min(adults, 6)), currency=currency.upper(),
        hl=settings.language, gl="us",
    )
    nights = (check_out - check_in).days
    props = data.get("properties") or []
    hotels = [p for p in props if (p.get("type") or "hotel") == "hotel"]
    if len(hotels) < 8:  # small towns: allow rentals so the planner has options
        hotels = props
    out = [h for h in (_to_option(p, currency.upper(), nights, center) for p in hotels) if h]
    # Safety net: a hotel far from the destination is a different city with the same name (Naples, Florida
    # for Naples, Italy) - never a candidate, whatever the text search returned.
    out = [h for h in out if haversine_km(center.lat, center.lon, h.location.lat, h.location.lon) <= MAX_HOTEL_KM]
    return [h for h in out if h.rating == 0 or h.reviews_count >= 5]


MAX_HOTEL_KM = 60


async def offers(property_token: str, city: str, check_in: date, check_out: date, adults: int, currency: str) -> dict:
    """The live booking offers for one hotel and these exact dates: each booking site with its price and a
    deep link to its booking page (Google Hotels' click-through link carries the dates and guests)."""
    data = await net.serpapi(
        "google_hotels", 6 * net.HOUR, q=f"Hotels in {city}", check_in_date=check_in.isoformat(),
        check_out_date=check_out.isoformat(), adults=max(1, min(adults, 6)), currency=currency.upper(),
        hl=settings.language, gl="us", property_token=property_token)
    nights = max((check_out - check_in).days, 1)
    out, seen = [], set()
    for p in (data.get("featured_prices") or []) + (data.get("prices") or []):
        link, src = p.get("link"), p.get("source")
        night = (p.get("rate_per_night") or {}).get("extracted_lowest")
        if not link or not src or night is None or (src, night) in seen:
            continue
        seen.add((src, night))
        total = (p.get("total_rate") or {}).get("extracted_lowest") or night * nights
        out.append({"source": src, "logo": p.get("logo"), "link": link, "rate_per_night": float(night),
                    "total": float(total), "official": bool(p.get("official")),
                    "free_cancellation": bool(p.get("free_cancellation")), "currency": currency.upper()})
    out.sort(key=lambda o: o["rate_per_night"])
    return {"name": data.get("name"), "hotel_website": data.get("link"), "nights": nights, "offers": out,
            "images": [i.get("thumbnail") for i in (data.get("images") or [])[:10] if i.get("thumbnail")],
            "description": data.get("description")}


async def reviews(property_token: str) -> list[dict]:
    data = await net.serpapi("google_hotels_reviews", 30 * net.DAY, property_token=property_token, hl=settings.language)
    return [{"rating": r.get("rating"), "date": r.get("date"), "source": r.get("source"), "snippet": r.get("snippet", "")}
            for r in data.get("reviews", [])]


NEGATED = re.compile(r"\b(not|no|never|wasn'?t|isn'?t|weren'?t|without|hardly)\b[^.!?]{0,25}\b(noisy|noise|loud)\b"
                     r"|\bnoise (levels? )?(was|were|is) (fine|ok|okay|low|minimal|not)", re.I)


def _mentions(snippet: str, pattern: re.Pattern) -> bool:
    """True if any sentence mentions the pattern without negating it ("not too loud" is not a complaint)."""
    for sentence in re.split(r"(?<=[.!?])\s+", snippet):
        if pattern.search(sentence) and not NEGATED.search(sentence):
            return True
    return False


def noise_from_reviews(items: list[dict]) -> tuple[str, list[str]]:
    """Classify noise from real guest reviews: (level, evidence snippets)."""
    noisy = [r["snippet"] for r in items if r.get("snippet") and _mentions(r["snippet"], NOISY)]
    quiet = [r["snippet"] for r in items if r.get("snippet") and (QUIET.search(r["snippet"]) or NEGATED.search(r["snippet"]))]
    if len(noisy) >= 2:
        return "noisy", noisy[:2]
    if noisy:
        return "moderate", noisy[:1]
    if len(quiet) >= 2:
        return "quiet", quiet[:2]
    return "unknown", []

