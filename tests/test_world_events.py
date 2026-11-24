"""World-famous events: only what the sources confirm, offered during a trip, added to the plan only on a yes."""

from datetime import date

import anyio
import pytest
from fastapi.testclient import TestClient

from travel_agent import narrative, research
from travel_agent.models import TripState
from travel_agent.nlu import Action
from travel_agent.providers import world_events as we
from travel_agent.workflow import run_turn

from .conftest import ROME_REQUEST

WINDOW = (date(2026, 9, 27), date(2027, 10, 31))
# Out of town (~29 km, like a circuit or a stadium): an outing on the day, not a day trip that owns it.
FILM_FEST = we.WorldEvent(
    id="Q1", name="Rome Film Fest", name_ar="مهرجان روما السينمائي", category="music", city="Rome", country_code="IT",
    lat=41.70, lon=12.25, start=date(2026, 10, 15), end=date(2026, 10, 25), dates_source="wikidata",
    why="Premieres and stars at the Auditorium", wikipedia="https://en.wikipedia.org/wiki/Rome_Film_Fest",
    website="https://www.romacinemafest.it", fame=30,
    ticket=we.Ticket(amount=20, currency="EUR", source="official site", quote="Biglietti da 20 €"))
MILAN_DESIGN = FILM_FEST.model_copy(update={"id": "Q2", "name": "Milan Design Week", "city": "Milan",
                                            "lat": 45.464, "lon": 9.19})
OKTOBERFEST = FILM_FEST.model_copy(update={"id": "Q3", "name": "Oktoberfest", "city": "Munich", "country_code": "DE"})


def test_fixed_rules_give_the_real_dates():
    assert we.easter(2027) == date(2027, 3, 28) and we.easter(2025) == date(2025, 4, 20)
    okt = next(f for f in we.FIXED if f.title == "Oktoberfest").rule
    assert okt(2026) == (date(2026, 9, 19), date(2026, 10, 4))
    assert okt(2023) == (date(2023, 9, 16), date(2023, 10, 3))  # 3 October is later than the first Sunday
    assert okt(2018)[0] == date(2018, 9, 22)  # 15 September was a Saturday: the next one
    rio = next(f for f in we.FIXED if f.title == "Rio Carnival").rule
    assert rio(2027) == (date(2027, 2, 5), date(2027, 2, 10))  # Friday to Ash Wednesday
    market = next(f for f in we.FIXED if f.title.startswith("Christkindlesmarkt")).rule
    assert market(2026) == (date(2026, 11, 27), date(2026, 12, 24))
    fringe = next(f for f in we.FIXED if f.title == "Edinburgh Festival Fringe").rule
    assert fringe(2025) == (date(2025, 8, 1), date(2025, 8, 25))
    hogmanay = [c for c in we.fixed_candidates(WINDOW) if c.title == "Hogmanay"]
    assert [(c.start, c.end) for c in hogmanay] == [(date(2026, 12, 30), date(2027, 1, 1))]


@pytest.mark.parametrize("raw,year,span", [
    ("23 December 2027 – 21 January 2028", 2027, ((2027, 12, 23), (2028, 1, 21))),
    ("19 June – 17 July", 2027, ((2027, 6, 19), (2027, 7, 17))),
    ("5–20 June 2027<ref>{{cite web|url=x}}</ref>", 2027, ((2027, 6, 5), (2027, 6, 20))),
    ("June 5{{ndash}}20, 2027", 2027, ((2027, 6, 5), (2027, 6, 20))),
    ("{{start date|2027|1|13}} – {{end date|2027|1|31}}", 2027, ((2027, 1, 13), (2027, 1, 31))),
    ("[[28 December]] 2026 to 5 January 2027<br />Final: 5 January", 2026, ((2026, 12, 28), (2027, 1, 5))),
    ("October–November 2027", 2027, None),  # no days: nothing to plan around
    ("TBA", 2027, None),
])
def test_infobox_dates_are_read_or_refused(raw, year, span):
    expect = (date(*span[0]), date(*span[1])) if span else None
    assert we.parse_span(raw, year) == expect


def _row(**kw) -> dict:
    return {k: {"value": v} for k, v in kw.items()}


