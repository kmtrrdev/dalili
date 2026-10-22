"""Attractions and restaurants: Google Maps / Google Local / Maps Reviews (SerpApi) + OpenTripMap.

Facts the providers publish (location, rating, review count, opening hours, price range)
are used as-is. Facts they don't publish are *assumed* and flagged:
  - hours_verified=False when Google has no hours (typical hours for that kind of place are used)
  - price_known=False for entry tickets and most meal prices (estimate in USD, scaled later
    by the city's real hotel price level)
"""

from __future__ import annotations

import asyncio
import hashlib
import re

from .. import net
from ..config import settings
from ..models import GeoPoint, Metadata, Money, Place
from ..utils import WEEKDAYS, haversine_km

GOOGLE = "Google Maps (SerpApi)"
OTM_URL = "https://api.opentripmap.com/0.1/en/places"
DAY_NAMES = {"monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu", "friday": "fri",
             "saturday": "sat", "sunday": "sun"}

# (keyword in Google type / OTM kind) -> (categories, indoor, minutes, estimated USD ticket)
KIND_RULES: list[tuple[str, list[str], bool, int, float]] = [
    # Sea & beach first: "water park" must not be read as a city park, "beach club" not as a club.
    ("beach", ["beach", "relaxation", "nature", "photography"], False, 180, 0),
    ("snorkel", ["beach", "adventure", "nature"], False, 180, 30),
    ("diving", ["beach", "adventure", "nature"], False, 180, 45),
    ("dive ", ["beach", "adventure", "nature"], False, 180, 45),
    ("water park", ["beach", "family", "adventure"], False, 240, 30),
    ("boat tour", ["beach", "adventure", "photography"], False, 180, 35),
    ("art gallery", ["art", "museums", "culture"], True, 90, 15),
    ("museum", ["museums", "art", "culture", "history"], True, 120, 18),
    ("archaeolog", ["history", "photography"], False, 120, 18),
    ("ruins", ["history", "photography"], False, 90, 15),
    ("castle", ["history", "architecture", "photography"], True, 90, 15),
    ("fortress", ["history", "architecture", "photography"], False, 90, 12),
    ("palace", ["history", "architecture", "culture"], True, 90, 18),
    ("basilica", ["architecture", "culture", "history"], True, 60, 0),
    ("cathedral", ["architecture", "culture", "history"], True, 60, 0),
    ("church", ["architecture", "culture"], True, 40, 0),
    ("mosque", ["architecture", "culture"], True, 45, 0),
    ("synagogue", ["architecture", "culture"], True, 45, 0),
    ("temple", ["architecture", "culture", "history"], True, 45, 0),
    ("religion", ["architecture", "culture"], True, 40, 0),
    ("garden", ["nature", "relaxation", "photography"], False, 75, 0),
    ("park", ["nature", "relaxation"], False, 75, 0),
    ("natural", ["nature", "photography"], False, 90, 0),
    ("beach", ["nature", "relaxation"], False, 150, 0),
    ("zoo", ["family", "nature"], False, 150, 25),
    ("aquarium", ["family"], True, 120, 25),
    ("market", ["shopping", "food", "culture"], True, 75, 0),
    ("shopping", ["shopping"], True, 90, 0),
    ("observation", ["photography"], False, 45, 12),
    ("scenic", ["photography", "relaxation"], False, 40, 0),
    ("viewpoint", ["photography", "relaxation"], False, 40, 0),
    ("tower", ["photography", "history"], False, 60, 12),
    ("bridge", ["photography", "architecture"], False, 20, 0),
    ("fountain", ["photography", "culture"], False, 25, 0),
    ("plaza", ["photography", "culture"], False, 30, 0),
    ("square", ["photography", "culture"], False, 30, 0),
    ("monument", ["history", "photography"], False, 30, 0),
    ("memorial", ["history"], False, 30, 0),
    ("historic", ["history", "culture"], False, 45, 0),
    ("architecture", ["architecture", "photography"], False, 30, 0),
    ("theatre", ["culture", "music"], True, 120, 35),
    ("theater", ["culture", "music"], True, 120, 35),
    ("opera", ["culture", "music"], True, 150, 45),
    ("night club", ["nightlife", "music"], True, 150, 20),
    ("bar", ["nightlife"], True, 90, 0),
    ("cultural", ["culture"], True, 60, 10),
    ("tourist attraction", ["culture", "photography"], False, 60, 0),
]
EXCLUDE_TYPES = re.compile(r"tour operator|tour agency|travel agency|tourist information|hotel|hostel|parking|bus stop|"
                           r"transit|car rental|souvenir|real estate|lodging|apartment|b&b", re.I)
