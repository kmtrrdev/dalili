"""LangGraph orchestration (the Travel Manager).

START -> understand -+-> answer (concierge ReAct agent over live tools) -----> END
                     +-> check_requirements -+-> ask -----------------------> END
                     |                       +-> propose_route --------------> END
                     |                       +-> research_setup
                     +-> apply_feedback -----+-> research_setup / plan / respond
research_setup -> [flights | hotels | restaurants | activities | weather] -> collect -> plan
plan -> validate -+-> repair -> plan            (until every mode passes or max iterations)
                  +-> finalize -> critic -+-> plan   (self-reflection: apply safe fixes, rebuild, verify)
                                          +-> respond -> END
"""

from __future__ import annotations

import asyncio
import logging
import operator
import time
import uuid
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import conflicts, constraints, journey, narrative, net, research, route_design, telemetry
from .agents import concierge, critic, strategist, trace
from .providers import geo
from .config import settings
from .engine.budget import compute_budget
from .engine.knobs import PlanKnobs
from .engine.planner import PlanContext, build_plan, plan_activity_ids
from .engine.repair import repair
from .engine.scoring import score_plan
from .engine.validators import validate_plan
from .mcp_hub import CURRENT_TURN, MCPToolError, get_hub
from .memory import recent_turns
from .models import PLANNING_MODES, ChatMessage, ResearchBundle, TripPlan, TripState
from .nlu import Action, TurnInterpretation, interpret
from .replanner import (
    FIND_CHEAPEST_PLACEHOLDER,
    REQUIRED_QUESTIONS,
    RESEARCH_DOMAINS,
    apply_actions,
    apply_requirements,
    build_contract,
    contract_dirty_domains,
    diff_plans,
    learn_from_feedback,
    missing_requirements,
    names_place,
    nice_amount,
    set_route,
)
from .utils import place_key

log = logging.getLogger(__name__)


class GraphState(TypedDict, total=False):
    trip: TripState
    message: str
    preset_actions: list[Action]
    route_decision: str | None   # "accept" from the UI's "Plan this route" button
    interpretation: TurnInterpretation
    route: str
    dirty: list[str]
    previous_plan: TripPlan | None
    knobs: dict[str, PlanKnobs]
    candidates: dict[str, TripPlan]
    iteration: int
    reply: str
    critic_next: str              # "plan" (apply the critic's fixes) or "respond"
    critic_backup: dict[str, Any]  # the plans before the critic's fixes (restored if the refinement is worse)
    repair_prev: dict[str, TripPlan]  # each mode's plan before the latest repair (kept if the repair made it worse)
    repair_stalled: list[str]         # modes whose last repair was reverted: no further repairs this turn
    # research partials (one key per parallel branch)
    r_info: dict[str, Any]
    r_flights: dict[str, Any]
    r_hotels: list
    r_restaurants: list
    r_activities: list
    r_weather: list
    r_errors: Annotated[list[str], operator.add]  # written by parallel branches


# ---------------------------------------------------------------------------
# Understanding
# ---------------------------------------------------------------------------


async def understand(state: GraphState) -> GraphState:
    trip = state["trip"]
    message = state.get("message", "")
    has_plan = bool(trip.plans)
    if state.get("preset_actions"):
        interp = TurnInterpretation(intent="feedback", actions=state["preset_actions"], source="api")
        return {"interpretation": interp, "route": "feedback"}
    if not message.strip():
        return {"route": "answer", "interpretation": TurnInterpretation(intent="smalltalk")}
    pending = trip.draft.route_proposal if trip.draft.route_proposal and not trip.draft.route_confirmed else None
    interp, notes = None, []
    # The trip agent decides what every message needs - before a plan, while a route proposal waits and after
    # planning: look things up and answer, or change the trip.
    result = await concierge.converse(trip, message)
    if result is not None and result.apply_what_if:
        # Accepting the comparison: the service swaps in the plan it kept aside (nothing to plan here).
        trip.metadata["apply_whatif"] = True
        return {"route": "answer", "reply": "-", "interpretation": TurnInterpretation(intent="feedback", source="agent")}
    if result is not None and result.changes is None:
        trip.metadata["suggestions"] = result.follow_ups
        trip.emit("message.interpreted", intent="question", source="agent")
        return {"route": "answer", "reply": result.answer,
                "interpretation": TurnInterpretation(intent="question", source="agent")}
    if result is not None:
        ch = result.changes
        interp = TurnInterpretation(intent="feedback" if has_plan else "plan_request", actions=ch.actions,
                                    requirements=ch.requirements, feedback=ch.feedback, route=ch.route,
                                    route_change_request=ch.route_change_request, route_decision=ch.route_decision,
                                    hypothetical=ch.hypothetical, source="agent")
        trip.metadata["turn_request"] = ch.summary  # what was asked, checked against what changed in the reply
    else:
        # No agent (offline test harness) or it failed: the one-shot interpreter.
        names = {p.id: p.name for p in trip.research.attractions + trip.research.restaurants} if trip.research else {}
        interp, notes = await interpret(message, has_plan, names, _interpreter_context(trip, pending))
    if interp.source == "unavailable":
        return {"route": "answer", "reply": narrative.unavailable_reply(message), "interpretation": interp}
    if has_plan and interp.apply_pending and trip.metadata.get("pending_whatif_summary"):
        trip.metadata["apply_whatif"] = True
        return {"route": "answer", "reply": "-", "interpretation": interp}
    if has_plan and interp.hypothetical:
        trip.metadata["hypothetical"] = True  # plan it (on the service's copy), then show the comparison
    # A free-text "add_place" without a place name carries nothing to add ("add more things" is a density change).
    interp.actions = [a for a in interp.actions if not (a.action in ("add_place", "replace_item") and not (a.text or "").strip())]
    if has_plan:
        _drop_echoes(trip, interp)
        notes = notes + await _budget_currency(trip, interp)
        r = interp.requirements
        if r.planning_mode and r.planning_mode != trip.selected_mode and r.planning_mode in trip.plans \
                and not any(a.action == "select_mode" for a in interp.actions):
            # "Show me the comfort one": the four plans already exist - switch cards instead of replanning.
            interp.actions.append(Action(action="select_mode", text=r.planning_mode))
    if interp.requirements.budget_amount:
        # The new total is already in the requirements: an adjust/set action on top would apply it twice.
        interp.actions = [a for a in interp.actions if a.action not in ("adjust_budget", "set_budget")]
    if interp.requirements.nights or interp.requirements.duration_days or interp.requirements.end_date:
        # The new length is stated absolutely: a relative extend/shorten on top would apply it twice.
        interp.actions = [a for a in interp.actions if a.action not in ("extend_trip", "shorten_trip")]
    if interp.requirements.return_to:
        # "Fly home to Cairo instead": the last flight is searched again anyway. Don't also swap the outbound
        # flight (change_flight would exclude it) - the traveller didn't ask for that.
        interp.actions = [a for a in interp.actions if a.action != "change_flight"]
    trip.emit("message.interpreted", intent=interp.intent, source=interp.source)
    # "Only Bali", "drop Taipei": the exact places the traveller wants now replace the route (no echo guessing).
    route_set = interp.route is not None and set_route(trip, interp.route)
    if route_set:
        r = interp.requirements
        r.destination, r.destinations, r.nights_per_destination, r.region = None, [], [], None
        interp.route_change_request = None
        if all(s.nights for s in interp.route):
            # The nights per place already give the new length ("add 3 days in Lombok" -> Bali 5 + Lombok 3): an
            # extend_trip or another total on top would count the change twice. Stated as the length, so a start
            # date given with it (or the first one, before any) keeps it.
            r.nights = r.end_date = None
            r.duration_days = sum(s.nights for s in interp.route) + 1
            interp.actions = [a for a in interp.actions if a.action not in ("extend_trip", "shorten_trip")]
    wants_change = interp.intent in ("feedback", "update_requirements", "plan_request")
    if has_plan and wants_change and _changes_trip_frame(trip, interp):
        route = "requirements"  # new dates / budget / destination: rebuild the contract (actions ride along)
    elif has_plan and interp.actions:
        route = "feedback"  # plan changes, even when the model labelled them "update_requirements"
    elif interp.intent == "feedback" and has_plan:
        route = "feedback"
    elif interp.intent in ("plan_request", "update_requirements"):
        route = "requirements"
    elif interp.intent == "question":
        route = "answer"
    elif has_plan and interp.feedback:
        route = "feedback"
    else:
        route = "answer"
    if has_plan and interp.route_change_request and not pending:
        # "Add a few days in Sharm and end in Cairo": reopen the route design with the traveller.
        d = trip.draft
        d.redesign, d.route_confirmed = True, False
        d.route_feedback = [interp.route_change_request, message]  # the model's summary + the traveller's own words
        d.route_proposal = None
        route = "requirements"
    elif (pending or route_set) and interp.intent not in ("question", "off_topic"):
        route = "requirements"  # an answer to a route proposal or a new set of places: rebuild from the requirements
    trip.assumptions = notes
    return {"interpretation": interp, "route": route}


