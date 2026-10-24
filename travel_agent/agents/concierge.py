"""Trip agent (concierge): every message the traveller sends goes to this agent - before a plan exists, while a route
proposal waits for an answer, and once the trip is planned. It reasons and acts (ReAct) over the full trip state and
real tools, and decides for itself what the message needs:

- answer it: "Is there good sushi near my hotel that's open late?", "Why this flight and not the cheaper one?",
  "Will it rain on day 3?", "What's Bali like in November?" -> live tools or the plan's facts, then final_answer;
- change the trip: "a week in Bali from Cairo, 60,000 EGP", "no, only Bali", "add a rooftop dinner on day 2",
  "switch to the direct flight" -> optionally look things up first (so it adds a REAL, named place), then change_plan
  with structured changes. The deterministic planner then researches, rebuilds, validates (budget, hours,
  distances...) and repairs the plan - the agent decides, code verifies the numbers.

Loop (at most MAX_STEPS): the model writes a thought and picks ONE tool with arguments; the tool runs (most are MCP
calls to live data); its observation is appended to the scratchpad; repeat until final_answer or change_plan.
Understanding follows principles shared with the interpreter (nlu.UNDERSTANDING), not phrase lists. Without a model,
the workflow falls back to the rule-based interpreter (offline test harness).
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from .. import knowledge, llm, narrative
from ..config import settings, today
from ..engine.budget import to_user
from ..mcp_hub import MCPToolError, get_hub
from ..memory import recent_turns
from ..models import TripState
from ..nlu import SCOPE_RULE, UNDERSTANDING, Action, FeedbackNote, Lenient, Requirements, RouteStop
from ..replanner import missing_requirements
from . import trace
from .context import anchor, km, plan_summary, profile_summary


MAX_STEPS = 5
STEP_TIMEOUT_S = 30  # one reasoning step normally takes 5-15 s; past this the provider is struggling (see converse)
ToolName = Literal["plan_lookup", "search_nearby", "find_place", "weather", "directions", "convert_currency",
                   "travel_guide", "flight_options", "final_answer", "change_plan", "apply_what_if"]

TOOLS_DOC = """Tools (pick exactly one per step; the first six need a researched trip):
- plan_lookup {"day": int|null}: the traveller's current plan (hotel, flights, each day's schedule and weather).
- search_nearby {"query": str, "near": "hotel" | a place name in the plan | "city"}: live Google Maps search, e.g.
  "sushi", "pharmacy", "rooftop bar", "ATM". Returns rating, reviews, price, hours, address, distance.
- find_place {"name": str}: one specific named place (hours, rating, ticket/price, address, website).
- weather {"day": int|null}: the forecast for the trip days.
- directions {"from": str, "to": str, "mode": "best"|"transit"|"walking"|"driving"}: live Google Maps directions;
  'from'/'to' may be "hotel" or a place name.
- flight_options {}: every researched flight and round-trip ticket (price, times, stops), the chosen ones and why.
- travel_guide {"query": str}: the Wikivoyage guide for the destination (customs, safety, tipping, transport...).
- convert_currency {"amount": number, "from": "EUR", "to": "EGP"}: live central-bank rates.
- final_answer {}: put the reply in 'answer' (and optional 'follow_ups').
- change_plan {}: put the structured changes in 'changes'; the planner researches / rebuilds, checks and explains.
- apply_what_if {}: only when context.pending_what_if exists and the traveller accepts it ("apply it", "تمام نفذها")."""

SYSTEM = f"""You are Dalili (دليلي), an expert travel planner agent with live tools - like a friend who knows travel
inside out. You research and plan trips; the traveller books them. Each turn you read the traveller's latest message
and the trip state in 'context', think, and choose ONE tool per step:
A) They want information -> answer from the context or look up REAL data with tools, then final_answer.
B) Anything that changes the trip (where, when, how long, who, budget, pace, places, flights, hotel, food...) ->
   change_plan. Before a plan exists this is how a trip request starts or gets new details: every trip detail in the
   message must reach the planner through change_plan - never only acknowledge it in an answer. If a message both
   asks and changes, change_plan (the planner's reply covers both).
C) Outside the travel scope -> final_answer right away, no tools: one or two friendly sentences in their language
   saying you only help with travel, then offer something useful. Never answer the off-topic question itself.
