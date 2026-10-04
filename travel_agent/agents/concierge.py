"""Trip agent (concierge): once a plan exists, every message goes to this agent. It reasons and acts (ReAct) over
real tools and decides for itself what the message needs:

- answer it: "Is there good sushi near my hotel that's open late?", "How do I get from the Colosseum to Trastevere?",
  "Will it rain on day 3?", "How much is 50 euros in pounds?" -> live tools, then final_answer;
- change the trip: "add a rooftop dinner on day 2", "I'm active, pack more in", "switch to the direct flight",
  "move my dates a week later" -> optionally look things up first (so it adds a REAL, named place), then
  change_plan with structured changes. The deterministic planner then rebuilds, validates (budget, hours,
  distances...) and repairs the plan - the agent decides, code verifies the numbers.

Loop (at most MAX_STEPS): the model writes a thought and picks ONE tool with arguments; the tool runs (most are MCP
calls to live data); its observation is appended to the scratchpad; repeat until final_answer or change_plan.
Answers are grounded in observations, in the traveller's language, with up to three follow-up requests that the UI
offers as one-tap replies. Without a model, the workflow falls back to the rule-based interpreter.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from .. import knowledge, llm
from ..config import today
from ..mcp_hub import MCPToolError, get_hub
from ..memory import recent_turns
from ..models import TripState
from ..nlu import SCOPE_RULE, Action, FeedbackNote, Requirements
from . import trace
from .context import anchor, km, plan_summary, profile_summary

log = logging.getLogger(__name__)

MAX_STEPS = 5
ToolName = Literal["plan_lookup", "search_nearby", "find_place", "weather", "directions", "convert_currency",
                   "travel_guide", "flight_options", "final_answer", "change_plan"]

TOOLS_DOC = """Tools (pick exactly one per step):
- plan_lookup {"day": int|null}: the traveller's current plan (hotel, flights, each day's schedule and weather).
- search_nearby {"query": str, "near": "hotel" | a place name in the plan | "city"}: live Google Maps search, e.g.
  "sushi", "pharmacy", "rooftop bar", "ATM". Returns rating, reviews, price, hours, address, distance.
- find_place {"name": str}: one specific named place (hours, rating, ticket/price, address, website).
- weather {"day": int|null}: the forecast for the trip days.
- directions {"from": str, "to": str, "mode": "best"|"transit"|"walking"|"driving"}: live Google Maps directions;
  'from'/'to' may be "hotel" or a place name.
- convert_currency {"amount": number, "from": "EUR", "to": "EGP"}: live central-bank rates.
- travel_guide {"query": str}: the Wikivoyage guide for the destination (customs, safety, tipping, transport...).
- flight_options {}: every researched flight (and round-trip ticket) with price, times and stops, plus the chosen ones.
- final_answer {}: put the reply in 'answer' (and optional 'follow_ups').
- change_plan {}: put the structured changes in 'changes'; the planner rebuilds, checks and explains the new plan."""

SYSTEM = f"""You are Dalili, an expert travel planner agent with live tools. The traveller already has a trip plan.
Read their latest message (any language or dialect - understand the intent, not keywords) and decide what it needs:
A) Information -> call tools for REAL data, then final_answer.
B) A change to the trip (pace, places, flights, hotel, budget, dates, length, food, walking...) -> change_plan.
   Look things up first when it makes the change better: "add a nice rooftop restaurant on day 2" -> search_nearby,
   then add_place with the real name you found; "take the direct flight" -> flight_options, then choose_flight with
   the exact ids. If the message both asks and changes, change_plan (the planner's reply covers both).
C) Outside the travel scope (below) -> final_answer right away, no tools: one or two friendly sentences in the
   traveller's language saying you only help with travel and their trip, then offer something useful for this trip.
   Never answer the off-topic question itself, not even briefly.
{SCOPE_RULE}
Rules:
- Never invent places, prices, opening hours or times: use tool observations. If a tool finds nothing, say so.
- Call the fewest tools needed (often 0-2). Don't repeat a call you already made.
- final_answer: concise, helpful, specific (names, ratings, distances, times), short markdown bullets for options.
  Write in the SAME language as the traveller (natural Egyptian Arabic if they write Egyptian Arabic).