def _interpreter_context(trip: TripState, pending) -> dict:
    """The trip state the one-shot interpreter reads (the agent builds its own, richer view)."""
    plan = trip.selected_plan
    return {
        "has_plan": bool(trip.plans),
        "pending_route_proposal": [f"{s.city}, {s.country} ({s.nights} nights)" for s in pending.stops] if pending else None,
        "draft": trip.draft.model_dump(mode="json", exclude_defaults=True,
                                       exclude={"destination_ref", "origin_ref", "destination_refs", "route_proposal"}),
        "contract": trip.trip_contract.model_dump(mode="json") if trip.trip_contract else None,
        "plan_days": [f"Day {d.day}: {d.title}" for d in plan.days] if plan else [],
        "plan_total": f"{plan.budget.total:.0f} {plan.budget.currency}" if plan and plan.budget else None,
        "traveller_profile": trip.traveler_profile.model_dump(include={"travel_style", "walking_tolerance",
                                                                       "transport_preference", "activity_preferences"}),
        "recent_conversation": recent_turns(trip),   # short-term memory: what was just said
        "pending_what_if": trip.metadata.get("pending_whatif_summary"),
    }


def _drop_echoes(trip: TripState, interp: TurnInterpretation) -> None:
    """The model often repeats facts already in the trip next to the real change. An echoed total or length must not
    cancel the relative change asked for ("add 2 nights", "+$500"), so values equal to the contract are cleared."""
    c, r = trip.trip_contract, interp.requirements
    if c is None:
        return
    same_cur = not r.budget_currency or r.budget_currency.strip().upper() == c.budget.currency.upper()
    if r.budget_amount and same_cur and abs(r.budget_amount - c.budget.amount) <= 0.5:
        r.budget_amount = None
    if r.nights and r.nights == c.nights:
        r.nights = None
    if r.duration_days and r.duration_days == c.num_days:
        r.duration_days = None
    if r.start_date and r.start_date == c.start_date.isoformat():
        r.start_date = None
    if r.end_date and r.end_date == c.end_date.isoformat():
        r.end_date = None


async def _convert(trip: TripState, amount: float, src: str, dst: str) -> float | None:
    """`amount` in `src` expressed in `dst` (live rate; the trip's own rates as a fallback). None when unknown."""
    try:
        res = await get_hub().call("currency", "convert_currency",
                                   {"amount": amount, "from_currency": src, "to_currency": dst})
        return float(res["converted"])
    except (MCPToolError, KeyError, TypeError, ValueError):
        pass
    fx = trip.research.fx_rates if trip.research else {}  # currency -> multiplier into the trip's currency
    return amount * fx[src] / fx[dst] if fx.get(src) and fx.get(dst) else None


async def _budget_currency(trip: TripState, interp: TurnInterpretation) -> list[str]:
    """A budget stated in another currency than the trip's ("make it in pounds", "100,000 EGP", "add 5,000 EGP").
    The number is never relabelled: it is converted, or the currency change is refused. Returns change notes."""
    c, r = trip.trip_contract, interp.requirements
    new = (r.budget_currency or "").strip().upper()
    if c is None or not new or new == c.budget.currency.upper():
        return []
    old = c.budget.currency.upper()
    absolute = next((a for a in interp.actions if a.action == "set_budget" and a.amount), None)
    if absolute and not r.budget_amount:
        r.budget_amount = float(absolute.amount)  # a new total in the new currency: the contract is rebuilt with both
    if r.budget_amount:
        return []
    deltas = [a for a in interp.actions if a.action == "adjust_budget" and a.amount]
    if deltas:
        # "Add 5,000 EGP" to a dollar budget: the same money in the trip's currency; the currency itself stays.
        for a in deltas:
            value = await _convert(trip, float(a.amount), new, old)
            if value is None:
                interp.actions.remove(a)
                return [f"I couldn't get an exchange rate from {new} to {old}, so the budget is unchanged."]
            a.amount = round(value, 2)
        r.budget_currency = None
        return []
    if trip.draft.find_cheapest:
        return []  # the planner finds the cheapest trip again, priced in the new currency
    value = await _convert(trip, c.budget.amount, old, new)
    if value is None:
        r.budget_currency = None
        return [f"I couldn't get a live exchange rate from {old} to {new}, so the budget stays in {old}."]
    r.budget_amount = float(round(value, -max(0, len(str(int(value))) - 3)))  # 75,412 -> 75,400
    return [f"Budget converted: {c.budget.amount:,.0f} {old} ≈ {r.budget_amount:,.0f} {new} at today's rate."]


def _changes_trip_frame(trip: TripState, interp: TurnInterpretation) -> bool:
    """Does the message change where / when / who / how much (which needs the requirements path)?"""
    r, c = interp.requirements, trip.trip_contract
    if c is None:
        return True
    # The model sometimes echoes facts already in the contract: only a different value is a change.
    wanted = [x for x in r.destinations if x and x.strip()]
    if wanted and not (len(wanted) == len(c.stops) and all(names_place(w, s.name, s.ref) for w, s in zip(wanted, c.stops))) \
            and [place_key(w) for w in wanted] != [place_key(x) for x in trip.draft.destinations]:
        return True
    if r.region and r.region.strip().lower() != (trip.draft.region or "").lower():
        return True
    if r.budget_currency and r.budget_currency.strip().upper() != c.budget.currency.upper():
        return True
    if r.wants_cheapest and not r.budget_amount and not trip.draft.find_cheapest:
        return True  # "the cheapest possible": a soft budget the planner finds
    if r.budget_is_hard_limit is not None and not trip.draft.find_cheapest \
            and r.budget_is_hard_limit != c.budget.hard_limit:
        return True
    if r.origin_airport and r.origin_airport.strip().upper() != (c.origin or "").upper():
        return True
    if r.start_date and r.start_date != c.start_date.isoformat():
        return True
    if r.arrive_on_start is not None and r.arrive_on_start != (c.arrive_by is not None):
        return True
    if r.end_date and r.end_date != c.end_date.isoformat():
        return True
    if r.duration_days and r.duration_days != c.num_days:
        return True
    if r.nights and r.nights != c.nights:
        return True
    if r.budget_amount and abs(r.budget_amount - c.budget.amount) > 0.5:
        return True
    if r.destination and not names_place(r.destination, c.destination, c.destination_ref) \
            and not any(names_place(r.destination, s.name, s.ref) for s in c.stops):
        return True  # a new place, or the same name in another country (a correction)
    if r.origin_city and not names_place(r.origin_city, c.origin_city, c.origin_ref):
        return True
    if r.return_to:
        home = names_place(r.return_to, c.origin_city, c.origin_ref)  # "back home" = no open-jaw
        if not (home and not c.return_city) and not (c.return_city and names_place(r.return_to, c.return_city, c.return_ref)):
            return True  # the last flight goes somewhere else now
    if r.rooms and r.rooms != c.rooms:
        return True
    return bool(r.travelers and r.travelers != c.travelers)


async def answer(state: GraphState) -> GraphState:
    trip = state["trip"]
    interp = state.get("interpretation")
    if state.get("reply"):
        return {}  # the trip agent already answered (with live tools) while understanding the message
    if interp and interp.intent == "off_topic":
        return {"reply": await narrative.off_topic_reply(trip, state.get("message", ""))}
    if interp and interp.intent == "question":
        question = state.get("message", "") or interp.question or ""
        # The concierge agent reasons and calls live tools (ReAct); the guide-based answer is the fallback.
        result = await concierge.answer(trip, question) if trip.trip_contract else None
        if result:
            trip.metadata["suggestions"] = result.follow_ups
            return {"reply": result.answer}
        reply = await narrative.answer_question(trip, interp.question or question)
    elif trip.pending_questions:
        reply = await narrative.compose_questions_reply(trip)
    else:
        reply = narrative.greeting()
    return {"reply": reply}


def _wrong_country(text: str, ref) -> bool:
    """'Bali, Indonesia' must not become a Bali somewhere else: a stated country is checked against the resolved one."""
    parts = [x.strip() for x in text.split(",")]
    cc = geo.country_code(parts[-1]) if len(parts) > 1 else None
    return bool(cc and ref.country_code and cc != ref.country_code.upper())


async def _try_resolve(text: str):
    """The place, or the MCPToolError that says it wasn't found (so lookups can run together)."""
    try:
        return await research.resolve_place(get_hub(), text)
    except MCPToolError as exc:
        return exc