D) They accept a pending what-if comparison -> apply_what_if.

{UNDERSTANDING}

The trip's stage (context.stage):
- "collecting": no plan yet; context.trip_so_far shows what is known and what is still missing. A greeting or a
  question -> final_answer that also invites the missing details naturally (where, when, budget).
- "route_proposal": you proposed context.pending_route_proposal and wait for the answer. Agreement or "you decide"
  -> change_plan with route_decision 'accept'. Anything else -> route_decision 'change', with `route` set to exactly
  the places they want when they say which, else route_change_request (in English) describing what to change.
- "planned": the plan is in context (trip, plan_cards, money, day_titles). Answer about it, or change it.
  context.big_events_during_trip lists world-famous events on during the trip, offered to the traveller in your
  replies (never added on your own). Wanting to go -> change_plan, add_place with the event's exact name; one with
  can_be_added=false is in another city of the country, reached by adding that city to the `route`.

Pilgrimage: an Umrah - or any trip to Makkah, unless they say otherwise - is change_plan with requirements.pilgrimage
'umrah'; unless they choose, the route is Makkah then Madinah ('Mecca, Saudi Arabia', 'Medina, Saudi Arabia') with
about two thirds of the nights in Makkah. Hajj is never planned here (permits come only through official channels):
requirements.pilgrimage 'hajj', and the planner explains the channels. Never give religious rulings yourself - point
to the Hajj & Umrah guide on the site.

Answering:
- Ground facts in tool observations or the context. Never invent places, prices, opening hours or times. General
  travel knowledge (seasons, customs, what a place is like) is fine, but never as a live price or schedule.
- Questions about prices, costs or why something was chosen are answered from the data: context.money, plan_cards
  and flight_options (call it when flights matter). Quote the real numbers - the cheapest fare and ticket found, what
  was chosen and why (flight_options.why_chosen: arrival day, hours, stops), the largest cost, what more money buys.
  Lead with that concrete answer. A lower price seen elsewhere is answered with what you found and when
  (money.fares_found) - the plan's fares are Google Flights prices, taxes included, for the trip's exact dates, and
  fares move during the day - plus an offer to use their flight if they share its number. Never pad it with lists of
  possible causes (taxes, fees, baggage, exchange rates, agents) the data doesn't show.
- If the state contradicts what the traveller wants (a place resolved to the wrong country, a change that did not
  happen), say so plainly and fix it with change_plan.
- Call the fewest tools needed (often 0-2). Don't repeat a call you already made.
- Offer only what you can really do: your tools and the plan changes above. You can't re-search prices on demand,
  watch fares or book anything - never promise it.
- final_answer: answer the question itself first, in one or two sentences with the key facts and numbers; then at
  most two or three concrete options or next steps. Specific and warm (names, ratings, distances, times); short
  markdown bullets for options; no lists of speculative causes.
  Write in the traveller's language - natural Egyptian Arabic when they write Egyptian Arabic; names may stay in
  English.
- follow_ups (with final_answer): up to 3 short requests the traveller could send next, in their language as if they
  typed them, specific to this trip. Dalili plans but never books: none may ask to book, reserve or pay.
