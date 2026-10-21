"""Ablation study: what each component of Dalili contributes, on identical scenarios and data.

  A  LLM only               - the model plans from the request alone (its own knowledge, prices and times)
  B  LLM + retrieval        - plus the destination's travel guide (Wikivoyage) as grounding text
  C  LLM + MCP              - plus the researched candidates (real flights, hotels, places, hours, prices); the model
                              picks and times everything itself
  D  LLM + MCP + validation - C, then the deterministic validators' findings go back to the model for one revision
  E  LLM + MCP + optimizer  - the model picks the places per day; Dalili's OR-Tools optimizer orders and times them
  F  Full Dalili            - deterministic planner + validators + repair loop (the model only understands/explains)

Measured with the same validators and scorer for every configuration:
  ungrounded rate   - share of the places the plan names that match nothing researched (hallucination proxy)
  hard violations   - deterministic validation errors (opening hours, schedule, budget, dietary, reality ...)
  budget error      - |the plan's own claimed total - its real total from researched prices| / real total
  grounded items    - share of itinerary items backed by a researched entity with provenance
  preference fit, landmark coverage, TripScore (hierarchical), latency, model tokens and estimated cost.

Usage:  python eval/ablation.py            (needs an LLM key: Azure or Anthropic, from .env)
Writes eval/ablation_results.json and eval/ABLATION.md. Every number comes from these runs.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

harness.setup_env(llm=True)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(harness.ROOT / ".env")

import anyio  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from travel_agent import llm, telemetry  # noqa: E402
from travel_agent.engine.validators import validate_plan  # noqa: E402

OUT = Path(__file__).resolve().parent


class Item(BaseModel):
    start: str               # HH:MM
    name: str
    kind: str = "activity"   # activity | meal
    meal_type: str | None = None
    place_id: str | None = None
    est_cost_per_person: float = 0.0


class Day(BaseModel):
    day: int
    items: list[Item]


class FreePlan(BaseModel):
    hotel_name: str
    hotel_id: str | None = None
    hotel_price_per_night: float = 0.0
    outbound_flight_id: str | None = None
    return_flight_id: str | None = None
    flights_price_per_person: float = 0.0
    days: list[Day]
    estimated_total_cost: float = 0.0


RULES = ("Plan every day: sights with realistic times (HH:MM), a lunch and a dinner on full days, opening hours "
         "respected, days geographically compact, within the budget. Give your estimated total cost for the group "
         "(flights + hotel + food + tickets + local transport) in the budget currency.")


def _facts(sc) -> dict:
    c, p = sc.trip.trip_contract, sc.trip.traveler_profile
    return {"request": sc.request, "city": c.destination_name, "from": c.origin_city, "start": str(c.start_date),
            "end": str(c.end_date), "days": c.num_days, "travellers": c.travelers,
            "budget": f"{c.budget.amount:.0f} {c.budget.currency}", "interests": p.activity_preferences,
            "pace": p.travel_style, "dietary": p.dietary_restrictions, "walking": p.walking_tolerance,
            "no_early_flights": p.avoid_early_flights}


def _candidates(sc) -> dict:
    r = sc.trip.research
    return {
        "hotels": [{"id": h.id, "name": h.name, "rating": h.rating, "per_night": h.price_per_night.amount,
                    "currency": h.price_per_night.currency} for h in r.hotels],
        "outbound_flights": [{"id": f.id, "dep": f.depart_at.isoformat(), "arr": f.arrive_at.isoformat(),
                              "price": f.price_per_person.amount, "stops": f.stops} for f in r.flights_outbound[:15]],
        "return_flights": [{"id": f.id, "dep": f.depart_at.isoformat(), "arr": f.arrive_at.isoformat(),
                            "price": f.price_per_person.amount, "stops": f.stops} for f in r.flights_return[:15]],
        "places": [{"id": a.id, "name": a.name, "minutes": a.duration_minutes, "hours": a.opening_hours,
                    "price": a.cost_per_person.amount, "currency": a.cost_per_person.currency,
                    "lat": round(a.location.lat, 4), "lon": round(a.location.lon, 4)}
                   for a in harness.city_attractions(r)[:40]],
        "restaurants": [{"id": x.id, "name": x.name, "meals": x.meal_types, "dietary": x.dietary,
                         "price": x.cost_per_person.amount, "currency": x.cost_per_person.currency,
                         "lat": round(x.location.lat, 4), "lon": round(x.location.lon, 4)} for x in r.restaurants[:40]],
    }


def _guide(sc) -> str:
    k = (sc.trip.research.destination_info or {}).get("knowledge") or {}
    secs = k.get("sections") or {}
    text = [k.get("overview", "")] + [f"== {n} ==\n{secs[n]}" for n in ("See", "Do", "Eat", "Get around", "Sleep") if n in secs]
    return "\n\n".join(text)[:9000]


def _to_plan(sc, fp: FreePlan):
    """Map the model's plan onto researched entities (ids when it gave them, else names)."""
    ctx = harness.ctx_for(sc)
    r = ctx.research
    places = {p.id: p for p in r.attractions + r.restaurants}
    hotels = {h.id: h for h in r.hotels}
    flights = {f.id: f for f in r.flights_outbound + r.flights_return}
    hotel = hotels.get(fp.hotel_id or "") or harness.match_hotel(fp.hotel_name, r.hotels)
    out, ret = flights.get(fp.outbound_flight_id or ""), flights.get(fp.return_flight_id or "")
    named = matched = 0
    days = []
    for d in sorted(fp.days, key=lambda d: d.day):
        rows = []
        for it in d.items:
            named += 1
            place = places.get(it.place_id or "") or harness.ground(it.name, r.restaurants if it.kind == "meal"
                                                                    else r.attractions)
            matched += bool(place)
            rows.append({"start": it.start, "name": it.name, "kind": it.kind, "meal_type": it.meal_type,
                         "place": place, "cost": it.est_cost_per_person})
        days.append(rows)
    plan = harness.assemble(ctx, hotel, out, ret, days)
    claimed = fp.estimated_total_cost or None
    return plan, {"sample_names": [it.name for d in fp.days for it in d.items][:8], "named_items": named, "ungrounded_rate": round(1 - matched / named, 3) if named else None,
                  "hotel_grounded": hotel is not None, "flights_grounded": bool(out and ret), "claimed_total": claimed}


