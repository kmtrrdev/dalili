"""Umrah trips: the Holy Mosque anchors the hotel, the rituals are planned only on an Umrah, prayer times every day;
Hajj is never planned."""

from datetime import date

import anyio
from fastapi.testclient import TestClient

from travel_agent import pilgrimage, workflow
from travel_agent.engine.ranking import score_hotel
from travel_agent.models import GeoPoint, HotelOption, Metadata, Money, TravelerProfile, TripState
from travel_agent.nlu import Requirements, TurnInterpretation
from travel_agent.providers import aladhan, wiki

KAABA = GeoPoint(lat=21.4225, lon=39.8262)


def _hotel(hid: str, lat: float, lon: float, price: float = 200, rating: float = 4.5) -> HotelOption:
    return HotelOption(id=hid, name=hid, neighborhood="", location=GeoPoint(lat=lat, lon=lon), rating=rating,
                       price_per_night=Money(amount=price, currency="SAR"),
                       metadata=Metadata(source="test", provider="test"))


def test_the_holy_cities_are_recognised_by_where_they_are():
    assert pilgrimage.holy_city(21.43, 39.82) == "makkah" and pilgrimage.holy_city(24.47, 39.61) == "madinah"
    assert pilgrimage.holy_city(21.54, 39.17) is None  # Jeddah


def test_the_walk_to_the_haram_leads_the_hotel_choice():
    near, far = _hotel("Near", 21.4235, 39.8262, price=400), _hotel("Far", 21.40, 39.87, price=150)
    args = ([KAABA], TravelerProfile(), "balanced", 400.0)
    a, b = score_hotel(near, *args, anchor_name="Masjid al-Haram"), score_hotel(far, *args, anchor_name="Masjid al-Haram")
    assert a.score > b.score and any("min walk to Masjid al-Haram" in r for r in a.reasons)
    assert any("shuttle or taxi" in t for t in b.tradeoffs)


def test_sacred_sites_use_wikipedias_coordinates_and_mark_the_rituals(monkeypatch):
    async def find(title):
        return None if title == "Jabal Thawr" else {"title": title, "coordinates": {"lat": 21.45, "lon": 39.86}}

    monkeypatch.setattr(wiki, "find_article", find)
    sites = anyio.run(pilgrimage.sacred_sites, "makkah")
    names = [s["name"] for s in sites]
    assert names[0].startswith("Umrah") and "ritual" in sites[0]["categories"]
    assert not any("Thawr" in n for n in names)  # no coordinates: never placed on a guessed point


def test_prayer_times_and_the_season_reach_the_plan():
    from travel_agent.models import DayPlan, ResearchBundle, TripPlan

    day = {"times": {"Fajr": "05:21", "Dhuhr": "12:10", "Asr": "15:16", "Maghrib": "17:37", "Isha": "19:07"},
           "hijri": {"day": 2, "month": 9, "year": 1448, "month_en": "Ramadan", "month_ar": "رمضان"}}
    b = ResearchBundle(destination_info={"holy": pilgrimage.HOLY["makkah"], "prayer_times": {"2027-02-10": day}})
    plan = TripPlan(mode="balanced", days=[DayPlan(day=1, date=date(2027, 2, 10), title="Umrah")])
    pilgrimage.add_prayer_notes(plan, [b], [(date(2027, 2, 10), date(2027, 2, 14))])
    assert plan.days[0].notes[0] == ("🕌 Prayer times in Makkah: Fajr 05:21 · Dhuhr 12:10 · Asr 15:16 · Maghrib 17:37 · "
                                     "Isha 19:07")
    assert "Ramadan" in pilgrimage.season_notes([b])[0]


def test_hajj_is_never_planned_but_explained():
    trip = TripState()
    out = anyio.run(workflow.check_requirements, {"trip": trip, "interpretation": TurnInterpretation(
        intent="plan_request", requirements=Requirements(pilgrimage="hajj", destination="Mecca, Saudi Arabia"))})
    assert out["route"] == "ask" and trip.pending_questions == [pilgrimage.HAJJ_NOTE] and trip.trip_contract is None


def test_the_prayer_times_page(monkeypatch):
    from travel_agent.api import app

    async def times(lat, lon, start, end):
        assert (lat, lon) == (pilgrimage.HOLY["madinah"]["lat"], pilgrimage.HOLY["madinah"]["lon"])
        return {start.isoformat(): {"times": {"Fajr": "05:30"}, "hijri": {"day": 1, "month": 7}}}

    monkeypatch.setattr(aladhan, "prayer_times", times)
    body = TestClient(app).get("/api/pilgrimage/prayer-times", params={"city": "madinah", "start": "2027-01-05"}).json()
    assert body["method"] == "Umm al-Qura" and body["days"]["2027-01-05"]["times"]["Fajr"] == "05:30"
