"""Planning intelligence: icons first, full arrival days, smart flights, honest budgets, safe critic, model wiring."""

from datetime import timedelta

import anyio

from travel_agent import llm
from travel_agent.agents import critic
from travel_agent.engine.knobs import PlanKnobs
from travel_agent.engine.planner import PlanContext, build_plan, select_core
from travel_agent.engine.ranking import fame, score_attraction
from travel_agent.engine.repair import PAINLESS_STEPS, repair
from travel_agent.engine.validators import validate_plan
from travel_agent.models import Money, RoundTrip, TravelerProfile, TripState
from travel_agent.nlu import Action, Requirements, TurnInterpretation
from travel_agent.workflow import _changes_trip_frame


def _ctx(contract, research, profile, mode="balanced", **knobs):
    return PlanContext(contract=contract, profile=profile, research=research, mode=mode, knobs=PlanKnobs(**knobs))


# ---------------------------------------------------------------- what tourists come for

def test_most_visited_landmarks_rank_first(rome_research, rome_contract):
    plain = TravelerProfile()
    ranked = sorted(rome_research.attractions, key=lambda a: -score_attraction(a, plain, rome_contract, "balanced").score)
    top_by_reviews = max(rome_research.attractions, key=lambda a: a.reviews_count or 0)
    assert fame(top_by_reviews) > 0.8
    assert top_by_reviews in ranked[:3]


def _city_icons(research, n):
    """The most-reviewed sights in the city itself (an overnight idea like Milan from Rome is not a Rome icon)."""
    city = [a for a in research.attractions if not a.day_trip and "overnight_trip" not in a.categories]
    return sorted(city, key=lambda a: -(a.reviews_count or 0))[:n]


def test_city_icons_are_in_a_week_long_plan(rome_research, rome_contract, profile):
    plan = build_plan(_ctx(rome_contract, rome_research, profile))
    planned = {i.place_id for d in plan.days for i in d.items if i.place_id}
    icons = _city_icons(rome_research, 5)
    assert all(a.id in planned for a in icons), [a.name for a in icons if a.id not in planned]


def test_price_cap_never_drops_an_icon(rome_research, rome_contract, profile):
    """'Free sights only' saves a few euros; it must not cost the traveller the Colosseum."""
    plan = build_plan(_ctx(rome_contract, rome_research, profile, activity_cost_cap_local=0.0))
    planned = {i.place_id for d in plan.days for i in d.items if i.place_id}
    paid_icons = [a for a in _city_icons(rome_research, 50) if fame(a) >= 0.8 and a.cost_per_person.amount > 0]
    assert paid_icons and all(a.id in planned for a in paid_icons)


# ---------------------------------------------------------------- arrival / departure days

def test_arrival_afternoon_is_used(rome_research, rome_contract, profile):
    """A morning landing leaves an afternoon: more than one sight, and no idle 'free time' while sights wait nearby."""
    active = profile.model_copy(update={"travel_style": "active"})
    plan = build_plan(_ctx(rome_contract, rome_research, active))
    day1 = plan.days[0]
    arrive = plan.outbound_flight.arrive_at.astimezone(_ctx(rome_contract, rome_research, active).tz)
    if arrive.hour < 13:
        assert day1.activity_count >= 2


# ---------------------------------------------------------------- flights

def test_round_trip_ticket_is_used_when_cheaper(rome_research, rome_contract, profile):
    r = rome_research.model_copy(deep=True)
    o = min(r.flights_outbound, key=lambda f: f.price_per_person.amount).model_copy(deep=True)
    b = min(r.flights_return, key=lambda f: f.price_per_person.amount).model_copy(deep=True)
    total = (o.price_per_person.amount + b.price_per_person.amount) * 0.6  # 40% cheaper as one ticket
    for f in (o, b):
        f.id += "_rt"
        f.price_per_person = Money(amount=total / 2, currency=f.price_per_person.currency, price_type="known")
    r.round_trips = [RoundTrip(outbound=o, inbound=b, total_per_person=Money(amount=total, currency=o.price_per_person.currency))]
    tight = rome_contract.model_copy(update={"budget": rome_contract.budget.model_copy(update={"amount": 1500.0})})
    out, ret, _, _, _ = select_core(_ctx(tight, r, profile, mode="budget"))
    assert out.item.id == o.id and ret.item.id == b.id  # both legs of the ticket, never one alone
    plan = build_plan(_ctx(tight, r, profile, mode="budget"))
    assert not [v for v in validate_plan(plan, tight, profile, r, 0.05).errors if v.check == "reality"]


