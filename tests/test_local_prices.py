"""Verified local prices: Wikivoyage listing parsing, price reading, place matching, quote verification."""

import anyio

from travel_agent import llm
from travel_agent.models import GeoPoint, Metadata, Money, Place, ResearchBundle
from travel_agent.providers import local_prices as lp, routing
from travel_agent.research import apply_local_prices


def test_listing_templates_are_parsed_with_nested_templates():
    wt = ("{{see | name=Acropolis Museum | lat=37.9684 | long=23.7285 | price=€20, reduced €10 | lastedit=2025-03-02 "
          "| content=The museum {{cite|x}}.}}\n{{listing | type=see | name=Egyptian Museum | price={{EGP|550}}, "
          "students {{EGP|275}} }}\n{{sleep | name=Hotel | price=€90}}\n{{eat|name=[[Taverna|Taverna Plaka]]|price=Mains €12-18}}")
    items = [x for x in (lp.parse_listing(b) for b in lp._templates(wt)) if x]
    assert [(i["kind"], i["name"]) for i in items] == [("see", "Acropolis Museum"), ("see", "Egyptian Museum"),
                                                      ("eat", "Taverna Plaka")]  # sleep listings are ignored
    assert items[0]["price_text"] == "€20, reduced €10" and items[0]["lastedit"] == "2025-03-02"
    assert items[1]["price_text"].startswith("EGP 550")


def test_prices_need_an_explicit_currency():
    cases = {
        "€20, reduced €10": (20.0, "EUR", False),
        "10€ - 18€. Free every Sunday after 3pm": (10.0, "EUR", False),
        "Adult 550 LE, student: 275 LE": (550.0, "EGP", False),
        "LE550 (students LE300)": (550.0, "EGP", False),
        "€27 + 50 TL boat trip": (27.0, "EUR", False),       # the first currency names the standard price
        "60 TL": (60.0, "TRY", False),
        "Free entry, donations welcome": (0.0, "EUR", True),
        "Medium price": (None, None, False),                  # no number
        "20": (None, None, False),                            # a bare number is not certain enough
        "Ticket prices vary": (None, None, False),
        "1,200 Kč": (1200.0, "CZK", False),
    }
    for text, want in cases.items():
        assert lp.parse_price(text, "EUR") == want, text


def test_matching_by_name_and_place_never_confuses_a_site_with_its_museum():
    items = [
        {"kind": "see", "name": "Acropolis", "alt": "", "lat": 37.9715, "lon": 23.7257},
        {"kind": "see", "name": "Acropolis Museum", "alt": "", "lat": 37.9684, "lon": 23.7285},
        {"kind": "eat", "name": "Colosseum Bar", "alt": "", "lat": None, "lon": None},
        {"kind": "see", "name": "Temple of Olympian Zeus", "alt": "", "lat": 37.9693, "lon": 23.7331},
    ]
    assert lp.match("Acropolis Museum", 37.9685, 23.7286, items, {"see"})["name"] == "Acropolis Museum"
    assert lp.match("Acropolis of Athens", 37.9715, 23.7257, items, {"see"})["name"] == "Acropolis"
    assert lp.match("Temple of Olympian Zeus, Athens", 37.9693, 23.7331, items, {"see"})["name"] == "Temple of Olympian Zeus"
    assert lp.match("Colosseum", 41.89, 12.49, items, {"see"}) is None  # an "eat" listing never prices a sight
    assert lp.match("Acropolis", 40.0, 20.0, items, {"see"}) is None     # same name far away: not the same place


def test_quoted_tariffs_are_accepted_only_verbatim(monkeypatch):
    text = ("Get around. A single ticket costs €1.20 and is valid for 90 minutes. Taxis charge a flag fall of €1.85 "
            "plus €0.90 per km. From the airport, taxis have a fixed fare of €40 to the city centre (€55 at night).")
    out = lp.Tariffs(
        transit_single_ticket=lp.Quoted(amount=1.2, currency="EUR", quote="A single ticket costs €1.20"),
        taxi_flag_fall=lp.Quoted(amount=1.85, currency="EUR", quote="a flag fall of €1.85"),
        taxi_per_km=lp.Quoted(amount=1.2, currency="EUR", quote="€0.90 per km"),  # wrong number -> rejected
        transit_day_pass=lp.Quoted(amount=4.1, currency="EUR", quote="A day pass costs €4.10"),  # not in text
        airport_fares=[lp.AirportFare(amount=40, currency="EUR", quote="taxis have a fixed fare of €40 to the city centre",
                                      airport="the airport", mode="taxi"),
                       # too short to show what it is for / doesn't say "taxi" -> rejected
                       lp.AirportFare(amount=55, currency="EUR", quote="€55 at night", airport="the airport", mode="taxi"),
                       lp.AirportFare(amount=40, currency="EUR", quote="a fixed fare of €40 to the city centre",
                                      airport="airport", mode="bus")])

    async def parse(system, user, schema, max_tokens=16000):
        return out

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "parse", parse)
    res = anyio.run(lp.tariffs, "Athens", text)
    assert res["transit_single_ticket"]["amount"] == 1.2 and res["taxi_flag_fall"]["amount"] == 1.85
    assert "taxi_per_km" not in res and "transit_day_pass" not in res
    assert [f["amount"] for f in res["airport_fares"]] == [40]


