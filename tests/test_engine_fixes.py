"""Engine fixes: every cheap round-trip ticket is seen, the buffer only covers estimates, the budget plan sees the
cheapest fares, and a flight that lands the next day makes day one a travel day (offline: fakes + replayed data)."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import anyio

from travel_agent import net
from travel_agent.engine.budget import compute_budget
from travel_agent.engine.knobs import PlanKnobs
from travel_agent.engine.planner import PlanContext, _rank_flights, build_plan, select_core
from travel_agent.engine.validators import validate_budget, validate_plan
from travel_agent.models import DayPlan, ItineraryItem, Money, TripPlan
from travel_agent.providers import flights as provider

CAIRO = ZoneInfo("Africa/Cairo")


def _ctx(contract, research, profile, mode="balanced", **knobs):
    return PlanContext(contract=contract, profile=profile, research=research, mode=mode, knobs=PlanKnobs(**knobs))


# ---------------------------------------------------------------- 1) round-trip tickets

def _it(number: str, dep: str, arr: str, price: float, token: str | None = None) -> dict:
    it = {"flights": [{"flight_number": number, "airline": "Emirates", "duration": 900,
                       "departure_airport": {"id": "CAI", "time": dep}, "arrival_airport": {"id": "DPS", "time": arr}}],
          "price": price, "total_duration": 900}
    return {**it, "departure_token": token} if token else it


def _back(number: str, price: float) -> dict:
    it = _it(number, "2026-11-07 10:00", "2026-11-08 06:00", price)
    seg = it["flights"][0]
    seg["departure_airport"]["id"], seg["arrival_airport"]["id"] = "DPS", "CAI"
    return it


def _fake_google(calls: list, fail_token: str | None = None):
    """Step 1: two Emirates outbounds tied at 47,642 (+ a dearer one); step 2 re-prices each as a whole round trip."""
    async def serpapi(engine, ttl, **params):
        calls.append(params.get("departure_token"))
        token = params.get("departure_token")
        if token is None:
            return {"best_flights": [_it("EK 928", "2026-11-01 00:50", "2026-11-02 15:00", 47642, "tok_0050"),
                                     _it("EK 922", "2026-11-01 08:00", "2026-11-02 22:35", 47642, "tok_0800")],
                    "other_flights": [_it("EK 928", "2026-11-01 00:50", "2026-11-02 15:00", 47642, "tok_dup"),
                                      _it("QR 1302", "2026-11-01 14:00", "2026-11-02 20:00", 52000, "tok_qr")]}
        if token == fail_token:
            raise net.QuotaExceeded("SerpApi per-turn call cap (20) reached")
        if token == "tok_0050":
            return {"best_flights": [_back("EK 399", 49047), _back("EK 401", 50100)]}
        if token == "tok_0800":
            return {"best_flights": [_back("EK 399", 47642)]}
        raise AssertionError(f"followed an unexpected outbound: {token}")
    return serpapi


def _round_trips(monkeypatch, fail_token=None):
    calls: list = []
    monkeypatch.setattr(net, "serpapi", _fake_google(calls, fail_token))
    tickets = anyio.run(lambda: provider.search_round_trip("CAI", "DPS", datetime(2026, 11, 1).date(),
                                                           datetime(2026, 11, 7).date(), "EGP", "Africa/Cairo",
                                                           "Asia/Makassar"))
    return tickets, calls


def test_round_trip_follows_both_tied_outbounds_and_keeps_the_cheapest(monkeypatch):
    tickets, calls = _round_trips(monkeypatch)
    # One outbound list + one follow for each of the 2 cheapest distinct outbounds (the duplicate and the dearer
    # Qatar fare are never followed).
    assert calls[0] is None and sorted(calls[1:]) == ["tok_0050", "tok_0800"]
    assert [t[2] for t in tickets] == [47642, 49047]  # every ticket, cheapest first, each at its own total
    out, back, total = tickets[0]
    assert out.flight_number == "EK 922" and out.price_per_person.amount == back.price_per_person.amount == total / 2
    # The same return flight on two tickets is two distinct legs: ids never collide.
    ids = [f.id for t in tickets for f in t[:2]]
    assert len(set(ids)) == 4 and all(i.endswith("_rt") for i in ids)


def test_one_failed_follow_keeps_the_other_ticket(monkeypatch):
    tickets, _ = _round_trips(monkeypatch, fail_token="tok_0050")
    assert [t[2] for t in tickets] == [47642]


def test_flight_server_keeps_every_ticket_that_beats_one_ways(monkeypatch):
    from travel_agent.mcp_servers import flights as flight_server

    tickets, _ = _round_trips(monkeypatch)
    one_way_out = tickets[0][0].model_copy(update={"id": "fl_ow_out", "price_per_person": Money(amount=30000, currency="EGP", price_type="known")})
    one_way_back = tickets[0][1].model_copy(update={"id": "fl_ow_back", "price_per_person": Money(amount=19500, currency="EGP", price_type="known")})

    async def one_way(dep, arr, on, currency, direction, dep_tz, arr_tz, travel_class=1):
        return ([one_way_out] if direction == "outbound" else [one_way_back]), {}

    async def round_trip(*a, **k):
        return list(reversed(tickets))  # order must not matter

    monkeypatch.setattr(provider, "search_one_way", one_way)
    monkeypatch.setattr(provider, "search_round_trip", round_trip)
    monkeypatch.setattr(flight_server.ai_fallback, "available", lambda: False)
    res = anyio.run(lambda: flight_server.search_flights("CAI", "DPS", "2026-11-01", "2026-11-07", "EGP"))
    # Both tickets beat 30,000 + 19,500 = 49,500 one-way: both are offered; the insight is the minimum.
    assert sorted(rt["total_per_person"]["amount"] for rt in res["round_trips"]) == [47642, 49047]
    assert res["price_insights"]["cheapest_round_trip"] == 47642


def test_planner_picks_the_cheaper_of_several_tickets(rome_research, rome_contract, profile):
    from travel_agent.models import RoundTrip

    r = rome_research.model_copy(deep=True)
    o = min(r.flights_outbound, key=lambda f: f.price_per_person.amount)
    b = min(r.flights_return, key=lambda f: f.price_per_person.amount)
    cur = o.price_per_person.currency
    one_ways = o.price_per_person.amount + b.price_per_person.amount
    r.round_trips = []
    for tag, total in (("a", one_ways * 0.8), ("b", one_ways * 0.6)):  # same flights, two prices
        legs = [f.model_copy(update={"id": f"{f.id}_{tag}_rt", "price_per_person": Money(amount=total / 2, currency=cur, price_type="known")})
                for f in (o, b)]
        r.round_trips.append(RoundTrip(outbound=legs[0], inbound=legs[1], total_per_person=Money(amount=total, currency=cur)))
    out, ret, _, _, _ = select_core(_ctx(rome_contract, r, profile, mode="budget"))
    assert (out.item.id, ret.item.id) == (r.round_trips[1].outbound.id, r.round_trips[1].inbound.id)


# ---------------------------------------------------------------- 2) the buffer covers estimates only

def test_buffer_only_on_prices_that_are_not_published(rome_research, rome_contract):
    o, b = rome_research.flights_outbound[0], rome_research.flights_return[0]
    hotel = rome_research.hotels[0]
    day = DayPlan(day=1, date=rome_contract.start_date, title="Day", items=[
        ItineraryItem(start="13:00", end="14:00", kind="meal", title="Lunch",
                      cost=Money(amount=100.0, currency="USD", price_type="estimated", source="AI estimate")),
        ItineraryItem(start="15:00", end="16:00", kind="activity", title="Museum",
                      cost=Money(amount=40.0, currency="USD", price_type="known"))])
    plan = TripPlan(mode="budget", outbound_flight=o, return_flight=b, hotel=hotel, days=[day])
    for f in (o, b):
        assert f.price_per_person.price_type == "known" and hotel.price_per_night.price_type == "known"
    fx = rome_research.fx_rates
    budget = compute_budget(plan.model_copy(deep=True), rome_contract, fx, 0.05)
    subtotal = budget.flights + budget.hotel + budget.food + budget.activities + budget.transport
    assert abs(budget.buffer - 0.05 * 140.0) < 0.01  # lunch and ticket; the published fares and hotel rate carry none
    assert abs(budget.total - (subtotal + budget.buffer)) < 0.05

    # The live case: a plan just under the limit is not "over budget" because of a buffer on a known airfare.
    tight = rome_contract.model_copy(update={"budget": rome_contract.budget.model_copy(update={"amount": round(subtotal + 10, 2)})})
    assert subtotal * 1.05 > tight.budget.amount  # the old 5%-of-everything buffer would have failed it
    b2 = compute_budget(plan.model_copy(deep=True), tight, fx, 0.05)
    assert b2.status == "PASS" and "carry none" in b2.notes[0]
    plan.budget = b2
    assert not [v for v in validate_budget(plan, tight, rome_research, 0.05) if "Over budget" in v.message]


def test_planned_buffer_skips_published_fares_and_rates(rome_research, rome_contract, profile):
    b = build_plan(_ctx(rome_contract, rome_research, profile)).budget
    subtotal = b.flights + b.hotel + b.food + b.activities + b.transport
    assert abs(b.buffer - 0.05 * (subtotal - b.flights - b.hotel)) < 0.05  # the Rome fares and rates are live
    assert b.buffer < 0.05 * subtotal  # flights and hotel are live prices


# ---------------------------------------------------------------- 3) the budget plan sees the cheapest fares

def _shifted(f, dep: datetime, arr: datetime, price: float, fid: str):
    return f.model_copy(update={"id": fid, "depart_at": dep, "arrive_at": arr,
                                "price_per_person": Money(amount=price, currency=f.price_per_person.currency,
                                                          price_type="known")})


def test_budget_plan_sees_a_cheap_late_or_dawn_fare(rome_research, rome_contract, profile):
    r = rome_research.model_copy(deep=True)
    tz = ZoneInfo(r.destination_info["timezone"])
    o = min(r.flights_outbound, key=lambda f: f.price_per_person.amount)
    b = min(r.flights_return, key=lambda f: f.price_per_person.amount)
    start, end = rome_contract.start_date, rome_contract.end_date
    late = _shifted(o, datetime.combine(start, time(20, 0), CAIRO), datetime.combine(start, time(23, 40), tz),
                    o.price_per_person.amount * 0.4, "fl_cheap_late")
    dawn = _shifted(b, datetime.combine(end, time(5, 0), tz), datetime.combine(end, time(9, 0), CAIRO),
                    b.price_per_person.amount * 0.4, "fl_cheap_dawn")
    r.flights_outbound.append(late)
    r.flights_return.append(dawn)

    def ids(mode, prof=profile):
        c = _ctx(rome_contract, r, prof, mode=mode)
        return ({x.item.id for x in _rank_flights(r.flights_outbound, c)},
                {x.item.id for x in _rank_flights(r.flights_return, c, leaving=True)})

    outs, rets = ids("balanced")
    assert late.id not in outs and dawn.id not in rets  # other modes still avoid them
    outs, rets = ids("budget")
    assert late.id in outs and dawn.id in rets
    o_pick, r_pick, _, _, _ = select_core(_ctx(rome_contract, r, profile, mode="budget"))
    assert o_pick.item.id == late.id and r_pick.item.id == dawn.id  # 60% cheaper: the budget plan takes them
    # A rule the traveller set is still a rule: no early flights means the 05:00 fare stays out.
    _, rets = ids("budget", profile.model_copy(update={"avoid_early_flights": True}))
    assert dawn.id not in rets


def test_wanting_to_arrive_on_the_first_day_beats_a_cheaper_next_day_landing(rome_research, rome_contract, profile):
    # "I want to arrive on the 1st": a fare 60% cheaper that lands the next day loses, even on the budget plan.
    r = rome_research.model_copy(deep=True)
    tz = ZoneInfo(r.destination_info["timezone"])
    o = min(r.flights_outbound, key=lambda f: f.price_per_person.amount)
    start = rome_contract.start_date
    next_day = _shifted(o, datetime.combine(start, time(20, 0), CAIRO),
                        datetime.combine(start + timedelta(days=1), time(9, 0), tz),
                        o.price_per_person.amount * 0.4, "fl_next_day")
    r.flights_outbound.append(next_day)
    o_pick, *_ = select_core(_ctx(rome_contract, r, profile, mode="budget"))
    assert o_pick.item.id == next_day.id  # no arrival day said: the cheapest wins
    wants = rome_contract.model_copy(update={"arrive_by": start})
    o_pick, *_ = select_core(_ctx(wants, r, profile, mode="budget"))
    assert o_pick.item.id != next_day.id and o_pick.item.arrive_at.astimezone(tz).date() == start
    assert "the day you want to arrive" in o_pick.reasons[0] and "cheaper lands a day later" in o_pick.reasons[0]


# ---------------------------------------------------------------- 4) landing on a later date

def _next_day_plan(rome_research, rome_contract, profile, land: time, leave: datetime | None = None):
    r = rome_research.model_copy(deep=True)
    tz = ZoneInfo(r.destination_info["timezone"])
    o = min(r.flights_outbound, key=lambda f: f.price_per_person.amount)
    start = rome_contract.start_date
    long_haul = _shifted(o, datetime.combine(start, time(8, 0), CAIRO),
                         datetime.combine(start + timedelta(days=1), land, tz), o.price_per_person.amount, "fl_long_haul")
    r.flights_outbound.append(long_haul)
    pins = [long_haul.id]
    if leave is not None:
        b = min(r.flights_return, key=lambda f: f.price_per_person.amount)
        night = _shifted(b, leave, leave + timedelta(hours=4), b.price_per_person.amount, "fl_after_midnight")
        r.flights_return.append(night)
        pins.append(night.id)
    plan = build_plan(_ctx(rome_contract, r, profile, flight_pins=pins))
    return plan, r, tz


def test_next_day_arrival_makes_day_one_a_travel_day(rome_research, rome_contract, profile):
    plan, r, _ = _next_day_plan(rome_research, rome_contract, profile, time(22, 35))
    d1, d2, d3 = plan.days[:3]
    assert plan.outbound_flight.id == "fl_long_haul"
    assert d1.travel_day and d1.title.startswith("Travel day") and [i.kind for i in d1.items] == ["flight"]
    assert d1.activity_count == 0 and "22:35" in d1.notes[0]
    # Day 2 is the landing: still in the air until 22:35 - no sightseeing, the flight and the late arrival only.
    assert d2.activity_count == 0 and d2.items[0].kind == "flight" and d2.items[0].end == "22:35"
    assert not any(i.kind in ("activity", "meal") for i in d2.items)
    assert d3.activity_count > 0  # the first real day
    report = validate_plan(plan, rome_contract, profile, r, 0.05)
    assert not [v for v in report.errors if v.check in ("schedule", "reality", "energy")], report.errors
    # Flights paid once (the hotel skips the unused first night: see test_planner_quality).
    b = plan.budget
    fares = (plan.outbound_flight.price_per_person.amount * r.fx_rates.get(plan.outbound_flight.price_per_person.currency, 1.0)
             + plan.return_flight.price_per_person.amount * r.fx_rates.get(plan.return_flight.price_per_person.currency, 1.0))
    assert abs(b.flights - fares * rome_contract.travelers) < 1
    assert len(plan.days) == rome_contract.num_days and sum(b.daily_spending.values()) >= 0


def test_next_day_midday_arrival_sights_start_after_landing(rome_research, rome_contract, profile):
    plan, r, _ = _next_day_plan(rome_research, rome_contract, profile, time(12, 0))
    d2 = plan.days[1]
    assert plan.days[0].travel_day and plan.days[0].activity_count == 0
    first = min((i.start for i in d2.items if i.kind in ("activity", "meal")), default="23:59")
    assert first >= "12:45"  # landing + arrival formalities at the very least
    report = validate_plan(plan, rome_contract, profile, r, 0.05)
    assert not [v for v in report.errors if v.check in ("schedule", "reality")], report.errors


def test_flight_home_after_midnight_means_the_airport_run_the_evening_before(rome_research, rome_contract, profile):
    tz = ZoneInfo(rome_research.destination_info["timezone"])
    leave = datetime.combine(rome_contract.end_date, time(1, 30), tz)
    plan, r, _ = _next_day_plan(rome_research, rome_contract, profile, time(9, 0), leave)
    last, evening = plan.days[-1], plan.days[-2]
    assert plan.return_flight.id == "fl_after_midnight"
    assert last.travel_day and [i.kind for i in last.items] == ["flight"] and last.items[0].start == "01:30"
    assert not any(i.kind == "flight" for i in evening.items)
    assert any(i.kind == "transfer" and "airport" in i.title.lower() for i in evening.items)
    run = next(i for i in evening.items if i.kind == "transfer" and "airport" in i.title.lower())
    assert run.end <= "23:00"  # at the airport ~2h30 before a 01:30 departure
    assert any(i.meal_type == "dinner" for i in evening.items)  # the evening before the airport is still fed
    report = validate_plan(plan, rome_contract, profile, r, 0.05)
    assert not [v for v in report.errors if v.check in ("schedule", "reality")], report.errors
