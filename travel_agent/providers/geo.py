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


async def geocode_all(text: str, city_only: bool = True, country: str | None = None, limit: int = 1) -> list[dict]:
    """Geoapify matches for the text, best first, optionally only inside one country (ISO code)."""
    if not settings.geoapify_key:
        raise net.ProviderError("GEOAPIFY_API_KEY is not configured")
    params = {"text": text, "format": "json", "limit": limit, "apiKey": settings.geoapify_key, "lang": "en"}
    if city_only:
        params["type"] = "city"
    if country:
        params["filter"] = f"countrycode:{country.lower()}"
    data = await net.fetch_json("geoapify", GEOAPIFY_GEOCODE, params, ttl_s=180 * net.DAY)
    return data.get("results") or []


async def geocode(text: str, city_only: bool = True) -> dict | None:
    results = await geocode_all(text, city_only)
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


GEOAPIFY_REVERSE = "https://api.geoapify.com/v1/geocode/reverse"


async def reverse_geocode(lat: float, lon: float) -> dict | None:
    """The Geoapify place at a point (city, country, country_code, timezone, ...)."""
    if not settings.geoapify_key:
        raise net.ProviderError("GEOAPIFY_API_KEY is not configured")
    data = await net.fetch_json("geoapify", GEOAPIFY_REVERSE, {"lat": round(lat, 5), "lon": round(lon, 5), "format": "json",
                                                              "apiKey": settings.geoapify_key, "lang": "en"},
                                ttl_s=180 * net.DAY)
    return (data.get("results") or [None])[0]


async def reverse_city(lat: float, lon: float) -> str | None:
    """"City, Country" at a point (Geoapify reverse geocoding), e.g. the town a landmark is in."""
    r = await reverse_geocode(lat, lon) or {}
    city = r.get("city") or r.get("town") or r.get("village") or r.get("county")
    return f"{city}, {r.get('country', '')}".strip(", ") if city else None


NEAR_KM = 200  # how far a place may lie from the airport Google lists for it (farther when Google says so)

Point = tuple[float, float]


def _km(a: Point, b: Point) -> float:
    from ..utils import haversine_km

    return haversine_km(a[0], a[1], b[0], b[1])


def _pt(r: dict) -> Point:
    return float(r["lat"]), float(r["lon"])


def _cc(r: dict) -> str:
    return (r.get("country_code") or "").upper()


def _is_city(r: dict) -> bool:
    return r.get("result_type") == "city"


def _rank(r: dict) -> tuple[bool, float]:
    """Cities before provinces and districts, then the better-known place."""
    return _is_city(r), float((r.get("rank") or {}).get("importance") or 0)


def _label_country(label: str) -> str | None:
    """ISO code of the country a "Place, Country" label ends with ("Bali, Indonesia" -> ID,
    "New York, NY, United States" -> US)."""
    return country_code(label.rsplit(",", 1)[-1]) if label else None


def _distance_km(text) -> float:
    """Google's airport distance ("23 mi", "37 km"); 0 when absent."""
    try:
        value, unit = str(text).split()[:2]
        return float(value.replace(",", "")) * (1.609 if unit.lower().startswith("mi") else 1.0)
    except ValueError:
        return 0.0


async def _airport_anchor(airports: list[dict]) -> tuple[Point, float] | None:
    """Where the place's main airport is (Wikipedia has nearly every airport) and how far from it the place may lie.
    Airport names are unambiguous where place names are not: they pin down which "Bali" Google meant."""
    for ap in airports[:2]:
        p = await wiki_point(ap["name"]) if ap.get("name") else None
        if p:
            return p, max(NEAR_KM, _distance_km(ap.get("distance")) + 100)
    return None


async def _search(text: str, city_only: bool, country: str | None) -> list[dict]:
    try:
        return await geocode_all(text, city_only, country, limit=5)
    except net.ProviderError:
        return []  # one failed search is not fatal: the plain search, Wikipedia and the airport remain