ASSUMED_HOURS = {"beach": ("08:00", "18:30"), "museums": ("09:00", "18:00"), "architecture": ("08:00", "18:00"), "nature": ("07:00", "20:00"),
                 "shopping": ("10:00", "19:00"), "nightlife": ("19:00", "23:59")}
OUTDOOR_ALWAYS_OPEN = ("fountain", "plaza", "square", "monument", "bridge", "memorial", "viewpoint", "scenic", "architecture")

CUISINES = ["italian", "roman", "french", "turkish", "seafood", "pizza", "sushi", "japanese", "chinese", "indian", "thai",
            "mexican", "spanish", "tapas", "greek", "lebanese", "middle eastern", "egyptian", "moroccan", "vegan",
            "vegetarian", "steak", "burger", "kebab", "mediterranean", "american", "asian", "ottoman", "meze", "fish",
            "bistro", "brasserie", "trattoria", "wine bar", "coffee", "bakery", "pastry", "ice cream", "gelato", "dessert"]
PRICE_LEVEL_USD = {1: 12.0, 2: 25.0, 3: 45.0, 4: 85.0}
CITY_RADIUS_KM = 25       # beyond this a sight is a day trip
MAX_DAY_TRIP_KM = 250     # beyond this it needs an overnight stay (not planned as a day trip)
MAX_OVERNIGHT_KM = 900    # famous places up to here are suggested as overnight side trips
FAMOUS_REVIEWS = 3000     # places outside the city must be well known to be worth the journey
SYMBOLS = {"€": "EUR", "£": "GBP", "₺": "TRY", "E£": "EGP", "¥": "JPY", "₹": "INR", "CHF": "CHF", "$": "USD", "AED": "AED", "SAR": "SAR",
           "US$": "USD", "R$": "BRL", "MX$": "MXN", "CA$": "CAD", "A$": "AUD", "NT$": "TWD", "HK$": "HKD", "S$": "SGD"}
# Currencies written with a plain "$" where they are spent: there a bare "$" is the local currency, anywhere else
# it is US dollars (a "$" in Dubai is never dirhams, a "$" in Mexico City is pesos).
LOCAL_DOLLAR = {"USD", "CAD", "AUD", "NZD", "SGD", "HKD", "TWD", "MXN", "ARS", "CLP", "COP", "UYU", "BSD", "BBD", "JMD",
                "TTD", "FJD", "NAD", "LRD", "BND", "XCD"}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _clock(tok: str, suffix: str | None) -> int | None:
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?$", tok.strip(), re.I)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    suf = (m.group(3) or suffix or "").upper()
    if suf == "PM" and h < 12:
        h += 12
    if suf == "AM" and h == 12:
        h = 0
    return h * 60 + mi


