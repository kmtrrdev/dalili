"""What-if impact (same comparison for chat and API) and repair accountability (a repair that makes things worse
is undone)."""

import anyio

from travel_agent import workflow
from travel_agent.models import TripState, ValidationReport, Violation
from travel_agent.nlu import Action
from travel_agent.service import TravelAgentService
from travel_agent.store import Store
from travel_agent.whatif import compare

from .conftest import ROME_REQUEST


def test_budget_what_if_is_incremental_and_complete():
    svc = TravelAgentService(Store(":memory:"))
    trip, _ = anyio.run(svc.chat, ROME_REQUEST)
    res = anyio.run(lambda: svc.what_if(trip.trip_id, budget_delta=-800))
    assert res["budget"] == trip.trip_contract.budget.amount - 800 and not res["applied"]
    assert set(res["before"]) == set(res["after"]) == set(trip.plans)       # every plan, not just the selected one
    assert all("requirements_met" in v and "valid" in v for v in res["after"].values())
    assert res["replanning"]["kind"] == "incremental"                        # a budget change reuses the research
    assert any(c.startswith("changed: budget_max") for c in res["constraint_changes"])
    assert svc.get(trip.trip_id).trip_contract.budget.amount == trip.trip_contract.budget.amount  # nothing applied


def test_compare_reports_cost_and_days():
    trip, _ = anyio.run(workflow.run_turn, TripState(), ROME_REQUEST)
    after, _ = anyio.run(lambda: workflow.run_turn(trip.model_copy(deep=True), "", preset_actions=[Action(action="shorten_trip", amount=1)]))
    cmp = compare(trip, after)
    assert cmp["days_changed"] >= 1 and cmp["cost_change"] is not None


def test_a_repair_that_adds_problems_is_reverted(monkeypatch, rome_research, rome_contract, profile):
    from travel_agent.engine.knobs import PlanKnobs
    from travel_agent.engine.planner import PlanContext, build_plan

    trip = TripState(trip_contract=rome_contract, research=rome_research, traveler_profile=profile)
    before = build_plan(PlanContext(contract=rome_contract, profile=profile, research=rome_research, mode="balanced",
                                    knobs=PlanKnobs()))
    after = before.model_copy(deep=True)
    before.validation = ValidationReport(result="FAIL", violations=[
        Violation(check="budget", severity="error", message="over")])
    worse = ValidationReport(result="FAIL", violations=[
        Violation(check="schedule", severity="error", message="overlap", day=2),
        Violation(check="opening_hours", severity="error", message="closed", day=3, place_id="x")])
    monkeypatch.setattr(workflow, "validate_plan", lambda *a, **k: worse)
    state = {"trip": trip, "candidates": {"balanced": after}, "knobs": {"balanced": PlanKnobs()},
             "repair_prev": {"balanced": before}, "iteration": 1}
    out = anyio.run(workflow.validate, state)
    assert out["candidates"]["balanced"] is before and "balanced" in out["repair_stalled"]
    record = trip.metadata["repair_history"][-1]
    assert record["reverted"] and record["errors_before"] == 1 and record["errors_after"] == 2
    assert workflow.after_validate({**state, **out}) == "finalize"  # no endless repair loop on that mode