async def _locate(label: str, name: str, cc: str | None, anchor: tuple[Point, float] | None) -> tuple[dict, Point]:
    """The geocode result describing the place, and the point to plan around.

    Geocoders return the first place with a matching name: "Bali" is also a district of New Taipei, "Lombok" a village
    1,000 km from the island, "Tenerife" a town in Colombia. A result counts only when it lies near the anchor airport,
    and (without an airport to vouch for it) in the expected country."""
    def near(p: Point) -> bool:
        return anchor is None or _km(p, anchor[0]) <= anchor[1]

    def fits(r: dict) -> bool:
        return (anchor is not None or not cc or _cc(r) == cc) and near(_pt(r))

    found = [r for r in await _search(label, True, cc) if fits(r)]
    if not any(_is_city(r) for r in found):
        # Islands, provinces and resorts are not cities to the geocoder (Bali is a province): search every type.
        found += [r for r in await _search(label, False, cc) if fits(r)]
    if not found:
        # The country-filtered searches failed or found nothing: the plain search, held to the same checks.
        for city_only in (True, False):
            try:
                hit = await geocode(label, city_only)
            except net.ProviderError:
                if anchor is None:
                    raise  # nothing else to go on: report why (e.g. the key is missing)
                break
            if hit:
                # An unfiltered hit that passes the checks is evidence of its own country ("Athens, Georgia" is a
                # US city, whatever the label's last word says).
                found = [{**hit, "_verified": True}] if fits(hit) else []
                break
    geo = max(found, key=_rank, default=None)
    if geo is not None and not _is_city(geo):
        return geo, _pt(geo)
    wp = await wiki_point(name)
    if geo is not None:
        # Borovets the ski resort, not the village of that name 50 km away: the Wikipedia point of the name wins
        # over a city match in the same region (15-300 km off), when it is near the airport too.
        if wp and 15 <= _km(_pt(geo), wp) <= 300 and near(wp):
            return geo, wp
        return geo, _pt(geo)
    # No geocode result is the place: Wikipedia's point for it when near the airport, else the airport itself.
    point = wp if wp and near(wp) else (anchor[0] if anchor else None)
    if point is None:
        raise PlaceNotFound(f"Could not geocode '{label}'")
    try:
        geo = await reverse_geocode(*point) or {}
    except net.ProviderError:
        geo = {}
    if anchor is None and cc and _cc(geo) != cc:
        raise PlaceNotFound(f"Could not geocode '{label}'")  # a same-named place in another country
    if not geo and not cc:
        raise PlaceNotFound(f"Could not geocode '{label}'")
    return geo, point


def _country_of(geo: dict, cc: str | None) -> tuple[str, str]:
    """(country, ISO code) of the result; the suggestion's country when known wins (a point near a border,
    e.g. Basel's airport in France, reverse-geocodes to the neighbour)."""
    if cc and _cc(geo) != cc and not geo.get("_verified"):
        return Locale("en").territories.get(cc, cc), cc
    return geo.get("country", ""), _cc(geo)


def _pick_suggestion(suggestions: list[dict], want: str | None) -> dict | None:
    """A city with airports, in the country the text names ("Bali, Indonesia") when it names one; else a country /
    region with airports."""
    cities = [s for s in suggestions if s.get("type") == "city" and s.get("airports")]
    others = [s for s in suggestions if s.get("airports") and s not in cities]
    ordered = cities + others
    if want:
        ordered = [s for s in ordered if _label_country(s.get("name", "")) == want] + ordered
    return ordered[0] if ordered else None