async def _resolve(trip: TripState) -> str | None:
    """Resolve destination/origin text against real geocoding. Returns a question if something is unclear."""
    d = trip.draft
    if not d.route_confirmed:
        texts = d.destinations or ([d.destination] if d.destination else [])
        d.countries = [x for x in texts if geo.country_code(x)]
    origin_text = d.origin_city or d.origin or trip.metadata.get("home_city") or settings.default_origin
    # Where they fly from is looked up alongside the destination(s); it is used once the destination is known.
    origin = (asyncio.create_task(_try_resolve(origin_text))
              if d.origin_ref is None and (d.destination_ref is not None or d.region or d.destination) else None)
    try:
        return await _resolve_places(trip, origin_text, origin)
    finally:
        if origin is not None and not origin.done():
            origin.cancel()  # the turn asks a question instead


async def _resolve_places(trip: TripState, origin_text: str, origin: "asyncio.Task | None") -> str | None:
    d = trip.draft
    if len(d.destinations) >= 2 and len(d.destination_refs) < 2:
        refs, kept, missing = [], [], []
        found = await asyncio.gather(*(_try_resolve(text) for text in d.destinations))
        for text, ref in zip(d.destinations, found):
            if isinstance(ref, MCPToolError):
                missing.append(text)
                continue
            if _wrong_country(text, ref):
                missing.append(text)
                continue
            if all((r.name, r.country) != (ref.name, ref.country) for r in refs):
                refs.append(ref)
                kept.append(text)
                trip.emit("place.resolved", role="stop", name=ref.name, country=ref.country)
        if not refs:
            bad, d.destinations, d.destination = ", ".join(missing), [], None
            return f"I couldn't find cities with an airport called {bad}. Which cities do you mean?"
        if missing:
            trip.assumptions.append(f"I couldn't find {', '.join(missing)}, so I left it out of the route.")
        d.destinations, d.destination_refs = kept, refs
        d.destination_ref, d.destination = refs[0], kept[0]
        if len(refs) < 2:  # e.g. "Paris and France" are the same place
            d.destinations, d.destination_refs, d.stop_nights = [], [], []
    if d.destination and d.destination_ref is None:
        ref = await _try_resolve(d.destination)
        if isinstance(ref, MCPToolError):
            bad, d.destination = d.destination, None
            return f"I couldn't find a city with an airport called '{bad}'. Which city do you mean?"
        if _wrong_country(d.destination, ref):
            # Never plan a trip in the wrong country: ask rather than guess.
            bad, d.destination = d.destination, None
            return (f"I couldn't pin down '{bad}' - the closest match I found is {ref.name}, {ref.country}. "
                    "Which city do you mean (the nearest big city or airport helps)?")
        d.destination_ref = ref
        trip.emit("place.resolved", role="destination", name=ref.name, country=ref.country)
    if d.origin_ref is None and (d.destination_ref is not None or d.region):  # no lookup before we know where
        ref = await (origin if origin is not None else _try_resolve(origin_text))
        if isinstance(ref, MCPToolError):
            d.origin_city = None
            return f"I couldn't find '{origin_text}'. Which city are you flying from?"
        d.origin_ref = ref
    if d.return_to and d.return_ref is None and d.origin_ref is not None:
        # Open-jaw: the city to fly home to.
        ref = await _try_resolve(d.return_to)
        if isinstance(ref, MCPToolError):
            bad, d.return_to = d.return_to, None
            return f"I couldn't find a city with an airport called '{bad}'. Which city do you want to fly home to?"
        d.return_ref = ref
        trip.emit("place.resolved", role="return", name=d.return_ref.name, country=d.return_ref.country)
        if d.return_ref.name == d.origin_ref.name and d.return_ref.country_code == d.origin_ref.country_code:
            d.return_to, d.return_ref = None, None  # that's home anyway
    # Never build a trip on a wrong assumption about where it starts.
    o = d.origin_ref
    dests = d.destination_refs or ([d.destination_ref] if d.destination_ref else [])
    if o is not None and dests:
        stated = bool(d.origin_city or d.origin)
        same_city = any(x.name == o.name and x.country_code == o.country_code for x in dests)
        same_country = any(x.country_code == o.country_code for x in dests)
        if same_city or (not stated and same_country):
            d.origin_ref, d.origin_city, d.origin = None, None, None
            return "Which city are you travelling from? I'll search flights from there."
    return None


async def check_requirements(state: GraphState) -> GraphState:
    trip = state["trip"]
    trip.pending_questions = []
    pace_before = (trip.traveler_profile.travel_style, trip.traveler_profile.walking_tolerance)
    req_notes = apply_requirements(trip, state["interpretation"].requirements)
    pace_changed = pace_before != (trip.traveler_profile.travel_style, trip.traveler_profile.walking_tolerance)
    if trip.selected_plan:
        trip.assumptions = trip.assumptions + req_notes
    trip.emit("requirements.updated", draft=trip.draft.model_dump(mode="json", exclude_defaults=True, exclude={"destination_ref", "origin_ref"}))
    question = await _resolve(trip)
    if question:
        trip.pending_questions.append(question)
    missing = missing_requirements(trip.draft)
    if missing or trip.pending_questions:
        trip.pending_questions += [REQUIRED_QUESTIONS[m] for m in missing if not (m == "destination" and question)]
        trip.status = "needs_input"
        return {"route": "ask"}
    if route_design.needs_design(trip):
        # Countries / a region, not cities: agree on the route with the traveller before researching it.
        d = trip.draft
        interp = state["interpretation"]
        message = state.get("message", "")
        # Accepted either by the "Plan this route" button or in the traveller's own words (understood by the model).
        decision = state.get("route_decision") or interp.route_decision
        if d.route_proposal and d.route_proposal.stops and decision == "accept":
            route_design.apply_proposal(trip)
            trip.emit("route.confirmed", stops=[s.city for s in d.route_proposal.stops])
        else:
            if d.route_proposal and message.strip():
                # Every answer counts, a repeated one too ("no, ONLY Bali" said twice means the last design missed it).
                d.route_feedback = (d.route_feedback + [message.strip()])[-8:]
            d.route_proposal = await route_design.propose(get_hub(), trip)
            trip.emit("route.proposed", version=d.route_proposal.version,
                      stops=[f"{s.city} ({s.nights})" for s in d.route_proposal.stops])
            trip.status = "needs_input"
            return {"route": "propose"}
    old = trip.trip_contract
    contract, assumptions = build_contract(trip)
    trip.assumptions = trip.assumptions + assumptions
    dirty = contract_dirty_domains(old, contract)
    trip.trip_contract = contract
    if trip.draft.planning_mode and (old is None or old.planning_mode != contract.planning_mode):
        trip.selected_mode = contract.planning_mode  # "the cheapest trip" -> show the budget plan
    trip.emit("trip.contract", contract=contract.model_dump(mode="json", exclude={"destination_ref", "origin_ref"}))
    if old is not None and trip.selected_plan and not dirty and not pace_changed:
        # Same destination, dates and pace: keep pinned days stable.
        trip.pinned_days = plan_activity_ids(trip.selected_plan)
    elif dirty or pace_changed:
        trip.pinned_days = {}  # a new pace reshapes every day
    actions = state["interpretation"].actions
    if old is not None and trip.selected_plan and actions:
        # "New dates, and pack more in": the plan changes ride along with the new trip frame.
        more_dirty, notes, _ = apply_actions(trip, actions)
        dirty = set(dirty or ()) | more_dirty
        trip.assumptions = trip.assumptions + notes
        if dirty:
            trip.pinned_days = {}
    return {"route": "research" if dirty or trip.research is None else "plan",
            "dirty": sorted(dirty or RESEARCH_DOMAINS), "previous_plan": trip.selected_plan}

async def ask(state: GraphState) -> GraphState:
    return {"reply": await narrative.compose_questions_reply(state["trip"])}


async def propose_route(state: GraphState) -> GraphState:
    return {"reply": await route_design.compose_message(state["trip"], state.get("message", ""))}


# Draft fields a feedback turn can change that the planner reads (places, priorities, must-haves / avoids).
_DRAFT_PLAN_FIELDS = {"must_visit", "wish_list", "priorities", "must_have", "avoid"}


