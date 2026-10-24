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
    lat=41.70, lon=12.25, start=date(2026, 10, 15), end=date(2026, 10, 25), dates_source="official site",
    why="Premieres and stars at the Auditorium", wikipedia="https://en.wikipedia.org/wiki/Rome_Film_Fest",
    website="https://www.romacinemafest.it", fame=30,
    ticket=we.Ticket(amount=20, currency="EUR", source="official site", quote="Biglietti da 20 €"))
MILAN_DESIGN = FILM_FEST.model_copy(update={"id": "Q2", "name": "Milan Design Week", "city": "Milan",
                                            "lat": 45.464, "lon": 9.19})
OKTOBERFEST = FILM_FEST.model_copy(update={"id": "Q3", "name": "Oktoberfest", "city": "Munich", "country_code": "DE"})


def _proposed(**kw) -> we.Proposed:
    base = {"title": "Oktoberfest", "category": "festival", "city": "Munich", "country_code": "DE",
            "start": "2027-09-18", "end": "2027-10-03", "why": "Beer tents", "why_ar": "خيم البيرة"}
    return we.Proposed(**{**base, **kw})


def _sources(monkeypatch, entity: dict, edition: we.Edition | None = None, page: str = ""):
    async def wikipedia(title):
        return {"title": "Oktoberfest", "wikibase_item": "Q32", "extract": "The world's largest Volksfest.",
                "coordinates": {"lat": 48.13, "lon": 11.55}, "content_urls": {"desktop": {"page": "https://w/Oktoberfest"}}}

    async def wikidata(qid):
        return entity

    async def official(name, site, window):
        return edition, page, "https://www.oktoberfest.de"

    async def no_edition_article(title):
        return None

    monkeypatch.setattr(we.wiki, "find_article", wikipedia)
    monkeypatch.setattr(we.wiki, "summary", no_edition_article)
    monkeypatch.setattr(we.wiki, "entity", wikidata)
    monkeypatch.setattr(we, "_official", official)


def _entity(fame: int, **claims) -> dict:
    return {"sitelinks": {f"w{i}": {} for i in range(fame)}, "labels": {"ar": {"value": "أكتوبرفست"}},
            "claims": {p: [{"mainsnak": {"snaktype": "value", "datavalue": {"value": v}}}] for p, v in claims.items()}}


def test_dates_from_the_official_site_must_be_quoted_from_the_page():
    page = "Oktoberfest 2027: 18. September bis 3. Oktober 2027 auf der Theresienwiese"
    assert we.dates_quoted("18. September bis 3. Oktober 2027", page, date(2027, 9, 18))
    assert not we.dates_quoted("19. September bis 3. Oktober 2027", page, date(2027, 9, 19))  # not on the page
    assert not we.dates_quoted("auf der Theresienwiese", page, date(2027, 9, 18))  # no date in it


def test_official_dates_and_ticket_win_over_the_models_guess(monkeypatch):
    page = "Tickets ab 25 EUR. Oktoberfest 2027: 18. September bis 3. Oktober 2027"
    _sources(monkeypatch, _entity(80, P856="https://www.oktoberfest.de"), we.Edition(
        found_dates=True, start="2027-09-18", end="2027-10-03", dates_quote="18. September bis 3. Oktober 2027",
        ticket_from=25, currency="EUR", ticket_quote="Tickets ab 25 EUR"), page)
    ev = anyio.run(we.verify, _proposed(start="2027-09-20", end="2027-10-05"), WINDOW)
    assert (ev.start, ev.end, ev.dates_source) == (date(2027, 9, 18), date(2027, 10, 3), "official site")
    assert ev.ticket.source == "official site" and ev.ticket.amount == 25 and ev.name_ar == "أكتوبرفست"


def test_unconfirmed_dates_stay_labelled_and_obscure_events_are_dropped(monkeypatch):
    _sources(monkeypatch, _entity(80))
    ev = anyio.run(we.verify, _proposed(ticket_from=15, ticket_currency="eur"), WINDOW)
    assert ev.dates_source == "usual dates" and ev.ticket.source == "AI estimate" and ev.ticket.currency == "EUR"
    _sources(monkeypatch, _entity(3))
    assert anyio.run(we.verify, _proposed(), WINDOW) is None  # three articles: not world-famous
    assert anyio.run(we.verify, _proposed(), WINDOW, 3) is not None  # a regional event's lower bar
    _sources(monkeypatch, _entity(80, P580={"time": "+2027-03-14T00:00:00Z", "precision": 11},
                                  P582={"time": "+2027-12-12T00:00:00Z", "precision": 11}))
    assert anyio.run(we.verify, _proposed(), WINDOW) is None  # a nine-month season is not an event


def test_this_years_edition_article_gives_exact_dates(monkeypatch):
    _sources(monkeypatch, _entity(80))
    edition = _entity(20, P580={"time": "+2027-09-18T00:00:00Z", "precision": 11},
                      P582={"time": "+2027-10-03T00:00:00Z", "precision": 11})

    async def summary(title):
        return {"title": title, "wikibase_item": "Q2027"} if title == "2027 Oktoberfest" else None

    async def wikidata(qid):
        return edition if qid == "Q2027" else _entity(80)

    monkeypatch.setattr(we.wiki, "summary", summary)
    monkeypatch.setattr(we.wiki, "entity", wikidata)
    ev = anyio.run(we.verify, _proposed(start="2027-09-20", end="2027-10-05"), WINDOW)
    assert (ev.start, ev.end, ev.dates_source) == (date(2027, 9, 18), date(2027, 10, 3), "wikidata")


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
