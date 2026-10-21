"""Planner quality: experiences named for a time of day happen at that time, a far-away hotel never empties the days,
a day far from the researched restaurants still eats, and the hotel is paid only for the nights the flights need
(offline: the recorded Rome fixtures plus small hand-made places)."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from travel_agent.agents.strategist import DEFAULTS
from travel_agent.engine.knobs import PlanKnobs
from travel_agent.engine.planner import (
    MAX_HOTEL_KM_FROM_SIGHTS,
    NO_RESTAURANT_NOTE,
    PlanContext,
    _anchor_points,
    _is_evening,
    build_plan,
    select_core,
    visit_windows,
)
from travel_agent.engine.repair import repair
from travel_agent.engine.validators import validate_budget, validate_plan
from travel_agent.models import (
    DayPlan,
    GeoPoint,
    Metadata,
    Money,
    Place,
    TripPlan,
    ValidationReport,
    Violation,
)
from travel_agent.utils import WEEKDAYS, haversine_km, sun_times, to_min

CAIRO = ZoneInfo("Africa/Cairo")


def _ctx(contract, research, profile, mode="balanced", strategy=None, **knobs):
    return PlanContext(contract=contract, profile=profile, research=research, mode=mode, knobs=PlanKnobs(**knobs),
                       strategy=strategy)


def _place(pid: str, name: str, loc: GeoPoint, hours=("00:00", "23:59"), verified=True, minutes=60) -> Place:
    return Place(id=pid, name=name, kind="attraction", categories=["culture", "photography"], location=loc,
                 cost_per_person=Money(amount=0.0, price_type="known"), duration_minutes=minutes, indoor=True,
                 opening_hours={d: [list(hours)] for d in WEEKDAYS}, hours_verified=verified, popularity="must_see",
                 description="Tourist attraction", metadata=Metadata(source="test", provider="test"))


def _with(research, *places: Place):
    r = research.model_copy(deep=True)
    r.attractions += list(places)
    return r


def _center(research) -> GeoPoint:
    return GeoPoint(**research.destination_info["center"])


def _items(plan, pid):
    return [(d, i) for d in plan.days for i in d.items if i.place_id == pid]


# ---------------------------------------------------------------- 1) the time of day an experience is named for

def test_sunset_show_with_24h_hours_is_scheduled_at_sunset(rome_research, rome_contract, profile):
    show = _place("a_sunset_show", "Sunset Fire Dance on the Gianicolo", _center(rome_research))
    r = _with(rome_research, show)
    plan = build_plan(_ctx(rome_contract, r, profile, must_include=[show.id]))
    placed = _items(plan, show.id)
    assert len(placed) == 1, "the requested sunset show is in the plan"
    day, item = placed[0]
    tz = ZoneInfo(r.destination_info["timezone"])
    _, sunset = sun_times(show.location.lat, show.location.lon, day.date, tz)
    # The show spans the sunset (Rome, mid-October: ~18:30) - not 11:30 because the place is "open 24 hours".
    assert to_min(item.start) <= sunset - 10 and to_min(item.end) >= sunset + 10, (item.start, item.end, sunset)
    report = validate_plan(plan, rome_contract, profile, r, 0.05)
    assert not [v for v in report.errors if v.place_id == show.id], report.errors


def test_validator_flags_a_sunset_show_at_midday(rome_research, rome_contract, profile):
    show = _place("a_sunset_show", "Sunset Fire Dance on the Gianicolo", _center(rome_research))
    r = _with(rome_research, show)
    plan = build_plan(_ctx(rome_contract, r, profile, must_include=[show.id]))
    _, item = _items(plan, show.id)[0]
    item.start, item.end = "11:30", "12:30"
    report = validate_plan(plan, rome_contract, profile, r, 0.05)
    bad = [v for v in report.errors if v.check == "opening_hours" and v.place_id == show.id]
    assert bad and "sunset experience" in bad[0].message


def test_sunrise_trek_comes_before_breakfast_on_a_full_day(rome_research, rome_contract, profile):
    trek = _place("a_sunrise_trek", "Monte Mario Sunrise Trekking", _center(rome_research), minutes=90)
    r = _with(rome_research, trek)
    plan = build_plan(_ctx(rome_contract, r, profile, must_include=[trek.id]))
    placed = _items(plan, trek.id)
    assert len(placed) == 1
    day, item = placed[0]
    assert 1 < day.day < rome_contract.num_days  # a full day, not the arrival or the departure
    tz = ZoneInfo(r.destination_info["timezone"])
    sunrise, _ = sun_times(trek.location.lat, trek.location.lon, day.date, tz)
    assert to_min(item.start) <= sunrise - 10 and to_min(item.end) >= sunrise + 10, (item.start, item.end, sunrise)
    breakfast = next(i for i in day.items if i.meal_type == "breakfast")
    assert to_min(breakfast.start) >= to_min(item.end)
    report = validate_plan(plan, rome_contract, profile, r, 0.05)
    # Before the 08:30 wake-up by design: not a schedule error.
    assert not [v for v in report.errors if v.check in ("schedule", "opening_hours") and v.day == day.day], report.errors


def test_time_of_day_signal_yields_to_published_hours_and_ignores_restaurants(rome_research):
    tz = ZoneInfo(rome_research.destination_info["timezone"])
    d, c = date(2026, 10, 14), _center(rome_research)
    sunrise, _ = sun_times(c.lat, c.lon, d, tz)
    # Published hours that never reach dawn: "Sunrise" is the brand's name, its hours stand.
    brand = _place("a_brand", "Sunrise Water Park", c, hours=("10:00", "18:00"), verified=True)
    assert visit_windows(brand, d, tz) == [(600, 1080)]
    # Only assumed hours: the experience's own time wins.
    guessed = brand.model_copy(update={"hours_verified": False})
    (o, cl), = visit_windows(guessed, d, tz)
    assert o <= sunrise - 10 and cl >= sunrise + 10 and cl < 10 * 60
    # Hours that already describe it (06:00-08:00) are kept, narrowed to the dawn.
    early = _place("a_early", "Sunrise Point", c, hours=("06:00", "08:00"))
    (o, cl), = visit_windows(early, d, tz)
    assert 360 <= o and cl <= 480
    # A night market open "24 hours" is an evening plan, from 18:00; a restaurant's name says nothing.
    market = _place("a_night", "Trastevere Night Market", c)
    assert _is_evening(market) and visit_windows(market, d, tz)[0][0] == 18 * 60
    cafe = market.model_copy(update={"kind": "restaurant", "name": "Sunset Cafe"})
    assert visit_windows(cafe, d, tz) == [(0, 23 * 60 + 59)]
    # Not every word: "Nightingale Garden" and "nightlife" are not "night".
    assert not _is_evening(_place("a_bird", "Nightingale Garden", c, hours=("09:00", "18:00")))


# ---------------------------------------------------------------- 2) no empty days from a far hotel / far restaurants

def test_shortlisted_hotel_on_the_far_coast_is_not_picked_when_none_is_near(rome_research, rome_contract, profile):
    r = rome_research.model_copy(deep=True)
    strategy = DEFAULTS.experience.model_copy(deep=True)
    ctx = _ctx(rome_contract, r, profile, mode="experience", strategy=strategy)
    anchors = _anchor_points(ctx)
    lat, lon = sum(a.lat for a in anchors) / len(anchors), sum(a.lon for a in anchors) / len(anchors)
    # No hotel within 10 km of the sights (an island where every resort is out of town)...
    for i, h in enumerate(r.hotels):
        h.location = GeoPoint(lat=lat + 0.12 + 0.01 * i, lon=lon)
    # ... and one on the far coast, the best rated and cheapest - the strategist's only shortlisted hotel.
    far = r.hotels[0]
    far.location = GeoPoint(lat=lat + 0.6, lon=lon)
    far.rating, far.stars = 4.9, 5
    far.price_per_night = far.price_per_night.model_copy(update={"amount": min(h.price_per_night.amount for h in r.hotels) * 0.8})
    strategy.hotel.shortlist = [far.name]

    def avg(h):
        return sum(haversine_km(h.location.lat, h.location.lon, a.lat, a.lon) for a in anchors) / len(anchors)

    nearest = min(avg(h) for h in r.hotels)
    assert nearest > MAX_HOTEL_KM_FROM_SIGHTS and avg(far) > nearest + MAX_HOTEL_KM_FROM_SIGHTS  # the scenario
    _, _, hotel, _, _ = select_core(ctx)
    assert hotel.item.id != far.id and avg(hotel.item) <= nearest + MAX_HOTEL_KM_FROM_SIGHTS


def _closing_at(research, close: str):
    r = research.model_copy(deep=True)
    for p in r.restaurants:
        p.opening_hours = {d: [["07:00", close]] for d in WEEKDAYS}
    return r


def test_day_with_no_researched_restaurant_in_reach_still_has_dinner(rome_research, rome_contract, profile):
    r = _closing_at(rome_research, "17:00")  # every researched restaurant is closed by dinner time
    plan = build_plan(_ctx(rome_contract, r, profile))
    for d in plan.days:
        if 1 < d.day < rome_contract.num_days and not d.travel_day:
            dinner = next(i for i in d.items if i.meal_type == "dinner")
            assert dinner.title.startswith("Dinner near") and dinner.place_id is None
            assert dinner.cost.price_type == "estimated" and dinner.cost.amount > 0
            assert d.activity_count > 0  # the day keeps its sights
    report = validate_plan(plan, rome_contract, profile, r, 0.05)
    assert not [v for v in report.errors if "has no dinner" in v.message], report.errors


def test_city_without_any_dinner_restaurant_is_a_warning_not_a_reason_to_empty_days(rome_research, rome_contract,
                                                                                      profile):
    r = rome_research.model_copy(deep=True)
    for p in r.restaurants:
        p.meal_types = [m for m in p.meal_types if m != "dinner"]
    plan = build_plan(_ctx(rome_contract, r, profile))
    full = [d for d in plan.days if 1 < d.day < rome_contract.num_days and not d.travel_day]
    assert full and all(any(n.startswith(NO_RESTAURANT_NOTE) for n in d.notes) for d in full)
    report = validate_plan(plan, rome_contract, profile, r, 0.05)
    missing = [v for v in report.violations if "has no dinner" in v.message]
    assert missing and all(v.severity == "warning" for v in missing)
    _, log = repair(plan, report, PlanKnobs(), r, profile)
    assert not [m for m in log if m.startswith("Freed up time")]


def test_repair_frees_one_stop_per_crowded_day_and_never_empties_an_empty_one(rome_research, profile):
    d0 = date(2026, 10, 14)
    plan = TripPlan(days=[DayPlan(day=3, date=d0, title="Busy", activity_count=3),
                          DayPlan(day=4, date=d0 + timedelta(days=1), title="Free", activity_count=0)])
    errs = [Violation(check="schedule", severity="error", day=day, message=f"Day {day} has no {m} planned.")
            for day in (3, 4) for m in ("lunch", "dinner")]
    knobs, log = repair(plan, ValidationReport(result="FAIL", violations=errs), PlanKnobs(), rome_research, profile)
    # A missing lunch and a missing dinner are one crowded day: one stop less, not two.
    assert knobs.day_capacity_override == {3: 2}
    assert log == ["Freed up time on day 3 to keep the schedule feasible."]


# ---------------------------------------------------------------- 3) hotel nights follow the flights

def _shifted(f, dep: datetime, arr: datetime, price: float, fid: str):
    return f.model_copy(update={"id": fid, "depart_at": dep, "arrive_at": arr,
                                "price_per_person": Money(amount=price, currency=f.price_per_person.currency,
                                                          price_type="known")})


def _flights_plan(research, contract, profile, land: datetime, leave: datetime | None = None):
    r = research.model_copy(deep=True)
    o = min(r.flights_outbound, key=lambda f: f.price_per_person.amount)
    out = _shifted(o, land - timedelta(hours=14), land, o.price_per_person.amount, "fl_test_out")
    r.flights_outbound.append(out)
    pins = [out.id]
    if leave is not None:
        b = min(r.flights_return, key=lambda f: f.price_per_person.amount)
        back = _shifted(b, leave, leave + timedelta(hours=4), b.price_per_person.amount, "fl_test_back")
        r.flights_return.append(back)
        pins.append(back.id)
    return build_plan(_ctx(contract, r, profile, flight_pins=pins)), r


def _hotel_line(plan, research, contract, nights):
    m = plan.hotel.price_per_night
    return m.amount * research.fx_rates.get(m.currency.upper(), 1.0) * nights * contract.rooms


def test_next_day_evening_landing_does_not_pay_the_first_night(rome_research, rome_contract, profile):
    tz = ZoneInfo(rome_research.destination_info["timezone"])
    start = rome_contract.start_date
    plan, r = _flights_plan(rome_research, rome_contract, profile, datetime.combine(start + timedelta(days=1), time(22, 35), tz))
    assert plan.outbound_flight.id == "fl_test_out" and plan.days[0].travel_day
    assert (plan.hotel_check_in, plan.hotel_check_out) == (start + timedelta(days=1), rome_contract.end_date)
    assert abs(plan.budget.hotel - _hotel_line(plan, r, rome_contract, rome_contract.nights - 1)) < 0.05
    # The validator re-derives the same total.
    assert not [v for v in validate_budget(plan, rome_contract, r, 0.05) if "does not match" in v.message]


def test_small_hours_landing_keeps_the_night_before(rome_research, rome_contract, profile):
    tz = ZoneInfo(rome_research.destination_info["timezone"])
    start = rome_contract.start_date
    plan, r = _flights_plan(rome_research, rome_contract, profile, datetime.combine(start + timedelta(days=1), time(2, 0), tz))
    # At the hotel ~03:30: the room was booked from the night before ("tell the hotel you'll arrive late").
    assert plan.hotel_check_in == start
    check_in = next(i for d in plan.days for i in d.items if i.kind == "hotel" and i.title.startswith("Check in"))
    assert "booked from the night before" in check_in.notes
    assert abs(plan.budget.hotel - _hotel_line(plan, r, rome_contract, rome_contract.nights)) < 0.05


def test_flight_home_after_midnight_checks_out_the_day_before(rome_research, rome_contract, profile):
    tz = ZoneInfo(rome_research.destination_info["timezone"])
    start, end = rome_contract.start_date, rome_contract.end_date
    plan, r = _flights_plan(rome_research, rome_contract, profile, datetime.combine(start, time(11, 0), tz),
                            datetime.combine(end, time(1, 30), tz))
    assert plan.days[-1].travel_day  # the evening before is the airport run (trip_edges)
    assert (plan.hotel_check_in, plan.hotel_check_out) == (start, end - timedelta(days=1))
    assert abs(plan.budget.hotel - _hotel_line(plan, r, rome_contract, rome_contract.nights - 1)) < 0.05
    report = validate_plan(plan, rome_contract, profile, r, 0.05)
    assert not [v for v in report.errors if v.check == "budget" and "does not match" in v.message]


def test_flight_choice_counts_the_night_a_late_landing_saves(rome_research, rome_contract, profile):
    """select_core prices each flight pair with the nights it really needs, as compute_budget will."""
    r = rome_research.model_copy(deep=True)
    tz = ZoneInfo(r.destination_info["timezone"])
    start = rome_contract.start_date
    for h in r.hotels:  # a pricey city: one night is ~10% of the trip
        h.price_per_night = h.price_per_night.model_copy(update={"amount": 1000.0})
    night_user = 1000.0 * r.fx_rates.get(r.hotels[0].price_per_night.currency.upper(), 1.0)
    o = min(r.flights_outbound, key=lambda f: f.price_per_person.amount)
    fx = r.fx_rates.get(o.price_per_person.currency.upper(), 1.0)
    same_day = _shifted(o, datetime.combine(start, time(8, 0), CAIRO), datetime.combine(start, time(12, 0), tz),
                        o.price_per_person.amount, "fl_same_day")
    # Dearer by 40% of a night for the group, but it saves the whole first night.
    extra = 0.4 * night_user * rome_contract.rooms / rome_contract.travelers / fx
    next_day = _shifted(o, datetime.combine(start, time(8, 0), CAIRO),
                        datetime.combine(start + timedelta(days=1), time(22, 35), tz),
                        o.price_per_person.amount + extra, "fl_next_day")
    r.flights_outbound, r.round_trips = [same_day, next_day], []
    o_pick, *_ = select_core(_ctx(rome_contract, r, profile, mode="budget"))
    assert o_pick.item.id == "fl_next_day"


def test_a_sunset_show_alone_in_its_day_is_kept():
    # The day starts at 09:15 and the show only fits around sunset: waiting all afternoon beats dropping it.
    from travel_agent.engine.optimizer import Stop, optimize_day
    from travel_agent.models import GeoPoint

    show = Stop(id="show", location=GeoPoint(lat=-8.83, lon=115.09), duration=60, windows=[(1046, 1141)], priority=0.8)
    res = optimize_day(GeoPoint(lat=-8.5, lon=115.26), [show], 555, 22 * 60, lambda a, b: 60)
    assert [s.id for s, _ in res.ordered] == ["show"] and res.ordered[0][1] >= 1046


def test_a_show_known_to_play_at_sunset_is_timed_even_without_the_word():
    # "Kecak Uluwatu": published hours 07:00-20:00, nothing in the name - the research tagged it best_time="sunset".
    from datetime import date
    from zoneinfo import ZoneInfo

    from travel_agent.engine.planner import visit_windows
    from travel_agent.models import GeoPoint, Metadata, Money, Place

    hours = {d: [["07:00", "20:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    show = Place(id="a_kecak", name="Kecak Uluwatu", kind="attraction", location=GeoPoint(lat=-8.83, lon=115.09),
                 opening_hours=hours, hours_verified=True, duration_minutes=60, best_time="sunset",
                 cost_per_person=Money(amount=150000, currency="IDR", price_type="known"),
                 metadata=Metadata(source="test", provider="test"))
    (start, end), = visit_windows(show, date(2026, 11, 3), ZoneInfo("Asia/Makassar"))
    assert 17 * 60 <= start and end <= 19 * 60 + 30  # around the 18:15 sunset, not at midday
    plain = show.model_copy(update={"best_time": None})
    assert visit_windows(plain, date(2026, 11, 3), ZoneInfo("Asia/Makassar")) == [(7 * 60, 20 * 60)]