- change_plan: fill 'changes' - the schema's field descriptions are the contract - and a one-line English 'summary'
  of what the traveller asked for (it is checked against what the planner actually changed).
{SCOPE_RULE}
{TOOLS_DOC}"""


class PlanChange(Lenient):
    summary: str = Field(default="", description="One line in English: what the traveller asked to change")
    actions: list[Action] = Field(default_factory=list)
    requirements: Requirements = Field(default_factory=Requirements)
    feedback: list[FeedbackNote] = Field(default_factory=list)
    route: list[RouteStop] | None = Field(default=None, description=(
        "The COMPLETE set of places the traveller now wants to stay in, in order - only when this message says or "
        "corrects which places the trip covers ('only Bali' -> [Bali, Indonesia]; 'drop Taipei' -> the remaining "
        "stops). Null when the places don't change."))
    route_change_request: str | None = Field(default=None, description=(
        "Only for a vague change of the places to stay that you can't list exactly ('add a few days by the sea'), in "
        "English. Flying home to another city with no stay there is requirements.return_to, not a route change."))
    route_decision: Literal["accept", "change"] | None = Field(default=None, description=(
        "Only at stage 'route_proposal': 'accept' (agrees / lets you decide) or 'change'"))
    hypothetical: bool = Field(default=False, description=(
        "True when the message asks what WOULD happen or cost ('what if...', 'how much would it be with...', "
        "'لو ... هيبقى إيه / بكام؟'): the change is planned on a copy and compared, and nothing changes until they "
        "accept. False when they ask for the change itself."))


class Step(Lenient):
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
    apply_what_if: bool = False        # the traveller accepted the pending what-if comparison


MODES = {"best": 6, "transit": 3, "walking": 2, "driving": 0}


def _trim(obj: Any, limit: int = 3500) -> str:
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit] + "…"


def _fit(payload: dict[str, Any], limit: int = 18000) -> str:
    """Serialise the scratchpad within budget while keeping valid JSON: shorten the oldest observations first."""
    text = json.dumps(payload, ensure_ascii=False, default=str)
    for s in payload["steps_so_far"]:
        if len(text) <= limit:
            break
        s["observation"] = s["observation"][:500] + "…"
        text = json.dumps(payload, ensure_ascii=False, default=str)
    return text


def stage(trip: TripState) -> str:
    d = trip.draft
    if d.route_proposal and d.route_proposal.stops and not d.route_confirmed:
        return "route_proposal"
    return "planned" if trip.plans else "collecting"


def _where(ref) -> str:
    """A resolved place as the agent should see it: name, country and airports (so a wrong country is visible)."""
    return f"{ref.name}, {ref.country}" + (f" (airports {', '.join(ref.airports)})" if ref.airports else "")


def _flight_line(f) -> str:
    return (f"{f.airline} {f.flight_number}, {f.stops} stop(s), departs {f.depart_at:%a %d %b %H:%M}, "
            f"arrives {f.arrive_at:%a %d %b %H:%M}")


def _fares_found(trip: TripState) -> dict[str, Any] | None:
    """What the flight search really returned, so "Google shows it cheaper" is answered with facts, not guesses."""
    r, c, plan = trip.research, trip.trip_contract, trip.selected_plan
    if r is None or c is None or plan is None:
        return None
    cur = c.budget.currency

    def user(m) -> float:
        return to_user(m, r.fx_rates, cur)

    if plan.stops:  # a tour: each leg's cheapest fare next to the chosen one
        return {"source": "Google Flights, per person, taxes included",
                "searched_at": min((f.metadata.retrieved_at for leg in r.legs for f in leg), default=None),
                "legs": [{"leg": f"{chosen.origin}->{chosen.destination}",
                          "chosen": f"{chosen.airline} {user(chosen.price_per_person):,.0f} {cur}",
                          "cheapest": f"{min(user(f.price_per_person) for f in leg):,.0f} {cur}" if leg else None}
                         for chosen, leg in zip(plan.legs, r.legs)]}

    outs, backs = r.flights_outbound, r.flights_return
    live = [f for f in outs + backs + [x for rt in r.round_trips for x in (rt.outbound, rt.inbound)]
            if f.metadata.source != "ai_knowledge"]
    chosen = [f for f in (plan.outbound_flight, plan.return_flight) if f]
    return {
        "source": "Google Flights, per person, taxes included",
        "searched_at": min((f.metadata.retrieved_at for f in live), default=None),
        "options_compared": len(outs) + len(backs) + len(r.round_trips),
        "cheapest_round_trip_ticket": f"{min(user(rt.total_per_person) for rt in r.round_trips):,.0f} {cur}" if r.round_trips else None,
        "cheapest_two_one_way_tickets": (f"{min(user(f.price_per_person) for f in outs) + min(user(f.price_per_person) for f in backs):,.0f} {cur}"
                                         if outs and backs else None),
        "chosen_flights_fare": f"{sum(user(f.price_per_person) for f in chosen):,.0f} {cur}" if chosen else None,
        "ai_estimated": len(live) < len(outs) + len(backs),
    }


def build_context(trip: TripState) -> dict[str, Any]:
    """Everything the agent needs to understand the message against the trip, compactly."""
    d, c, plan = trip.draft, trip.trip_contract, trip.selected_plan
    ctx: dict[str, Any] = {"today": today().isoformat(), "stage": stage(trip)}
    if ctx["stage"] != "planned" or c is None:
        ctx["trip_so_far"] = {
            "destination": d.destinations or d.destination, "region": d.region,
            "resolved_as": [_where(r) for r in d.destination_refs] or ([_where(d.destination_ref)] if d.destination_ref else []),
            "from": d.origin_city or d.origin or trip.metadata.get("home_city"),
            "dates": [str(d.start_date) if d.start_date else None, str(d.end_date) if d.end_date else None],
            "days": d.duration_days, "travellers": d.travelers,
            "budget": (f"{d.budget_amount:,.0f} {d.budget_currency or ''}".strip() if d.budget_amount
                       else "find the cheapest" if d.find_cheapest else None),
            "places_to_see": d.must_visit, "still_missing": missing_requirements(d)}
    if ctx["stage"] == "route_proposal":
        ctx["pending_route_proposal"] = [{"place": f"{s.city}, {s.country}", "nights": s.nights, "covers": s.covers,
                                          "day_trips": s.day_trips} for s in d.route_proposal.stops]
    if c is not None:
        summary = {k: v for k, v in plan_summary(trip).items() if k != "days"}
        summary["length"] = f"{c.nights} nights / {c.num_days} days"
        if c.arrive_by:
            summary["wants_to_arrive_on"] = str(c.arrive_by)
        summary["resolved_places"] = [_where(s.ref) for s in c.stops] or ([_where(c.destination_ref)] if c.destination_ref else [])
        ctx["trip"] = summary
    if plan is not None:
        ctx["day_titles"] = [f"Day {x.day} ({x.date:%a %d %b}): {x.title}" for x in plan.days]
        ctx["plan_cards"] = [{
            "mode": m, "selected": m == trip.selected_mode, "idea": p.pitch,
            "total": f"{p.budget.total:,.0f} {p.budget.currency}" if p.budget else None,
            "within_budget": p.within_budget,
            "hotels": [f"{h.name} ({h.rating}/5)" for h in p.hotels],
            "flights": [_flight_line(f) for f in (p.legs or [x for x in (p.outbound_flight, p.return_flight) if x])],
        } for m, p in trip.plans.items()]
        if plan.budget:
            b = plan.budget
            money: dict[str, Any] = {
                "budget": f"{c.budget.amount:,.0f} {c.budget.currency}", "selected_plan_total": f"{b.total:,.0f} {b.currency}",
                "cost_breakdown": {k: round(getattr(b, k)) for k in ("flights", "hotel", "food", "activities", "transport",
                                                                     "buffer") if getattr(b, k)}}
            money.update(narrative.budget_reality(trip))
            money.update(narrative.flight_alternatives(trip))
            money["fares_found"] = _fares_found(trip)
            ctx["money"] = money
    expert = [n for n in trip.metadata.get("expert_added", [])]
    asked = [n for n in d.must_visit if n.lower() not in {e.lower() for e in expert}]
    if asked:
        ctx["places_the_traveller_asked_for"] = asked
    if expert:
        ctx["places_your_expert_review_added"] = expert  # your picks, not the traveller's request
    events = narrative.event_offers(trip)
    if events:
        # Offered in the replies, never added on our own: "yes, the festival" is an add_place with the event's name.
        ctx["big_events_during_trip"] = events
    ctx["traveller"] = profile_summary(trip)
    if trip.metadata.get("pending_whatif_summary"):
        ctx["pending_what_if"] = trip.metadata["pending_whatif_summary"]
    last = next((m.content for m in reversed(trip.conversation) if m.role == "assistant"), "")
    if last:
        ctx["last_assistant_message"] = last[:2500]
    ctx["recent_conversation"] = recent_turns(trip)  # so "and the second one?" follows the last answer
    return ctx


def flight_options(trip: TripState) -> Any:
    """Every researched flight and round-trip ticket, with the ids choose_flight needs and why the chosen ones won."""
    r, plan = trip.research, trip.selected_plan
    if r is None:
        return "No flights researched yet."

    def row(f) -> dict[str, Any]:
        return {"id": f.id, "flight": f"{f.airline} {f.flight_number}", "from_to": f"{f.origin}->{f.destination}",
                "departs": f"{f.depart_at:%a %d %b %H:%M}", "arrives": f"{f.arrive_at:%a %d %b %H:%M}",
                "stops": f.stops, "duration_min": f.duration_minutes,
                "price_per_person": f"{f.price_per_person.amount:,.0f} {f.price_per_person.currency}"}

    chosen = (plan.legs or [x for x in (plan.outbound_flight, plan.return_flight) if x]) if plan else []
    out: dict[str, Any] = {
        "chosen": [f.id for f in chosen],
        "why_chosen": (plan.explanations.get("outbound_flight", []) + plan.explanations.get("return_flight", []))[:5]
        if plan else [],
        "outbound": [row(f) for f in sorted(r.flights_outbound, key=lambda f: f.price_per_person.amount)[:10]],
        "return": [row(f) for f in sorted(r.flights_return, key=lambda f: f.price_per_person.amount)[:10]],
    }
    if r.round_trips:
        out["round_trip_tickets"] = [{"outbound": row(rt.outbound), "return": row(rt.inbound),
                                      "ticket_price_per_person": f"{rt.total_per_person.amount:,.0f} {rt.total_per_person.currency}",
                                      "note": "one ticket: choose both ids together"} for rt in r.round_trips]
    if r.legs:
        out["tour_legs"] = [[row(f) for f in sorted(leg, key=lambda f: f.price_per_person.amount)[:6]] for leg in r.legs]
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


def _is_empty(ch: PlanChange) -> bool:
    return not (ch.actions or ch.feedback or ch.route or ch.route_change_request or ch.route_decision or ch.hypothetical
                or any(v not in (None, [], "") for v in ch.requirements.model_dump().values()))


async def converse(trip: TripState, message: str, allow_changes: bool = True) -> ConciergeResult | None:
    """Run the ReAct loop on the traveller's message. Returns an answer, or the changes to make (`changes`).
    None when no model is available or it fails (the caller falls back)."""
    if not llm.available():
        return None
    scratch: list[dict[str, Any]] = []
    context = build_context(trip)
    for n in range(MAX_STEPS):
        last = n == MAX_STEPS - 1
        finish = "You must choose final_answer or change_plan now." if allow_changes else "You must choose final_answer now."
        payload = {"traveller_message": message, "context": context, "steps_so_far": scratch,
                   "mode": None if allow_changes else "answer only: change_plan is unavailable",
                   "instruction": finish if last else None}
        text = _fit(payload)
        step = await llm.parse(SYSTEM, text, Step, effort=settings.agent_reasoning_effort, timeout=STEP_TIMEOUT_S)
        if step is None and "exceeded" in (llm.last_error or ""):
            # The provider is slow right now: answer with less deliberation rather than keep the traveller waiting.
            step = await llm.parse(SYSTEM, text, Step, effort="low", timeout=STEP_TIMEOUT_S)
        if step is None:
            return None
        trace.step(trip, "concierge", "thought", step.thought)
        if step.tool == "apply_what_if" and allow_changes:
            if trip.metadata.get("pending_whatif_summary"):
                trace.step(trip, "concierge", "decision", "Applying the what-if comparison the traveller accepted.")
                return ConciergeResult(apply_what_if=True, steps=n + 1)
            scratch.append({"thought": step.thought, "tool": step.tool, "args": {},
                            "observation": "There is no pending what-if to apply."})
            continue
        if step.tool == "change_plan" and allow_changes:
            changes = step.changes or PlanChange()
            if _is_empty(changes):
                if last:
                    return None  # an empty change: let the interpreter take the message
                scratch.append({"thought": step.thought, "tool": step.tool, "args": {},
                                "observation": "Your change_plan had no changes. Fill 'changes', or answer instead."})
                continue
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