# ---------------------------------------------------------------- same-name cities (Naples, Italy vs Naples, Florida)

def test_hotel_search_names_the_country_and_drops_far_hotels(monkeypatch):
    from datetime import date

    from travel_agent import net
    from travel_agent.models import GeoPoint
    from travel_agent.providers import hotels
    from travel_agent.research import _qualified

    class Ref:
        name, country = "Naples", "Italy"

    assert _qualified(Ref) == "Naples, Italy"
    sent = {}

    async def fake_serpapi(engine, ttl, **params):
        sent.update(params)

        def prop(name, lat, lon):
            return {"name": name, "type": "hotel", "gps_coordinates": {"latitude": lat, "longitude": lon},
                    "rate_per_night": {"extracted_lowest": 90}, "overall_rating": 4.2, "reviews": 300}
        return {"properties": [prop("Hotel Napoli Centro", 40.85, 14.26),
                               prop("Red Roof Inn Naples Downtown-5th Ave S", 26.14, -81.79)]}  # Florida

    monkeypatch.setattr(net, "serpapi", fake_serpapi)
    found = anyio.run(hotels.search, "Naples, Italy", date(2026, 10, 13), date(2026, 10, 16), 1, "EUR",
                      GeoPoint(lat=40.8518, lon=14.2681))
    assert sent["q"] == "Hotels in Naples, Italy"
    assert [h.name for h in found] == ["Hotel Napoli Centro"]


# ---------------------------------------------------------------- open-jaw trips and rooms

def test_fly_home_to_another_city_and_rooms(rome_contract):
    """'From Riyadh to Istanbul, then back to Cairo, all three in one room.'"""
    from travel_agent.replanner import apply_requirements, build_contract
    from travel_agent.workflow import _changes_trip_frame

    trip = TripState(trip_contract=rome_contract)
    d = trip.draft
    d.origin_city, d.origin_ref = "Cairo", rome_contract.origin_ref
    d.destination, d.destination_ref = "Rome", rome_contract.destination_ref
    d.start_date, d.end_date, d.budget_amount, d.travelers = rome_contract.start_date, rome_contract.end_date, 3000, 3

    ask = Requirements(return_to="Milan", rooms=1)
    assert _changes_trip_frame(trip, TurnInterpretation(intent="feedback", requirements=ask))
    apply_requirements(trip, ask)
    assert d.return_to == "Milan" and d.rooms == 1
    d.return_ref = rome_contract.destination_ref.model_copy(update={"name": "Milan", "airports": ["MXP"]})
    c, _ = build_contract(trip)
    assert c.return_city == "Milan" and c.return_to == "MXP" and c.end_ref.name == "Milan" and c.rooms == 1

    apply_requirements(trip, Requirements(return_to="Cairo"))  # back home = the normal trip again
    assert d.return_to is None and d.return_ref is None


def test_open_jaw_searches_the_last_flight_home_to_that_city(monkeypatch):
    from travel_agent.mcp_servers import flights as flight_server
    from travel_agent.providers import flights as provider

    calls = []

    async def one_way(dep, arr, on, currency, direction, dep_tz, arr_tz, travel_class=1):
        calls.append((direction, dep, arr))
        return [], {}

    async def round_trip(*a, **k):
        raise AssertionError("an open-jaw trip has no round-trip ticket")

    monkeypatch.setattr(provider, "search_one_way", one_way)
    monkeypatch.setattr(provider, "search_round_trip", round_trip)
    monkeypatch.setattr(flight_server.ai_fallback, "available", lambda: False)
    anyio.run(lambda: flight_server.search_flights("RUH", "IST", "2026-10-24", "2026-10-30", "SAR",
                                                   return_to="CAI", return_timezone="Africa/Cairo"))
    assert calls == [("outbound", "RUH", "IST"), ("return", "IST", "CAI")]


# ---------------------------------------------------------------- the budget plan is the cheapest