async def apply_feedback(state: GraphState) -> GraphState:
    trip = state["trip"]
    interp = state["interpretation"]
    previous = trip.selected_plan
    learn_from_feedback(trip, interp.feedback, state.get("message", ""))
    # Requirements mentioned alongside feedback (e.g. a new wake-up time, "I walk everywhere", "we must see the
    # Pantheon") also apply - to the profile, the knobs and the draft's places and priorities.
    p = trip.traveler_profile

    def snapshot() -> tuple:
        return (p.model_dump(exclude={"learned", "explicit_fields"}), trip.user_knobs.model_dump(),
                trip.draft.model_dump(include=_DRAFT_PLAN_FIELDS))

    def searched_for() -> tuple:
        # What the restaurant and activity searches depend on: a new diet or interest needs new candidates.
        return sorted(p.dietary_restrictions), sorted(p.food_preferences), sorted(p.activity_preferences)

    before, research_before = snapshot(), searched_for()
    req_notes = apply_requirements(trip, interp.requirements)
    after = snapshot()
    dirty, notes, needs_replan = apply_actions(trip, interp.actions)
    notes = req_notes + notes
    needs_replan = needs_replan or before != after
    if searched_for() != research_before:
        dirty = set(dirty) | {"restaurants", "activities"}
    c = trip.trip_contract
    if c is not None and before[2] != after[2]:
        # Contract fields that live in the draft: the plan is built against the updated ones.
        c.must_have, c.avoid, c.priorities = list(trip.draft.must_have), list(trip.draft.avoid), list(trip.draft.priorities)
    trip.emit("feedback.received", actions=[a.model_dump() for a in interp.actions], notes=notes)
    trip.assumptions = notes
    if not needs_replan:
        trip.last_changes = notes
        return {"route": "respond", "previous_plan": previous}
    return {"route": "research" if dirty else "plan", "dirty": sorted(dirty), "previous_plan": previous}


# ---------------------------------------------------------------------------
# Research (parallel fan-out through MCP)
# ---------------------------------------------------------------------------


def _dirty(state: GraphState, domain: str) -> bool:
    return domain in set(state.get("dirty") or RESEARCH_DOMAINS) or state["trip"].research is None


async def research_setup(state: GraphState) -> GraphState:
    trip = state["trip"]
    c = trip.trip_contract
    assert c is not None
    fresh = _dirty(state, "destination")  # also true when there is no research yet
    if c.is_multi:
        net.allow_extra_calls(journey.SERPAPI_PER_EXTRA_STOP * (len(c.stops) - 1))
    if _dirty(state, "flights"):
        # Flights need only the route and dates, and are the slowest search: started before the destination facts.
        _EARLY_FLIGHTS[trip.trip_id] = asyncio.create_task(_journeys(get_hub(), trip, None))
    if c.is_multi:
        old_infos = trip.research.destination_info.get("stops") if trip.research else None
        if fresh or not old_infos or len(old_infos) != len(c.stops):
            infos = list(await asyncio.gather(*(research.research_destination(get_hub(), journey.stop_contract(c, i))
                                                for i in range(len(c.stops)))))
        else:
            infos = old_infos
        info = {**infos[0], "stops": infos}
    elif fresh:
        info = await research.research_destination(get_hub(), c)
    else:
        info = trip.research.destination_info
    # The city's published prices need only the city: fetched alongside flights, hotels and places instead of after
    # them (collect hands them to enrichment).
    places = [(journey.stop_contract(c, i), x) for i, x in enumerate(info["stops"])] if c.is_multi else [(c, info)]
    _LOCAL_PRICES[trip.trip_id] = [research.start_local_prices(get_hub(), sc, x.get("currency", "USD"))
                                   for sc, x in places]
    _EARLY_EVENTS[trip.trip_id] = asyncio.create_task(research.fetch_major_events(get_hub(), c))
    return {"r_info": info}


# Work started early for a later step (trip id -> task): the flight search (awaited by its research branch), strategy
# designs (awaited by plan()), each city's published prices and the world-famous events during the trip (awaited by
# collect()), and the reply and hotel reviews written while the expert reviews the plan (awaited by respond()).
_EARLY_FLIGHTS: dict[str, "asyncio.Task"] = {}
_EARLY_EVENTS: dict[str, "asyncio.Task"] = {}
_EARLY_STRATEGY: dict[str, "asyncio.Task"] = {}
_LOCAL_PRICES: dict[str, list[tuple["asyncio.Task", "asyncio.Task"]]] = {}
_EARLY_REPLY: dict[str, "asyncio.Task"] = {}
_EARLY_REVIEWS: dict[str, "asyncio.Task"] = {}


def _branch(domain: str, key: str, call):
    async def node(state: GraphState) -> GraphState:
        if not _dirty(state, domain):
            return {}
        try:
            value = await call(get_hub(), state["trip"], state["r_info"])
        except (MCPToolError, KeyError, ValueError) as exc:
            log.warning("research %s failed: %s", domain, exc)
            return {key: None, "r_errors": [f"{domain}: {exc}"]}
        return {key: value}
    node.__name__ = f"research_{domain}"
    return node


def _review_lookups(trip: TripState) -> int:
    """Guest-review searches before choosing a hotel (each costs a credit): only for noise-sensitive travellers,
    where noise changes the choice. Everyone else gets reviews for the chosen hotel only (finalize)."""
    return settings.hotel_review_lookups if trip.traveler_profile.noise_tolerance == "low" else 0


async def _offer_events(trip: TripState) -> None:
    """The world-famous events on during the trip (fetched since research_setup) become offers for the reply."""
    task = _EARLY_EVENTS.pop(trip.trip_id, None)
    if task is None:
        return
    try:
        found = await task
    except Exception as exc:  # noqa: BLE001 - an offer is optional: never fail the research over it
        log.info("major events skipped: %s", exc)
        return
    offers = research.offer_major_events(trip, found)
    if offers:
        trip.emit("events.offered", events=[o["name"] for o in offers])


async def collect(state: GraphState) -> GraphState:
    """Merge fresh research with anything still valid, then run the enrichment phase."""
    trip = state["trip"]
    old = trip.research or ResearchBundle()
    trip.metadata["refreshed"] = sorted(d for d in RESEARCH_DOMAINS if _dirty(state, d))

    domain_of = {"r_flights": "flights", "r_hotels": "hotels", "r_restaurants": "restaurants",
                 "r_activities": "activities", "r_weather": "weather"}

    def pick(key: str, fallback):
        # Old research is reused only where it is still valid. A domain that needed refreshing (new dates, a new city)
        # and failed stays empty and is reported - never silently filled with results for other dates or places.
        if state.get(key) is not None:
            return state.get(key)
        return [] if _dirty(state, domain_of[key]) else fallback

    fl = state.get("r_flights")
    if fl is None and _dirty(state, "flights"):
        fl = {"outbound": [], "return": [], "round_trips": [], "insights": {}, "legs": [[] for _ in range(len(c.stops) + 1)]
              if (c := trip.trip_contract) and c.is_multi else []}
    c = trip.trip_contract
    early = _LOCAL_PRICES.pop(trip.trip_id, None) or []  # each city's published prices, already on their way
    if c.is_multi:
        k = len(c.stops)
        old_stops = old.stops if len(old.stops) == k else []

        def per(key: str, attr: str, i: int):
            value = state.get(key)
            if value is not None and len(value) == k:
                return value[i]
            if _dirty(state, domain_of[key]):
                return []  # needed refreshing and failed: never reuse another route's or dates' results
            return getattr(old_stops[i], attr) if old_stops else []

        legs = fl["legs"] if fl else old.legs
        infos = state["r_info"]["stops"]
        stops = [ResearchBundle(destination_info=infos[i], flights_outbound=legs[i], flights_return=legs[i + 1],
                                hotels=per("r_hotels", "hotels", i), restaurants=per("r_restaurants", "restaurants", i),
                                attractions=per("r_activities", "attractions", i), weather=per("r_weather", "weather", i))
                 for i in range(k)]
        await asyncio.gather(*(research.enrich(get_hub(), b, journey.stop_contract(c, i),
                                               review_lookups=min(1, _review_lookups(trip)), price_scale=0.6,
                                               local_prices=early[i] if len(early) == k else None)
                               for i, b in enumerate(stops)))
        bundle = journey.merge_research(stops, legs, list(state.get("r_errors") or []) + (fl.get("errors", []) if fl else []))
        trip.research = bundle
        await _offer_events(trip)
        trip.emit("journey.researched", stops=[s.name for s in c.stops],
                  legs=[len(x) for x in legs], errors=bundle.errors)
        return {}
    bundle = ResearchBundle(
        destination_info=state["r_info"],
        flights_outbound=fl["outbound"] if fl else old.flights_outbound,
        flights_return=fl["return"] if fl else old.flights_return,
        round_trips=fl.get("round_trips", []) if fl else old.round_trips,
        flight_insights=fl["insights"] if fl else old.flight_insights,
        hotels=pick("r_hotels", old.hotels),
        restaurants=pick("r_restaurants", old.restaurants),
        attractions=pick("r_activities", old.attractions),
        weather=pick("r_weather", old.weather),
        errors=list(state.get("r_errors") or []),
    )
    # The strategist needs only the raw options (airlines, fares, hotels): it starts now and works while enrichment
    # prices places and reads guides, instead of waiting for planning (enrich cleans the data before its first await).
    trip.research = bundle
    _EARLY_STRATEGY[trip.trip_id] = asyncio.create_task(strategist.design(trip))
    await research.enrich(get_hub(), bundle, trip.trip_contract, review_lookups=_review_lookups(trip),
                          local_prices=early[0] if len(early) == 1 else None)
    await _offer_events(trip)
    for domain, n in (("flight", len(bundle.flights_outbound) + len(bundle.flights_return)), ("hotel", len(bundle.hotels)),
                      ("restaurant", len(bundle.restaurants)), ("activity", len(bundle.attractions)),
                      ("transfer", len(bundle.airport_transfers))):
        trip.emit(f"{domain}.researched", count=n)
    if bundle.errors:
        trip.emit("research.errors", errors=bundle.errors)
    return {}

