"""Place resolution picks the place Google's suggestion means, not the first geocode with a matching name.

Providers are faked (realistic Geoapify / Wikipedia shapes): no network, no recorded responses needed."""

import anyio
import pytest

from travel_agent import net
from travel_agent.providers import geo
from travel_agent.utils import haversine_km


def _r(lat, lon, country, cc, result_type, importance, tz, **kw):
    return {"lat": lat, "lon": lon, "country": country, "country_code": cc, "result_type": result_type,
            "rank": {"importance": importance}, "timezone": {"name": tz}, **kw}


TAIPEI_BALI = _r(25.15, 121.40, "Taiwan", "tw", "suburb", 0.46, "Asia/Taipei", city="Bali District")
BALI_STATE = _r(-8.227, 115.192, "Indonesia", "id", "state", 0.65, "Asia/Makassar", state="Bali")
ROME = _r(41.8933, 12.4829, "Italy", "it", "city", 0.83, "Europe/Rome", city="Rome")
LOMBOK_VILLAGE = _r(0.52, 117.12, "Indonesia", "id", "city", 0.21, "Asia/Makassar", city="Lombok")
LOMBOK_ISLAND = _r(-8.65, 116.32, "Indonesia", "id", "unknown", 0.6, "Asia/Makassar")
BOROVETS_VILLAGE = _r(42.30, 23.12, "Bulgaria", "bg", "city", 0.3, "Europe/Sofia", city="Borovets")
TENERIFE_COLOMBIA = _r(9.9, -74.86, "Colombia", "co", "city", 0.35, "America/Bogota", city="Tenerife")
MALLORCA_PH = _r(10.2, 123.1, "Philippines", "ph", "city", 0.3, "Asia/Manila", city="Mallorca")
MALLORCA_ISLAND = _r(39.61, 2.95, "Spain", "es", "state", 0.7, "Europe/Madrid", state="Balearic Islands")

# (text, type=city?) -> what an unfiltered Geoapify search returns, best match first.
SEARCH = {
    ("Bali, Indonesia", True): [TAIPEI_BALI],
    ("Bali, Indonesia", False): [TAIPEI_BALI, BALI_STATE],
    ("Rome, Italy", True): [ROME],
    ("Rome, Italy", False): [ROME],
    ("Lombok, Indonesia", True): [LOMBOK_VILLAGE],
    ("Lombok, Indonesia", False): [LOMBOK_ISLAND, LOMBOK_VILLAGE],
    ("Borovets, Bulgaria", True): [BOROVETS_VILLAGE],
    ("Tenerife, Spain", True): [TENERIFE_COLOMBIA],
    ("Mallorca, Spain", True): [MALLORCA_PH],
    ("Mallorca, Spain", False): [MALLORCA_PH, MALLORCA_ISLAND],
}
WIKI = {
    "I Gusti Ngurah Rai International Airport": (-8.748, 115.167), "Bali": (-8.335, 115.088),
    "Leonardo da Vinci International Airport": (41.8003, 12.2389), "Rome": (41.8931, 12.4828),
    "Lombok International Airport": (-8.757, 116.276), "Lombok": (-8.565, 116.351),
    "Sofia Airport": (42.695, 23.408), "Borovets": (42.266, 23.606), "Tenerife": (28.27, -16.6),
}
REVERSE = {(28.27, -16.6): _r(28.27, -16.6, "Spain", "es", "city", 0.5, "Atlantic/Canary", city="La Orotava")}


