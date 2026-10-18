"""Per-day route optimization.

Given the hotel, the day's candidate stops (with durations, opening-hour windows
and priorities) and a travel-time function, find the visiting order that fits
the time windows, keeps a lunch break, minimises travel, and drops the
lowest-priority stops when not everything fits.

Solved as a single-vehicle routing problem with time windows (OR-Tools),
with a greedy fallback when OR-Tools is unavailable or finds no solution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from ..models import GeoPoint

log = logging.getLogger(__name__)

try:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    HAS_ORTOOLS = True
except ImportError:  # pragma: no cover
    HAS_ORTOOLS = False


@dataclass
class Stop:
    id: str
    location: GeoPoint
    duration: int
    windows: list[tuple[int, int]]
    priority: float = 0.5


@dataclass
class OrderResult:
    ordered: list[tuple[Stop, int]] = field(default_factory=list)  # (stop, service start minute)
    dropped: list[Stop] = field(default_factory=list)
    lunch_start: int | None = None
    solver: str = "none"


LUNCH_DURATION = 75


def _feasible_starts(stop: Stop, day_start: int, day_end: int) -> list[tuple[int, int]]:
    out = []
    for o, c in stop.windows:
        lo, hi = max(o, day_start), min(c, day_end) - stop.duration
        if lo <= hi:
            out.append((lo, hi))
    return sorted(out)


def optimize_day(depot: GeoPoint, stops: list[Stop], day_start: int, day_end: int,
                 travel: Callable[[GeoPoint, GeoPoint], int], lunch_window: tuple[int, int] | None = (12 * 60, 13 * 60 + 45),
                 time_limit_s: float = 1.0) -> OrderResult:
    feasible = [s for s in stops if _feasible_starts(s, day_start, day_end)]
    dropped = [s for s in stops if s not in feasible]
    if lunch_window and day_start > lunch_window[1]:
        lunch_window = None
    if not feasible:
        return OrderResult(dropped=dropped, lunch_start=lunch_window[0] if lunch_window else None, solver="empty")
    if HAS_ORTOOLS:
        try:
            res = _solve_ortools(depot, feasible, day_start, day_end, travel, lunch_window, time_limit_s)
            if res is not None:
                res.dropped += dropped
                return res
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("OR-Tools failed, using greedy ordering: %s", exc)
    res = _solve_greedy(depot, feasible, day_start, day_end, travel, lunch_window)
    res.dropped += dropped
    return res


def _solve_ortools(depot, stops, day_start, day_end, travel, lunch_window, time_limit_s) -> OrderResult | None:
    n = len(stops) + 1
    locs = [depot] + [s.location for s in stops]
    service = [0] + [s.duration for s in stops]
    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j and j != 0:  # open route: returning to the depot is free (evening is planned separately)
                matrix[i][j] = travel(locs[i], locs[j])

    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def transit(from_index, to_index):
        i, j = manager.IndexToNode(from_index), manager.IndexToNode(to_index)
        return matrix[i][j] + service[i]

    cb = routing.RegisterTransitCallback(transit)
    routing.SetArcCostEvaluatorOfAllVehicles(cb)
    # Waiting is allowed up to the whole day: a sunset show that is the day's only stop starts hours after the day
    # does (a 4 h cap dropped it and left the day empty). The span cost below still keeps ordinary days compact.
    routing.AddDimension(cb, 24 * 60, 24 * 60, False, "Time")
    time_dim = routing.GetDimensionOrDie("Time")
    # Penalise the day's span so the schedule is compact (no idle mornings).
    time_dim.SetSpanCostCoefficientForAllVehicles(1)

    for node, stop in enumerate(stops, start=1):
        idx = manager.NodeToIndex(node)
        ranges = _feasible_starts(stop, day_start, day_end)
        cumul = time_dim.CumulVar(idx)
        cumul.SetRange(ranges[0][0], ranges[-1][1])
        for (_, hi), (lo_next, _) in zip(ranges, ranges[1:]):
            if hi + 1 <= lo_next - 1:
                cumul.RemoveInterval(hi + 1, lo_next - 1)
        routing.AddDisjunction([idx], int(10_000 * (0.3 + max(stop.priority, 0.0))))

    start = routing.Start(0)
    end = routing.End(0)
    time_dim.CumulVar(start).SetRange(day_start, day_start)
    time_dim.CumulVar(end).SetRange(day_start, day_end)

    brk = None
    if lunch_window:
        node_visit_transit = [0] * routing.Size()
        for index in range(routing.Size()):
            node_visit_transit[index] = service[manager.IndexToNode(index)]
        brk = routing.solver().FixedDurationIntervalVar(lunch_window[0], lunch_window[1], LUNCH_DURATION, False, "lunch")
        time_dim.SetBreakIntervalsOfVehicle([brk], 0, node_visit_transit)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    # Days have < 10 stops: greedy descent reaches a local optimum in milliseconds;
    # guided local search would always run to the time limit.
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GREEDY_DESCENT
    params.time_limit.FromMilliseconds(int(time_limit_s * 1000))
    solution = routing.SolveWithParameters(params)
    if solution is None:
        return None

    ordered = []
    index = routing.Start(0)
    visited = set()
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        if node != 0:
            ordered.append((stops[node - 1], solution.Min(time_dim.CumulVar(index))))
            visited.add(node)
        index = solution.Value(routing.NextVar(index))
    dropped = [s for k, s in enumerate(stops, start=1) if k not in visited]

    lunch_start = None
    if brk is not None:
        intervals = solution.IntervalVarContainer()
        for i in range(intervals.Size()):
            el = intervals.Element(i)
            if el.Var().Name() == "lunch" and el.PerformedValue():
                lunch_start = el.StartValue()
        if lunch_start is None:
            lunch_start = lunch_window[0]
    return OrderResult(ordered=ordered, dropped=dropped, lunch_start=lunch_start, solver="ortools")


def _solve_greedy(depot, stops, day_start, day_end, travel, lunch_window) -> OrderResult:
    t, here = day_start, depot
    remaining = sorted(stops, key=lambda s: -s.priority)
    ordered, lunch_start = [], None
    while remaining:
        if lunch_window and lunch_start is None and t >= lunch_window[0]:
            lunch_start = min(t, lunch_window[1])
            t = lunch_start + LUNCH_DURATION
        best, best_key = None, None
        for s in remaining:
            arrive = t + travel(here, s.location)
            start = next((max(arrive, lo) for lo, hi in _feasible_starts(s, day_start, day_end) if max(arrive, lo) <= hi), None)
            if start is None:
                continue
            key = (start - t) - 60 * s.priority
            if best_key is None or key < best_key:
                best, best_key = (s, start), key
        if best is None:
            break
        s, start = best
        if lunch_window and lunch_start is None and start + s.duration > lunch_window[1] + LUNCH_DURATION and start >= lunch_window[0] - 30:
            lunch_start = max(t, lunch_window[0])
            t = lunch_start + LUNCH_DURATION
            continue
        ordered.append((s, start))
        remaining.remove(s)
        t, here = start + s.duration, s.location
    if lunch_window and lunch_start is None:
        lunch_start = max(lunch_window[0], min(t, lunch_window[1]))
    return OrderResult(ordered=ordered, dropped=remaining, lunch_start=lunch_start, solver="greedy")