# ---------------------------------------------------------------------------
# Plan -> validate -> repair loop
# ---------------------------------------------------------------------------


async def plan(state: GraphState) -> GraphState:
    trip = state["trip"]
    assert trip.trip_contract is not None and trip.research is not None
    # Constraints follow every change (a plan edit like "lower the budget" changes the contract directly).
    trip.trip_contract.constraints = constraints.derive(trip, trip.trip_contract)
    trip.trip_contract.priorities = list(trip.draft.priorities)
    if not state.get("iteration"):
        # Places named by the traveller ("add the Vatican Museums"): find them and force them into every plan.
        for note in await research.ensure_must_visit(get_hub(), trip):
            if note not in trip.assumptions:
                trip.assumptions.append(note)
        research.resolve_wishes(trip)
    await research.prepare_routing(trip.research)  # real walk/drive times (cached after the first call)
    knobs = dict(state.get("knobs") or {m: PlanKnobs() for m in PLANNING_MODES})
    candidates = dict(state.get("candidates") or {})
    # Places the critic added (not the traveller): welcome when they fit, never at the cost of a better stop.
    expert = {n.lower() for n in trip.metadata.get("expert_added", [])}
    expert_ids = [pid for key, pid in (trip.metadata.get("must_visit") or {}).items()
                  if pid and key.split("|", 1)[-1].lower() in expert]

    # What each plan means for THIS trip: designed by the strategist from the real options, then applied by the engine.
    early = _EARLY_STRATEGY.pop(trip.trip_id, None)
    if early is not None:
        try:
            await early  # started during research (cached on the trip when it finishes)
        except Exception as exc:  # the regular call below falls back to the defaults
            log.info("early strategy failed: %s", exc)
    strategies = await strategist.design(trip)
    if not state.get("iteration"):
        sig: dict[str, list[str]] = {}
        for mode in ("experience",):  # signature experiences are what the experience plan is about
            strat = getattr(strategies, mode)
            if trip.trip_contract.is_multi:
                # Each city's own signature experiences, found in that city (ids are per stop; a stop ignores others').
                ids: list[str] = []
                for i, stop in enumerate(trip.trip_contract.stops):
                    names = strategist.for_city(strat, stop.name).activities.signature_experiences
                    if names and strat.cities:
                        ids += await research.find_places(get_hub(), trip, names, stop=i)
                if ids:
                    sig[mode] = ids
            elif strat.activities.signature_experiences:
                sig[mode] = await research.find_places(get_hub(), trip, strat.activities.signature_experiences)
        trip.metadata["signature_ids"] = sig

    def build(mode: str, pins: dict) -> TripPlan:
        strat = getattr(strategies, mode)
        mode_knobs = trip.user_knobs.merged(knobs[mode])
        mode_knobs.expert_picks = expert_ids
        mode_knobs.max_price_level = min(mode_knobs.max_price_level, strat.food.max_price_level)
        mode_knobs.density_delta += strat.activities.pace_delta
        if strat.transport == "taxi":
            mode_knobs.prefer_taxi = True
        elif strat.transport == "public":
            mode_knobs.transfer_mode = mode_knobs.transfer_mode or "bus"
        if mode == "budget":
            mode_knobs.skip_snacks = True  # no optional coffee / dessert stops on the money-saving plan
        mode_knobs.signature_picks = list((trip.metadata.get("signature_ids") or {}).get(mode, []))
        if trip.trip_contract.is_multi:
            plan_ = journey.plan_journey(trip.trip_contract, trip.traveler_profile, trip.research, mode,
                                         mode_knobs, settings.budget_buffer_ratio, pins, strat)
        else:
            plan_ = build_plan(PlanContext(
                contract=trip.trip_contract, profile=trip.traveler_profile, research=trip.research, mode=mode,
                knobs=mode_knobs, buffer_ratio=settings.budget_buffer_ratio, pinned_days=pins, strategy=strat))
        plan_.pitch, plan_.pitch_ar = strat.headline, strat.headline_ar
        return plan_

    c = trip.trip_contract
    finding = trip.draft.find_cheapest and not trip.draft.budget_amount
    if finding and not state.get("iteration"):
        # "The cheapest trip possible": plan the cheapest good trip with no limit, and make its cost the budget
        # (again on every replan, so "pack more in" moves it). The other modes are then planned against it -
        # they show what a bit more money buys.
        c.budget.amount = FIND_CHEAPEST_PLACEHOLDER
        cheapest = build("budget", trip.pinned_days if trip.selected_mode == "budget" else {})
        c.budget.amount = nice_amount(cheapest.budget.total) if cheapest.budget else c.budget.amount
        trip.metadata["found_budget"] = c.budget.amount
        trace.step(trip, "planner", "decision",
                   f"Cheapest good plan costs {cheapest.budget.total:,.0f} {c.budget.currency}: budget set to "
                   f"{c.budget.amount:,.0f}.")

    # Upgrades: comfort / experience may spend a bit more than the budget to keep their promise (the strategist sets
    # how much; after "the cheapest trip possible" every other mode may spend up to 30% more than the cheapest).
    # They are planned and validated against that limit, then measured against the real budget, so the cards show
    # honestly what each upgrade costs. The budget and balanced plans always respect the budget.
    stretch = {m: (1.3 if finding else 1 + getattr(strategies, m).budget_stretch) if m not in ("budget", "balanced")
               else 1.0 for m in PLANNING_MODES}
    trip.metadata["budget_stretch"] = stretch
    repair_prev: dict[str, TripPlan] = {}
    for mode in PLANNING_MODES:
        existing = candidates.get(mode)
        if existing and existing.validation and existing.validation.result == "PASS":
            continue
        if existing and mode in (state.get("repair_stalled") or []):
            continue  # its last repair made things worse: keep the plan as it is
        if existing and existing.validation:
            repair_prev[mode] = existing  # compared with the rebuilt plan in validate()
        pins = trip.pinned_days if mode == trip.selected_mode else {}
        if stretch[mode] > 1:
            real = c.budget.amount
            c.budget.amount = real * stretch[mode]
            try:
                new = build(mode, pins)
            finally:
                c.budget.amount = real
            new.budget = compute_budget(new, c, trip.research.fx_rates, settings.budget_buffer_ratio)
            new.within_budget = new.budget.total <= real
        else:
            new = build(mode, pins)
        if existing:
            new.repair_log = existing.repair_log + new.repair_log
        candidates[mode] = new

    # Four cards that are really one plan help no one: an upgrade that came out with the same hotel and flights as a
    # cheaper plan is rebuilt without that hotel (it then shows what the upgrade really costs).
    def hotels_of(p: TripPlan) -> list[str]:
        # Every city's hotel on a multi-city trip, else the one hotel.
        return [s.hotel.id for s in p.stops if s.hotel] if p.stops else ([p.hotel.id] if p.hotel else [])

    def core(p: TripPlan) -> tuple:
        return (tuple(hotels_of(p)), tuple(f.id for f in p.legs) if p.legs else
                (p.outbound_flight.id if p.outbound_flight else None, p.return_flight.id if p.return_flight else None))

    _budget_is_cheapest(candidates)  # first, so a plan copied onto the budget card is then made different below
    if not state.get("iteration"):
        for mode in ("comfort", "experience"):
            twin = next((m for m in ("budget", "balanced", "comfort") if m != mode and m in candidates
                         and core(candidates[m]) == core(candidates[mode])), None)
            mine = hotels_of(candidates[mode])
            others = [h for h in trip.research.hotels if h.id not in mine]
            if twin is None or not mine or not others or stretch[mode] <= 1:
                continue
            knobs[mode] = knobs[mode].model_copy(update={"hotel_exclude": knobs[mode].hotel_exclude + mine})
            real = c.budget.amount
            c.budget.amount = real * stretch[mode]
            try:
                new = build(mode, trip.pinned_days if mode == trip.selected_mode else {})
            finally:
                c.budget.amount = real
            new.budget = compute_budget(new, c, trip.research.fx_rates, settings.budget_buffer_ratio)
            new.within_budget = new.budget.total <= real
            new.repair_log.append(f"Was identical to the {twin} plan: picked a different hotel that fits this plan.")
            candidates[mode] = new
    return {"candidates": candidates, "knobs": knobs, "iteration": state.get("iteration", 0) + 1,
            "repair_prev": repair_prev}