def parse_google_hours(operating_hours: dict | None) -> dict[str, list[list[str]]] | None:
    """Google's {"monday": "9 AM–12:30 PM, 2–6 PM", ...} -> {"mon": [["09:00","12:30"],["14:00","18:00"]], ...}."""
    if not operating_hours:
        return None
    out: dict[str, list[list[str]]] = {}
    for day, raw in operating_hours.items():
        key = DAY_NAMES.get(day.lower())
        if key is None:
            continue
        text = str(raw).replace(" ", " ").replace(" ", " ").replace("–", "-").replace("—", "-").strip()
        if re.search(r"open 24 hours", text, re.I):
            out[key] = [["00:00", "23:59"]]
            continue
        if re.search(r"closed", text, re.I):
            out[key] = []
            continue
        windows = []
        for part in text.split(","):
            if "-" not in part:
                continue
            a, b = (x.strip() for x in part.split("-", 1))
            b_suf = re.search(r"(AM|PM)", b, re.I)
            end = _clock(b, None)
            start = _clock(a, b_suf.group(1) if b_suf and not re.search(r"(AM|PM)", a, re.I) else None)
            if start is None or end is None:
                continue
            if b_suf and not re.search(r"(AM|PM)", a, re.I) and end is not None and start > end:
                start = _clock(a, "AM")  # "11-2 PM" means 11 AM - 2 PM
            if end <= start:
                end = 23 * 60 + 59  # closes after midnight
            windows.append([f"{start // 60:02d}:{start % 60:02d}", f"{end // 60:02d}:{end % 60:02d}"])
        out[key] = windows
    for d in WEEKDAYS:
        out.setdefault(d, [])
    return out


def parse_price(text: str | None, local_currency: str) -> tuple[float | None, str | None, int | None]:
    """'€10–20' -> (15, 'EUR', None); '$$' -> (None, None, 2)."""
    if not text:
        return None, None, None
    t = text.replace(" ", " ").replace("–", "-")
    if re.fullmatch(r"[$€£₺¥]{1,4}", t.strip()):
        return None, None, len(t.strip())
    cur = None
    for sym, code in sorted(SYMBOLS.items(), key=lambda kv: -len(kv[0])):
        if sym in t:
            cur = local_currency if (sym == "$" and local_currency in LOCAL_DOLLAR) else code
            break
    nums = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", t)]
    if not nums:
        return None, None, None
    return (sum(nums[:2]) / len(nums[:2])), cur or local_currency, None


def classify(types: list[str], name: str = "") -> tuple[list[str], bool, int, float, str]:
    text = " ".join(types + [name]).lower()
    cats: list[str] = []
    indoor, minutes, ticket, matched = False, 60, 0.0, ""
    for kw, c, ind, mins, usd in KIND_RULES:
        if kw in text:
            if not matched:
                indoor, minutes, ticket, matched = ind, mins, usd, kw
            cats += [x for x in c if x not in cats]
    if "food" in text or "cooking" in text:
        cats.append("food")
    return cats or ["culture"], indoor, minutes, ticket, matched


def _assumed_hours(cats: list[str], matched: str) -> dict[str, list[list[str]]]:
    if matched in OUTDOOR_ALWAYS_OPEN:
        o, c = "00:00", "23:59"
    else:
        o, c = next((ASSUMED_HOURS[x] for x in cats if x in ASSUMED_HOURS), ("09:00", "18:00"))
    return {d: [[o, c]] for d in WEEKDAYS}


def _pid(prefix: str, raw: str) -> str:
    return f"{prefix}_{hashlib.sha1(raw.encode()).hexdigest()[:12]}"


def _popularity(reviews: int, rating: float) -> str:
    if reviews >= 40000:
        return "must_see"
    if reviews >= 8000:
        return "popular"
    if rating >= 4.6 and reviews < 2500:
        return "hidden_gem"
    return "local_favorite" if rating >= 4.5 else "popular"


# ---------------------------------------------------------------------------
# Google Maps
# ---------------------------------------------------------------------------


async def maps_search(q: str, center: GeoPoint, zoom: int = 14, ttl_days: int = 7) -> list[dict]:
    data = await net.serpapi("google_maps", ttl_days * net.DAY, q=q, ll=f"@{center.lat:.4f},{center.lon:.4f},{zoom}z",
                             type="search", hl=settings.language)
    return data.get("local_results") or []


