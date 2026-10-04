"""Pure parsing/classification logic over real provider payload shapes (no network)."""

from datetime import date

import pytest

from travel_agent import knowledge
from travel_agent.providers.events import _event_date, _event_times
from travel_agent.providers.flights import _parse_itinerary
from travel_agent.providers.hotels import noise_from_reviews
from travel_agent.providers.places import classify, dedupe, parse_google_hours, parse_price, _google_attraction, _google_restaurant


def test_google_hours_formats():
    h = parse_google_hours({
        "monday": "9 AM–12:30 PM, 2–6 PM",
        "tuesday": "12–11:30 PM",
        "wednesday": "Open 24 hours",
        "thursday": "Closed",
        "friday": "6 PM–2 AM",
        "saturday": "11–2 PM",
    })
    assert h["mon"] == [["09:00", "12:30"], ["14:00", "18:00"]]
    assert h["tue"] == [["12:00", "23:30"]]
    assert h["wed"] == [["00:00", "23:59"]]
    assert h["thu"] == []
    assert h["fri"] == [["18:00", "23:59"]], "past-midnight closing is clamped to the same day"
    assert h["sat"] == [["11:00", "14:00"]], "'11-2 PM' means 11 AM to 2 PM"
    assert h["sun"] == [], "days Google omits are treated as unknown/closed"
    assert parse_google_hours(None) is None


@pytest.mark.parametrize("text,expected", [
    ("€10–20", (15.0, "EUR", None)), ("$$", (None, None, 2)), ("£8", (8.0, "GBP", None)), (None, (None, None, None)),
])
def test_price_parsing(text, expected):
    assert parse_price(text, "EUR") == expected


def test_classification_of_google_types():
    cats, indoor, minutes, ticket, matched = classify(["Tourist attraction", "Museum", "Art museum"])
    assert "museums" in cats and indoor and minutes >= 90 and ticket > 0
    cats, indoor, minutes, ticket, _ = classify(["Tourist attraction", "Historical landmark", "Fountain"])
    assert not indoor and minutes <= 30 and ticket == 0 and "photography" in cats


def test_attraction_filters_and_assumptions():
    junk = {"title": "Some tour shop", "types": ["Tour operator"], "reviews": 5000, "gps_coordinates": {"latitude": 1, "longitude": 1}}
    assert _google_attraction(junk, "EUR") is None
    few = {"title": "Tiny plaque", "types": ["Tourist attraction"], "reviews": 12, "gps_coordinates": {"latitude": 1, "longitude": 1}}
    assert _google_attraction(few, "EUR") is None
    museum = {"title": "City Museum", "place_id": "x", "types": ["Museum"], "reviews": 9000, "rating": 4.7,
              "gps_coordinates": {"latitude": 41.9, "longitude": 12.5}}
    p = _google_attraction(museum, "EUR")
    assert p and not p.hours_verified and not p.price_known and p.cost_per_person.price_type == "estimated"
    colosseum = {"title": "Colosseum", "place_id": "c", "types": ["Tourist attraction", "Historical landmark"],
                 "reviews": 500000, "gps_coordinates": {"latitude": 41.89, "longitude": 12.49}}
    c = _google_attraction(colosseum, "EUR")
    assert c.duration_minutes >= 90 and c.cost_per_person.amount > 0 and c.popularity == "must_see"


