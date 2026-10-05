"""Planner benchmark: random vs greedy vs OR-Tools vs LLM vs Dalili, on identical scenarios and data.

Every planner gets the same researched flights, hotels, places, opening hours, prices and travel times, and the same
number of activities per day (from the traveller's pace). Plans are then judged by the same deterministic validators
and scorer: hard violations, travel time and distance, cost, landmark coverage, preference fit, compute time.

  random   - random hotel, flights and sights; random order
  greedy   - best-scored hotel, cheapest same-day flights, top-scored sights round-robin over days, nearest-neighbour
  ortools  - greedy's choices, each day ordered and timed by the OR-Tools time-window router (Dalili's optimizer)
  llm      - the model picks the hotel, flights and each day's sights from the same candidate lists (needs --llm)
  dalili   - the full planner: joint flight+hotel choice, day assignment, OR-Tools days, validators + repair loop

Usage:  python eval/benchmark.py [--llm] [--seeds 5]
Writes eval/benchmark_results.json and eval/BENCHMARK.md. Results come only from these runs.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--llm", action="store_true", help="include the LLM planner (needs Azure/Anthropic keys)")
parser.add_argument("--seeds", type=int, default=5, help="random baseline repetitions per scenario")
ARGS = parser.parse_args()
harness.setup_env(ARGS.llm)

import anyio  # noqa: E402

from planners import plan_dalili, plan_greedy, plan_llm, plan_ortools, plan_random  # noqa: E402

OUT = Path(__file__).resolve().parent


async def main():
    scs = await harness.scenarios()
    rows = []
    for sc in scs:
        for seed in range(ARGS.seeds):
            plan, ms = harness.timed(plan_random, sc, seed)
            rows.append({"scenario": sc.name, "planner": "random", "seed": seed, **harness.evaluate(plan, sc, ms)})
        for name, fn in (("greedy", plan_greedy), ("ortools", plan_ortools), ("dalili", plan_dalili)):
            plan, ms = harness.timed(fn, sc)
            rows.append({"scenario": sc.name, "planner": name, **harness.evaluate(plan, sc, ms)})
        if ARGS.llm:
            t0 = time.perf_counter()
            res = await plan_llm(sc)
            ms = (time.perf_counter() - t0) * 1000
            if res:
                plan, invented = res
                rows.append({"scenario": sc.name, "planner": "llm",
                             **harness.evaluate(plan, sc, ms, {"invented_ids": invented})})
        print(f"done {sc.name}", flush=True)
    keys = ["hard_violations", "feasible", "travel_minutes", "travel_km", "km_per_hop", "cost", "within_budget",
            "activities", "landmark_coverage", "preference_satisfaction", "tripscore", "quality", "requirements_met",
            "compute_ms"]
    planners = [p for p in ("random", "greedy", "ortools", "llm", "dalili") if any(r["planner"] == p for r in rows)]
    summary = {p: harness.summarize([r for r in rows if r["planner"] == p], keys) for p in planners}
    (OUT / "benchmark_results.json").write_text(json.dumps({"generated": harness.tz_now(), "scenarios": [s.name for s in scs],
                                                            "summary": summary, "rows": rows}, indent=2, default=str))
    lines = ["# Planner benchmark", "", f"Generated {harness.tz_now()} from `python eval/benchmark.py"
             f"{' --llm' if ARGS.llm else ''}` - {len(scs)} scenarios on recorded real data "
             f"(random: {ARGS.seeds} seeds each). Means over scenarios.", "",
             "| planner | hard violations | feasible | travel min | km/hop | cost | within budget | landmarks | "
             "pref. fit | TripScore | compute ms |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for p in planners:
        s = summary[p]
        lines.append(f"| {p} | {s.get('hard_violations')} | {s.get('feasible')} | {s.get('travel_minutes')} | "
                     f"{s.get('km_per_hop')} | {s.get('cost')} | {s.get('within_budget')} | {s.get('landmark_coverage')} | "
                     f"{s.get('preference_satisfaction')} | {s.get('tripscore')} | {s.get('compute_ms')} |")
    (OUT / "BENCHMARK.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    anyio.run(main)