@pytest.fixture
def providers(monkeypatch):
    calls = []

    async def fake_fetch_json(service, url, params=None, *, ttl_s, **_kw):
        calls.append((service, url, dict(params or {})))
        p = params or {}
        if service == "wikipedia":
            point = WIKI.get(p["titles"])
            coords = [{"lat": point[0], "lon": point[1]}] if point else None
            return {"query": {"pages": {"1": {"title": p["titles"], **({"coordinates": coords} if coords else {})}}}}
        if url == geo.GEOAPIFY_REVERSE:
            hit = REVERSE.get((p["lat"], p["lon"]))
            return {"results": [hit] if hit else []}
        results = SEARCH.get((p["text"], p.get("type") == "city"), [])
        if "filter" in p:
            results = [r for r in results if "countrycode:" + r["country_code"] == p["filter"]]
        return {"results": results[: p["limit"]]}

    monkeypatch.setattr(geo.net, "fetch_json", fake_fetch_json)
    return calls


def _suggest(monkeypatch, *suggestions):
    async def fake_autocomplete(q):
        return list(suggestions)

    monkeypatch.setattr(geo, "autocomplete", fake_autocomplete)


def _city(name, gid, *airports):
    return {"type": "city", "name": name, "id": gid,
            "airports": [{"id": code, "name": an, "city": name.split(",")[0], "distance": d} for code, an, d in airports]}


def _resolve(text):
    return anyio.run(lambda: geo.resolve_place(text))


def test_bali_is_the_island_in_indonesia_not_the_taipei_district(providers, monkeypatch):
    _suggest(monkeypatch, _city("Bali, Indonesia", "/g/121hxh1j",
                                ("DPS", "I Gusti Ngurah Rai International Airport", "23 mi")))
    ref = _resolve("Bali")
    assert (ref.name, ref.country, ref.country_code) == ("Bali", "Indonesia", "ID")
    assert haversine_km(ref.lat, ref.lon, -8.748, 115.167) < 150
    assert ref.timezone == "Asia/Makassar"
    assert ref.airports == ["DPS"] and ref.city_id == "/g/121hxh1j"
    # The geocoder was asked inside Indonesia only.
    assert all(c[2].get("filter") == "countrycode:id" for c in providers if c[1] == geo.GEOAPIFY_GEOCODE)


def test_rome_stays_the_city_centre(providers, monkeypatch):
    _suggest(monkeypatch, _city("Rome, Italy", "/m/06c62", ("FCO", "Leonardo da Vinci International Airport", "18 mi")))
    ref = _resolve("Rome")
    assert (ref.name, ref.country_code, ref.timezone) == ("Rome", "IT", "Europe/Rome")
    assert (ref.lat, ref.lon) == (ROME["lat"], ROME["lon"])
    # A city match near the airport needs no second search.
    assert sum(1 for c in providers if c[1] == geo.GEOAPIFY_GEOCODE) == 1


def test_lombok_is_the_island_not_the_same_country_village_far_away(providers, monkeypatch):
    _suggest(monkeypatch, _city("Lombok, Indonesia", "/m/lombok", ("LOP", "Lombok International Airport", "25 mi")))
    ref = _resolve("Lombok")
    assert ref.country_code == "ID"
    assert (ref.lat, ref.lon) == (LOMBOK_ISLAND["lat"], LOMBOK_ISLAND["lon"])


def test_wikipedia_point_of_the_resort_beats_the_same_named_village(providers, monkeypatch):
    _suggest(monkeypatch, _city("Borovets, Bulgaria", "/m/borovets", ("SOF", "Sofia Airport", "45 mi")))
    ref = _resolve("Borovets")
    assert 30 < haversine_km(BOROVETS_VILLAGE["lat"], BOROVETS_VILLAGE["lon"], 42.266, 23.606) < 50
    assert (ref.lat, ref.lon) == (42.266, 23.606) and ref.country_code == "BG"


def test_without_an_airport_point_a_place_in_another_country_is_never_returned(providers, monkeypatch):
    # No Wikipedia coordinates for the airport and the country-filtered search finds nothing: the plain search's
    # Colombian Tenerife is rejected; Wikipedia's Tenerife (reverse-geocoded to Spain) is used instead.
    _suggest(monkeypatch, _city("Tenerife, Spain", "/m/tenerife", ("TFS", "Unlisted Airport", "")))
    ref = _resolve("Tenerife")
    assert (ref.name, ref.country, ref.country_code) == ("Tenerife", "Spain", "ES")
    assert (ref.lat, ref.lon) == (28.27, -16.6) and ref.timezone == "Atlantic/Canary"