def test_budget_mode_takes_the_cheapest_flights_and_hotel(rome_research, rome_contract, profile):
    def core_cost(mode):
        o, r, h, _, _ = select_core(_ctx(rome_contract, rome_research, profile, mode=mode))
        return o.item.price_per_person.amount + r.item.price_per_person.amount + h.item.price_per_night.amount * rome_contract.nights

    assert core_cost("budget") <= min(core_cost(m) for m in ("balanced", "comfort", "experience")) * 1.03


def test_budget_plan_never_costs_more_than_another_mode(rome_research, rome_contract, profile):
    from travel_agent.workflow import _budget_is_cheapest

    plans = {m: build_plan(_ctx(rome_contract, rome_research, profile, mode=m))
             for m in ("balanced", "budget", "comfort", "experience")}
    plans["budget"].budget.total = max(p.budget.total for p in plans.values()) + 100  # force the bug
    _budget_is_cheapest(plans)
    assert plans["budget"].budget.total == min(p.budget.total for p in plans.values())
    assert plans["budget"].mode == "budget"


def test_find_cheapest_sets_the_budget_to_the_cheapest_plan(monkeypatch):
    from travel_agent.replanner import nice_amount
    from travel_agent.workflow import plan as plan_node, run_turn
    from tests.conftest import ROME_REQUEST

    rome, _ = anyio.run(run_turn, TripState(), ROME_REQUEST)
    trip = rome.model_copy(deep=True)
    trip.draft.find_cheapest, trip.draft.budget_amount = True, None
    out = anyio.run(plan_node, {"trip": trip})
    budget_plan = out["candidates"]["budget"]
    assert trip.trip_contract.budget.amount == trip.metadata["found_budget"]
    assert budget_plan.budget.total <= trip.trip_contract.budget.amount
    assert trip.metadata["found_budget"] == nice_amount(trip.metadata["found_budget"])


def test_four_plans_follow_their_strategies(monkeypatch):
    """Budget = cheapest flights and hotel; comfort = the best-rated hotel and better restaurants; each has a pitch."""
    from travel_agent.workflow import plan as plan_node, run_turn
    from tests.conftest import ROME_REQUEST

    rome, _ = anyio.run(run_turn, TripState(), ROME_REQUEST)
    out = anyio.run(plan_node, {"trip": rome.model_copy(deep=True)})
    plans = out["candidates"]

    def meal_spend(p):
        costs = [i.cost.amount for d in p.days for i in d.items
                 if i.kind == "meal" and i.meal_type in ("lunch", "dinner") and i.cost.amount > 0]
        return sum(costs) / max(len(costs), 1)

    b, c = plans["budget"], plans["comfort"]
    assert b.hotel.price_per_night.amount <= min(p.hotel.price_per_night.amount for p in plans.values())
    assert c.hotel.rating >= max(p.hotel.rating for p in plans.values()) - 0.05
    assert meal_spend(c) >= meal_spend(b)
    assert all(p.pitch and p.pitch_ar for p in plans.values())


def test_menu_search_gives_a_link_and_a_meal_built_from_quoted_prices(monkeypatch):
    from travel_agent import net
    from travel_agent.providers import menus

    async def fake_serpapi(engine, ttl, **params):
        assert engine == "google" and "menu" in params["q"]
        return {"organic_results": [{"link": "https://menu.example/neve", "title": "N'EVET menu",
                                     "snippet": "Adana kebab ₺450 · Lentil soup ₺120 · Ayran ₺60 · Baklava ₺180"}]}

    async def no_page(url, ttl_s=0):
        raise net.ProviderError("offline")

    def answer(items, meal):
        async def parse(system, user, schema, max_tokens=16000, effort=None, timeout=None):
            return menus.MenuEstimate(found=True, menu_url="https://menu.example/neve", currency="TRY",
                                      items=items, meal_per_person=meal, basis="main + drink")
        return parse

    monkeypatch.setattr(net, "serpapi", fake_serpapi)
    monkeypatch.setattr(net, "fetch_page", no_page)
    monkeypatch.setattr(llm, "available", lambda: True)
    real = [menus.PricedItem(item="Adana kebab", price=450, quote="Adana kebab ₺450"),
            menus.PricedItem(item="Ayran", price=60, quote="Ayran ₺60")]
    monkeypatch.setattr(llm, "parse", answer(real, 510))
    out = anyio.run(menus.menu_price, "N'EVET", "Istanbul")
    assert out == {"amount": 510, "currency": "TRY", "menu_url": "https://menu.example/neve", "basis": "main + drink",
                   "google": False}

    invented = [menus.PricedItem(item="Steak", price=900, quote="Steak ₺900"),
                menus.PricedItem(item="Wine", price=300, quote="Wine ₺300")]
    monkeypatch.setattr(llm, "parse", answer(invented, 1200))
    assert anyio.run(menus.menu_price, "N'EVET", "Istanbul") is None  # prices not in the sources: never shown