async def validate(state: GraphState) -> GraphState:
    trip = state["trip"]
    c = trip.trip_contract
    for mode, p in state["candidates"].items():
        walk = trip.user_knobs.merged(state["knobs"][mode]).walk_tolerance_override
        real = c.budget.amount
        stretch = (trip.metadata.get("budget_stretch") or {}).get(mode, 1.0)
        c.budget.amount = real * stretch  # an upgrade's own limit
        if stretch > 1 and p.budget:
            # An upgrade is priced honestly (the card shows the extra), never repaired back into the budget plan.
            c.budget.amount = max(c.budget.amount, p.budget.total * (1 + settings.budget_buffer_ratio) + 1)
        try:
            p.validation = validate_plan(p, c, trip.traveler_profile, trip.research, settings.budget_buffer_ratio, walk)
        finally:
            c.budget.amount = real
    # Repair accountability: compare each repaired plan with the one before the repair.
    candidates, stalled = dict(state["candidates"]), list(state.get("repair_stalled") or [])
    history = trip.metadata.setdefault("repair_history", [])
    for mode, before in (state.get("repair_prev") or {}).items():
        after = candidates.get(mode)
        if after is None or after is before or not before.validation or not after.validation:
            continue
        old = {(v.check, v.place_id, v.day) for v in before.validation.errors}
        new = {(v.check, v.place_id, v.day) for v in after.validation.errors}
        fixed, introduced = old - new, new - old
        record = {"mode": mode, "iteration": state.get("iteration", 0), "errors_before": len(old),
                  "errors_after": len(new), "fixed": sorted({x[0] for x in fixed}),
                  "introduced": sorted({x[0] for x in introduced}),
                  "cost_before": before.budget.total if before.budget else None,
                  "cost_after": after.budget.total if after.budget else None}
        # A repair that leaves more problems than it solved is undone - never trade one violation for worse ones.
        if len(new) > len(old) or (introduced and len(new) >= len(old)):
            record["reverted"] = True
            candidates[mode] = before
            stalled.append(mode)
            before.repair_log.append("Reverted a repair that caused new problems (" +
                                     ", ".join(sorted({x[0] for x in introduced})) + ").")
        history.append(record)
    del history[:-40]
    return {"candidates": candidates, "repair_stalled": stalled, "repair_prev": {}}


def after_validate(state: GraphState) -> str:
    stalled = set(state.get("repair_stalled") or [])
    failing = [p for m, p in state["candidates"].items() if p.validation and p.validation.result == "FAIL"
               and m not in stalled]
    if failing and state.get("iteration", 0) < settings.max_repair_iterations:
        return "repair"
    return "finalize"


async def repair_node(state: GraphState) -> GraphState:
    trip = state["trip"]
    knobs = dict(state["knobs"])
    progressed = False
    stalled = set(state.get("repair_stalled") or [])
    for mode, p in state["candidates"].items():
        if p.validation and p.validation.result == "FAIL" and mode not in stalled:
            new_knobs, log_lines = repair(p, p.validation, knobs[mode], trip.research, trip.traveler_profile)
            knobs[mode] = new_knobs
            p.repair_log.extend(log_lines)
            progressed = progressed or bool(log_lines)
            trip.emit("itinerary.repaired", mode=mode, actions=log_lines)
    # Nothing left to try: stop iterating.
    return {"knobs": knobs, "iteration": state["iteration"] if progressed else settings.max_repair_iterations}


EXPERT_PICK = "Added by the expert review: a highlight you shouldn't miss"


def _label_expert_picks(trip: TripState, plans: dict[str, TripPlan]) -> None:
    """Places the critic added are shown as expert picks, not as places the traveller asked for."""
    picks = {n.lower() for n in trip.metadata.get("expert_added", [])}
    if not picks:
        return
    for p in plans.values():
        for d in p.days:
            for i in d.items:
                if i.explanation and i.explanation[0] == "You asked to visit this place" and i.title.lower() in picks:
                    i.explanation[0] = EXPERT_PICK


def _budget_is_cheapest(plans: dict[str, TripPlan]) -> None:
    """The budget plan must never cost more than another mode: if one came out cheaper, it becomes the budget plan."""
    b = plans.get("budget")
    if not b or not b.budget:
        return
    cheaper = min((p for m, p in plans.items() if m != "budget" and p.budget), key=lambda p: p.budget.total, default=None)
    if cheaper is not None and cheaper.budget.total < b.budget.total - 0.5:
        copy = cheaper.model_copy(deep=True)
        copy.mode, copy.pitch, copy.pitch_ar = "budget", b.pitch, b.pitch_ar
        copy.repair_log.append(f"Budget plan: the {cheaper.mode} plan came out cheaper, so it is the budget plan now.")
        plans["budget"] = copy


async def finalize(state: GraphState) -> GraphState:
    trip = state["trip"]
    c = trip.trip_contract
    _label_expert_picks(trip, state["candidates"])
    _budget_is_cheapest(state["candidates"])
    for mode, p in state["candidates"].items():
        p.score = score_plan(p, c, trip.traveler_profile, trip.research, mode)  # type: ignore[arg-type]
        trip.emit("itinerary.validated", mode=mode, result=p.validation.result if p.validation else None,
                  score=p.score.total, total=p.budget.total if p.budget else None)
    trip.plans = state["candidates"]
    # With a hard budget, never present an over-budget plan as the default when one fits.
    selected = trip.plans.get(trip.selected_mode)
    if c and c.budget.hard_limit and selected and not selected.within_budget:
        fitting = [m for m, p in trip.plans.items() if p.within_budget]
        if fitting:
            best = max(fitting, key=lambda m: trip.plans[m].score.rank_key() if trip.plans[m].score else (False,))
            trip.assumptions.append(f"The {trip.selected_mode} plan went over your hard budget, so I'm showing the "
                                    f"{best} plan instead.")
            trip.selected_mode = best  # type: ignore[assignment]
    # Requirements the selected plan can't meet, with ranked, priced ways out (offered, never applied silently).
    trip.metadata["conflicts"] = [x.model_dump(mode="json") for x in conflicts.analyze(trip)]
    trip.pinned_days = plan_activity_ids(trip.selected_plan) if trip.selected_plan else {}
    changes = diff_plans(state.get("previous_plan"), trip.selected_plan)
    trip.last_changes = (trip.assumptions + changes) if state.get("previous_plan") else []
    trip.status = "planned"
    trip.emit("itinerary.generated", mode=trip.selected_mode, iterations=state.get("iteration", 0))
    return {}


def _errors(p: TripPlan | None) -> int:
    return len(p.validation.errors) if p and p.validation else 0


def _score(p: TripPlan | None) -> float:
    return p.score.total if p and p.score else 0.0


def _reality(p: TripPlan | None) -> int:
    return sum(1 for v in (p.validation.errors if p and p.validation else []) if v.check == "reality")


def _coverage(p: TripPlan | None) -> int:
    return sum(d.activity_count for d in p.days) if p else 0


def refinement_verdict(trip: TripState, before: TripPlan | None, after: TripPlan | None) -> tuple[bool, list[str]]:
    """Multi-objective acceptance of the critic's refinement - every condition must hold, a better score alone
    is never enough: no new hard violations, no new ungrounded items, the traveller's requirements and
    preferences not worse, no lost icon or noticeable loss of coverage, and quality at least as good."""
    if not before or not after or not before.score or not after.score:
        return False, ["missing plan or score"]
    b, a = before.score, after.score
    reasons = []
    if _errors(after) > _errors(before):
        reasons.append(f"hard violations {_errors(before)} -> {_errors(after)}")
    if _reality(after) > _reality(before):
        reasons.append("an ungrounded item appeared")
    if a.constraint_satisfaction < b.constraint_satisfaction:
        reasons.append(f"requirements met {b.constraint_satisfaction}% -> {a.constraint_satisfaction}%")
    if a.preference_satisfaction < b.preference_satisfaction - 5:
        reasons.append(f"preferences met {b.preference_satisfaction}% -> {a.preference_satisfaction}%")
    lost = _lost_icons(trip, before, after)
    if lost:
        reasons.append("would drop " + ", ".join(lost))
    if _coverage(after) < _coverage(before) - 1:
        reasons.append(f"sights {_coverage(before)} -> {_coverage(after)}")
    if a.quality < b.quality - 1:
        reasons.append(f"quality {b.quality} -> {a.quality}")
    return not reasons, reasons


