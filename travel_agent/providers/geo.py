"""Place resolution: free text ("Rome", "Italy", "CAI") -> PlaceRef with coordinates, timezone, airports.

Google Flights autocomplete (SerpApi) gives the city id and its airports;
Geoapify geocoding gives coordinates, country and timezone.
Country metadata (currency, languages) comes from CLDR via Babel (offline, standard data).
"""

from __future__ import annotations

from functools import lru_cache

from babel import Locale
from babel.languages import get_official_languages
from babel.numbers import get_territory_currencies

from .. import net
from ..config import settings
from ..models import PlaceRef

GEOAPIFY_GEOCODE = "https://api.geoapify.com/v1/geocode/search"


class PlaceNotFound(net.ProviderError):
    pass


async def autocomplete(q: str) -> list[dict]:
    data = await net.serpapi("google_flights_autocomplete", 90 * net.DAY, q=q, hl=settings.language)
    return data.get("suggestions", [])


async def resolve_destination(text: str) -> dict:
    """A place to explore trips to: a country / region ({"kind": "region"}) or one city ({"kind": "city"}), with the
    Google id that Travel Explore accepts. The first suggestion wins unless an exact-name one exists."""
    text = text.strip()
    sug = [s for s in await autocomplete(text) if s.get("type") in ("region", "city") and s.get("id")]
    if not sug:
        raise PlaceNotFound(f"Could not find '{text}'")
    low = text.lower()
    exact = next((s for s in sug if s.get("name", "").lower().split(",")[0].split(" - ")[0].strip() in (low, low.split(",")[0])), None)
    best = exact or sug[0]
    return {"kind": best["type"], "id": best["id"], "name": best.get("name", text)}


async def geocode(text: str, city_only: bool = True) -> dict | None:
    if not settings.geoapify_key:
        raise net.ProviderError("GEOAPIFY_API_KEY is not configured")
    params = {"text": text, "format": "json", "limit": 1, "apiKey": settings.geoapify_key, "lang": "en"}
    if city_only:
        params["type"] = "city"
    data = await net.fetch_json("geoapify", GEOAPIFY_GEOCODE, params, ttl_s=180 * net.DAY)
    results = data.get("results") or []
    return results[0] if results else None


WIKIPEDIA = "https://en.wikipedia.org/w/api.php"


async def wiki_point(title: str) -> tuple[float, float] | None:
    """Coordinates of the Wikipedia article for a place: the place travellers mean when a name is shared
    (Borovets the ski resort, not the village of the same name 50 km away)."""
    try:
        data = await net.fetch_json("wikipedia", WIKIPEDIA, {"action": "query", "prop": "coordinates", "titles": title,
                                                             "redirects": 1, "format": "json"}, ttl_s=180 * net.DAY)
    except net.ProviderError:
        return None
    page = next(iter((data.get("query") or {}).get("pages", {}).values()), {})
    c = (page.get("coordinates") or [None])[0]
    return (float(c["lat"]), float(c["lon"])) if c else None


async def _checked_point(name: str, lat: float, lon: float) -> tuple[float, float]:
    """The geocoder takes the first place with a matching name, which can be a same-named village nearby.
    A Wikipedia point in the same region (15-300 km away) wins; one farther away is a different place, ignored."""
    from ..utils import haversine_km

    wp = await wiki_point(name)
    if wp and 15 <= haversine_km(lat, lon, wp[0], wp[1]) <= 300:
        return wp
    return lat, lon


GEOAPIFY_REVERSE = "https://api.geoapify.com/v1/geocode/reverse"


async def reverse_city(lat: float, lon: float) -> str | None:
    """"City, Country" at a point (Geoapify reverse geocoding), e.g. the town a landmark is in."""
    if not settings.geoapify_key:
        raise net.ProviderError("GEOAPIFY_API_KEY is not configured")
    data = await net.fetch_json("geoapify", GEOAPIFY_REVERSE, {"lat": round(lat, 5), "lon": round(lon, 5), "format": "json",
                                                              "apiKey": settings.geoapify_key, "lang": "en"},
                                ttl_s=180 * net.DAY)
    r = (data.get("results") or [{}])[0]
    city = r.get("city") or r.get("town") or r.get("village") or r.get("county")
    return f"{city}, {r.get('country', '')}".strip(", ") if city else None