def test_each_city_of_a_journey_gets_its_own_picks():
    from travel_agent.agents.strategist import DEFAULTS, CityPicks, for_city

    exp = DEFAULTS.experience.model_copy(update={"cities": [
        CityPicks(city="Venice", hotel_shortlist=["Hotel Danieli"], signature_experiences=["Gondola ride"]),
        CityPicks(city="Florence", hotel_shortlist=["Hotel Brunelleschi"], signature_experiences=["Cooking class"])]})
    venice = for_city(exp, "Venice")
    assert venice.hotel.shortlist == ["Hotel Danieli"] and venice.activities.signature_experiences == ["Gondola ride"]
    assert for_city(exp, "Florence").hotel.shortlist == ["Hotel Brunelleschi"]
    assert for_city(exp, "Milan") is exp  # a city the strategist didn't cover keeps the plan's general strategy


def test_nice_amount():
    from travel_agent.replanner import nice_amount

    assert nice_amount(25730) == 26000 and nice_amount(1240) == 1250 and nice_amount(830) == 830


# ---------------------------------------------------------------- honest budgets

def test_impossible_budget_keeps_the_experience(rome_research, rome_contract, profile):
    """When flights + hotel alone exceed the budget, repairs only trim painless extras (never sights or meals)."""
    broke = rome_contract.model_copy(update={"budget": rome_contract.budget.model_copy(update={"amount": 300.0})})
    plan = build_plan(_ctx(broke, rome_research, profile))
    report = validate_plan(plan, broke, profile, rome_research, 0.05)
    assert report.result == "FAIL"
    knobs, log = repair(plan, report, PlanKnobs(), rome_research, 0, profile)
    steps = [s for s in knobs.budget_steps if not s.startswith(("hotel_tried", "floor_noted"))]
    assert all(s in PAINLESS_STEPS for s in steps)
    assert knobs.activity_cost_cap_local is None and knobs.density_delta == 0
    assert any("kept" in line for line in log)


# ---------------------------------------------------------------- critic guardrails

def test_critic_never_removes_an_icon(rome_research, rome_contract, profile):
    trip = TripState(trip_contract=rome_contract, research=rome_research, traveler_profile=profile)
    plan = build_plan(_ctx(rome_contract, rome_research, profile))
    trip.plans = {"balanced": plan}
    titles = [i.title for d in plan.days for i in d.items if i.kind == "activity"]
    by_name = {a.name: a for a in rome_research.attractions}
    icon = next(t for t in titles if t in by_name and fame(by_name[t]) >= 0.8)
    minor = next(t for t in titles if t in by_name and fame(by_name[t]) < 0.8)
    crit = critic.Critique(quality=70, verdict="ok", issues=[
        critic.Issue(severity="high", problem="swap icon", fix=Action(action="replace_item", text=icon)),
        critic.Issue(severity="high", problem="swap minor", fix=Action(action="replace_item", text=minor)),
    ])
    assert [a.text for _, a in critic.safe_fixes(trip, crit)] == [minor]


def test_refinement_that_loses_an_icon_is_detected(rome_research, rome_contract, profile):
    """The critic's self-check must see a lost landmark even when the TripScore goes up."""
    from travel_agent.workflow import _lost_icons

    trip = TripState(trip_contract=rome_contract, research=rome_research, traveler_profile=profile)
    before = build_plan(_ctx(rome_contract, rome_research, profile))
    icon = next(a for a in _city_icons(rome_research, 50) if any(i.place_id == a.id for d in before.days for i in d.items))
    after = build_plan(_ctx(rome_contract, rome_research, profile, exclude_ids=[icon.id]))
    # The removed icon is reported (a rebuilt plan may shuffle other stops too; each lost icon is listed).
    assert icon.name in _lost_icons(trip, before, after)
    assert _lost_icons(trip, before, before) == []


