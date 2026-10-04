"""Multi-city journeys: parsing, night split, and planning across stops (offline, replayed data)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from travel_agent.engine.knobs import PlanKnobs
from travel_agent.engine.validators import validate_plan
from travel_agent.journey import build_stops, merge_research, plan_journey, split_nights
from travel_agent.models import FlightOption, Metadata, Money, TripState
from travel_agent.nlu import extract_destination_list, extract_requirements
from travel_agent.tripbook import render_html, render_markdown


def test_destination_lists():
    assert extract_destination_list("A Europe tour: Italy, France and Spain for 12 days")[0] == ["Italy", "France", "Spain"]
    assert extract_destination_list("Rome then Paris then Barcelona, 10 days")[0] == ["Rome", "Paris", "Barcelona"]
    assert extract_destination_list("3 nights in Rome, 2 nights in Florence and 4 in Venice") == (
        ["Rome", "Florence", "Venice"], [3, 2, 4])
    # Not tours: a city with its country, companions, interests.
    assert extract_destination_list("Barcelona, Spain for 5 days")[0] == []
    assert extract_destination_list("relaxed trip to Rome with my wife, food and photography")[0] == []
    r, _ = extract_requirements("tour of Italy & Greece in October, budget $3000", date(2026, 9, 27))
    assert r.destinations == ["Italy", "Greece"] and r.destination == "Italy"


def test_split_nights():
    assert split_nights(9, 3) == [3, 3, 3]
    assert split_nights(10, 3) == [4, 3, 3]
    assert split_nights(9, 3, [3, 2, 4]) == [3, 2, 4]
    assert sum(split_nights(8, 3, [3, 2, 4])) == 8
    assert all(n >= 1 for n in split_nights(3, 3))


def test_build_stops_chains_dates(rome_contract):
    ref = rome_contract.destination_ref
    stops, end, notes = build_stops([ref, ref.model_copy(update={"name": "Florence"})], date(2026, 10, 12),
                                    date(2026, 10, 12), None)
    assert end == date(2026, 10, 14)  # extended: one night per city at least
    assert stops[0].end_date == stops[1].start_date
    assert any("extended" in n for n in notes)


def _train(a: str, b: str, on: date) -> FlightOption:
    dep = datetime.combine(on, datetime.strptime("09:30", "%H:%M").time()).replace(tzinfo=ZoneInfo("Europe/Rome"))
    return FlightOption(id="fl_train_test", direction="outbound", mode="train", airline="Train", flight_number="Train 09:30",
                        origin=a, destination=b, depart_at=dep, arrive_at=dep + timedelta(minutes=114),
                        duration_minutes=114, stops=0, price_per_person=Money(amount=41, currency="USD"),
                        metadata=Metadata(source="transport_mcp", provider="test", confidence=0.8, notes="Test train."))


def test_plan_journey_merges_stops_and_travel_day(rome_contract, rome_research, profile):
    c = rome_contract
    second = c.destination_ref.model_copy(update={"name": "Rome B"})
    stops, _, _ = build_stops([c.destination_ref, second], c.start_date, c.end_date, [3, 3])
    contract = c.model_copy(update={"stops": stops})
    train = _train("Rome", "Rome B", stops[0].end_date)
    legs = [rome_research.flights_outbound, [train], rome_research.flights_return]
    b1 = rome_research.model_copy(deep=True)
    b2 = rome_research.model_copy(deep=True)
    b2.destination_info = {**b2.destination_info, "name": "Rome B"}
    research = merge_research([b1, b2], legs, [])

    plan = plan_journey(contract, profile, research, "balanced", PlanKnobs(), 0.05, {})
    assert [s.name for s in plan.stops] == ["Rome", "Rome B"]
    assert [s.first_day for s in plan.stops] == [1, 4]
    assert len(plan.days) == contract.num_days == 7
    assert [f.mode for f in plan.legs] == ["flight", "train", "flight"]

    travel = plan.days[3]
    assert travel.travel_day and travel.city == "Rome B" and travel.title == "Rome → Rome B"
    titles = [i.title for i in travel.items]
    assert sum(1 for i in travel.items if i.kind == "flight") == 1  # the journey appears once
    assert any(t.startswith("Transfer to station") for t in titles)
    assert any(t.startswith("Station transfer") for t in titles)
    assert not any("airport" in t.lower() for t in titles)

    # Every leg is paid once: flights as flights, the train as ground transport.
    b = plan.budget
    flights = sum(f.price_per_person.amount * research.fx_rates.get(f.price_per_person.currency, 1.0)
                  for f in (plan.legs[0], plan.legs[2])) * contract.travelers
    assert abs(b.flights - round(flights, 2)) < 1
    assert b.transport >= 41 * contract.travelers
    assert b.hotel > 0

    report = validate_plan(plan, contract, profile, research, 0.05)
    assert not [v for v in report.errors if v.check in ("schedule", "reality")], report.errors

    # "Cheaper flights" repairs compare a flight only with the same journey: a cheap train/hop on another leg
    # must never knock out every option of the international leg.
    from travel_agent.engine.repair import _apply_budget_step

    k = PlanKnobs()
    p = plan
    for _ in range(12):
        _apply_budget_step("cheaper_flights", p, k, research, profile)
        p = plan_journey(contract, profile, research, "balanced", k, 0.05, {})
        assert p.outbound_flight is not None and p.legs[0].mode == "flight"
    assert {f.id for f in rome_research.flights_outbound} - set(k.flight_exclude)

    # The Trip Book shows the route, every leg and one hotel per city.
    plan.validation = report
    trip = TripState(trip_contract=contract, research=research, plans={"balanced": plan}, traveler_profile=profile)
    html = render_html(trip)
    assert "Journey" in html and "Hotels" in html and "Rome B" in html and "travel day" in html
    assert '"stops": [' in html
    md = render_markdown(trip)
    assert "## Route" in md and "(estimated schedule and fare)" in md