def test_restaurant_meal_types_and_diet():
    cafe = {"title": "Forno Roma", "place_id": "f", "types": ["Bakery", "Cafe"], "reviews": 800, "rating": 4.6,
            "gps_coordinates": {"latitude": 41.9, "longitude": 12.5},
            "operating_hours": {d: "7 AM–8 PM" for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")}}
    p = _google_restaurant(cafe, "EUR")
    assert p.kind == "cafe" and {"breakfast", "coffee", "dessert"} <= set(p.meal_types) and p.hours_verified
    veg = {"title": "Green Place", "place_id": "g", "types": ["Vegetarian restaurant"], "reviews": 300, "price": "€10–20",
           "gps_coordinates": {"latitude": 41.9, "longitude": 12.5}}
    v = _google_restaurant(veg, "EUR")
    assert "vegetarian" in v.dietary and v.price_known and v.cost_per_person.amount == 15.0


def test_dedupe_keeps_better_known_spot():
    a = _google_attraction({"title": "Spanish Steps", "place_id": "a", "types": ["Monument"], "reviews": 112000,
                            "gps_coordinates": {"latitude": 41.90599, "longitude": 12.48277}}, "EUR")
    b = _google_attraction({"title": "Piazza di Spagna", "place_id": "b", "types": ["Plaza"], "reviews": 90000,
                            "gps_coordinates": {"latitude": 41.9056, "longitude": 12.4823}}, "EUR")
    assert [p.name for p in dedupe([b, a])] == ["Spanish Steps"]


def test_flight_itinerary_parsing_with_timezones():
    it = {"flights": [{"departure_airport": {"name": "Cairo", "id": "CAI", "time": "2026-10-12 04:45"},
                       "arrival_airport": {"name": "Fiumicino", "id": "FCO", "time": "2026-10-12 07:10"},
                       "duration": 205, "airline": "ITA", "flight_number": "AZ 895", "travel_class": "Economy",
                       "extensions": ["Average legroom (31 in)"]}],
          "total_duration": 205, "price": 190, "carbon_emissions": {"this_flight": 190000}}
    f = _parse_itinerary(it, "outbound", "Africa/Cairo", "Europe/Rome", "USD", "https://g.co/x")
    assert f.price_per_person.amount == 190 and f.price_per_person.price_type == "known"
    assert f.depart_at.utcoffset().total_seconds() == 3 * 3600 and f.arrive_at.utcoffset().total_seconds() == 2 * 3600
    assert (f.arrive_at - f.depart_at).total_seconds() / 60 == 205, "tz-aware times give the true flight duration"
    assert f.stops == 0 and f.carbon_kg == 190 and f.booking_url


def test_noise_from_reviews_handles_negation():
    assert noise_from_reviews([{"snippet": "Noise levels were fine at night, not too loud."}] * 2)[0] != "noisy"
    level, ev = noise_from_reviews([{"snippet": "Very noisy street, hard to sleep."}, {"snippet": "Loud bar below the room."}])
    assert level == "noisy" and ev
    assert noise_from_reviews([{"snippet": "Great breakfast."}])[0] == "unknown"


def test_event_date_and_time_parsing():
    assert _event_date("Oct 14", date(2026, 10, 12), date(2026, 10, 18)) == date(2026, 10, 14)
    assert _event_date("Dec 1", date(2026, 10, 12), date(2026, 10, 18)) is None
    assert _event_times("Wed, Oct 14, 8 – 10:30 PM") == (20 * 60, 22 * 60 + 30)


def test_wikivoyage_sections_phrases_and_retrieval():
    text = ("Rome is the capital.\n== Understand ==\nAncient city with many layers of history and ruins everywhere.\n"
            "== Respect ==\nCover your shoulders and knees when you visit churches in the city please.\n"
            "== Stay safe ==\nThe emergency number is 112 and police can be reached quickly from any phone.\n")
    intro, sections = knowledge._sections(text)
    assert intro == "Rome is the capital." and {"Understand", "Respect", "Stay safe"} <= set(sections)
    pb = "Intro\n=== Basics ===\nHello.\nCiao. (chow)\nThank you.\nGrazie. (GRAHT-tsyeh)\n"
    assert knowledge._phrases(pb) == [["Hello", "Ciao. (chow)"], ["Thank you", "Grazie. (GRAHT-tsyeh)"]]
    guide = {"overview": intro, "sections": sections}
    top = knowledge.search(guide, "what should I wear in churches?")
    assert top and "shoulders" in top[0]["text"]