# ---------------------------------------------------------------- understanding -> routing

def test_plan_changes_are_not_lost_when_labelled_update_requirements(rome_contract):
    trip = TripState(trip_contract=rome_contract)
    echo = TurnInterpretation(intent="update_requirements", actions=[Action(action="increase_density")],
                              requirements=Requirements(destination="Rome", travel_style="very_active",
                                                        start_date=rome_contract.start_date.isoformat()))
    assert not _changes_trip_frame(trip, echo)  # echoed facts + a pace change: replan, don't restart
    moved = TurnInterpretation(intent="update_requirements",
                               requirements=Requirements(start_date=(rome_contract.start_date + timedelta(days=3)).isoformat()))
    assert _changes_trip_frame(trip, moved)


# ---------------------------------------------------------------- the trip agent decides

def _scripted_agent(monkeypatch, steps):
    """A fake model for the trip agent: returns the scripted Steps in order; other schemas get None (fallbacks)."""
    from travel_agent.agents import concierge

    script = iter(steps)

    async def parse(system, user, schema, max_tokens=16000, effort=None, timeout=None):
        return next(script) if schema is concierge.Step else None

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "parse", parse)
    monkeypatch.setattr(llm, "text", _none)


async def _none(*a, **k):
    return None


def test_agent_changes_the_plan_through_the_planner(monkeypatch):
    from travel_agent.agents import concierge
    from travel_agent.workflow import run_turn
    from tests.conftest import ROME_REQUEST

    rome, _ = anyio.run(run_turn, TripState(), ROME_REQUEST)  # model off: the classic pipeline builds the plan
    before = rome.traveler_profile.travel_style
    _scripted_agent(monkeypatch, [concierge.Step(
        thought="They want fuller days.", tool="change_plan",
        changes=concierge.PlanChange(summary="Faster pace", actions=[Action(action="increase_density")]))])
    trip, _ = anyio.run(run_turn, rome.model_copy(deep=True), "انا اكتيف وعايز اشوف حاجات اكتر")
    assert trip.traveler_profile.travel_style != before  # the pace changed and the plan was rebuilt
    assert trip.selected_plan.validation.result in ("PASS", "FAIL")  # validated by code, not by the model


def test_agent_answers_with_tools_without_touching_the_plan(monkeypatch):
    from travel_agent.agents import concierge
    from travel_agent.workflow import run_turn
    from tests.conftest import ROME_REQUEST

    rome, _ = anyio.run(run_turn, TripState(), ROME_REQUEST)
    _scripted_agent(monkeypatch, [
        concierge.Step(thought="Check the forecast.", tool="weather", args={"day": 2}),
        concierge.Step(thought="Done.", tool="final_answer", answer="Day 2 looks dry.", follow_ups=["Add a museum on day 3"]),
    ])
    trip, reply = anyio.run(run_turn, rome.model_copy(deep=True), "will it rain on day 2?")
    assert reply == "Day 2 looks dry."
    assert trip.metadata["suggestions"] == ["Add a museum on day 3"]
    assert trip.selected_plan.days == rome.selected_plan.days


def test_no_keyword_guessing_in_production(monkeypatch):
    """Without the model, production says so; it never falls back to keyword rules."""
    from travel_agent.config import settings
    from travel_agent.workflow import run_turn

    monkeypatch.setattr(settings, "rules_fallback", False)
    trip, reply = anyio.run(run_turn, TripState(), "عايز اروح روما يومين من 14/10 بـ 20 الف جنيه")
    assert "مش متاح" in reply and trip.trip_contract is None and not trip.plans