def test_wikidata_rows_become_dated_famous_events_only():
    rows = [
        _row(item="http://www.wikidata.org/entity/Q1", n="20", start="2027-07-02T00:00:00Z", prec="11"),
        _row(item="http://www.wikidata.org/entity/Q1", root="http://www.wikidata.org/entity/Q16510064", cc="fr",
             end="2027-07-25T00:00:00Z", endPrec="11", locLabel="Stade X", upLabel="Lyon"),
        # Known to the year only: the infobox has to give the days.
        _row(item="http://www.wikidata.org/entity/Q2", n="20", start="2027-01-01T00:00:00Z", prec="9"),
        _row(item="http://www.wikidata.org/entity/Q2", root="http://www.wikidata.org/entity/Q13406554", cc="KE"),
        # An election: dated and famous, but not something people travel to.
        _row(item="http://www.wikidata.org/entity/Q3", n="40", start="2027-04-18T00:00:00Z", prec="11"),
        # Famous only in the region: kept in Saudi Arabia, dropped elsewhere.
        _row(item="http://www.wikidata.org/entity/Q4", n="5", start="2026-12-05T00:00:00Z", prec="11"),
        _row(item="http://www.wikidata.org/entity/Q4", root="http://www.wikidata.org/entity/Q16510064", cc="SA",
             locLabel="Riyadh", locTown="true"),
        _row(item="http://www.wikidata.org/entity/Q5", n="5", start="2026-12-05T00:00:00Z", prec="11"),
        _row(item="http://www.wikidata.org/entity/Q5", root="http://www.wikidata.org/entity/Q16510064", cc="US"),
    ]
    got = {c.qid: c for c in we.wikidata_candidates(rows)}
    assert set(got) == {"Q1", "Q2", "Q4"}
    assert (got["Q1"].start, got["Q1"].end, got["Q1"].country_code, got["Q1"].city) == \
        (date(2027, 7, 2), date(2027, 7, 25), "FR", "Lyon")
    assert got["Q2"].start is None and got["Q2"].approx == (2027, None)
    assert got["Q4"].city == "Riyadh"


def test_formula_1_weekends_run_from_practice_to_the_race():
    races = [{"season": "2026", "raceName": "Qatar Grand Prix", "date": "2026-11-29",
              "url": "https://en.wikipedia.org/wiki/2026_Qatar_Grand_Prix", "FirstPractice": {"date": "2026-11-27"},
              "Circuit": {"Location": {"lat": "25.49", "long": "51.45", "locality": "Lusail", "country": "Qatar"}}}]
    c, = we.f1_candidates(races)
    assert (c.title, c.fallback_title, c.start, c.end, c.country_code, c.city) == \
        ("2026 Qatar Grand Prix", "Qatar Grand Prix", date(2026, 11, 27), date(2026, 11, 29), "QA", "Lusail")


def _wiki(monkeypatch, articles: dict, infobox: tuple | None = None):
    async def summary(title, lang="en"):
        return articles.get((lang, title))

    async def entity(qid):
        return {"sitelinks": {f"w{i}": {} for i in range(30)} | {"arwiki": {"title": "أكتوبرفست"}},
                "labels": {"ar": {"value": "أكتوبرفست"}}, "claims": {}}

    async def box(title, year):
        return infobox

    monkeypatch.setattr(we.wiki, "summary", summary)
    monkeypatch.setattr(we.wiki, "entity", entity)
    monkeypatch.setattr(we, "infobox_dates", box)


OKT_ARTICLE = {"title": "Oktoberfest", "wikibase_item": "Q32", "extract": "Oktoberfest is the world's largest Volksfest. "
               "It is held in Munich.", "content_urls": {"desktop": {"page": "https://w/Oktoberfest"}}}


def test_a_described_event_carries_its_article_in_both_languages(monkeypatch):
    _wiki(monkeypatch, {("en", "Oktoberfest"): OKT_ARTICLE,
                        ("ar", "أكتوبرفست"): {"title": "أكتوبرفست", "wikibase_item": "Q32",
                                              "extract": "أكتوبرفست هو أكبر مهرجان شعبي في العالم. يقام في ميونخ."}})
    c, = [c for c in we.fixed_candidates(WINDOW) if c.title == "Oktoberfest" and c.start.year == 2027]
    ev = anyio.run(we.describe, c, WINDOW)
    assert (ev.id, ev.start, ev.end, ev.dates_source) == ("Q32@2027-09-18", date(2027, 9, 18), date(2027, 10, 3),
                                                          "fixed date")
    assert ev.why == "Oktoberfest is the world's largest Volksfest." and ev.why_ar.startswith("أكتوبرفست هو")
    assert ev.name_ar == "أكتوبرفست" and ev.fame == 31 and ev.ticket is None


def test_dates_known_to_the_year_need_the_infobox(monkeypatch):
    art = {("en", "2027 Africa Cup of Nations"): {"title": "2027 Africa Cup of Nations", "wikibase_item": "Q2",
                                                   "extract": "The 2027 Africa Cup of Nations will be the 36th edition."}}
    c = we.Candidate(title="2027 Africa Cup of Nations", qid="Q2", category="sports", country_code="KE",
                     approx=(2027, None), dates_source="wikidata")
    _wiki(monkeypatch, art, (date(2027, 6, 19), date(2027, 7, 17)))
    ev = anyio.run(we.describe, c, WINDOW)
    assert (ev.start, ev.end, ev.dates_source) == (date(2027, 6, 19), date(2027, 7, 17), "wikipedia")
    _wiki(monkeypatch, art, None)
    assert anyio.run(we.describe, c, WINDOW) is None  # no days anywhere: left out, never guessed
    _wiki(monkeypatch, art, (date(2028, 6, 19), date(2028, 7, 17)))
    assert anyio.run(we.describe, c, WINDOW) is None  # the infobox speaks of another year