async def resolve_place(text: str) -> PlaceRef:
    """Resolve a city, country or airport code the user typed."""
    text = text.strip()
    try:
        suggestions = await autocomplete(text)
    except net.ProviderError as exc:
        # Google Flights autocomplete unavailable (e.g. SerpApi quota used up): Geoapify for the city,
        # the AI model for its airports.
        return await _resolve_without_serpapi(text, exc)
    want = _label_country(text) if "," in text else None
    best = _pick_suggestion(suggestions, want)
    if want and (best is None or _label_country(best.get("name", "")) != want):
        # Google often answers nothing for "Istanbul, Turkey" yet finds "Istanbul": search the bare name, and take
        # only a match in the stated country (so "Bali, Indonesia" still never becomes the Bali in Taiwan).
        try:
            retry = await autocomplete(text.rsplit(",", 1)[0].strip())
        except net.ProviderError as exc:
            return await _resolve_without_serpapi(text, exc)
        best = _pick_suggestion([s for s in retry if _label_country(s.get("name", "")) == want], want) or best
    if best is None:
        raise PlaceNotFound(f"Could not find a city with an airport for '{text}'")
    # The suggestion is the place's identity: its country, its airports, its Google id.
    cc = _label_country(best.get("name", ""))
    city = best
    if best.get("type") != "city":
        # Countries / regions: take the city of their first listed airport.
        ap = best["airports"][0]
        city = {"name": ap.get("city") or best["name"], "id": ap.get("city_id"),
                "airports": [a for a in best["airports"] if a.get("city") == ap.get("city")] or [ap]}
    city_name = city["name"].split(",")[0].strip()
    geo, (lat, lon) = await _locate(city["name"], city_name, cc, await _airport_anchor(city.get("airports", [])))
    country, code = _country_of(geo, cc)
    if country and city_name.lower().endswith(" " + country.lower()):
        city_name = city_name[: -len(country)].strip(" -–")  # "Riyadh Saudi Arabia" / "Dubai - United Arab Emirates"
    airports = [a["id"] for a in city.get("airports", []) if a.get("id") and len(a["id"]) == 3]
    return PlaceRef(
        name=city_name,
        country=country,
        country_code=code,
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
    cc = code or (_label_country(text) if "," in text else None)
    try:
        geo, (lat, lon) = await _locate(query, query.split(",")[0].strip(), cc, None)
    except PlaceNotFound:
        raise PlaceNotFound(f"Could not find '{text}' (live airport search unavailable: {live_error})") from None
    name = geo.get("city") or geo.get("name") or query.split(",")[0]
    country, cc = _country_of(geo, cc)
    airports = await ai_fallback.airports(name, country) if ai_fallback.available() else []
    return PlaceRef(name=name, country=country, country_code=cc,
                    lat=lat, lon=lon, timezone=(geo.get("timezone") or {}).get("name", "UTC"),
                    city_id=None, airports=[a.iata.upper() for a in airports],
                    airport_names={a.iata.upper(): a.name for a in airports})


COUNTRY_ALIASES = {"usa": "US", "us": "US", "america": "US", "united states of america": "US", "uk": "GB",
                   "england": "GB", "scotland": "GB", "britain": "GB", "great britain": "GB", "holland": "NL",
                   "uae": "AE", "emirates": "AE", "ksa": "SA", "saudi": "SA", "czechia": "CZ", "turkiye": "TR", "turkey": "TR", "czech republic": "CZ",
                   "ivory coast": "CI", "bosnia": "BA", "macedonia": "MK",
                   "türkiye": "TR", "korea": "KR", "south korea": "KR", "russia": "RU", "vietnam": "VN",
                   # Long forms Google uses in place labels where CLDR's short names differ.
                   "democratic republic of the congo": "CD", "republic of the congo": "CG", "east timor": "TL",
                   "palestine": "PS", "myanmar": "MM", "burma": "MM", "cabo verde": "CV", "swaziland": "SZ"}


def _norm_country(t: str) -> str:
    """Lower-case with the spelling variants of country names folded ("Trinidad and Tobago" = CLDR's
    "Trinidad & Tobago", "Saint Lucia" = "St. Lucia", "Côte d’Ivoire" = "Côte d'Ivoire")."""
    t = t.strip().lower().replace("’", "'").replace(" and ", " & ")
    return "st. " + t[6:] if t.startswith("saint ") else t


@lru_cache(maxsize=1)
def _country_names() -> dict[str, str]:
    names = {_norm_country(n): code for code, n in Locale("en").territories.items() if len(code) == 2 and code.isalpha()}
    names.update(COUNTRY_ALIASES)
    return names


def country_code(text: str | None) -> str | None:
    """ISO code if the text names a country ("Italy", "the UK"), else None (a city, region or anything else)."""
    if not text:
        return None
    t = _norm_country(text)
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