def _place(pid, name, kind, lat, lon):
    return Place(id=pid, name=name, kind=kind, location=GeoPoint(lat=lat, lon=lon),
                 cost_per_person=Money(amount=18, currency="USD"), metadata=Metadata(source="t", provider="t"))


def test_published_prices_replace_estimates_and_fares_become_verified():
    b = ResearchBundle(attractions=[_place("a1", "Acropolis Museum", "attraction", 37.9684, 23.7285),
                                    _place("a2", "Unknown Gallery", "attraction", 37.97, 23.73),
                                    _place("a3", "Colosseum", "attraction", 41.8902, 12.4922)],
                       restaurants=[_place("r1", "Taverna Plaka", "restaurant", 37.972, 23.73)],
                       fx_rates={"USD": 1.0, "EUR": 1.1}, fares={"transit": 2.0, "taxi_base": 4.0, "taxi_per_km": 1.5})
    prices = {"listings_total": 3, "listings": [
        {"kind": "see", "name": "Acropolis Museum", "alt": "", "lat": 37.9684, "lon": 23.7285, "price_text": "€20, reduced €10",
         "amount": 20.0, "currency": "EUR", "free": False, "lastedit": "2025-03-02"},
        {"kind": "eat", "name": "Taverna Plaka", "alt": "", "lat": None, "lon": None, "price_text": "Mains €12-18",
         "amount": 12.0, "currency": "EUR", "free": False, "lastedit": "2025-01-10"},
        {"kind": "see", "name": "Colosseum", "alt": "", "lat": 41.8902, "lon": 12.4922, "price_text": "€12",
         "amount": 12.0, "currency": "EUR", "free": False, "lastedit": "2019-04-01"}],
        "tariffs": {"transit_single_ticket": {"amount": 1.2, "currency": "EUR", "quote": "A single ticket costs €1.20"},
                    "taxi_flag_fall": {"amount": 1.85, "currency": "EUR", "quote": "flag fall of €1.85"},
                    "taxi_per_km": {"amount": 0.9, "currency": "EUR", "quote": "€0.90 per km"}, "airport_fares": []}}
    apply_local_prices(b, prices, "USD")
    museum, gallery, colosseum = b.attractions
    assert museum.price_known and museum.cost_per_person.amount == 20 and museum.cost_per_person.currency == "EUR"
    assert museum.cost_per_person.price_type == "known" and museum.cost_per_person.source == "Wikivoyage · updated 2025-03"
    assert not gallery.price_known and gallery.cost_per_person.price_type == "estimated"  # never invented
    # A price last checked in 2019 is only a reference: used for the estimate, never shown as verified.
    assert not colosseum.price_known and colosseum.cost_per_person.price_type == "estimated"
    assert colosseum.cost_per_person.amount == 12 and "may have changed" in colosseum.cost_per_person.source
    assert b.restaurants[0].cost_per_person.price_type == "range"
    assert b.fares["transit"] == 1.32 and b.fares["transit_verified"] == 1.0
    assert b.fares["taxi_base"] == 2.04 and b.fares["taxi_verified"] == 1.0
    assert b.price_coverage["attractions"] == {"verified": 1, "total": 3} and b.price_coverage["taxi"]
    # City legs now carry the verified fare type.
    walk, transit, taxi = routing.options(GeoPoint(lat=37.97, lon=23.72), GeoPoint(lat=37.99, lon=23.74), 1, b.fares, "USD")
    assert transit.cost.price_type == "known" and taxi.cost.price_type == "calculated"


def test_google_transit_fare_is_used_when_shown():
    assert routing.google_fare({"cost": 7.75, "currency": "EUR"}).model_dump(exclude={"source"}) == \
        {"amount": 7.75, "currency": "EUR", "price_type": "known"}
    assert routing.google_fare({"cost": None, "currency": "EUR"}) is None
    assert routing.google_fare({"duration": 1200}) is None