def _google_attraction(r: dict, local_currency: str) -> Place | None:
    gps = r.get("gps_coordinates") or {}
    types = r.get("types") or ([r["type"]] if r.get("type") else [])
    if not gps or EXCLUDE_TYPES.search(" ".join(types)) or int(r.get("reviews") or 0) < 300:
        return None
    cats, indoor, minutes, ticket, matched = classify(types, r.get("title", ""))
    if matched in ("historic", "tourist attraction") and int(r.get("reviews") or 0) >= 100000:
        # A world-famous generic "landmark" (e.g. the Colosseum) is usually a long, ticketed visit.
        minutes, ticket = 90, 20.0
    hours = parse_google_hours(r.get("operating_hours"))
    verified = hours is not None
    if hours is None:
        hours = _assumed_hours(cats, matched)
        verified = matched in OUTDOOR_ALWAYS_OPEN  # public squares/fountains really are always accessible
    price, cur, _ = parse_price(r.get("price"), local_currency)
    reviews = int(r.get("reviews") or 0)
    rating = float(r.get("rating") or 4.0)
    return Place(
        id=_pid("a", r.get("place_id") or r["title"]), name=r["title"], kind="attraction", categories=cats,
        location=GeoPoint(lat=gps["latitude"], lon=gps["longitude"]), rating=rating,
        price_level=1 if not ticket else 2,
        cost_per_person=Money(amount=price, currency=cur, price_type="range") if price is not None
        else Money(amount=ticket, currency="USD", price_type="estimated"),
        price_known=price is not None, opening_hours=hours, hours_verified=verified, duration_minutes=minutes,
        indoor=indoor, popularity=_popularity(reviews, rating), description=r.get("description") or ", ".join(types),
        reviews_count=reviews, address=r.get("address", ""), website=r.get("website"),
        google_place_id=r.get("place_id"), thumbnail=r.get("thumbnail"),
        notes=None if price is not None else ("Free to visit." if not ticket else "Entry price is an estimate - check the official site."),
        metadata=Metadata(source="activities_mcp", provider=GOOGLE, confidence=0.85 if verified else 0.6,
                          source_url=f"https://www.google.com/maps/place/?q=place_id:{r.get('place_id')}" if r.get("place_id") else None),
    )


def _link(value) -> str | None:
    """Google gives reservation / order links either as a URL or as {"link": ...}."""
    if isinstance(value, str) and value.startswith("http"):
        return value
    if isinstance(value, dict) and str(value.get("link", "")).startswith("http"):
        return value["link"]
    return None


