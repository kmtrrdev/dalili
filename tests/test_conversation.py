"""The conversation: the trip agent reads every message, corrections replace what was there, places keep their country."""

from datetime import date

import anyio
import pytest

from travel_agent import llm, workflow
from travel_agent.agents import concierge
from travel_agent.models import PlaceRef, ProposedStop, RouteProposal, TripState
from travel_agent.nlu import Requirements, RouteStop, TurnInterpretation
from travel_agent.replanner import apply_requirements, build_contract, contract_dirty_domains, names_place, set_route
from travel_agent.workflow import run_turn

from .conftest import ROME_REQUEST

BALI_TW = PlaceRef(name="Bali", country="Taiwan", country_code="TW", lat=25.15, lon=121.40, airports=["DPS"])
TAIPEI = PlaceRef(name="Taipei City", country="Taiwan", country_code="TW", lat=25.03, lon=121.56, airports=["TPE"])


@pytest.fixture(scope="module")
def planned():
    trip, _ = anyio.run(run_turn, TripState(), ROME_REQUEST)
    return trip


@pytest.fixture
def rome(planned):
    return planned.model_copy(deep=True)


def _proposal_trip() -> TripState:
    """The reported session: Bali resolved to Taiwan, and a 2-city route waiting for an answer."""
    trip = TripState()
    d = trip.draft
    d.destination, d.destination_ref = "Bali", BALI_TW
    d.start_date, d.end_date, d.budget_amount, d.budget_currency = date(2026, 11, 1), date(2026, 11, 7), 60000, "EGP"
    d.redesign = True
    d.must_visit = ["Taroko National Park"]
    trip.metadata["expert_added"] = ["Taroko National Park"]
    d.route_proposal = RouteProposal(stops=[ProposedStop(city="Bali", country="Taiwan", nights=3, ref=BALI_TW),
                                            ProposedStop(city="Taipei City", country="Taiwan", nights=3, ref=TAIPEI)])
    return trip


def _scripted(monkeypatch, steps):
    script = iter(steps)

    async def parse(system, user, schema, max_tokens=16000, effort=None, timeout=None):
        return next(script) if schema is concierge.Step else None

    async def none(*a, **k):
        return None

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "parse", parse)
    monkeypatch.setattr(llm, "text", none)


def test_a_place_keeps_its_country():
    assert names_place("Bali", "Bali", BALI_TW)
    assert names_place("Taiwan", None, BALI_TW)  # an echoed country is the same trip
    assert not names_place("Bali, Indonesia", "Bali", BALI_TW)  # same name, another country: a correction
    assert workflow._wrong_country("Bali, Indonesia", BALI_TW) and not workflow._wrong_country("Bali", BALI_TW)


def test_only_x_replaces_the_proposed_route():
    trip = _proposal_trip()
    assert set_route(trip, [RouteStop(place="Bali, Indonesia")])
    d = trip.draft
    assert d.destination == "Bali, Indonesia" and d.destination_ref is None  # resolved again, in Indonesia
    assert d.destinations == [] and d.route_proposal is None and not d.redesign and d.route_confirmed
    assert d.must_visit == [] and "expert_added" not in trip.metadata  # the expert's Taiwan pick went with the route


def test_the_agent_answers_a_route_proposal_with_the_exact_places(monkeypatch):
    trip = _proposal_trip()
    trip.conversation = []
    _scripted(monkeypatch, [concierge.Step(
        thought="They want Bali only - and the Indonesian one.", tool="change_plan",
        changes=concierge.PlanChange(summary="Only Bali, Indonesia", route_decision="change",
                                     route=[RouteStop(place="Bali, Indonesia")]))])
    out = anyio.run(workflow.understand, {"trip": trip, "message": "لا عايزها بالي بس"})
    assert out["route"] == "requirements"
    assert trip.draft.route_proposal is None and trip.draft.destination == "Bali, Indonesia"


def test_the_agent_also_answers_before_any_plan(monkeypatch):
    _scripted(monkeypatch, [concierge.Step(thought="A greeting.", tool="final_answer",
                                           answer="أهلاً! رايح فين وإمتى؟", follow_ups=["أسبوع في بالي في نوفمبر"])])
    trip, reply = anyio.run(run_turn, TripState(), "ازيك")
    assert reply == "أهلاً! رايح فين وإمتى؟" and trip.trip_contract is None
    assert trip.metadata["suggestions"] == ["أسبوع في بالي في نوفمبر"]


def test_a_country_correction_is_a_new_destination(rome):
    i = TurnInterpretation(intent="feedback", requirements=Requirements(destination="Rome, United States"))
    assert workflow._changes_trip_frame(rome, i)
    for echo in ("Rome", "Rome, Italy", "Italy"):
        assert not workflow._changes_trip_frame(rome, TurnInterpretation(
            intent="feedback", requirements=Requirements(destination=echo)))
    apply_requirements(rome, Requirements(destination="Rome, United States"))
    assert rome.draft.destination_ref is None  # looked up again instead of keeping the Italian Rome


