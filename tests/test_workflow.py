"""Conversation-level tests over recorded real API sessions."""

import anyio
import pytest

from travel_agent.models import TripState
from travel_agent.service import TravelAgentService
from travel_agent.store import Store
from travel_agent.workflow import run_turn

from .conftest import ISTANBUL_REQUEST, ROME_REQUEST


def turn(trip, msg):
    return anyio.run(run_turn, trip, msg)


@pytest.fixture(scope="module")
def rome():
    trip, _ = turn(TripState(), ROME_REQUEST)
    return trip


def test_missing_information_triggers_questions():
    trip, reply = turn(TripState(), "I want to go to Rome, we love history")
    assert trip.status == "needs_input" and not trip.plans
    assert trip.draft.destination_ref and trip.draft.destination_ref.country == "Italy"
    assert "budget" in reply.lower() and "when" in reply.lower()


def test_unknown_place_asks_again():
    trip, reply = turn(TripState(), "I want to go somewhere warm in December")
    assert not trip.plans and "where" in reply.lower()


def test_real_plan(rome):
    c = rome.trip_contract
    assert c.destination == "Rome" and c.travelers == 2 and c.num_days == 7
    assert set(rome.plans) == {"balanced", "budget", "comfort", "experience"}
    plan = rome.selected_plan
    assert plan.validation.result == "PASS"
    assert plan.outbound_flight.booking_url and plan.hotel.property_token
    assert {"place.resolved", "trip.contract", "flight.researched", "itinerary.validated"} <= {e.type for e in rome.events}


def test_replans_without_new_research(rome):
    trip, _ = turn(rome.model_copy(deep=True), "I don't want to wake up before 10")
    for d in trip.selected_plan.days[1:-1]:
        assert next(i for i in d.items if i.kind in ("meal", "activity")).start >= "10:00"
    trip, _ = turn(rome.model_copy(deep=True), "My budget is only $2,600")
    assert trip.trip_contract.budget.amount == 2600
    assert trip.selected_plan.within_budget or not any(p.within_budget for p in trip.plans.values())


def test_extend_trip_refreshes_flights_and_hotel(rome):
    trip, _ = turn(rome.model_copy(deep=True), "I want to stay two more days")
    assert trip.trip_contract.num_days == 9 and len(trip.selected_plan.days) == 9
    assert trip.selected_plan.return_flight.depart_at.date() == trip.trip_contract.end_date
    assert all(d.activity_count > 0 for d in trip.selected_plan.days[1:-1])


def test_named_place_is_added_to_the_plan(rome):
    """ "Add X": a researched place that wasn't scheduled ends up in every plan mode, and stays on later replans."""
    # A relaxed pace leaves researched places unscheduled (a full pace may use them all).
    rome, _ = turn(rome.model_copy(deep=True), "I prefer a relaxed pace")
    planned = {i.place_id for d in rome.selected_plan.days for i in d.items if i.place_id}
    extra = next(a for a in sorted(rome.research.attractions, key=lambda a: a.reviews_count)
                 if a.id not in planned and not a.day_trip and not a.dates and a.opening_hours
                 and "overnight_trip" not in a.categories)
    trip, reply = turn(rome.model_copy(deep=True), f"please add {extra.name} to my plan")
    assert extra.name in trip.draft.must_visit
    for mode, plan in trip.plans.items():
        days = [d.day for d in plan.days for i in d.items if i.place_id == extra.id]
        assert days, f"{extra.name} missing from the {mode} plan"
        assert plan.requested == {extra.name: days[0]}
    assert extra.name in reply
    trip, _ = turn(trip, "I don't want to wake up before 10")
    assert any(i.place_id == extra.id for d in trip.selected_plan.days for i in d.items)


def test_question_answered_from_wikivoyage(rome):
    _, reply = turn(rome.model_copy(deep=True), "Do I need to tip in restaurants?")
    assert "wikivoyage" in reply.lower()


def test_what_if_is_not_applied_until_confirmed():
    svc = TravelAgentService(Store(":memory:"))
    trip, _ = anyio.run(svc.chat, ROME_REQUEST)
    before = trip.trip_contract.budget.amount
    trip, reply = anyio.run(svc.chat, "What if I increase my budget by $1000?", trip.trip_id)
    assert "not applied" in reply.lower() and svc.get(trip.trip_id).trip_contract.budget.amount == before
    anyio.run(svc.chat, "apply it", trip.trip_id)
    assert svc.get(trip.trip_id).trip_contract.budget.amount == before + 1000


def test_second_city_vegetarian_no_early_flights():
    trip, _ = turn(TripState(), ISTANBUL_REQUEST)
    plan = trip.selected_plan
    assert trip.trip_contract.destination == "Istanbul" and trip.research.destination_info["currency"] == "TRY"
    assert plan.outbound_flight.depart_at.hour >= 8 and plan.return_flight.depart_at.hour >= 8
    for d in plan.days:
        for i in d.items:
            if i.kind == "meal" and i.place_id:
                assert "vegetarian" in trip.research.place(i.place_id).dietary