def _google_restaurant(r: dict, local_currency: str) -> Place | None:
    gps = r.get("gps_coordinates") or {}
    if not gps or int(r.get("reviews") or 0) < 50:
        return None
    types = [t.lower() for t in (r.get("types") or ([r["type"]] if r.get("type") else []))]
    text = " ".join(types) + " " + r.get("title", "").lower()
    if EXCLUDE_TYPES.search(text):
        return None
    cuisine = [c.replace(" ", "_") for c in CUISINES if c in text]
    dietary = [d for d in ("vegetarian", "vegan") if d in text]
    exts = str(r.get("extensions") or "").lower()
    if "vegetarian options" in exts or "vegan options" in exts:
        dietary = sorted(set(dietary) | {"vegetarian"})
    is_cafe = any(k in text for k in ("cafe", "café", "coffee", "bakery", "pastry", "ice cream", "gelato", "dessert", "tea house", "breakfast"))
    is_restaurant = "restaurant" in text or "pizzeria" in text or "trattoria" in text
    hours = parse_google_hours(r.get("operating_hours"))
    verified = hours is not None
    if hours is None:
        o, c = ("07:30", "19:00") if is_cafe and not is_restaurant else ("12:00", "23:00")
        hours = {d: [[o, c]] for d in WEEKDAYS}
    opens_early = any(w and w[0][0] <= "09:30" for w in hours.values())
    meals: list[str] = []
    if is_restaurant:
        meals += ["lunch", "dinner"]
    if is_cafe:
        meals += ["coffee"]
        if opens_early or "breakfast" in text or "bakery" in text:
            meals += ["breakfast"]
        if any(k in text for k in ("ice cream", "gelato", "dessert", "pastry", "bakery", "chocolate")):
            meals += ["dessert"]
    if not meals:
        meals = ["lunch", "dinner"]
    price, cur, level = parse_price(r.get("price"), local_currency)
    level = level or (2 if is_restaurant else 1)
    rating = float(r.get("rating") or 4.0)
    reviews = int(r.get("reviews") or 0)
    base = PRICE_LEVEL_USD.get(level, 25.0) if is_restaurant else 8.0
    return Place(
        id=_pid("r", r.get("place_id") or r["title"]), name=r["title"], kind="restaurant" if is_restaurant else "cafe",
        categories=["food"], cuisine=cuisine, dietary=dietary, meal_types=list(dict.fromkeys(meals)),  # type: ignore[arg-type]
        location=GeoPoint(lat=gps["latitude"], lon=gps["longitude"]), rating=rating, price_level=level,
        cost_per_person=Money(amount=price, currency=cur, price_type="range") if price is not None
        else Money(amount=base, currency="USD", price_type="estimated"),
        price_known=price is not None, opening_hours=hours, hours_verified=verified,
        duration_minutes=75 if is_restaurant else 30, indoor=True, popularity=_popularity(reviews * 5, rating),
        requires_reservation=bool(r.get("reserve_a_table")), description=r.get("type") or "",
        reviews_count=reviews, address=r.get("address", ""), website=r.get("website"),
        booking_url=_link(r.get("reserve_a_table")) or _link(r.get("order_online")),
        google_place_id=r.get("place_id"), thumbnail=r.get("thumbnail"),
        metadata=Metadata(source="places_mcp", provider=GOOGLE, confidence=0.85 if verified else 0.6),
    )


def _raise_if_all_failed(results: list) -> None:
    """Every live query failed (e.g. SerpApi quota used up): surface it so the tool can fall back.
    A replay miss (offline tests) is not an outage: keep the old best-effort behaviour there."""
    errors = [r for r in results if isinstance(r, Exception)]
    if results and len(errors) == len(results) and not isinstance(errors[0], net.ReplayMiss):
        raise errors[0] if isinstance(errors[0], net.ProviderError) else net.ProviderError(str(errors[0]))