def test_same_name_in_another_place_refreshes_all_research(rome):
    old = rome.trip_contract
    new, _ = build_contract(rome)
    assert contract_dirty_domains(old, new) == set()
    new.destination_ref = new.destination_ref.model_copy(update={"country_code": "US", "lat": 34.26, "lon": -85.16})
    assert contract_dirty_domains(old, new) >= {"flights", "hotels", "activities", "restaurants"}


def test_null_fields_from_the_model_mean_not_said():
    # gpt-5-mini sometimes sends "requirements": null; that must not throw the whole answer away.
    step = concierge.Step.model_validate({"thought": "Add Lombok.", "tool": "change_plan", "args": None, "changes": {
        "summary": "Add 3 nights in Lombok", "requirements": None, "feedback": None,
        "actions": [{"action": "extend_trip", "amount": 3, "text": None}],
        "route": [{"place": "Bali, Indonesia", "nights": 5}, {"place": "Lombok, Indonesia", "nights": 3}]}})
    assert step.changes.requirements == Requirements() and step.changes.route[1].nights == 3


def test_nights_per_place_give_the_new_length_once(rome, monkeypatch):
    start = rome.trip_contract.start_date
    _scripted(monkeypatch, [concierge.Step(thought="Add Florence.", tool="change_plan", changes=concierge.PlanChange(
        summary="Add 3 nights in Florence", actions=[{"action": "extend_trip", "amount": 3}],
        route=[RouteStop(place="Rome, Italy", nights=rome.trip_contract.nights),
               RouteStop(place="Florence, Italy", nights=3)]))])
    out = anyio.run(workflow.understand, {"trip": rome, "message": "add 3 days in Florence"})
    assert out["route"] == "requirements" and not out["interpretation"].actions  # extend_trip would add 3 more
    assert (rome.draft.end_date - start).days == rome.trip_contract.nights + 3
    assert rome.draft.destinations == ["Rome, Italy", "Florence, Italy"]


def test_a_first_message_with_nights_per_place_keeps_its_length(monkeypatch):
    # "5 nights in Bali from Nov 3, $2,000": the length rides on the route, before any start date exists.
    trip = TripState()
    trip.draft.must_visit = ["Tanah Lot"]  # named before any destination: kept
    _scripted(monkeypatch, [concierge.Step(thought="A new trip.", tool="change_plan", changes=concierge.PlanChange(
        summary="Bali 5 nights", route=[RouteStop(place="Bali, Indonesia", nights=5)],
        requirements=Requirements(start_date="2026-11-03", nights=5, budget_amount=2000, budget_currency="USD")))])
    out = anyio.run(workflow.understand, {"trip": trip, "message": "5 nights in Bali from Nov 3, $2,000"})
    apply_requirements(trip, out["interpretation"].requirements)
    d = trip.draft
    assert (d.start_date, d.end_date) == (date(2026, 11, 3), date(2026, 11, 8)) and d.must_visit == ["Tanah Lot"]


def test_the_drafts_own_words_are_an_echo_not_a_new_place():
    trip = TripState()
    d = trip.draft
    d.destination = "Sharm El Sheikh, Egypt"
    d.destination_ref = PlaceRef(name="Sharm el-Sheikh", country="Egypt", country_code="EG", lat=27.9, lon=34.3)
    d.must_visit = ["Ras Mohammed"]
    apply_requirements(trip, Requirements(destination="Sharm El Sheikh, Egypt", budget_amount=2000))
    assert d.destination_ref is not None and d.must_visit == ["Ras Mohammed"]


def test_the_arrival_day_stays_when_they_leave_a_day_earlier():
    trip = TripState()
    d = trip.draft
    d.start_date, d.end_date = date(2026, 11, 1), date(2026, 11, 7)
    apply_requirements(trip, Requirements(arrive_on_start=True))
    assert d.arrive_by == date(2026, 11, 1)
    apply_requirements(trip, Requirements(start_date="2026-10-31"))  # leave the day before to land on the 1st
    assert d.arrive_by == date(2026, 11, 1)
    apply_requirements(trip, Requirements(start_date="2026-11-10"))  # the whole trip moved
    assert d.arrive_by == date(2026, 11, 10)


def test_a_slow_model_step_is_retried_quickly_instead_of_waited_for(monkeypatch):
    efforts = []

    async def parse(system, user, schema, max_tokens=16000, effort=None, timeout=None):
        efforts.append((effort, timeout))
        if effort != "low":
            llm.last_error = f"model call exceeded {timeout:.0f}s"
            return None
        return concierge.Step(thought="Hi.", tool="final_answer", answer="Hello!")

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "parse", parse)
    res = anyio.run(concierge.converse, TripState(), "hi")
    assert res.answer == "Hello!" and efforts == [("medium", 30), ("low", 30)]


def test_saying_the_same_route_again_changes_nothing(rome):
    assert not set_route(rome, [RouteStop(place="Rome, Italy")])