def _lost_icons(trip: TripState, before: TripPlan | None, after: TripPlan | None) -> list[str]:
    """World-famous sights in the plan before a refinement that are gone after it (the score can't see that)."""
    if not before or not after or not trip.research:
        return []
    from .engine.ranking import icon_ids

    kept = {i.place_id for d in after.days for i in d.items if i.place_id}
    had = {i.place_id for d in before.days for i in d.items if i.place_id}
    icons = icon_ids(trip.research.attractions)
    return [p.name for p in trip.research.attractions if p.id in had - kept and p.id in icons]


async def critic_node(state: GraphState) -> GraphState:
    """Self-reflection: an expert review of a new plan; safe fixes are applied and verified, others suggested."""
    trip = state["trip"]
    backup = state.get("critic_backup")
    if backup:  # second pass: keep the refined plan only if it is at least as good
        trip.metadata.pop("strategies_locked", None)
        before, after = backup["plans"][backup["mode"]], trip.selected_plan
        crit = trip.metadata.get("critique") or {}
        accepted, why_not = refinement_verdict(trip, before, after)
        if not accepted:
            trip.plans, trip.selected_mode = backup["plans"], backup["mode"]
            trip.user_knobs, trip.traveler_profile = backup["knobs"], backup["profile"]
            trip.pinned_days, trip.excluded_ids = backup["pins"], backup["excluded"]
            trip.draft.must_visit = backup["must_visit"]
            trip.metadata["expert_added"] = backup["expert_added"]
            trip.metadata.update({k: v for k, v in (backup.get("meta") or {}).items() if v is not None})
            for i in crit.get("issues", []):
                i["applied"] = False
            trace.step(trip, "critic", "decision",
                       "Refinement rejected (" + "; ".join(why_not) + "). Kept the original plan.")
        else:
            early = _EARLY_REPLY.pop(trip.trip_id, None)
            if early is not None:
                early.cancel()  # written for the plan before the refinement: respond() writes a new one
            crit["changes"] = diff_plans(before, after)
            # A place the critic added that didn't fit into any day (e.g. a far day trip at a relaxed pace) was not
            # applied: it is offered as a suggestion, and not forced into later replans.
            landed = {n.lower() for n, day in (after.requested or {}).items() if day}
            for i in crit.get("issues", []):
                name = (i.get("text") or "").lower()
                if i.get("applied") and i.get("action") == "add_place" and name not in landed:
                    i["applied"] = False
                    trip.draft.must_visit = [n for n in trip.draft.must_visit if n.lower() != name]
                    trip.metadata["expert_added"] = [n for n in trip.metadata.get("expert_added", [])
                                                     if n.lower() != name]
                    for p in trip.plans.values():  # else the reply lists it as a place the traveller asked for
                        p.requested = {k: v for k, v in p.requested.items() if k.lower() != name}
            trace.step(trip, "critic", "decision",
                       f"Refinement kept: score {_score(before)} -> {_score(after)}.", changes=crit["changes"][:6])
        _publish_suggestions(trip)
        return {"critic_next": "respond"}

    if trip.metadata.get("critique"):
        crit = trip.metadata["critique"]
        crit["fresh"] = False  # an older review stays visible, but isn't announced again
        said = state.get("message", "").strip()
        for i in crit.get("issues", []):  # the traveller tapped one of the critic's ideas: it's done now
            if said and (i.get("suggestion") or "").strip() == said:
                i["applied"] = True
    # Only new plans are reviewed: on feedback turns the traveller is steering, and replans stay ~1 s.
    if state.get("previous_plan") is not None or not trip.selected_plan:
        return {"critic_next": "respond"}
    # While the expert reviews: the reply for this plan and its hotel's guest reviews. Most reviews keep the plan as
    # it is (no safe fix, or the refinement isn't better), and then both are ready when respond() needs them.
    _EARLY_REPLY[trip.trip_id] = asyncio.create_task(narrative.write_plan_reply(trip, narrative.plan_reply_facts(trip)))
    _EARLY_REVIEWS[trip.trip_id] = asyncio.create_task(research.fetch_hotel_reviews(
        get_hub(), research.reviews_todo(trip, trip.plans)))
    critique = await critic.review(trip)
    if critique is None:
        return {"critic_next": "respond"}
    fixes = critic.safe_fixes(trip, critique)
    applied = {id(issue) for issue, _ in fixes}
    trip.metadata["critique"] = {
        "fresh": True, "mode": trip.selected_mode, "quality": critique.quality, "verdict": critique.verdict, "verdict_ar": critique.verdict_ar,
        "strengths": critique.strengths[:3],
        "issues": [{"severity": i.severity, "day": i.day, "problem": i.problem, "problem_ar": i.problem_ar,
                    "suggestion": i.suggestion, "action": i.fix.action if i.fix else None,
                    "text": i.fix.text if i.fix else None, "applied": id(i) in applied}
                   for i in critique.issues],
    }
    if not fixes:
        _publish_suggestions(trip)
        return {"critic_next": "respond"}
    backup = {"plans": {m: p.model_copy(deep=True) for m, p in trip.plans.items()}, "mode": trip.selected_mode,
              "knobs": trip.user_knobs.model_copy(deep=True), "profile": trip.traveler_profile.model_copy(deep=True),
              "pins": dict(trip.pinned_days), "excluded": list(trip.excluded_ids),
              "must_visit": list(trip.draft.must_visit)}
    backup["expert_added"] = list(trip.metadata.get("expert_added", []))
    # The refinement is compared against the same strategies (the critic's edits must not re-design the plans).
    backup["meta"] = {k: trip.metadata.get(k) for k in ("strategies", "signature_ids", "budget_stretch")}
    trip.metadata["strategies_locked"] = True
    # Places the critic adds go through the must-visit mechanism, but they are the expert's picks, not the traveller's.
    trip.metadata["expert_added"] = backup["expert_added"] + [a.text for _, a in fixes if a.action == "add_place" and a.text]
    _, notes, _ = apply_actions(trip, [a for _, a in fixes], by_traveller=False)  # the expert's edits, not the traveller's
    for issue, a in fixes:
        trace.step(trip, "critic", "fix", f"{a.action}({a.text or a.category or a.day or ''}) for: {issue.problem}")
    trip.emit("plan.self_review", quality=critique.quality, fixes=notes)
    # Rebuild every mode with the fixes, then validate / repair / score again before the second critic pass.
    return {"critic_next": "plan", "critic_backup": backup, "candidates": {}, "iteration": 0,
            "repair_stalled": [], "repair_prev": {}}


def _publish_suggestions(trip: TripState) -> None:
    crit = trip.metadata.get("critique") or {}
    trip.metadata["suggestions"] = [i["suggestion"] for i in crit.get("issues", [])
                                    if not i.get("applied") and i.get("suggestion")][:3]


async def respond(state: GraphState) -> GraphState:
    trip = state["trip"]
    if not trip.selected_plan:
        return {"reply": "I couldn't build a plan yet. " + "; ".join(trip.research.errors if trip.research else [])}
    # Started while the expert reviewed this plan (critic_node); gone when the refinement changed the plan.
    early, reviews = _EARLY_REPLY.pop(trip.trip_id, None), _EARLY_REVIEWS.pop(trip.trip_id, None)

    async def insights() -> None:
        # What guests say about the hotel of the plan shown (review-analyst agent). Once per turn - after the critic
        # - so a refined plan doesn't cost a second review search; hotels already analysed cost nothing. The reply
        # doesn't read the reviews (the hotel card does), so both run at the same time.
        prefetched = None
        if reviews is not None:
            try:
                prefetched = await reviews
            except Exception as exc:  # noqa: BLE001 - fetched again below
                log.info("hotel reviews prefetch failed: %s", exc)
        await research.plan_hotel_insights(get_hub(), trip, trip.plans, prefetched)

    async def reply() -> tuple[narrative.PlanReply, bool]:
        if early is not None:
            try:
                return await early, True
            except Exception as exc:  # noqa: BLE001 - written now instead
                log.info("early reply failed: %s", exc)
        return await narrative.compose_plan_reply(trip), False

    _, (out, ahead) = await asyncio.gather(insights(), reply())
    critic_ideas = [s for s in trip.metadata.get("suggestions", []) if s not in out.suggestions]
    if ahead:
        # Written while the expert reviewed (nothing it proposed was applied): its verdict closes the reply and its
        # ideas come first among the one-tap suggestions.
        line = narrative.review_line(trip, bool(critic_ideas))
        trip.metadata["suggestions"] = (critic_ideas[:2] + out.suggestions)[:4]
        return {"reply": out.reply + (f"\n\n{line}" if line else "")}
    # The reply model's own next steps for this trip; the critic's open ideas fill any space left.
    trip.metadata["suggestions"] = (out.suggestions + critic_ideas)[:4]
    return {"reply": out.reply}


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def _per_city(fn):
    """A single-city research call; for a multi-city trip, one call per stop (in parallel)."""
    async def call(hub, trip, info):
        c = trip.trip_contract
        if c.is_multi:
            return await journey.per_stop(c, info["stops"], lambda sc, si: fn(hub, trip, sc, si))
        return await fn(hub, trip, c, info)
    return call