async def attractions(city: str, center: GeoPoint, local_currency: str, interests: list[str],
                      country: str | None = None, days: int = 7) -> list[Place]:
    extra = next((q for key, q in (("museums", "museums"), ("art", "art museums"), ("history", "historic sites"),
                                   ("nature", "parks and gardens"), ("food", "food markets"), ("shopping", "markets"),
                                   ("architecture", "famous churches"), ("nightlife", "live music venues"))
                  if key in interests), None)
    # (query, map zoom, is_wide). Every search costs a SerpApi credit, so each one must earn its place:
    # - the top-attractions list (20 places) + OpenTripMap (free) covers a short trip;
    # - an interest search only when the traveller named one and the trip has room for it (>= 3 days);
    # - wide searches find famous places *around* the city (the Pyramids from Cairo, Versailles from Paris)
    #   and only matter when there are days to spare for a day trip (>= 4) or an overnight side trip (>= 6).
    queries: list[tuple[str, int, bool]] = [(f"top tourist attractions in {city}", 13, False)]
    if extra and days >= 3:
        queries.append((f"{extra} in {city}", 13, False))
    if days >= 4:
        queries.append((f"famous landmarks and day trips near {city}", 9, True))
    if country and days >= 6:
        queries.append((f"top tourist attractions in {country}", 7, True))
    if "beach" in interests:
        queries.append((f"best beaches near {city}", 10, True))  # sea lovers: real beaches within day-trip reach
    results = await asyncio.gather(*(maps_search(q, center, z, ttl_days=30) for q, z, _ in queries), return_exceptions=True)
    _raise_if_all_failed(results)
    places: dict[str, Place] = {}
    for (_, _, wide), res in zip(queries, results):
        if isinstance(res, Exception):
            continue
        for r in res:
            p = _google_attraction(r, local_currency)
            if p is None or p.id in places:
                continue
            km = haversine_km(center.lat, center.lon, p.location.lat, p.location.lon)
            if wide and MAX_DAY_TRIP_KM < km <= MAX_OVERNIGHT_KM and p.reviews_count >= 10000:
                # A national highlight too far for a day trip (Luxor from Cairo): never scheduled,
                # but surfaced as an overnight side-trip suggestion.
                p.distance_km, p.day_trip = round(km, 1), True
                p.categories = list(dict.fromkeys(p.categories + ["overnight_trip"]))
                p.notes = f"About {km:.0f} km from {city}: too far for a day trip - worth an overnight stay or a domestic flight."
                places[p.id] = p
                continue
            # A beach is worth the drive for a sea lover even if it isn't world-famous.
            bar = 300 if "beach" in p.categories else FAMOUS_REVIEWS
            if km > MAX_DAY_TRIP_KM or (km > CITY_RADIUS_KM and p.reviews_count < bar):
                continue  # too far for a day trip, or not famous enough to justify the journey
            if not wide and km > CITY_RADIUS_KM * 2:
                continue
            p.distance_km = round(km, 1)
            if km > CITY_RADIUS_KM:
                p.day_trip = True
                p.categories = list(dict.fromkeys(p.categories + ["day_trip"]))
                p.notes = ((p.notes or "") + f" Day trip: about {km:.0f} km from {city} - plan most of a day.").strip()
            places[p.id] = p
    try:
        # Free candidates (OpenTripMap / Wikipedia): more of them when fewer Google searches ran.
        for p in await opentripmap_gems(center, list(places.values()), limit=10 if len(queries) >= 3 else 18):
            places.setdefault(p.id, p)
    except net.ProviderError:
        pass  # OpenTripMap is a bonus source; Google results stand on their own
    return dedupe(list(places.values()))


def tag_distance(p: Place, center: GeoPoint, city: str) -> Place:
    """Distance from the city centre -> day trip / overnight trip tags (same rules as the attraction search)."""
    km = haversine_km(center.lat, center.lon, p.location.lat, p.location.lon)
    p.distance_km = round(km, 1)
    p.day_trip = km > CITY_RADIUS_KM
    p.categories = [c for c in p.categories if c not in ("day_trip", "overnight_trip")]
    if km > MAX_DAY_TRIP_KM:
        p.categories.append("overnight_trip")
        p.notes = f"About {km:.0f} km from {city}: too far for a day trip - worth an overnight stay."
    elif p.day_trip:
        p.categories.append("day_trip")
        p.notes = f"Day trip: about {km:.0f} km from {city} - plan most of a day."
    return p