async def resolve_place(text: str) -> PlaceRef:
    """Resolve a city, country or airport code the user typed."""
    text = text.strip()
    try:
        suggestions = await autocomplete(text)
    except net.ProviderError as exc:
        # Google Flights autocomplete unavailable (e.g. SerpApi quota used up): Geoapify for the city,
        # the AI model for its airports.
        return await _resolve_without_serpapi(text, exc)
    city = next((s for s in suggestions if s.get("type") == "city" and s.get("airports")), None)
    if city is None:
        # Countries / regions: take the city of their first listed airport.
        with_airports = next((s for s in suggestions if s.get("airports")), None)
        if with_airports:
            ap = with_airports["airports"][0]
            city = {"name": ap.get("city") or with_airports["name"], "id": ap.get("city_id"),
                    "airports": [a for a in with_airports["airports"] if a.get("city") == ap.get("city")] or [ap]}
    if city is None:
        raise PlaceNotFound(f"Could not find a city with an airport for '{text}'")
    city_name = city["name"].split(",")[0].strip()
    geo = await geocode(city["name"]) or await geocode(city_name, city_only=False)
    if geo is None:
        raise PlaceNotFound(f"Could not geocode '{city['name']}'")
    country = geo.get("country", "")
    if country and city_name.lower().endswith(" " + country.lower()):
        city_name = city_name[: -len(country)].strip()  # "Riyadh Saudi Arabia" -> "Riyadh"
    airports = [a["id"] for a in city.get("airports", []) if a.get("id") and len(a["id"]) == 3]
    lat, lon = await _checked_point(city_name, float(geo["lat"]), float(geo["lon"]))
    return PlaceRef(
        name=city_name,
        country=geo.get("country", ""),
        country_code=(geo.get("country_code") or "").upper(),
        lat=lat,
        lon=lon,
        timezone=(geo.get("timezone") or {}).get("name", "UTC"),
        city_id=city.get("id"),
        airports=airports,
        airport_names={a["id"]: a["name"] for a in city.get("airports", []) if a.get("id") in airports},
    )


async def _resolve_without_serpapi(text: str, live_error: Exception) -> PlaceRef:
    from . import ai_fallback

    code = country_code(text)
    query = text
    if code and ai_fallback.available():
        # A country: its main gateway city (the one with the main international airport).
        main = await ai_fallback.airports(f"the main international gateway city of {text}", text)
        query = main[0].name.split(" International")[0] if main else text
    geo = await geocode(query) or await geocode(query, city_only=False)
    if geo is None:
        raise PlaceNotFound(f"Could not find '{text}' (live airport search unavailable: {live_error})")
    name = geo.get("city") or geo.get("name") or query.split(",")[0]
    country = geo.get("country", "")
    airports = await ai_fallback.airports(name, country) if ai_fallback.available() else []
    lat, lon = await _checked_point(name, float(geo["lat"]), float(geo["lon"]))
    return PlaceRef(name=name, country=country, country_code=(geo.get("country_code") or "").upper(),
                    lat=lat, lon=lon, timezone=(geo.get("timezone") or {}).get("name", "UTC"),
                    city_id=None, airports=[a.iata.upper() for a in airports],
                    airport_names={a.iata.upper(): a.name for a in airports})


COUNTRY_ALIASES = {"usa": "US", "us": "US", "america": "US", "united states of america": "US", "uk": "GB",
                   "england": "GB", "scotland": "GB", "britain": "GB", "great britain": "GB", "holland": "NL",
                   "uae": "AE", "emirates": "AE", "ksa": "SA", "saudi": "SA", "czechia": "CZ", "turkiye": "TR", "turkey": "TR", "czech republic": "CZ",
                   "ivory coast": "CI", "bosnia": "BA", "macedonia": "MK",
                   "türkiye": "TR", "korea": "KR", "south korea": "KR", "russia": "RU", "vietnam": "VN"}


@lru_cache(maxsize=1)
def _country_names() -> dict[str, str]:
    names = {n.lower(): code for code, n in Locale("en").territories.items() if len(code) == 2 and code.isalpha()}
    names.update(COUNTRY_ALIASES)
    return names


def country_code(text: str | None) -> str | None:
    """ISO code if the text names a country ("Italy", "the UK"), else None (a city, region or anything else)."""
    if not text:
        return None
    t = text.strip().lower()
    t = t[4:] if t.startswith("the ") else t
    return _country_names().get(t)


@lru_cache(maxsize=256)
def country_meta(country_code: str) -> dict:
    """Currency and official languages for an ISO country code (CLDR data)."""
    cc = country_code.upper()
    try:
        currencies = get_territory_currencies(cc)
    except Exception:
        currencies = []
    names = Locale("en").languages
    languages = []
    for code in get_official_languages(cc, de_facto=True) or ():
        base = code.split("_")[0]
        if base in names and names[base] not in languages:
            languages.append(names[base])
    return {"currency": currencies[0] if currencies else "USD", "languages": languages}


# Typical local dinner start (cultural norm, used only to schedule dinner).
DINNER_TIME = {"ES": "21:00", "PT": "20:30", "GR": "21:00", "IT": "19:45", "AR": "21:30", "TR": "19:00",
               "FR": "19:30", "EG": "20:00", "SA": "20:30", "AE": "20:00", "MA": "20:00", "GB": "19:00",
               "DE": "19:00", "NL": "18:30", "US": "19:00", "JP": "19:00"}


def dinner_time(country_code: str) -> str:
    return DINNER_TIME.get(country_code.upper(), "19:30")
