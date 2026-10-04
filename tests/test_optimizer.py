from travel_agent.engine.optimizer import LUNCH_DURATION, Stop, _solve_greedy, optimize_day
from travel_agent.models import GeoPoint

HOME = GeoPoint(lat=41.90, lon=12.48)


def travel(a, b):
    return 15 if (a.lat, a.lon) != (b.lat, b.lon) else 0


def pt(i):
    return GeoPoint(lat=41.90 + i * 0.005, lon=12.48)


def check_feasible(res, day_start, day_end):
    t = day_start
    for stop, start in res.ordered:
        assert start >= t, "stops must not overlap"
        assert any(o <= start and start + stop.duration <= c for o, c in stop.windows), "must respect opening hours"
        assert start + stop.duration <= day_end
        t = start + stop.duration
    if res.lunch_start is not None:
        for stop, start in res.ordered:
            assert start + stop.duration <= res.lunch_start or start >= res.lunch_start + LUNCH_DURATION, "no activity during lunch"


def test_respects_time_windows_and_lunch():
    stops = [Stop("a", pt(1), 120, [(540, 1080)], 0.9), Stop("b", pt(2), 90, [(840, 1080)], 0.8),
             Stop("c", pt(3), 60, [(600, 720)], 0.7)]
    res = optimize_day(HOME, stops, 540, 1110, travel)
    assert res.solver == "ortools"
    assert {s.id for s, _ in res.ordered} == {"a", "b", "c"}
    check_feasible(res, 540, 1110)


def test_drops_lowest_priority_when_overbooked():
    stops = [Stop(f"s{i}", pt(i), 150, [(540, 1080)], 0.9 - i * 0.2) for i in range(4)]
    res = optimize_day(HOME, stops, 540, 1080, travel)
    assert res.dropped, "four 150-minute stops cannot fit"
    kept = {s.id for s, _ in res.ordered}
    assert "s0" in kept, "highest priority stop is kept"
    check_feasible(res, 540, 1080)


def test_closed_stop_is_dropped_up_front():
    res = optimize_day(HOME, [Stop("closed", pt(1), 60, [], 1.0), Stop("open", pt(2), 60, [(540, 1000)], 0.5)], 540, 1080, travel)
    assert [s.id for s, _ in res.ordered] == ["open"]
    assert [s.id for s in res.dropped] == ["closed"]


def test_greedy_fallback_is_feasible():
    stops = [Stop("a", pt(1), 120, [(540, 1080)], 0.9), Stop("b", pt(2), 90, [(840, 1080)], 0.8)]
    res = _solve_greedy(HOME, stops, 540, 1110, travel, (720, 825))
    assert res.solver == "greedy" and len(res.ordered) == 2
    check_feasible(res, 540, 1110)