async def find_place(name: str, city: str, center: GeoPoint, local_currency: str, zoom: int = 11) -> Place | None:
    """One specific place the traveller asked for by name ("Vatican Museums", "Pyramids of Giza").

    The usual popularity filters don't apply: the traveller chose it. Places outside the city are
    tagged as day trips like any other; ones too far for a day trip are tagged as overnight trips.
    With city="" the search is by name only (a multi-city trip assigns the place to its nearest city).
    """
    data = await net.serpapi("google_maps", 14 * net.DAY, q=f"{name} {city}".strip(),
                             ll=f"@{center.lat:.4f},{center.lon:.4f},{zoom}z", type="search", hl=settings.language)
    # A precise query returns the single matching place in `place_results`, a vague one a list.
    results = ([data["place_results"]] if data.get("place_results") else []) + (data.get("local_results") or [])
    for r in results[:3]:
        gps = r.get("gps_coordinates") or {}
        if not gps:
            continue
        raw_type = r.get("type")
        # place_results gives "type" as a list, local_results as a string.
        types = r.get("types") or (list(raw_type) if isinstance(raw_type, list) else [raw_type] if raw_type else [])
        r = {**r, "types": types, "type": types[0] if types else ""}
        text = " ".join(types).lower() + " " + r.get("title", "").lower()
        if any(k in text for k in ("restaurant", "cafe", "café", "bakery", "pizzeria", "trattoria", "bar ")):
            p = _google_restaurant({**r, "reviews": max(int(r.get("reviews") or 0), 50)}, local_currency)
            if p is None:
                continue
            # Asked for by name: plan it as a visit (a meal slot there), not just a restaurant candidate.
            p = p.model_copy(update={"kind": "activity", "id": "a" + p.id[1:], "duration_minutes": 75,
                                     "categories": list(dict.fromkeys(p.categories + ["food"]))})
        else:
            p = _google_attraction({**r, "reviews": max(int(r.get("reviews") or 0), 300)}, local_currency)
            if p is None:  # excluded type (e.g. a hotel) - still honour the request as a place to see
                cats, indoor, minutes, ticket, _ = classify(types, r.get("title", ""))
                p = Place(id=_pid("a", r.get("place_id") or r["title"]), name=r["title"], kind="attraction",
                          categories=cats, location=GeoPoint(lat=gps["latitude"], lon=gps["longitude"]),
                          rating=float(r.get("rating") or 4.0), cost_per_person=Money(amount=ticket, currency="USD"),
                          opening_hours=_assumed_hours(cats, ""), hours_verified=False, duration_minutes=minutes,
                          indoor=indoor, reviews_count=int(r.get("reviews") or 0), address=r.get("address", ""),
                          google_place_id=r.get("place_id"),
                          metadata=Metadata(source="activities_mcp", provider=GOOGLE, confidence=0.6))
        p.reviews_count = int(r.get("reviews") or 0)
        p.popularity = "must_see"
        return tag_distance(p, center, city or "the city")
    return None


def dedupe(items: list[Place], radius_km: float = 0.1) -> list[Place]:
    """Google often lists one spot twice (e.g. "Spanish Steps" and "Piazza di Spagna"): keep the better-known one."""
    kept: list[Place] = []
    for p in sorted(items, key=lambda x: -x.reviews_count):
        if not any(haversine_km(p.location.lat, p.location.lon, k.location.lat, k.location.lon) < radius_km for k in kept):
            kept.append(p)
    return kept


MAX_RESTAURANT_KM = 25


async def restaurants(city: str, center: GeoPoint, local_currency: str, dietary: list[str]) -> list[Place]:
    # Everyday places plus the city's best tables, so a comfort plan has real upscale options to choose from.
    queries = [("restaurants", 15), ("cafes and bakeries for breakfast", 15), ("best fine dining restaurants", 14)]
    if "vegetarian" in dietary or "vegan" in dietary:
        queries.append(("vegetarian restaurants", 14))
    # Restaurants and cafés change slowly: three weeks of cache.
    results = await asyncio.gather(*(maps_search(q, center, z, ttl_days=21) for q, z in queries), return_exceptions=True)
    _raise_if_all_failed(results)
    out: dict[str, Place] = {}
    far = 0
    for res in results:
        if isinstance(res, Exception):
            continue
        for r in res:
            p = _google_restaurant(r, local_currency)
            if not p:
                continue
            # With nothing around the point, Google Maps can answer from anywhere (e.g. cafés in Florida).
            if haversine_km(p.location.lat, p.location.lon, center.lat, center.lon) > MAX_RESTAURANT_KM:
                far += 1
                continue
            out.setdefault(p.id, p)
    if not out and far:
        raise net.ProviderError(f"Google Maps found no restaurants within {MAX_RESTAURANT_KM} km of {city}")
    return list(out.values())