- follow_ups (with final_answer): up to 3 short requests the traveller could send next, in their language as if they
  typed them, e.g. "Add Sushi Zen to day 3 dinner" / "ضيف مطعم سوشي زن لعشا اليوم التالت". Specific, not generic.
  Dalili plans but never books: no follow-up may ask to book, reserve or pay for anything.
- change_plan: fill 'changes'. Use actions for plan changes and requirements for facts about the trip or traveller:
  - more stops / "I'm active" / "ضيف حاجات" -> increase_density (and requirements.travel_style when they describe
    themselves); "too tiring" -> reduce_density (day = the day if named); more rest -> more_free_time;
  - a named place -> add_place (text = its usual English name); drop one -> replace_item (text = exact plan title);
  - "landmarks / top sights" -> more_category with category "landmarks"; other kinds -> more_category /
    fewer_category with a lowercase category (museums, history, art, food, nature, shopping, nightlife...);
  - flights: choose_flight once per leg with text = the flight id from flight_options (a round-trip ticket: both ids);
    change_flight only for "a different flight" without a specific one;
  - hotel: change_hotel / avoid_noise / upgrade; cheaper -> cheaper;
  - budget: set_budget (absolute) / adjust_budget (signed delta); "raise it to the real cost" -> set_budget with
    the plan total rounded up; "make it the cheapest possible / what's the minimum" -> requirements.wants_cheapest
    = true (the planner finds the cheapest good trip and its cost); trip length: extend_trip / shorten_trip with amount = days; later_start text=HH:MM;
  - walking vs transport -> requirements.transport_preference (walk | mixed | public_transport | taxi);
  - new dates / travellers / destination -> requirements (ISO dates, resolve relative dates against 'today');
    adding or dropping a whole city, or moving nights between cities -> route_change_request (in English).
  Put a one-line English 'summary' of what you are changing.
{TOOLS_DOC}"""


class PlanChange(BaseModel):
    summary: str = Field(default="", description="One line in English: what is being changed and why")
    actions: list[Action] = Field(default_factory=list)
    requirements: Requirements = Field(default_factory=Requirements)
    feedback: list[FeedbackNote] = Field(default_factory=list)
    route_change_request: str | None = None


class Step(BaseModel):
    thought: str = Field(description="Your reasoning for this step (one or two sentences)")
    tool: ToolName
    args: dict[str, Any] = Field(default_factory=dict)
    answer: str | None = Field(default=None, description="Only with final_answer: the reply to the traveller")
    follow_ups: list[str] = Field(default_factory=list, description="Only with final_answer: up to 3 next requests")
    changes: PlanChange | None = Field(default=None, description="Only with change_plan: the structured changes")


class ConciergeResult(BaseModel):
    answer: str = ""
    follow_ups: list[str] = []
    steps: int = 0
    changes: PlanChange | None = None  # set when the agent decided to change the trip instead of answering


MODES = {"best": 6, "transit": 3, "walking": 2, "driving": 0}


def _trim(obj: Any, limit: int = 3500) -> str:
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit] + "…"


def _fit(payload: dict[str, Any], limit: int = 14000) -> str:
    """Serialise the scratchpad within budget while keeping valid JSON: shorten the oldest observations first."""
    text = json.dumps(payload, ensure_ascii=False, default=str)
    for s in payload["steps_so_far"]:
        if len(text) <= limit:
            break
        s["observation"] = s["observation"][:500] + "…"
        text = json.dumps(payload, ensure_ascii=False, default=str)
    return text


def flight_options(trip: TripState) -> Any:
    """Every researched flight and round-trip ticket, with the ids choose_flight needs."""
    r, plan = trip.research, trip.selected_plan
    if r is None:
        return "No flights researched yet."

    def row(f) -> dict[str, Any]:
        return {"id": f.id, "flight": f"{f.airline} {f.flight_number}", "from_to": f"{f.origin}->{f.destination}",
                "departs": f"{f.depart_at:%a %d %b %H:%M}", "arrives": f"{f.arrive_at:%a %d %b %H:%M}",
                "stops": f.stops, "duration_min": f.duration_minutes,
                "price_per_person": f"{f.price_per_person.amount:,.0f} {f.price_per_person.currency}"}

    out: dict[str, Any] = {
        "chosen": [plan.outbound_flight.id, plan.return_flight.id] if plan and plan.outbound_flight and plan.return_flight else [],
        "outbound": [row(f) for f in sorted(r.flights_outbound, key=lambda f: f.price_per_person.amount)[:10]],
        "return": [row(f) for f in sorted(r.flights_return, key=lambda f: f.price_per_person.amount)[:10]],
    }
    if r.round_trips:
        out["round_trip_tickets"] = [{"outbound": row(rt.outbound), "return": row(rt.inbound),
                                      "ticket_price_per_person": f"{rt.total_per_person.amount:,.0f} {rt.total_per_person.currency}",
                                      "note": "one ticket: choose both ids together"} for rt in r.round_trips]
    return out


async def _run_tool(trip: TripState, tool: str, args: dict[str, Any]) -> Any:
    hub = get_hub()
    c = trip.trip_contract
    ref = c.destination_ref if c else None
    if tool == "plan_lookup":
        return plan_summary(trip, args.get("day"))
    if tool == "flight_options":
        return flight_options(trip)
    if tool == "weather":
        days = trip.research.weather if trip.research else []
        start = c.start_date if c else None
        return [{"day": (w.date - start).days + 1 if start else None, "date": f"{w.date:%a %d %b}",
                 "condition": w.condition, "min_c": w.temp_min_c, "max_c": w.temp_max_c,
                 "rain_chance": w.precipitation_probability, "source": w.metadata.provider}
                for w in days if not args.get("day") or start is None or (w.date - start).days + 1 == args["day"]] \
            or "No forecast for these dates yet."
    if tool == "travel_guide":
        guide = (trip.research.destination_info.get("knowledge") if trip.research else None) or {}
        hits = knowledge.search(guide, str(args.get("query", "")), top_k=4) if guide else []
        return [h["text"][:500] for h in hits] or "The guide has nothing on that."
    if tool == "convert_currency":
        return await hub.call("currency", "convert_currency", {
            "amount": float(args.get("amount") or 0), "from_currency": str(args.get("from", "USD")).upper(),
            "to_currency": str(args.get("to", "USD")).upper()})
    if tool == "search_nearby":
        pt, where = anchor(trip, str(args.get("near") or "hotel"))
        if pt is None:
            return "I don't know where the trip is yet."
        # Rounded to ~100 m so repeated questions about the same area reuse the cached search (no new credit).
        res = await hub.call("places", "search_places", {"query": str(args.get("query", "")).strip().lower(),
                                                          "lat": round(pt.lat, 3), "lon": round(pt.lon, 3), "zoom": 15})
        out = []
        for r in (res.get("results") or [])[:6]:
            gps = r.get("gps_coordinates") or {}
            out.append({"name": r.get("title"), "rating": r.get("rating"), "reviews": r.get("reviews"),
                        "price": r.get("price"), "type": r.get("type"), "address": r.get("address"),
                        "hours": r.get("hours") or (r.get("operating_hours") or {}),
                        "open_state": r.get("open_state"),
                        "km_from_" + (where or "anchor"): km(pt, gps["latitude"], gps["longitude"]) if gps else None})
        return out or f"Nothing found for that near {where}."
    if tool == "find_place":
        if ref is None:
            return "I don't know where the trip is yet."
        res = await hub.call("activities", "find_place", {"name": str(args.get("name", "")), "city": ref.name,
                                                           "lat": ref.lat, "lon": ref.lon,
                                                           "local_currency": (trip.research.destination_info.get("currency")
                                                                              if trip.research else None) or "USD"})
        p = res.get("place") or res.get("result") or res
        if isinstance(p, dict) and p.get("name"):
            return {k: p.get(k) for k in ("name", "kind", "rating", "reviews_count", "address", "opening_hours",
                                          "hours_verified", "cost_per_person", "website", "booking_url", "description",
                                          "day_trip", "distance_km")}
        return "Couldn't find that place."
    if tool == "directions":
        start_pt, start_name = anchor(trip, str(args.get("from") or "hotel"))
        end_pt, end_name = anchor(trip, str(args.get("to") or ""))
        if start_pt is None or end_pt is None:
            return "I need two places from the plan (or the hotel) to route between."
        res = await hub.call("transport", "get_directions", {
            "start": f"{start_pt.lat},{start_pt.lon}", "end_lat": end_pt.lat, "end_lon": end_pt.lon,
            "travel_mode": MODES.get(str(args.get("mode", "best")), 6)})
        routes = [{k: r.get(k) for k in ("travel_mode", "via", "formatted_duration", "formatted_distance")}
                  for r in (res.get("routes") or [])[:3]]
        return {"from": start_name, "to": end_name, "routes": routes} if routes else "No route found."
    return f"Unknown tool {tool}."


async def answer(trip: TripState, question: str) -> ConciergeResult | None:
    """Answer only (no plan changes): the ReAct loop restricted to information tools."""
    res = await converse(trip, question, allow_changes=False)
    return res if res and res.answer else None


async def converse(trip: TripState, message: str, allow_changes: bool = True) -> ConciergeResult | None:
    """Run the ReAct loop on the traveller's message. Returns an answer, or the changes to make (`changes`).
    None when no model is available or it fails (the caller falls back)."""
    if not llm.available():
        return None
    scratch: list[dict[str, Any]] = []
    context = {"trip": plan_summary(trip) if trip.trip_contract else None,
               "traveller": profile_summary(trip) if trip.trip_contract else None}
    context["trip"] = {k: v for k, v in (context["trip"] or {}).items() if k != "days"} or None  # details on demand
    plan = trip.selected_plan
    context["day_titles"] = [f"Day {d.day} ({d.date:%a %d %b}): {d.title}" for d in plan.days] if plan else []
    context["plan_total"] = f"{plan.budget.total:,.0f} {plan.budget.currency}" if plan and plan.budget else None
    context["today"] = today().isoformat()
    context["recent_conversation"] = recent_turns(trip)  # so "and the second one?" follows the last answer
    for n in range(MAX_STEPS):
        last = n == MAX_STEPS - 1
        finish = "You must choose final_answer or change_plan now." if allow_changes else "You must choose final_answer now."
        payload = {"traveller_message": message, "context": context, "steps_so_far": scratch,
                   "mode": None if allow_changes else "answer only: change_plan is unavailable",
                   "instruction": finish if last else None}
        step = await llm.parse(SYSTEM, _fit(payload), Step)
        if step is None:
            return None
        trace.step(trip, "concierge", "thought", step.thought)
        if step.tool == "change_plan" and allow_changes:
            changes = step.changes or PlanChange()
            if not (changes.actions or changes.feedback or changes.route_change_request
                    or any(v not in (None, [], "") for v in changes.requirements.model_dump().values())):
                return None  # an empty change: let the interpreter take the message
            trace.step(trip, "concierge", "decision", changes.summary or "Changing the plan.",
                       actions=[a.model_dump(exclude_none=True) for a in changes.actions])
            return ConciergeResult(changes=changes, steps=n + 1)
        if step.tool in ("final_answer", "change_plan") or last:
            text = (step.answer or "").strip()
            if not text and not last:
                # Chose to answer but wrote nothing: ask for the answer instead of starting over elsewhere.
                scratch.append({"thought": step.thought, "tool": step.tool, "args": {},
                                "observation": "Your final_answer had no text. Write the answer now in 'answer'."})
                continue
            if not text:
                return None
            trace.step(trip, "concierge", "answer", text, follow_ups=step.follow_ups[:3])
            return ConciergeResult(answer=text, follow_ups=[f.strip() for f in step.follow_ups if f.strip()][:3],
                                   steps=n + 1)
        trace.step(trip, "concierge", "tool", f"{step.tool}({json.dumps(step.args, ensure_ascii=False)})",
                   tool=step.tool)
        try:
            obs = await _run_tool(trip, step.tool, step.args)
        except MCPToolError as exc:
            obs = f"Tool failed: {exc}"
        except (KeyError, TypeError, ValueError) as exc:
            obs = f"Bad arguments: {exc}"
        scratch.append({"thought": step.thought, "tool": step.tool, "args": step.args, "observation": _trim(obs)})
        trace.step(trip, "concierge", "observation", _trim(obs, 400), tool=step.tool)
    return None