async def _ask(system: str, payload: dict) -> FreePlan | None:
    return await llm.parse(system, json.dumps(payload, default=str, ensure_ascii=False), FreePlan, effort="low")


async def config_a(sc):
    fp = await _ask("You are a travel planner. Plan this trip from your own knowledge. " + RULES, {"trip": _facts(sc)})
    return _to_plan(sc, fp) if fp else None


async def config_b(sc):
    fp = await _ask("You are a travel planner. Plan this trip using the travel guide below for places. " + RULES,
                    {"trip": _facts(sc), "guide": _guide(sc)})
    return _to_plan(sc, fp) if fp else None


SYSTEM_C = ("You are a travel planner. Use ONLY the candidates given and give their ids (hotel_id, flight ids, "
            "place_id for every sight and meal). " + RULES)


async def config_c(sc):
    fp = await _ask(SYSTEM_C, {"trip": _facts(sc), "candidates": _candidates(sc)})
    return _to_plan(sc, fp) if fp else None


async def config_d(sc):
    first = await _ask(SYSTEM_C, {"trip": _facts(sc), "candidates": _candidates(sc)})
    if not first:
        return None
    plan, info = _to_plan(sc, first)
    t = sc.trip
    rep = validate_plan(plan, t.trip_contract, t.traveler_profile, t.research, 0.05)
    if rep.result == "PASS":
        return plan, {**info, "revised": False}
    issues = [v.message for v in rep.errors][:25]
    fp = await _ask(SYSTEM_C + " Fix every problem the validator found in your previous plan.",
                    {"trip": _facts(sc), "candidates": _candidates(sc), "previous_plan": first.model_dump(),
                     "validator_findings": issues})
    if not fp:
        return plan, {**info, "revised": False}
    plan2, info2 = _to_plan(sc, fp)
    return plan2, {**info2, "revised": True}


