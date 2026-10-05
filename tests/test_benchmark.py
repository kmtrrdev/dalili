"""The evaluation harness itself: baselines and Dalili are judged by the same validators on the same data."""

import sys
from pathlib import Path

import anyio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

import harness  # noqa: E402
import planners  # noqa: E402


def test_planners_are_scored_on_identical_data():
    scs = anyio.run(harness.scenarios)
    assert [s.name for s in scs][:3] == ["rome-as-asked", "rome-active-pace", "rome-tight-budget"]
    sc = scs[0]
    rows = {}
    for name, fn in (("greedy", planners.plan_greedy), ("ortools", planners.plan_ortools),
                     ("dalili", planners.plan_dalili)):
        plan, ms = harness.timed(fn, sc)
        rows[name] = harness.evaluate(plan, sc, ms)
    rand, ms = harness.timed(planners.plan_random, sc, 0)
    rows["random"] = harness.evaluate(rand, sc, ms)
    for m in rows.values():
        assert {"hard_violations", "travel_minutes", "landmark_coverage", "tripscore"} <= set(m)
    # the full planner is at least as sound as the naive baselines on the same inputs
    assert rows["dalili"]["hard_violations"] <= min(rows[p]["hard_violations"] for p in ("random", "greedy"))
    assert rows["dalili"]["tripscore"] >= rows["random"]["tripscore"]