def test_without_serpapi_the_country_in_the_text_filters_the_geocoder(providers, monkeypatch):
    async def quota_gone(q):
        raise net.QuotaExceeded("out of searches")

    monkeypatch.setattr(geo, "autocomplete", quota_gone)
    from travel_agent.providers import ai_fallback

    monkeypatch.setattr(ai_fallback, "available", lambda: False)
    ref = _resolve("Mallorca, Spain")
    assert ref.country_code == "ES" and (ref.lat, ref.lon) == (MALLORCA_ISLAND["lat"], MALLORCA_ISLAND["lon"])


def test_the_suggestion_in_the_country_the_text_names_wins():
    us = _city("San Jose, CA, United States", "/m/sj", ("SJC", "San Jose Mineta International Airport", "3 mi"))
    cr = _city("San José, Costa Rica", "/m/sjcr", ("SJO", "Juan Santamaría International Airport", "11 mi"))
    assert geo._pick_suggestion([us, cr], geo._label_country("San Jose, Costa Rica")) is cr
    assert geo._pick_suggestion([us, cr], None) is us


@pytest.mark.parametrize("label, code", [
    ("Bali, Indonesia", "ID"), ("Paris, France", "FR"), ("New York, NY, United States", "US"),
    ("Port of Spain, Trinidad and Tobago", "TT"), ("Castries, Saint Lucia", "LC"), ("Abidjan, Côte d'Ivoire", "CI"),
    ("Kinshasa, Democratic Republic of the Congo", "CD"), ("Rome", None),
])
def test_country_of_a_place_label(label, code):
    assert geo._label_country(label) == code


def test_a_place_with_its_country_is_found_by_its_bare_name_too(providers, monkeypatch):
    # Google answers nothing for "Rome, Italy"-style text at times but finds "Rome": the bare name is searched, and
    # only a suggestion in the stated country is taken.
    rome = _city("Rome, Italy", "/m/06c62", ("FCO", "Leonardo da Vinci International Airport", "16 mi"))
    georgia = _city("Rome, Georgia", "/m/0rome_ga", ("ATL", "Hartsfield-Jackson Atlanta International Airport", "60 mi"))

    async def fake_autocomplete(q):
        return [] if "," in q else [georgia, rome]

    monkeypatch.setattr(geo, "autocomplete", fake_autocomplete)
    ref = _resolve("Rome, Italy")
    assert (ref.name, ref.country_code) == ("Rome", "IT")


def test_an_airport_name_with_an_honorific_still_anchors_the_place(providers, monkeypatch):
    # Google: "Heraklion International Airport N. Kazantzakis"; Wikipedia knows "Heraklion International Airport".
    # Without that anchor a same-named town on the mainland (330 km away) was taken for Crete's Agios Nikolaos.
    mainland = _r(38.35, 22.16, "Greece", "gr", "city", 0.4, "Europe/Athens", city="Agios Nikolaos")
    crete = _r(35.19, 25.72, "Greece", "gr", "city", 0.35, "Europe/Athens", city="Agios Nikolaos")
    SEARCH[("Agios Nikolaos, Greece", True)] = [mainland, crete]
    WIKI["Heraklion International Airport"] = (35.339, 25.180)
    try:
        _suggest(monkeypatch, _city("Agios Nikolaos, Greece", "/m/agn",
                                    ("HER", "Heraklion International Airport N. Kazantzakis", "32 mi")))
        ref = _resolve("Crete, Greece")
    finally:
        SEARCH.pop(("Agios Nikolaos, Greece", True))
        WIKI.pop("Heraklion International Airport")
    assert haversine_km(ref.lat, ref.lon, 35.19, 25.72) < 1