async def config_e(sc):
    import planners

    return await planners.llm_select_then_optimize(sc)


def config_f(sc):
    import planners

    return planners.dalili(sc), {"ungrounded_rate": 0.0, "claimed_total": None}


CONFIGS = {"A": ("LLM only", config_a), "B": ("LLM + retrieval", config_b), "C": ("LLM + MCP", config_c),
           "D": ("LLM + MCP + validation", config_d), "E": ("LLM + MCP + optimizer", config_e),
           "F": ("Full Dalili", config_f)}


async def main():
    if not llm.available():
        print("No LLM configured (AZURE_AI_KEY/AZURE_AI_ENDPOINT or Anthropic): the ablation needs one.")
        return
    scs = await harness.scenarios()
    rows = []
    for sc in scs:
        for key, (label, fn) in CONFIGS.items():
            usage = telemetry.new_usage()
            token = telemetry.USAGE.set(usage)
            t0 = time.perf_counter()
            err = None
            try:
                res = fn(sc)
                res = await res if hasattr(res, "__await__") else res
            except Exception as exc:  # one broken model answer is a failed run, not a failed study
                res, err = None, f"{type(exc).__name__}: {str(exc)[:200]}"
            finally:
                telemetry.USAGE.reset(token)
            ms = (time.perf_counter() - t0) * 1000
            if not res:
                rows.append({"scenario": sc.name, "config": key, "label": label, "failed": True, "error": err})
                continue
            plan, info = res
            m = harness.evaluate(plan, sc, ms)
            items = [i for d in plan.days for i in d.items if i.kind in ("activity", "meal")]
            grounded = sum(1 for i in items if i.place_id and sc.trip.research.place(i.place_id))
            claimed = info.get("claimed_total")
            rows.append({"scenario": sc.name, "config": key, "label": label, **m, **info,
                         "grounded_items": round(grounded / len(items), 3) if items else None,
                         "budget_error": round(abs(claimed - plan.budget.total) / plan.budget.total, 3)
                         if claimed and plan.budget.total else (0.0 if key in "EF" else None),
                         "llm_calls": usage["llm_calls"], "tokens": usage["input_tokens"] + usage["output_tokens"],
                         "llm_cost_usd": telemetry.finish(usage, 0, ms)["llm_cost_usd_est"]})
            print(f"{sc.name} {key} done", flush=True)
    keys = ["ungrounded_rate", "hard_violations", "feasible", "budget_error", "grounded_items", "preference_satisfaction",
            "landmark_coverage", "tripscore", "compute_ms", "llm_calls", "tokens", "llm_cost_usd"]
    summary = {k: {"label": CONFIGS[k][0], **harness.summarize([r for r in rows if r["config"] == k and not r.get("failed")], keys),
                   "failed_runs": sum(1 for r in rows if r["config"] == k and r.get("failed"))} for k in CONFIGS}
    (OUT / "ablation_results.json").write_text(json.dumps({"generated": harness.tz_now(), "model": llm.model_name(),
                                                           "scenarios": [s.name for s in scs], "summary": summary,
                                                           "rows": rows}, indent=2, default=str))
    lines = ["# Ablation study", "", f"Generated {harness.tz_now()} from `python eval/ablation.py` with "
             f"{llm.model_name()} on {len(scs)} scenarios (recorded real data). Means over scenarios.", "",
             "| config | ungrounded | hard violations | feasible | budget error | grounded items | pref. fit | "
             "landmarks | TripScore | latency ms | LLM calls | tokens | LLM cost $ | failed |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, s in summary.items():
        lines.append(f"| {k}. {s['label']} | {s.get('ungrounded_rate')} | {s.get('hard_violations')} | {s.get('feasible')} | "
                     f"{s.get('budget_error')} | {s.get('grounded_items')} | {s.get('preference_satisfaction')} | "
                     f"{s.get('landmark_coverage')} | {s.get('tripscore')} | {s.get('compute_ms')} | {s.get('llm_calls')} | "
                     f"{s.get('tokens')} | {s.get('llm_cost_usd')} | {s['failed_runs']} |")
    (OUT / "ABLATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    anyio.run(main)