def test_a_grand_prix_redirected_to_the_season_takes_the_races_own_article(monkeypatch):
    season = {"title": "2026 Formula One World Championship", "wikibase_item": "Q9", "extract": "The season."}
    race = {"title": "Qatar Grand Prix", "wikibase_item": "Q7", "extract": "The Qatar Grand Prix is a race."}
    _wiki(monkeypatch, {("en", "2026 Qatar Grand Prix"): season, ("en", "Qatar Grand Prix"): race})
    c = we.Candidate(title="2026 Qatar Grand Prix", fallback_title="Qatar Grand Prix", name="2026 Qatar Grand Prix",
                     category="sports", country_code="QA", start=date(2026, 11, 27), end=date(2026, 11, 29),
                     dates_source="official calendar")
    ev = anyio.run(we.describe, c, WINDOW)
    assert (ev.id, ev.name, ev.why) == ("Q7@2026-11-27", "2026 Qatar Grand Prix", "The Qatar Grand Prix is a race.")


def test_a_season_is_not_an_event(monkeypatch):
    _wiki(monkeypatch, {("en", "2027 Formula One World Championship"): {
        "title": "2027 Formula One World Championship", "wikibase_item": "Q9", "extract": "The season."}})
    c = we.Candidate(title="2027 Formula One World Championship", category="sports", country_code="GB",
                     start=date(2027, 3, 14), end=date(2027, 12, 12), dates_source="wikidata")
    assert anyio.run(we.describe, c, WINDOW) is None


def test_a_search_hit_for_another_edition_is_refused(monkeypatch):
    async def summary(title):
        return None if title.startswith("2027") else {"title": title, "type": "standard", "wikibase_item": "Q9"}

    async def search(service, url, params=None, **kw):
        return {"query": {"search": [{"title": "2026 Giro d'Italia"}]}}

    monkeypatch.setattr(we.wiki, "summary", summary)
    monkeypatch.setattr(we.wiki.net, "fetch_json", search)
    assert anyio.run(we.wiki.find_article, "2027 Giro d'Italia") is None
    # Wikipedia redirects an edition without its own page to the season: that's not the race.
    assert not we.wiki.same_subject("2027 Monaco Grand Prix", "2027 Formula One World Championship")
    assert we.wiki.same_subject("Mardi Gras (New Orleans)", "Mardi Gras in New Orleans")


def test_events_are_matched_to_the_trips_countries_and_days():
    found = we.during([FILM_FEST, OKTOBERFEST], date(2026, 10, 12), date(2026, 10, 18), {"IT"}, [(41.9, 12.5)])
    assert [(e.name, days[0], days[-1]) for e, days, _ in found] == [("Rome Film Fest", date(2026, 10, 15),
                                                                       date(2026, 10, 18))]
    assert found[0][2] < 40  # km from Rome


@pytest.fixture(scope="module")
def rome():
    trip, _ = anyio.run(run_turn, TripState(), ROME_REQUEST)
    return trip


def test_an_event_is_offered_but_only_added_when_the_traveller_says_yes(rome):
    trip = rome.model_copy(deep=True)
    offers = research.offer_major_events(trip, [FILM_FEST, MILAN_DESIGN])
    film, milan = offers
    assert film["place"] and film["stop"] == 0 and film["trip_days"] == ["2026-10-15", "2026-10-16", "2026-10-17",
                                                                         "2026-10-18"]
    assert milan["place"] is None  # in Italy but ~480 km away: mentioned, not something to fit into a Rome day
    assert not any(a.id == "wev_Q1" for a in trip.research.attractions)  # an offer changes nothing yet
    facts = narrative.event_offers(trip)
    assert facts[0]["can_be_added"] and facts[0]["in_plan_on_day"] is None and facts[0]["dates"] == "confirmed"
    assert facts[0]["ticket"] == "from 20 EUR (official site)"

    assert film["place"]["distance_km"] > 25 and not film["place"]["day_trip"]
    # The agent may add the venue to the name: it is still the event (with its ticket and dates), never the venue.
    trip, _ = anyio.run(run_turn, trip, "", [Action(action="add_place", text="Rome Film Fest (Auditorium Parco della Musica)")])
    day, item = next((d, i) for d in trip.selected_plan.days for i in d.items if i.place_id == "wev_Q1")
    assert str(day.date) in film["trip_days"]
    assert (item.cost.amount, item.cost.currency, item.cost.price_type) == (40, "EUR", "known")  # 2 tickets
    assert any(i.kind == "meal" and i.meal_type == "lunch" for i in day.items) or "Lunch at the venue" in item.notes
    assert narrative.event_offers(trip)[0]["status"].startswith("IN THE PLAN")
    assert narrative.event_offers(trip)[0]["in_plan_on_day"] == day.day


def test_the_events_page_lists_the_catalogue(monkeypatch):
    from travel_agent.api import app

    monkeypatch.setattr(we, "catalogue", lambda: ([FILM_FEST, OKTOBERFEST], True))
    body = TestClient(app).get("/api/events", params={"country": "it"}).json()
    assert body["complete"] is False and [e["name"] for e in body["events"]] == ["Rome Film Fest"]
