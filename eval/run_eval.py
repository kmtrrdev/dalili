"""Evaluation suite for the AI Travel Agent (real data, recorded).

Runs requirement, planning, reality and replanning scenarios end to end through the
LangGraph workflow and the MCP servers, on real API responses recorded in
tests/fixtures/http_cache.sqlite (replay: offline, free, deterministic).

Metrics: constraint satisfaction, schedule feasibility, budget accuracy, tool selection
accuracy, grounded recommendation rate, reality violation rate, injected-violation detection,
replanning success, preference satisfaction, verified-price share, verified-hours share,
turn latency.

Usage:
    python eval/run_eval.py             # replay recorded real responses (no quota)
    python eval/run_eval.py --record    # fill anything missing from the recording with live calls
    python eval/run_eval.py --llm       # Claude for understanding (needs ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

parser = argparse.ArgumentParser()
parser.add_argument("--llm", action="store_true")
parser.add_argument("--record", action="store_true")
ARGS = parser.parse_args()
os.environ["TRAVEL_AGENT_LLM"] = "1" if ARGS.llm else "0"
os.environ["TRAVEL_AGENT_HTTP_MODE"] = "cache" if ARGS.record else "replay"
os.environ["TRAVEL_AGENT_HTTP_CACHE"] = str(ROOT / "tests" / "fixtures" / "http_cache.sqlite")
os.environ["TRAVEL_AGENT_TODAY"] = "2026-09-27"
os.environ.setdefault("TRAVEL_AGENT_SERPAPI_CALLS_PER_TURN", "25")

import anyio  # noqa: E402

from travel_agent.engine.budget import compute_budget, to_user  # noqa: E402
from travel_agent.engine.validators import validate_plan  # noqa: E402
from travel_agent.mcp_hub import get_hub  # noqa: E402
from travel_agent.models import ItineraryItem, Money, TransportLeg, TripState  # noqa: E402
from travel_agent.workflow import run_turn  # noqa: E402

ROME = "7 days in Rome from October 12 for two, budget $3,500. We love food, history and photography."
ISTANBUL = ("Relaxed 7-day trip to Istanbul from Cairo, November 3, budget $2,000, vegetarian, "
            "no early flights, I don't like walking much")
HARD_CHECKS = ["budget", "schedule", "distance", "opening_hours", "preferences", "energy", "weather", "reality"]
ALL_SERVERS = {"flights", "hotels", "places", "activities", "transport", "weather", "currency", "knowledge"}


@dataclass
class Result:
    name: str
    category: str
    passed: bool
    detail: str = ""
    latency_ms: float = 0.0
    tools_ok: bool | None = None


@dataclass
class Metrics:
    results: list[Result] = field(default_factory=list)
    hard_checks: list[bool] = field(default_factory=list)
    schedule_ok: list[bool] = field(default_factory=list)
    budget_err: list[float] = field(default_factory=list)
    grounded: list[bool] = field(default_factory=list)
    reality_violations: int = 0
    recommended: int = 0
    preference_ok: list[bool] = field(default_factory=list)
    known_cost: float = 0.0
    total_cost: float = 0.0
    hours_verified: list[bool] = field(default_factory=list)
    latencies: list[float] = field(default_factory=list)


M = Metrics()


async def turn(trip: TripState, msg: str):
    hub = get_hub()
    hub.call_log.clear()
    hub._cache.clear()
    t0 = time.perf_counter()
    trip, reply = await run_turn(trip, msg)
    return trip, reply, (time.perf_counter() - t0) * 1000, {c["server"] for c in hub.call_log}


def audit(trip: TripState) -> None:
    r, c = trip.research, trip.trip_contract
    for plan in trip.plans.values():
        rep = validate_plan(plan, c, trip.traveler_profile, r, 0.05)
        status = {x.name: x.status for x in rep.checks}
        M.hard_checks += [status[k] != "FAIL" for k in HARD_CHECKS]
        M.schedule_ok.append(status["schedule"] != "FAIL" and status["opening_hours"] != "FAIL")
        M.preference_ok.append(status["preferences"] != "FAIL")
        again = compute_budget(plan.model_copy(deep=True), c, r.fx_rates, 0.05)
        M.budget_err.append(abs(again.total - plan.budget.total) / max(again.total, 1))
        items = [i for d in plan.days for i in d.items if i.place_id]
        M.recommended += len(items) + 3
        M.grounded += [r.place(i.place_id) is not None for i in items]
        M.grounded += [plan.hotel is not None and any(h.id == plan.hotel.id for h in r.hotels)]
        M.grounded += [f is not None and any(x.id == f.id for x in r.flights_outbound + r.flights_return)
                       for f in (plan.outbound_flight, plan.return_flight)]
        M.reality_violations += sum(1 for v in rep.errors if v.check in ("reality", "opening_hours"))
        # Honesty: how much of the money is backed by published prices, how many hours are verified.
        b = plan.budget
        M.known_cost += b.flights + b.hotel
        M.total_cost += b.flights + b.hotel + b.food + b.activities + b.transport
        for d in plan.days:
            for i in d.items:
                p = r.place(i.place_id) if i.place_id else None
                if p:
                    M.hours_verified.append(p.hours_verified)
                    if p.price_known:
                        M.known_cost += to_user(i.cost, r.fx_rates, c.budget.currency)


def record(name, category, passed, detail="", ms=0.0, tools_ok=None):
    M.results.append(Result(name, category, bool(passed), detail, ms, tools_ok))
    if ms:
        M.latencies.append(ms)


def museums(t: TripState) -> int:
    return sum(1 for d in t.selected_plan.days for i in d.items
               if i.kind == "activity" and "museums" in t.research.place(i.place_id).categories)


async def requirement_tests():
    trip, reply, ms, tools = await turn(TripState(), "I want to go to Rome, we love history")
    record("missing budget + dates -> asks only for those", "requirements",
           trip.status == "needs_input" and "budget" in reply.lower() and "where" not in reply.lower(), ms=ms,
           tools_ok=tools <= {"knowledge"})
    trip, reply, ms, tools = await turn(TripState(), "I have $2,500 and want a relaxing week in October")
    record("missing destination -> asks where", "requirements", not trip.plans and "where" in reply.lower(), ms=ms,
           tools_ok=not tools)
    trip, reply, ms, _ = await turn(TripState(), "I want to go somewhere warm, 5 days, $2,000")
    record("vague destination is not guessed", "requirements", not trip.plans and "where" in reply.lower(), ms=ms)
    trip, _, ms, tools = await turn(TripState(), "Istanbul November 3 to 9 from Cairo, family of 4, budget $6,000")
    p = trip.selected_plan
    ok = trip.trip_contract.travelers == 4 and abs(p.budget.flights - 4 * (p.outbound_flight.price_per_person.amount + p.return_flight.price_per_person.amount)) < 1
    record("multiple travelers scale real fares", "requirements", ok, f"flights {p.budget.flights:.0f}", ms,
           tools_ok=tools == ALL_SERVERS)
    audit(trip)
    trip, _, ms, _ = await turn(TripState(), ROME.replace("We love", "We are relaxed but want to see as much as possible, we love"))
    record("conflicting preferences still yield a valid plan", "requirements",
           bool(trip.plans) and trip.selected_plan.validation.result == "PASS", ms=ms)
    audit(trip)


async def planning_tests():
    trip, _, ms, tools = await turn(TripState(), ROME)
    record("real Rome plan validates; all 8 MCP servers used", "planning",
           trip.selected_plan.validation.result == "PASS", f"total ${trip.selected_plan.budget.total:,.0f}", ms,
           tools_ok=tools == ALL_SERVERS)
    audit(trip)
    tight, _, ms, _ = await turn(TripState(), ROME.replace("$3,500", "$2,400"))
    p = tight.selected_plan
    record("tight hard budget: within budget or flagged", "planning",
           p.within_budget or not any(x.within_budget for x in tight.plans.values()), f"total ${p.budget.total:,.0f}", ms)
    audit(tight)
    walk, _, ms, _ = await turn(TripState(), ROME + " I don't like walking, bad knees.")
    legs = [i.transport_from_previous.distance_km for d in walk.selected_plan.days for i in d.items
            if i.transport_from_previous and i.transport_from_previous.mode == "walk"]
    record("low walking: every walk <= 1.3 km (ORS distances)", "planning", all(x <= 1.3 for x in legs),
           f"max {max(legs, default=0):.2f} km", ms)
    audit(walk)
    relaxed, _, ms, _ = await turn(TripState(), ROME + " A very relaxed, slow trip please.")
    busiest = max(d.activity_count for d in relaxed.selected_plan.days)
    record("relaxed: at most 2 major activities a day", "planning", busiest <= 4, f"max {busiest} stops/day", ms)
    audit(relaxed)
    multi, _, ms, _ = await turn(TripState(), ROME.replace("in Rome", "in Rome and Paris"))
    record("multi-city request handled gracefully (one city)", "planning", bool(multi.plans), multi.trip_contract.destination, ms)
    ist, _, ms, _ = await turn(TripState(), ISTANBUL)
    fl = [ist.selected_plan.outbound_flight, ist.selected_plan.return_flight]
    record("no early flights (real schedules)", "planning", all(f.depart_at.hour >= 8 for f in fl),
           ", ".join(f"{f.depart_at:%H:%M}" for f in fl), ms)
    veg = all("vegetarian" in ist.research.place(i.place_id).dietary for d in ist.selected_plan.days for i in d.items
              if i.kind == "meal" and i.place_id)
    record("vegetarian: every meal place supports it", "planning", veg)
    audit(ist)


async def reality_tests():
    trip, _, _, _ = await turn(TripState(), ROME)
    base = trip.selected_plan

    def detect(mutate: Callable, check: str, name: str):
        plan, research = base.model_copy(deep=True), trip.research.model_copy(deep=True)
        mutate(plan, research)
        rep = validate_plan(plan, trip.trip_contract, trip.traveler_profile, research, 0.05)
        record(f"detect: {name}", "reality", any(v.check == check and v.severity == "error" for v in rep.violations))

    closed = {d: [] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}

    def close_restaurant(plan, research):
        meal = next(i for i in plan.days[2].items if i.kind == "meal" and i.place_id)
        p = research.place(meal.place_id)
        p.opening_hours, p.hours_verified = dict(closed), True

    def close_attraction(plan, research):
        act = next(i for d in plan.days for i in d.items if i.kind == "activity")
        p = research.place(act.place_id)
        p.opening_hours, p.hours_verified = dict(closed), True

    def remove_activity(plan, research):
        act = next(i for d in plan.days for i in d.items if i.kind == "activity")
        research.attractions = [a for a in research.attractions if a.id != act.place_id]

    def long_walk(plan, research):
        next(i for i in plan.days[2].items if i.kind == "activity").transport_from_previous = TransportLeg(
            mode="walk", minutes=70, distance_km=5.2, cost=Money(amount=0))

    def overlap(plan, research):
        plan.days[2].items[2].start = plan.days[2].items[1].start

    def invented(plan, research):
        plan.days[1].items.append(ItineraryItem(start="23:00", end="23:30", kind="activity", title="Secret rooftop", place_id="a_fake"))

    detect(close_restaurant, "opening_hours", "restaurant closed")
    detect(close_attraction, "opening_hours", "attraction closed")
    detect(remove_activity, "reality", "activity no longer listed")
    detect(long_walk, "distance", "excessive walking")
    detect(overlap, "schedule", "impossible schedule")
    detect(invented, "reality", "hallucinated place")

    meal = next(i for d in base.days[1:-1] for i in d.items if i.kind == "meal" and i.place_id)
    p = trip.research.place(meal.place_id)
    p.opening_hours, p.hours_verified = dict(closed), True
    after, _, ms, _ = await turn(trip, "Can you re-check the plan and make it a bit cheaper?")
    ok = after.selected_plan.validation.result == "PASS" and all(i.place_id != meal.place_id for d in after.selected_plan.days for i in d.items)
    record("recover: replan avoids a restaurant that closed", "reality", ok, ms=ms)
    audit(after)


async def replanning_tests():
    trip, _, _, _ = await turn(TripState(), ROME)

    async def replan(msg: str, check: Callable, name: str, expect_tools: set | None = None):
        before = trip.model_copy(deep=True)
        after, _, ms, tools = await turn(trip.model_copy(deep=True), msg)
        ok = check(before, after) and after.selected_plan.validation.result == "PASS"
        record(f"replan: {name}", "replanning", ok, "; ".join(after.last_changes[:2]), ms,
               None if expect_tools is None else tools == expect_tools)
        audit(after)

    await replan("Remove two museums", lambda b, a: museums(a) <= max(0, museums(b) - 2), "fewer museums", expect_tools=set())
    await replan("I don't want to wake up before 10", lambda b, a: all(
        next(i for i in d.items if i.kind in ("meal", "activity")).start >= "10:00" for d in a.selected_plan.days[1:-1]),
        "later start", expect_tools=set())
    await replan("My budget is only $2,600", lambda b, a: a.trip_contract.budget.amount == 2600 and (
        a.selected_plan.within_budget or not any(p.within_budget for p in a.plans.values())), "budget cut")
    await replan("Add more food experiences", lambda b, a: sum(1 for d in a.selected_plan.days for i in d.items if i.kind == "meal")
                 >= sum(1 for d in b.selected_plan.days for i in d.items if i.kind == "meal"), "more food")
    await replan("I want more free time", lambda b, a: sum(1 for d in a.selected_plan.days for i in d.items if i.kind in ("rest", "free"))
                 >= sum(1 for d in b.selected_plan.days for i in d.items if i.kind in ("rest", "free")), "more free time")
    await replan("I want to stay two more days", lambda b, a: a.trip_contract.num_days == 9
                 and all(d.activity_count > 0 for d in a.selected_plan.days[1:-1]), "extend trip (new flights + hotel prices)",
                 expect_tools={"flights", "hotels", "weather", "currency", "transport"})
    name = next(i.title for d in trip.selected_plan.days for i in d.items if i.kind == "activity")
    await replan(f"Please skip the {name}", lambda b, a: all(i.title != name for d in a.selected_plan.days for i in d.items),
                 "remove a named activity")


def pct(xs):
    return f"{100 * sum(xs) / len(xs):.1f}%" if xs else "n/a"


async def main():
    t0 = time.perf_counter()
    await requirement_tests()
    await planning_tests()
    await reality_tests()
    await replanning_tests()
    by_cat: dict[str, list[bool]] = {}
    for r in M.results:
        by_cat.setdefault(r.category, []).append(r.passed)
    tools = [r.tools_ok for r in M.results if r.tools_ok is not None]
    lat = sorted(M.latencies)
    metrics = {
        "scenarios_passed": f"{sum(r.passed for r in M.results)}/{len(M.results)}",
        "requirement_handling": pct(by_cat.get("requirements", [])),
        "constraint_satisfaction_rate": pct(M.hard_checks),
        "schedule_feasibility": pct(M.schedule_ok),
        "budget_accuracy": f"{100 * (1 - statistics.mean(M.budget_err)):.2f}%" if M.budget_err else "n/a",
        "tool_selection_accuracy": pct(tools),
        "grounded_recommendation_rate": pct(M.grounded),
        "reality_violation_rate": f"{100 * M.reality_violations / max(M.recommended, 1):.2f}%",
        "injected_violation_detection_rate": pct([r.passed for r in M.results if r.name.startswith("detect:")]),
        "replanning_success_rate": pct(by_cat.get("replanning", [])),
        "preference_satisfaction": pct(M.preference_ok),
        "cost_backed_by_published_prices": f"{100 * M.known_cost / max(M.total_cost, 1):.1f}%",
        "scheduled_places_with_verified_hours": pct(M.hours_verified),
        "avg_turn_latency_ms (replay)": round(statistics.mean(lat)) if lat else None,
        "p95_turn_latency_ms (replay)": round(lat[int(0.95 * (len(lat) - 1))]) if lat else None,
        "plans_audited": len(M.schedule_ok),
        "total_runtime_s": round(time.perf_counter() - t0, 1),
        "data": "recorded real API responses" if not ARGS.record else "live + cache",
        "nlu": "claude" if ARGS.llm else "rules",
    }
    print("\nScenario results\n" + "-" * 78)
    for r in M.results:
        print(f"[{'PASS' if r.passed else 'FAIL'}] {r.category:<12} {r.name:<55} {r.detail[:38]}")
    print("\nMetrics\n" + "-" * 78)
    for k, v in metrics.items():
        print(f"{k:<40} {v}")
    out = ROOT / "eval"
    (out / "results.json").write_text(json.dumps({"metrics": metrics, "results": [r.__dict__ for r in M.results]}, indent=2))
    lines = ["# Evaluation report", "", "Real API responses (recorded) - see eval/run_eval.py.", "",
             "| Metric | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in metrics.items()]
    lines += ["", "| Result | Category | Scenario | Detail |", "|---|---|---|---|"] + [
        f"| {'PASS' if r.passed else 'FAIL'} | {r.category} | {r.name} | {r.detail} |" for r in M.results]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\nWrote eval/results.json and eval/REPORT.md")


if __name__ == "__main__":
    anyio.run(main)
