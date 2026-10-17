"""Changes to a trip that already has a plan: currency, budget, length, dates, destination, streaming failures."""

from datetime import date, timedelta

import anyio
import pytest

from travel_agent import workflow
from travel_agent.models import TripState
from travel_agent.nlu import Action, Requirements, TurnInterpretation
from travel_agent.replanner import (FIND_CHEAPEST_PLACEHOLDER, apply_actions, apply_requirements, build_contract,
                                    diff_plans, resize_nights)
from travel_agent.workflow import run_turn

from .conftest import ROME_REQUEST


@pytest.fixture(scope="module")
def planned():
    trip, _ = anyio.run(run_turn, TripState(), ROME_REQUEST)
    return trip


@pytest.fixture
def rome(planned):
    return planned.model_copy(deep=True)


@pytest.fixture
def egp(monkeypatch):
    """A fixed exchange rate: 1 USD = 50 EGP."""
    rates = {("USD", "EGP"): 50.0, ("EGP", "USD"): 1 / 50}

    async def convert(trip, amount, src, dst):
        return amount * rates[(src, dst)]

    monkeypatch.setattr(workflow, "_convert", convert)


def interp(**kw) -> TurnInterpretation:
    actions = kw.pop("actions", [])
    return TurnInterpretation(intent="update_requirements", requirements=Requirements(**kw), actions=actions)


def test_currency_only_change_converts_the_budget(rome, egp):
    # "Make it in Egyptian pounds" after the plan exists: 3,500 USD must become ~175,000 EGP, never 3,500 EGP.
    i = interp(budget_currency="EGP")
    assert workflow._changes_trip_frame(rome, i)
    notes = anyio.run(workflow._budget_currency, rome, i)
    assert i.requirements.budget_amount == 175_000 and "≈" in notes[0]
    apply_requirements(rome, i.requirements)
    contract, _ = build_contract(rome)
    assert (contract.budget.currency, contract.budget.amount) == ("EGP", 175_000)


def test_new_total_in_another_currency_is_taken_with_its_currency(rome, egp):
    i = interp(budget_currency="EGP", actions=[Action(action="set_budget", amount=100_000)])
    anyio.run(workflow._budget_currency, rome, i)
    assert i.requirements.budget_amount == 100_000 and i.requirements.budget_currency == "EGP"


def test_a_delta_in_another_currency_is_converted_and_the_currency_kept(rome, egp):
    i = interp(budget_currency="EGP", actions=[Action(action="adjust_budget", amount=5_000)])
    anyio.run(workflow._budget_currency, rome, i)
    assert i.requirements.budget_currency is None and i.actions[0].amount == pytest.approx(100)


def test_no_rate_means_no_relabelled_number(rome, monkeypatch):
    async def none(*_a):
        return None

    monkeypatch.setattr(workflow, "_convert", none)
    i = interp(budget_currency="EGP")
    notes = anyio.run(workflow._budget_currency, rome, i)
    assert i.requirements.budget_currency is None and i.requirements.budget_amount is None and notes


def test_echoed_values_do_not_cancel_a_relative_change(rome):
    c = rome.trip_contract
    i = interp(nights=c.nights, budget_amount=c.budget.amount, actions=[Action(action="extend_trip", amount=2)])
    workflow._drop_echoes(rome, i)
    assert i.requirements.nights is None and i.requirements.budget_amount is None
    assert not workflow._changes_trip_frame(rome, i)


def test_moving_the_start_keeps_the_length(rome):
    c = rome.trip_contract
    new_start = c.start_date + timedelta(days=3)
    apply_requirements(rome, Requirements(start_date=new_start.isoformat()))
    assert rome.draft.start_date == new_start
    assert rome.draft.end_date == new_start + timedelta(days=c.num_days - 1)


def test_a_new_destination_drops_the_old_places(rome):
    rome.draft.must_visit, rome.draft.wish_list = ["Colosseum"], ["Trevi Fountain"]
    apply_requirements(rome, Requirements(destination="Istanbul", must_visit=["Hagia Sophia"]))
    assert rome.draft.must_visit == ["Hagia Sophia"] and rome.draft.wish_list == []


def test_a_new_origin_city_forgets_the_old_airport(rome):
    rome.draft.origin = "CAI"
    apply_requirements(rome, Requirements(origin_city="Riyadh"))
    assert rome.draft.origin is None


def test_cheapest_trip_budget_delta_starts_from_the_found_budget(rome):
    c = rome.trip_contract
    rome.draft.find_cheapest, c.budget.amount, c.budget.hard_limit = True, FIND_CHEAPEST_PLACEHOLDER, False
    rome.metadata["found_budget"] = 2_000
    apply_actions(rome, [Action(action="adjust_budget", amount=500)])
    assert c.budget.amount == 2_500 and c.budget.hard_limit and not rome.draft.find_cheapest


def test_tour_nights_follow_the_new_length():
    assert resize_nights([3, 2, 2], 9) == [3, 2, 4]   # extra nights go to the last city
    assert resize_nights([4, 2, 2], 6) == [2, 2, 2]   # removed ones come off the longest stay
    assert resize_nights([1, 1], 1) == [1, 1]         # every city keeps a night


def test_change_list_never_subtracts_across_currencies(planned):
    old, new = planned.selected_plan, planned.selected_plan.model_copy(deep=True)
    new.budget.currency, new.budget.total = "EGP", old.budget.total * 50
    lines = diff_plans(old, new)
    assert any(x.startswith("Prices now in EGP") for x in lines)
    assert not any(x.startswith("Total cost") for x in lines)


def test_a_failed_streamed_turn_sends_no_done(monkeypatch):
    class Broken:
        async def astream(self, *_a, **_k):
            raise RuntimeError("boom")
            yield  # pragma: no cover

    monkeypatch.setattr(workflow, "get_graph", lambda: Broken())

    async def collect():
        return [e async for e in workflow.run_turn_stream(TripState(), "hello")]

    events = anyio.run(collect)
    assert [e["type"] for e in events] == ["error"]


def test_month_only_gets_a_start_date(rome):
    rome.draft.start_date = date(2026, 10, 12)
    notes = apply_requirements(rome, Requirements(travel_month=11))
    assert rome.draft.start_date.month == 11 and notes
