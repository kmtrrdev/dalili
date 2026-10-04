"""Regression tests for the Phase 2 correctness fixes (currency-safe repair, FX fallback, agreed day capacity,
post-midnight arrivals, repairs not undone by redistribution)."""

from datetime import datetime, timedelta, timezone

import anyio

from travel_agent import net
from travel_agent.engine.knobs import PlanKnobs
from travel_agent.engine.planner import PlanContext, build_plan, build_slots
from travel_agent.engine.repair import repair
from travel_agent.engine.validators import validate_energy
from travel_agent.models import Money, ValidationReport, Violation
from travel_agent.providers import currency


def _ctx(contract, research, profile, mode="balanced", **knobs):
    return PlanContext(contract=contract, profile=profile, research=research, mode=mode, knobs=PlanKnobs(**knobs))


def test_repair_caps_are_in_the_budget_currency(rome_research, rome_contract, profile):
    """A hotel priced in EUR and a budget in USD: the 'cheaper hotel' cap must be a USD amount."""
    plan = build_plan(_ctx(rome_contract, rome_research, profile))
    report = ValidationReport(result="FAIL", violations=[Violation(check="budget", severity="error", message="over",
                                                                   fix_hint="hotel")])
    plan.budget.total = plan.budget.limit * 1.04
    k, _ = repair(plan, report, PlanKnobs(), rome_research, 0, profile)
    h = plan.hotel.price_per_night
    in_usd = h.amount * (1.0 if h.currency == plan.budget.currency else rome_research.fx_rates[h.currency.upper()])
    assert k.hotel_max_price_local is not None and abs(k.hotel_max_price_local - in_usd * 0.85) < 0.01


def test_one_unknown_currency_does_not_break_the_others(monkeypatch):
    async def frank(service, url, params=None, *, ttl_s, **kw):
        if service == "frankfurter":
            return [{"quote": "EUR", "rate": 0.9, "date": "2026-10-01"}]
        return {"result": "success", "rates": {"XYZ": 3.0}, "time_last_update_utc": "today"}

    monkeypatch.setattr(net, "fetch_json", frank)
    rates, meta = anyio.run(currency.rates, "USD", ["EUR", "XYZ"])
    assert rates == {"USD": 1.0, "EUR": 0.9, "XYZ": 3.0} and "open.er-api" in meta.provider

    async def none_for_abc(service, url, params=None, *, ttl_s, **kw):
        return [{"quote": "EUR", "rate": 0.9}] if service == "frankfurter" else {"result": "success", "rates": {}}

    monkeypatch.setattr(net, "fetch_json", none_for_abc)
    rates, _ = anyio.run(lambda: currency.rates("USD", ["EUR", "ABC"], allow_missing=True))
    assert rates == {"USD": 1.0, "EUR": 0.9}  # ABC reported missing by the caller, never treated as 1:1


def test_a_day_the_traveller_packed_is_not_flagged_as_too_dense(rome_research, rome_contract, profile):
    plan = build_plan(_ctx(rome_contract, rome_research, profile, day_capacity_override={3: 6}))
    day3 = next(d for d in plan.days if d.day == 3)
    assert day3.capacity == 6
    assert not [v for v in validate_energy(plan, profile) if v.day == 3 and v.severity == "error"]


def test_landing_after_midnight_leaves_day_one_empty_not_lost(rome_research, rome_contract, profile):
    out = min(rome_research.flights_outbound, key=lambda f: f.price_per_person.amount).model_copy(deep=True)
    tz = _ctx(rome_contract, rome_research, profile).tz
    land = datetime.combine(rome_contract.start_date + timedelta(days=1), datetime.min.time()).replace(hour=0, minute=40, tzinfo=tz)
    out.arrive_at, out.depart_at = land.astimezone(timezone.utc), (land - timedelta(hours=3)).astimezone(timezone.utc)
    slots = build_slots(_ctx(rome_contract, rome_research, profile), out, None, None, None)
    assert slots[0].max_count == 0


def test_redistribution_respects_a_repair_exclusion(rome_research, rome_contract, profile):
    base = build_plan(_ctx(rome_contract, rome_research, profile))
    day = next(d for d in base.days if d.activity_count >= 2 and 1 < d.day < len(base.days))
    banned = [i.place_id for i in day.items if i.kind == "activity" and i.place_id]
    plan = build_plan(_ctx(rome_contract, rome_research, profile, exclude_on_day={day.day: banned}))
    again = next(d for d in plan.days if d.day == day.day)
    assert not set(banned) & {i.place_id for i in again.items if i.place_id}


def test_unknown_money_is_not_a_price():
    assert Money(amount=0.0).price_type == "estimated"  # unchanged default for existing data