async def _journeys(hub, trip, info):
    c = trip.trip_contract
    return await (journey.research_legs(hub, c) if c.is_multi else research.research_flights(hub, c))


async def _flights(hub, trip, info):
    early = _EARLY_FLIGHTS.pop(trip.trip_id, None)  # started by research_setup
    return await (early if early is not None else _journeys(hub, trip, info))


BRANCHES = [
    ("flights", "r_flights", _flights),
    ("hotels", "r_hotels", _per_city(lambda hub, trip, c, info: research.research_hotels(hub, c))),
    ("restaurants", "r_restaurants", _per_city(lambda hub, trip, c, info: research.research_restaurants(
        hub, c, info["currency"], trip.traveler_profile.dietary_restrictions))),
    ("activities", "r_activities", _per_city(lambda hub, trip, c, info: research.research_activities(
        hub, c, info["currency"], trip.traveler_profile.activity_preferences))),
    ("weather", "r_weather", _per_city(lambda hub, trip, c, info: research.research_weather(hub, c))),
]


def _timed(name: str, fn):
    """A graph step that records how long it ran (the turn's path, drawn in the UI as the message's route)."""
    async def node(state: GraphState) -> GraphState:
        started = time.perf_counter()
        try:
            return await fn(state)
        finally:
            telemetry.record_node(name, (time.perf_counter() - started) * 1000)
    node.__name__ = name
    return node


def build_graph():
    g = StateGraph(GraphState)
    steps = {"understand": understand, "answer": answer, "check_requirements": check_requirements, "ask": ask,
             "propose_route": propose_route, "apply_feedback": apply_feedback, "research_setup": research_setup,
             **{f"research_{domain}": _branch(domain, key, fn) for domain, key, fn in BRANCHES},
             "collect": collect, "plan": plan, "validate": validate, "repair": repair_node, "finalize": finalize,
             "critic": critic_node, "respond": respond}
    for name, fn in steps.items():
        g.add_node(name, _timed(name, fn))

    g.add_edge(START, "understand")
    g.add_conditional_edges("understand", lambda s: s["route"],
                            {"answer": "answer", "requirements": "check_requirements", "feedback": "apply_feedback"})
    g.add_edge("answer", END)
    g.add_conditional_edges("check_requirements", lambda s: s["route"],
                            {"ask": "ask", "propose": "propose_route", "research": "research_setup", "plan": "plan"})
    g.add_edge("ask", END)
    g.add_edge("propose_route", END)
    g.add_conditional_edges("apply_feedback", lambda s: s["route"],
                            {"research": "research_setup", "plan": "plan", "respond": "respond"})
    branch_nodes = [f"research_{d}" for d, _, _ in BRANCHES]
    for n in branch_nodes:
        g.add_edge("research_setup", n)
    g.add_edge(branch_nodes, "collect")
    g.add_edge("collect", "plan")
    g.add_edge("plan", "validate")
    g.add_conditional_edges("validate", after_validate, {"repair": "repair", "finalize": "finalize"})
    g.add_edge("repair", "plan")
    g.add_edge("finalize", "critic")
    g.add_conditional_edges("critic", lambda s: s["critic_next"], {"plan": "plan", "respond": "respond"})
    g.add_edge("respond", END)
    return g.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


_GRAPH_CONFIG = {"recursion_limit": 80}


def _begin_turn(trip: TripState, message: str, preset_actions: list[Action] | None,
                route_decision: str | None) -> dict:
    """Shared turn setup: record the message, reset the per-turn network / trace state, return the graph inputs."""
    if message:
        trip.conversation.append(ChatMessage(role="user", content=message))
    net.start_turn()
    trace.start(trip)
    trip.metadata["refreshed"] = []  # research domains refreshed this turn (set by collect)
    trip.metadata["suggestions"] = []
    trip.metadata.pop("turn_request", None)
    return {"trip": trip, "message": message, "preset_actions": preset_actions or [], "route_decision": route_decision}


async def run_turn(trip: TripState, message: str = "", preset_actions: list[Action] | None = None,
                   route_decision: str | None = None) -> tuple[TripState, str]:
    inputs = _begin_turn(trip, message, preset_actions, route_decision)
    started = time.perf_counter()
    usage = telemetry.new_usage()
    token = telemetry.USAGE.set(usage)
    try:
        result = await get_graph().ainvoke(inputs, _GRAPH_CONFIG)
    finally:
        telemetry.USAGE.reset(token)
    trip = result["trip"]
    reply = result.get("reply", "")
    _finish_turn(trip, usage, started)
    trip.conversation.append(ChatMessage(role="assistant", content=reply))
    return trip, reply


async def run_turn_stream(trip: TripState, message: str = "", preset_actions: list[Action] | None = None,
                          route_decision: str | None = None):
    """Same as run_turn, but yields live progress: every graph node and every MCP tool call as it completes.

    Yields dicts: {"type": "node", "node": ...}, {"type": "tool", "server", "tool", "ok", "ms"},
    {"type": "preview", "trip": TripState} once the new plan is built (before the expert review and the reply),
    and finally {"type": "done", "trip": TripState, "reply": str} - or {"type": "error"} and no "done" when the turn
    failed (nothing half-processed is saved).
    """
    inputs = _begin_turn(trip, message, preset_actions, route_decision)
    started = time.perf_counter()
    queue: asyncio.Queue = asyncio.Queue()
    hub = get_hub()

    turn_id = uuid.uuid4().hex

    def on_tool(event: dict) -> None:
        if event.get("turn") != turn_id:
            return  # another user's turn: never leaked into this stream
        queue.put_nowait({"type": "tool", **{k: v for k, v in event.items() if k != "turn"}})

    final: dict = {}
    failed = False
    previewed = False

    async def runner() -> None:
        nonlocal failed, previewed
        try:
            async for mode, chunk in get_graph().astream(inputs, _GRAPH_CONFIG, stream_mode=["updates", "values"]):
                if mode == "updates":
                    for node in chunk:
                        queue.put_nowait({"type": "node", "node": node, "ms": round((time.perf_counter() - started) * 1000)})
                        if node == "finalize" and not previewed and not _what_if(trip):
                            # The plan is ready: shown now, while the expert reviews it and the reply is written
                            # (a copy - the turn goes on changing the trip). A what-if is never shown as the plan.
                            previewed = True
                            queue.put_nowait({"type": "preview", "trip": trip.model_copy(deep=True)})
                else:
                    final.update(chunk)
        except Exception as exc:  # surfaced to the UI instead of a silent hang
            failed = True
            log.exception("turn failed: %s", net.redact(str(exc)))  # details stay in the server log
            queue.put_nowait({"type": "error", "message": "Something went wrong while planning - please try again."})
        finally:
            queue.put_nowait(None)

    hub.listeners.append(on_tool)
    usage = telemetry.new_usage()
    token = CURRENT_TURN.set(turn_id)  # copied into the runner task and every node/tool call it starts
    utoken = telemetry.USAGE.set(usage)
    try:
        task = asyncio.create_task(runner())
    finally:
        CURRENT_TURN.reset(token)
        telemetry.USAGE.reset(utoken)
    try:
        while (event := await queue.get()) is not None:
            yield event
    finally:
        hub.listeners.remove(on_tool)
        await task
    if failed or "trip" not in final:
        return  # no "done": the stored trip stays as it was before this turn
    trip = final["trip"]
    reply = final.get("reply", "")
    _finish_turn(trip, usage, started)
    trip.conversation.append(ChatMessage(role="assistant", content=reply))
    yield {"type": "done", "trip": trip, "reply": reply}


def _what_if(trip: TripState) -> bool:
    """A turn whose plan is only compared (a what-if), or that switches to the compared version (service._settle)."""
    return bool(trip.metadata.get("hypothetical") or trip.metadata.get("apply_whatif"))


def _finish_turn(trip: TripState, usage: dict, started: float) -> None:
    """Per-turn telemetry on the trip (latency, model calls and tokens, cost estimate, tools, live searches) and one
    structured log line - counts only, never the conversation."""
    ms = (time.perf_counter() - started) * 1000
    trip.metadata["last_turn_ms"] = round(ms)
    trip.metadata["usage"] = telemetry.finish(usage, net.serpapi_calls_this_turn(), ms)
    trip.metadata["turn_path"] = telemetry.path(usage, ms)  # the route this message took (the UI draws it)
    plan = trip.selected_plan
    telemetry.event("turn", trip=trip.trip_id, mode=trip.selected_mode,
                    validation=plan.validation.result if plan and plan.validation else None,
                    repairs=len(trip.metadata.get("repair_history") or []),
                    conflicts=len(trip.metadata.get("conflicts") or []), **trip.metadata["usage"])
