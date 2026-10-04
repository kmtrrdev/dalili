"""Trip ideas for a budget: group costing, budget tiers, preferences (no network: a fake MCP hub)."""

import anyio
from datetime import date

from travel_agent import suggest as suggest_mod
from travel_agent.models import PlaceRef

ATHENS = {"name": "Athens", "country": "Greece", "start_date": "2026-12-03", "end_date": "2026-12-09",
          "flight_price": 184, "hotel_price": 86, "lat": 37.98, "lon": 23.72}
LONDON = {"name": "London", "country": "United Kingdom", "start_date": "2026-12-26", "end_date": "2027-01-01",
          "flight_price": 366, "hotel_price": 194}
ZURICH = {"name": "Zurich", "country": "Switzerland", "start_date": "2026-12-01", "end_date": "2026-12-07",
          "flight_price": 700, "hotel_price": 300}


class FakeHub:
    def __init__(self, by_interest=None):
        self.calls = []
        self.by_interest = by_interest or {}

    async def call(self, server, tool, args):
        assert (server, tool) == ("activities", "explore_destinations")
        self.calls.append(args)
        n = args.get("adults", 1)  # like Google: the fare covers every adult searched for
        group = lambda ds: [dict(d, flight_price=d["flight_price"] * n) for d in ds]
        if "interest" in args:
            return {"destinations": group(self.by_interest.get(args["interest"], []))}
        return {"destinations": group([ATHENS, LONDON, ZURICH])}


def _setup(monkeypatch):
    async def cairo(hub, text):
        return PlaceRef(name="Cairo", country="Egypt", country_code="EG", lat=30.04, lon=31.24, airports=["CAI"])

    monkeypatch.setattr(suggest_mod.research, "resolve_place", cairo)
    monkeypatch.setattr(suggest_mod.llm, "available", lambda: False)  # offline ranking


def test_ideas_are_costed_for_the_group_and_split_into_budget_tiers(monkeypatch):
    _setup(monkeypatch)
    hub = FakeHub()
    res = anyio.run(lambda: suggest_mod.suggest(hub, 2000, "USD", "Cairo", travelers=2, duration="week"))
    assert hub.calls[0]["departure_id"] == "CAI" and hub.calls[0]["travel_duration"] == 2 and hub.calls[0]["adults"] == 2
    by = {i["name"]: i for i in res["ideas"]}
    # 2 travellers -> 2 flights (Google's group fare, counted once), 1 room x 6 nights
    assert by["Athens"]["flight_price"] == 184  # shown per person
    assert by["Athens"]["total"] == 184 * 2 + 86 * 6 and by["Athens"]["fit"] == "comfortable"
    # London: 2 x 366 + 194 x 6 = 1896 -> within budget but leaves little for food & sights
    assert by["London"]["fit"] == "tight" and by["London"]["left"] == 104
    # Zurich is over budget: the page still has fewer than MIN_IDEAS, so it is shown last and marked
    assert by["Zurich"]["fit"] == "over" and res["ideas"][-1]["name"] == "Zurich"
    assert res["all_fit"] and not res["personal"]


def test_exact_dates_and_flight_preferences_reach_the_search(monkeypatch):
    _setup(monkeypatch)
    hub = FakeHub()
    res = anyio.run(lambda: suggest_mod.suggest(hub, 3000, "USD", "Cairo", start_date=date(2026, 12, 10),
                                                end_date=date(2026, 12, 14), direct_only=True, max_flight_hours=5))
    args = hub.calls[0]
    assert args["outbound_date"] == "2026-12-10" and args["return_date"] == "2026-12-14"
    assert "month" not in args and "travel_duration" not in args
    assert args["stops"] == 1 and args["max_duration"] == 300
    athens = next(i for i in res["ideas"] if i["name"] == "Athens")
    assert athens["nights"] == 4 and athens["start_date"] == "2026-12-10"  # the traveller's dates, not Google's


def test_interests_search_google_topics_and_rank_matches_first(monkeypatch):
    _setup(monkeypatch)
    beach = dict(ATHENS, name="Santorini")
    hub = FakeHub({suggest_mod.GOOGLE_INTEREST["beach"]: [beach, ATHENS]})
    res = anyio.run(lambda: suggest_mod.suggest(hub, 2000, "USD", "Cairo", interests=["beach", "food"]))
    # food has no Google topic; only two beach results, so the popular list widens the choice
    assert [c.get("interest") for c in hub.calls] == [suggest_mod.GOOGLE_INTEREST["beach"], None]
    assert res["personal"] and res["ideas"][0]["name"] == "Santorini" and res["ideas"][0]["matched"] == ["beach"]
    assert {"London", "Zurich"} <= {i["name"] for i in res["ideas"]}
    london = next(i for i in res["ideas"] if i["name"] == "London")
    assert london["score"] < res["ideas"][0]["score"]  # no beach match -> ranked below


class DestHub:
    """Autocomplete + explore for the optional 'To' field."""
    PLACES = {"paris": {"kind": "city", "id": "/m/paris", "name": "Paris, France"},
              "france": {"kind": "region", "id": "/m/france", "name": "France"},
              "annecy": {"kind": "city", "id": "/m/annecy", "name": "Annecy, France"}}

    def __init__(self):
        self.calls = []

    async def call(self, server, tool, args):
        self.calls.append((tool, args))
        if tool == "resolve_destination":
            return {"result": self.PLACES[args["query"].lower()]}
        if args.get("arrival_area_id") == "/m/france":
            return {"destinations": [dict(ATHENS, name="Lyon", country="France"), dict(LONDON, name="Paris", country="France")]}
        if args.get("arrival_id") == "/m/annecy":  # one city: flights only (as providers.flights.explore shapes it)
            return {"destinations": [{"name": None, "country": None, "start_date": "2026-12-03", "end_date": "2026-12-09",
                                      "flight_price": 300, "hotel_price": None, "flights_only": True}]}
        return {"destinations": []}


def test_a_named_city_is_searched_through_its_country_and_comes_first(monkeypatch):
    _setup(monkeypatch)
    hub = DestHub()
    res = anyio.run(lambda: suggest_mod.suggest(hub, 2000, "USD", "Cairo", destination="Paris"))
    explore = [a for tool, a in hub.calls if tool == "explore_destinations"]
    assert explore and all(a.get("arrival_area_id") == "/m/france" for a in explore)  # full prices incl. hotel
    assert res["ideas"][0]["name"] == "Paris" and res["ideas"][0]["target"]  # first, even though Lyon is cheaper
    assert [i["name"] for i in res["ideas"]][1:] == ["Lyon"] and res["destination"]["kind"] == "city"


def test_a_small_city_missing_from_its_country_list_is_searched_alone(monkeypatch):
    _setup(monkeypatch)
    res = anyio.run(lambda: suggest_mod.suggest(DestHub(), 2000, "USD", "Cairo", destination="Annecy"))
    first = res["ideas"][0]
    assert first["name"] == "Annecy" and first["country"] == "France" and first["target"]
    assert first["hotel_unknown"] and first["total"] == 300  # flights only, flagged


def test_empty_topic_search_falls_back_to_the_popular_list_not_estimates(monkeypatch):
    _setup(monkeypatch)
    hub = FakeHub()  # the beach topic returns nothing
    res = anyio.run(lambda: suggest_mod.suggest(hub, 2000, "USD", "Cairo", interests=["beach"]))
    assert not res["estimated"] and {i["name"] for i in res["ideas"]} == {"Athens", "London", "Zurich"}
