"""Planner + validators on real recorded Rome data, including injected reality violations."""

import anyio
import pytest

from travel_agent import research
from travel_agent.engine.knobs import PlanKnobs
from travel_agent.engine.planner import STYLE_CAPACITY, PlanContext, build_plan, day_load
from travel_agent.engine.repair import repair
from travel_agent.engine.scoring import score_plan
from travel_agent.engine.validators import validate_plan
from travel_agent.models import PLANNING_MODES, Budget, ItineraryItem, Metadata, Money, TransportLeg, TravelerProfile


@pytest.fixture(autouse=True)
def _routing(rome_research):
    anyio.run(lambda: research.prepare_routing(rome_research))


def build(contract, profile, r, mode="balanced", knobs=None):
    return build_plan(PlanContext(contract, profile, r, mode, knobs or PlanKnobs()))


def repaired(contract, profile, r, mode):
    knobs = PlanKnobs()
    for i in range(6):
        plan = build(contract, profile, r, mode, knobs)
        plan.validation = validate_plan(plan, contract, profile, r, 0.05)
        if plan.validation.result == "PASS":
            break
        knobs, _ = repair(plan, plan.validation, knobs, r, i, profile)
    plan.score = score_plan(plan, contract, profile, r, mode)
    return plan


@pytest.mark.parametrize("mode", PLANNING_MODES)
def test_every_mode_validates_on_real_data(rome_contract, rome_research, profile, mode):
    plan = repaired(rome_contract, profile, rome_research, mode)
    errors = [v.message for v in plan.validation.errors]
    assert plan.validation.result == "PASS" or errors == [m for m in errors if "Over budget" in m]
    assert len(plan.days) == rome_contract.num_days and 0 <= plan.score.total <= 100


def test_budget_adds_up_and_uses_real_prices(rome_contract, rome_research, profile):
    plan = build(rome_contract, profile, rome_research)
    b = plan.budget
    assert abs(b.flights + b.hotel + b.food + b.activities + b.transport + b.buffer - b.total) < 0.05
    expected_flights = (plan.outbound_flight.price_per_person.amount + plan.return_flight.price_per_person.amount) * 2
    assert abs(b.flights - expected_flights) < 0.01, "flights are the real Google Flights fares x travelers"
    assert abs(b.hotel - plan.hotel.price_per_night.amount * rome_contract.nights) < 0.01


def test_relaxed_capacity_and_meals(rome_contract, rome_research):
    relaxed = TravelerProfile(travel_style="relaxed", activity_preferences=["history"])
    plan = build(rome_contract, relaxed, rome_research)
    cap = STYLE_CAPACITY["relaxed"][0]
    for d in plan.days[1:-1]:
        acts = [i for i in d.items if i.kind == "activity"]
        assert day_load([int(i.end[:2]) * 60 + int(i.end[3:]) - int(i.start[:2]) * 60 - int(i.start[3:]) for i in acts]) <= cap
        assert {"breakfast", "dinner"} <= {i.meal_type for i in d.items if i.kind == "meal"}


def test_wake_up_time_respected(rome_contract, rome_research):
    plan = build(rome_contract, TravelerProfile(preferred_wake_up_time="10:00"), rome_research)
    for d in plan.days[1:-1]:
        assert next(i for i in d.items if i.kind in ("meal", "activity")).start >= "10:00"


def test_pins_keep_days_stable(rome_contract, rome_research, profile):
    base = build(rome_contract, profile, rome_research)
    pins = {d.day: [i.place_id for i in d.items if i.kind == "activity"] for d in base.days}
    again = build_plan(PlanContext(rome_contract, profile, rome_research, "balanced", PlanKnobs(), pinned_days=pins))
    # Same places on the same days (the route optimizer may re-sequence stops the gap filler had appended).
    assert {d.day: sorted(i.place_id for i in d.items if i.kind == "activity") for d in again.days} == \
        {day: sorted(ids) for day, ids in pins.items()}


def test_requested_places_survive_packed_days(rome_contract, rome_research, profile):
    """Named places are kept even when every day is already full (as the pyramids once got squeezed out of Cairo)."""
    base = build(rome_contract, profile, rome_research)
    pins = {d.day: [i.place_id for i in d.items if i.kind == "activity"] for d in base.days}  # every day already full
    planned = {pid for ids in pins.values() for pid in ids}
    wanted = [a for a in sorted(rome_research.attractions, key=lambda a: -a.duration_minutes)
              if a.id not in planned and not a.day_trip and not a.dates and "overnight_trip" not in a.categories
              and a.opening_hours][:3]
    knobs = PlanKnobs(must_include=[a.id for a in wanted])
    for mode in PLANNING_MODES:
        plan = build_plan(PlanContext(rome_contract, profile, rome_research, mode, knobs, pinned_days=pins))
        assert all(day for day in plan.requested.values()), (mode, plan.requested)
        placed = {i.place_id for d in plan.days for i in d.items}
        assert {a.id for a in wanted} <= placed


def errors(report, check):
    return [v for v in report.violations if v.check == check and v.severity == "error"]


def test_injected_violations_are_caught(rome_contract, rome_research, profile):
    plan = build(rome_contract, profile, rome_research)
    assert validate_plan(plan, rome_contract, profile, rome_research, 0.05).result == "PASS"

    over = rome_contract.model_copy(update={"budget": Budget(amount=500)})
    assert errors(validate_plan(plan, over, profile, rome_research, 0.05), "budget")

    p = plan.model_copy(deep=True)
    meal = next(i for i in p.days[2].items if i.kind == "meal" and i.place_id and rome_research.place(i.place_id).hours_verified)
    meal.start, meal.end = "04:00", "05:00"
    assert errors(validate_plan(p, rome_contract, profile, rome_research, 0.05), "opening_hours")

    p = plan.model_copy(deep=True)
    p.days[1].items.append(ItineraryItem(start="23:00", end="23:30", kind="activity", title="Invented rooftop", place_id="a_fake"))
    assert errors(validate_plan(p, rome_contract, profile, rome_research, 0.05), "reality")

    p = plan.model_copy(deep=True)
    item = next(i for i in p.days[2].items if i.kind == "activity")
    item.transport_from_previous = TransportLeg(mode="walk", minutes=70, distance_km=5.5, cost=Money(amount=0))
    assert errors(validate_plan(p, rome_contract, profile, rome_research, 0.05), "distance")

    p = plan.model_copy(deep=True)
    p.days[2].items[2].start = p.days[2].items[1].start
    assert errors(validate_plan(p, rome_contract, profile, rome_research, 0.05), "schedule")


def test_storm_forecast_moves_plans_indoors(rome_contract, rome_research, profile):
    r = rome_research.model_copy(deep=True)
    for w in r.weather[1:-1]:
        w.risk, w.condition = "high", "Thunderstorm"
        w.metadata = Metadata(source="weather_mcp", provider="Open-Meteo forecast", confidence=0.8)
    plan = repaired(rome_contract, profile, r, "balanced")
    assert not errors(plan.validation, "weather")
    acts = [i for d in plan.days[1:-1] for i in d.items if i.kind == "activity"]
    assert sum(1 for i in acts if i.indoor) >= len(acts) * 0.6