def test_agent_what_if_compares_then_applies_on_acceptance(monkeypatch):
    from travel_agent.agents import concierge
    from travel_agent.service import TravelAgentService
    from travel_agent.store import Store
    from tests.conftest import ROME_REQUEST

    svc = TravelAgentService(Store(":memory:"))
    trip, _ = anyio.run(svc.chat, ROME_REQUEST)  # model off: the offline harness builds the plan
    before = trip.trip_contract.budget.amount

    _scripted_agent(monkeypatch, [concierge.Step(
        thought="A what-if.", tool="change_plan",
        changes=concierge.PlanChange(actions=[Action(action="adjust_budget", amount=1000)], hypothetical=True))])
    trip, reply = anyio.run(svc.chat, "لو زودت الميزانية 1000 دولار هيحصل ايه؟", trip.trip_id)
    assert "ماتطبقتش" in reply and svc.get(trip.trip_id).trip_contract.budget.amount == before

    _scripted_agent(monkeypatch, [concierge.Step(thought="They accept.", tool="apply_what_if")])
    trip, reply = anyio.run(svc.chat, "تمام نفذها", trip.trip_id)
    assert svc.get(trip.trip_id).trip_contract.budget.amount == before + 1000
    assert "طبّقت" in reply


def test_chosen_flight_is_kept(rome_research, rome_contract, profile):
    pricey = max(rome_research.flights_outbound, key=lambda f: f.price_per_person.amount)
    plan = build_plan(_ctx(rome_contract, rome_research, profile, flight_pins=[pricey.id]))
    assert plan.outbound_flight.id == pricey.id


def test_off_topic_is_declined_not_answered(monkeypatch):
    """'Who is Messi?' gets a polite travel-only reply; the question itself is never answered."""
    from travel_agent import workflow

    async def interpret(*a, **k):
        return TurnInterpretation(intent="off_topic", source="test"), []

    monkeypatch.setattr(workflow, "interpret", interpret)
    monkeypatch.setattr(llm, "available", lambda: False)
    trip, reply = anyio.run(workflow.run_turn, TripState(), "مين هو ليو ميسي؟")
    assert "السفر" in reply and "ميسي" not in reply
    assert trip.trip_contract is None and not trip.plans


# ---------------------------------------------------------------- model wiring (Responses API)

class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def test_responses_api_text_and_json(monkeypatch):
    from travel_agent.config import settings

    monkeypatch.setattr(settings, "azure_endpoint", "https://x.services.ai.azure.com/openai/v1/responses")
    monkeypatch.setattr(settings, "azure_key", "k")
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_provider", "azure")
    sent = []

    async def fake_post(body):
        sent.append(body)
        text = '{"intent": "smalltalk"}' if "text" in body else "اهلا بيك"
        return _Resp({"status": "completed", "output": [
            {"type": "reasoning", "content": []},
            {"type": "message", "content": [{"type": "output_text", "text": text}]}]})

    monkeypatch.setattr(llm, "_azure_post", fake_post)
    assert anyio.run(llm.text, "sys", "hi") == "اهلا بيك"
    parsed = anyio.run(llm.parse, "sys", "hi", TurnInterpretation)
    assert parsed is not None and parsed.intent == "smalltalk"
    assert sent[0]["input"][0]["role"] == "system" and "reasoning" in sent[0]
    assert sent[1]["text"]["format"]["type"] == "json_schema"


def test_responses_api_incomplete_falls_back(monkeypatch):
    from travel_agent.config import settings

    monkeypatch.setattr(settings, "azure_endpoint", "https://x.services.ai.azure.com/openai/v1/responses")
    monkeypatch.setattr(settings, "azure_key", "k")
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_provider", "azure")

    async def fake_post(body):
        return _Resp({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": []})

    monkeypatch.setattr(llm, "_azure_post", fake_post)
    assert anyio.run(llm.text, "sys", "hi") is None


def test_a_stated_number_of_nights_is_absolute(rome_contract):
    """'Make it 3 nights' on a 6-night trip: 3 nights (4 days) - the code does the arithmetic, never the model."""
    from datetime import timedelta

    from travel_agent.replanner import apply_requirements

    trip = TripState(trip_contract=rome_contract)
    d = trip.draft
    d.start_date, d.end_date = rome_contract.start_date, rome_contract.end_date
    ask = Requirements(nights=3, end_date=rome_contract.end_date.isoformat())  # an echoed old end date must not win
    assert _changes_trip_frame(trip, TurnInterpretation(intent="update_requirements", requirements=ask))
    apply_requirements(trip, ask)
    assert d.end_date == d.start_date + timedelta(days=3) and d.duration_days == 4