# ---------------------------------------------------------------------------
# OpenTripMap: well-documented places beyond Google's top list (hidden gems)
# ---------------------------------------------------------------------------

OTM_KIND_TYPES = [("museums", "museum"), ("archaeolog", "archaeological site"), ("castles", "castle"),
                  ("fortifications", "fortress"), ("palaces", "palace"), ("cathedrals", "cathedral"),
                  ("churches", "church"), ("mosques", "mosque"), ("gardens_and_parks", "garden"),
                  ("view_points", "viewpoint"), ("towers", "tower"), ("bridges", "bridge"), ("fountains", "fountain"),
                  ("squares", "square"), ("monuments", "monument"), ("theatres", "theatre"), ("historic", "historic")]


async def opentripmap_gems(center: GeoPoint, known: list[Place], limit: int = 10) -> list[Place]:
    if not settings.opentripmap_key:
        return []
    items = await net.fetch_json("opentripmap", f"{OTM_URL}/radius", {
        "radius": 6000, "lon": center.lon, "lat": center.lat, "rate": "3h", "kinds": "interesting_places",
        "format": "json", "limit": 80, "apikey": settings.opentripmap_key}, ttl_s=90 * net.DAY)
    known_names = {p.name.lower() for p in known}

    def is_known(it: dict) -> bool:
        name = (it.get("name") or "").lower()
        if not name or name in known_names or any(name in k or k in name for k in known_names if len(k) > 5):
            return True
        return any(haversine_km(p.location.lat, p.location.lon, it["point"]["lat"], it["point"]["lon"]) < 0.08 for p in known)

    fresh = [it for it in items if it.get("wikidata") and not is_known(it)
             and not any(k in it.get("kinds", "") for k in ("sculptures", "unclassified", "burial", "cemeteries"))][:limit]

    async def detail(it: dict) -> Place | None:
        d = await net.fetch_json("opentripmap", f"{OTM_URL}/xid/{it['xid']}", {"apikey": settings.opentripmap_key},
                                 ttl_s=180 * net.DAY)
        kinds = d.get("kinds", "")
        google_like = [t for k, t in OTM_KIND_TYPES if k in kinds] or ["tourist attraction"]
        cats, indoor, minutes, ticket, matched = classify(google_like, d.get("name", ""))
        text = ((d.get("wikipedia_extracts") or {}).get("text") or "")[:300]
        return Place(
            id=_pid("a", it["xid"]), name=d.get("name") or it["name"], kind="attraction", categories=cats,
            location=GeoPoint(lat=it["point"]["lat"], lon=it["point"]["lon"]), rating=4.5, price_level=1,
            cost_per_person=Money(amount=ticket, currency="USD", price_type="estimated"), price_known=False,
            opening_hours=_assumed_hours(cats, matched), hours_verified=matched in OUTDOOR_ALWAYS_OPEN,
            duration_minutes=min(minutes, 75), indoor=indoor, popularity="hidden_gem", description=text,
            website=d.get("wikipedia"), thumbnail=(d.get("preview") or {}).get("source"),
            notes="Less-visited place from OpenTripMap/Wikipedia; hours and price not published - check before going.",
            metadata=Metadata(source="activities_mcp", provider="OpenTripMap", confidence=0.55, source_url=d.get("otm")),
        )

    gate = asyncio.Semaphore(3)  # OpenTripMap rate-limits bursts (HTTP 429)

    async def limited(it: dict) -> Place | None:
        async with gate:
            return await detail(it)

    out = []
    for res in await asyncio.gather(*(limited(it) for it in fresh), return_exceptions=True):
        if isinstance(res, Place):
            out.append(res)
    return out
