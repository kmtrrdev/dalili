"""Typed constraints (priority/source/evidence) and conflict resolution (ranked, priced relaxations)."""

import anyio

from travel_agent import conflicts
from travel_agent.constraints import by_type
from travel_agent.models import ChatMessage, TripState
from travel_agent.nlu import Requirements
from travel_agent.replanner import apply_requirements, build_contract
from travel_agent.workflow import run_turn

from .conftest import ROME_REQUEST


def _trip_with(rome_contract, **req):
    trip = TripState(trip_contract=rome_contract)
    d = trip.draft
    d.origin_city, d.origin_ref = "Cairo", rome_contract.origin_ref
    d.destination, d.destination_ref = "Rome", rome_contract.destination_ref
    d.start_date, d.end_date = rome_contract.start_date, rome_contract.end_date
    trip.conversation.append(ChatMessage(role="user", content="I must see the Vatican Museums, maybe the Aventine Keyhole"))
    apply_requirements(trip, Requirements(**req))
    return trip


def test_firm_and_soft_wording_become_different_priorities(rome_contract):
    trip = _trip_with(rome_contract, must_visit=["Vatican Museums"], wish_list=["Aventine Keyhole"], budget_amount=3000)
    c, _ = build_contract(trip)
    visit = by_type(c, "must_visit")[0]
    wish = by_type(c, "wish")[0]
    assert visit.priority == "hard" and visit.source == "explicit" and "Vatican" in visit.evidence[0]
    assert wish.priority == "preference"
    budget = by_type(c, "budget_max")[0]
    # a stated budget with no word on flexibility: treated as a limit, but openly marked as an inference
    assert budget.priority == "hard" and budget.source == "inferred" and budget.confidence < 1


def test_unstated_values_are_flagged_as_assumptions_not_requirements(rome_contract):
    trip = _trip_with(rome_contract)
    c, _ = build_contract(trip)
    travelers = by_type(c, "travelers")[0]
    assert travelers.source == "default" and travelers.confidence < 1 and "assumed" in travelers.reason.lower()
    assert not [x for x in c.constraints if x.source == "default" and x.priority == "hard" and x.flexibility == "fixed"]


def test_flexible_budget_is_soft(rome_contract):
    trip = _trip_with(rome_contract, budget_amount=3000, budget_is_hard_limit=False)
    c, _ = build_contract(trip)
    assert by_type(c, "budget_max")[0].priority == "soft"


def _over_budget_trip():
    trip, _ = anyio.run(run_turn, TripState(), ROME_REQUEST)
    trip, _ = anyio.run(run_turn, trip, "Actually my budget is only $1,500")
    return trip


def test_over_budget_plan_gets_ranked_priced_options():
    trip = _over_budget_trip()
    found = [x for x in trip.metadata.get("conflicts", []) if x["kind"] == "budget"]
    if trip.selected_plan.within_budget:
        assert not found
        return
    conflict = conflicts.Conflict.model_validate(found[0])
    assert conflict.gap > 0 and conflict.options
    closing = [o for o in conflict.options if o.closes_gap]
    assert closing and all(o.saving >= conflict.gap - 0.5 for o in closing)
    assert closing == sorted(closing, key=lambda o: o.penalty)  # best (least harmful) first
    assert any(o.saving is None for o in conflict.options)  # "other dates": offered without an invented number


def test_what_the_traveller_values_changes_the_ranking():
    trip = _over_budget_trip()
    if trip.selected_plan.within_budget:
        return
    gap = trip.selected_plan.budget.total - trip.trip_contract.budget.amount
    relax = conflicts._budget_relaxations(trip, gap)
    raise_budget = next(r for r in relax if r.kind == "raise_budget")
    before = conflicts._penalty(raise_budget, trip)
    trip.trip_contract.priorities = ["cost"]
    assert conflicts._penalty(raise_budget, trip) > before
