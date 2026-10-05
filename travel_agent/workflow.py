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

from . import conflicts, journey, narrative, net, research, route_design
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
    nice_amount,
)

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
    timings: dict[str, float]
    critic_next: str              # "plan" (apply the critic's fixes) or "respond"
    critic_backup: dict[str, Any]  # the plans before the critic's fixes (restored if the refinement is worse)
    # research partials (one key per parallel branch)
    r_info: dict[str, Any]
    r_flights: dict[str, Any]
    r_hotels: list
    r_restaurants: list
    r_activities: list
    r_weather: list
    r_transfers: list
    r_fx: tuple
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
    names = {}
    if trip.research:
        names = {p.id: p.name for p in trip.research.attractions + trip.research.restaurants}
    pending = trip.draft.route_proposal if trip.draft.route_proposal and not trip.draft.route_confirmed else None
    context = {
        "has_plan": has_plan,
        "pending_route_proposal": [f"{s.city}, {s.country} ({s.nights} nights)" for s in pending.stops] if pending else None,
        "draft": trip.draft.model_dump(mode="json", exclude_defaults=True,
                                       exclude={"destination_ref", "origin_ref", "destination_refs", "route_proposal"}),
        "contract": trip.trip_contract.model_dump(mode="json") if trip.trip_contract else None,
        "plan_days": [f"Day {d.day}: {d.title}" for d in trip.selected_plan.days] if trip.selected_plan else [],
        "plan_total": (f"{trip.selected_plan.budget.total:.0f} {trip.selected_plan.budget.currency}"
                       if trip.selected_plan and trip.selected_plan.budget else None),
        "traveller_profile": trip.traveler_profile.model_dump(include={"travel_style", "walking_tolerance",
                                                                       "transport_preference", "activity_preferences"}),
        "recent_conversation": recent_turns(trip),   # short-term memory: what was just said
        "pending_what_if": trip.metadata.get("pending_whatif_summary"),
    }
    interp, notes = None, []
    if has_plan and not pending:
        # The trip agent decides what the message needs: look things up and answer, or change the trip.
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
            interp = TurnInterpretation(intent="feedback", actions=ch.actions, requirements=ch.requirements,
                                        feedback=ch.feedback, route_change_request=ch.route_change_request,
                                        hypothetical=ch.hypothetical, source="agent")
    if interp is None:
        interp, notes = await interpret(message, has_plan, names, context)
    if interp.source == "unavailable":
        return {"route": "answer", "reply": narrative.unavailable_reply(message), "interpretation": interp}
    if has_plan and interp.apply_pending and trip.metadata.get("pending_whatif_summary"):
        trip.metadata["apply_whatif"] = True
        return {"route": "answer", "reply": "-", "interpretation": interp}
    if has_plan and interp.hypothetical:
        trip.metadata["hypothetical"] = True  # plan it (on the service's copy), then show the comparison
    # A free-text "add_place" without a place name carries nothing to add ("add more things" is a density change).
    interp.actions = [a for a in interp.actions if not (a.action in ("add_place", "replace_item") and not (a.text or "").strip())]
    if interp.requirements.budget_amount:
        # The new total is already in the requirements: an adjust/set action on top would apply it twice.
        interp.actions = [a for a in interp.actions if a.action not in ("adjust_budget", "set_budget")]
    if interp.requirements.return_to:
        # "Fly home to Cairo instead": the last flight is searched again anyway. Don't also swap the outbound
        # flight (change_flight would exclude it) - the traveller didn't ask for that.
        interp.actions = [a for a in interp.actions if a.action != "change_flight"]
    trip.emit("message.interpreted", intent=interp.intent, source=interp.source)
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
    elif pending and interp.intent not in ("question", "off_topic"):
        route = "requirements"  # any answer to a route proposal (yes / change it) continues the design loop
    trip.assumptions = notes
    return {"interpretation": interp, "route": route}


def _changes_trip_frame(trip: TripState, interp: TurnInterpretation) -> bool:
    """Does the message change where / when / who / how much (which needs the requirements path)?"""
    r, c = interp.requirements, trip.trip_contract
    if c is None:
        return True
    # The model sometimes echoes facts already in the contract: only a different value is a change.
    if r.destinations or r.region:
        return True
    if r.start_date and r.start_date != c.start_date.isoformat():
        return True
    if r.end_date and r.end_date != c.end_date.isoformat():
        return True
    if r.duration_days and r.duration_days != c.num_days:
        return True
    if r.budget_amount and abs(r.budget_amount - c.budget.amount) > 0.5:
        return True
    if r.destination and r.destination.strip().lower() not in {c.destination.lower(), (c.destination_name or "").lower()}:
        return True
    if r.origin_city and r.origin_city.strip().lower() != (c.origin_city or "").lower():
        return True
    if r.return_to:
        wanted = r.return_to.strip().lower()
        wanted = None if wanted == (c.origin_city or "").lower() else wanted  # "back home" = no open-jaw
        if wanted != ((c.return_city or "").lower() or None):
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
        reply = narrative.compose_questions(trip)
    else:
        reply = narrative.greeting()
    return {"reply": reply}


async def _resolve(trip: TripState) -> str | None:
    """Resolve destination/origin text against real geocoding. Returns a question if something is unclear."""
    d = trip.draft
    hub = get_hub()
    if not d.route_confirmed:
        texts = d.destinations or ([d.destination] if d.destination else [])
        d.countries = [x for x in texts if geo.country_code(x)]
    if len(d.destinations) >= 2 and len(d.destination_refs) < 2:
        refs, kept, missing = [], [], []
        for text in d.destinations:
            try:
                ref = await research.resolve_place(hub, text)
            except MCPToolError:
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
        try:
            d.destination_ref = await research.resolve_place(hub, d.destination)
            trip.emit("place.resolved", role="destination", name=d.destination_ref.name, country=d.destination_ref.country)
        except MCPToolError:
            bad, d.destination = d.destination, None
            return f"I couldn't find a city with an airport called '{bad}'. Which city do you mean?"
    if d.origin_ref is None and (d.destination_ref is not None or d.region):  # no lookup before we know where
        text = d.origin_city or d.origin or settings.default_origin
        try:
            d.origin_ref = await research.resolve_place(hub, text)
        except MCPToolError:
            d.origin_city = None
            return f"I couldn't find '{text}'. Which city are you flying from?"
    if d.return_to and d.return_ref is None and d.origin_ref is not None:
        # Open-jaw: the city to fly home to.
        try:
            d.return_ref = await research.resolve_place(hub, d.return_to)
            trip.emit("place.resolved", role="return", name=d.return_ref.name, country=d.return_ref.country)
        except MCPToolError:
            bad, d.return_to = d.return_to, None
            return f"I couldn't find a city with an airport called '{bad}'. Which city do you want to fly home to?"
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
            if d.route_proposal and message.strip() and message.strip() not in d.route_feedback:
                d.route_feedback.append(message.strip())
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


async def apply_feedback(state: GraphState) -> GraphState:
    trip = state["trip"]
    interp = state["interpretation"]
    previous = trip.selected_plan
    learn_from_feedback(trip, interp.feedback, state.get("message", ""))
    # Requirements mentioned alongside feedback (e.g. a new wake-up time, "I walk everywhere") also apply.
    before = (trip.traveler_profile.model_dump(exclude={"learned", "explicit_fields"}), trip.user_knobs.model_dump())
    req_notes = apply_requirements(trip, interp.requirements)
    after = (trip.traveler_profile.model_dump(exclude={"learned", "explicit_fields"}), trip.user_knobs.model_dump())
    dirty, notes, needs_replan = apply_actions(trip, interp.actions)
    notes = req_notes + notes
    needs_replan = needs_replan or before != after
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
    fresh = _dirty(state, "destination") or trip.research is None
    if c.is_multi:
        net.allow_extra_calls(journey.SERPAPI_PER_EXTRA_STOP * (len(c.stops) - 1))
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
    return {"r_info": info, "timings": {"research_start": time.perf_counter()}}


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


async def collect(state: GraphState) -> GraphState:
    """Merge fresh research with anything still valid, then run the enrichment phase."""
    trip = state["trip"]
    old = trip.research or ResearchBundle()

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
                                               review_lookups=min(1, _review_lookups(trip)), price_scale=0.6)
                               for i, b in enumerate(stops)))
        bundle = journey.merge_research(stops, legs, list(state.get("r_errors") or []) + (fl.get("errors", []) if fl else []))
        trip.research = bundle
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
    await research.enrich(get_hub(), bundle, trip.trip_contract, review_lookups=_review_lookups(trip))
    trip.research = bundle
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
    for mode in PLANNING_MODES:
        existing = candidates.get(mode)
        if existing and existing.validation and existing.validation.result == "PASS":
            continue
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
    return {"candidates": candidates, "knobs": knobs, "iteration": state.get("iteration", 0) + 1}


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
    return {}


def after_validate(state: GraphState) -> str:
    failing = [p for p in state["candidates"].values() if p.validation and p.validation.result == "FAIL"]
    if failing and state.get("iteration", 0) < settings.max_repair_iterations:
        return "repair"
    return "finalize"


async def repair_node(state: GraphState) -> GraphState:
    trip = state["trip"]
    knobs = dict(state["knobs"])
    progressed = False
    for mode, p in state["candidates"].items():
        if p.validation and p.validation.result == "FAIL":
            new_knobs, log_lines = repair(p, p.validation, knobs[mode], trip.research, state.get("iteration", 0),
                                          trip.traveler_profile)
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
            best = max(fitting, key=lambda m: trip.plans[m].score.total if trip.plans[m].score else 0)
            trip.assumptions.append(f"The {trip.selected_mode} plan went over your hard budget, so I'm showing the "
                                    f"{best} plan instead.")
            trip.selected_mode = best  # type: ignore[assignment]
    # Requirements the selected plan can't meet, with ranked, priced ways out (offered, never applied silently).
    trip.metadata["conflicts"] = [x.model_dump(mode="json") for x in conflicts.analyze(trip)]
    trip.pinned_days = plan_activity_ids(trip.selected_plan) if trip.selected_plan else {}
    changes = diff_plans(state.get("previous_plan"), trip.selected_plan)
    trip.last_changes = (trip.assumptions if state.get("route") != "requirements" else []) + changes \
        if state.get("previous_plan") else []
    trip.status = "planned"
    trip.emit("itinerary.generated", mode=trip.selected_mode, iterations=state.get("iteration", 0))
    return {}


def _errors(p: TripPlan | None) -> int:
    return len(p.validation.errors) if p and p.validation else 0


def _score(p: TripPlan | None) -> float:
    return p.score.total if p and p.score else 0.0


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
        lost = _lost_icons(trip, before, after)
        if lost:
            trace.step(trip, "critic", "thought", f"The refinement would drop {', '.join(lost)} - an icon of the city.")
        if lost or _errors(after) > _errors(before) or _score(after) < _score(before) - 1:
            trip.plans, trip.selected_mode = backup["plans"], backup["mode"]
            trip.user_knobs, trip.traveler_profile = backup["knobs"], backup["profile"]
            trip.pinned_days, trip.excluded_ids = backup["pins"], backup["excluded"]
            trip.draft.must_visit = backup["must_visit"]
            trip.metadata["expert_added"] = backup["expert_added"]
            trip.metadata.update({k: v for k, v in (backup.get("meta") or {}).items() if v is not None})
            for i in crit.get("issues", []):
                i["applied"] = False
            trace.step(trip, "critic", "decision",
                       f"Refinement rejected: score {_score(before)} -> {_score(after)}, errors {_errors(before)} -> "
                       f"{_errors(after)}. Kept the original plan.")
        else:
            crit["changes"] = diff_plans(before, after)
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
    critique = await critic.review(trip)
    if critique is None:
        return {"critic_next": "respond"}
    fixes = critic.safe_fixes(trip, critique)
    applied = {id(issue) for issue, _ in fixes}
    trip.metadata["critique"] = {
        "fresh": True, "quality": critique.quality, "verdict": critique.verdict, "verdict_ar": critique.verdict_ar,
        "strengths": critique.strengths[:3],
        "issues": [{"severity": i.severity, "day": i.day, "problem": i.problem, "problem_ar": i.problem_ar,
                    "suggestion": i.suggestion, "action": i.fix.action if i.fix else None, "applied": id(i) in applied}
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
    return {"critic_next": "plan", "critic_backup": backup, "candidates": {}, "iteration": 0}


def _publish_suggestions(trip: TripState) -> None:
    crit = trip.metadata.get("critique") or {}
    trip.metadata["suggestions"] = [i["suggestion"] for i in crit.get("issues", [])
                                    if not i.get("applied") and i.get("suggestion")][:3]


async def respond(state: GraphState) -> GraphState:
    trip = state["trip"]
    if not trip.selected_plan:
        return {"reply": "I couldn't build a plan yet. " + "; ".join(trip.research.errors if trip.research else [])}
    # What guests say about the hotel of the plan shown (review-analyst agent). Once per turn - after the critic -
    # so a refined plan doesn't cost a second review search; hotels already analysed cost nothing.
    await research.plan_hotel_insights(get_hub(), trip, trip.plans)
    out = await narrative.compose_plan_reply(trip)
    # The reply model's own next steps for this trip; the critic's open ideas fill any space left.
    critic_ideas = [s for s in trip.metadata.get("suggestions", []) if s not in out.suggestions]
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


BRANCHES = [
    ("flights", "r_flights", _journeys),
    ("hotels", "r_hotels", _per_city(lambda hub, trip, c, info: research.research_hotels(hub, c))),
    ("restaurants", "r_restaurants", _per_city(lambda hub, trip, c, info: research.research_restaurants(
        hub, c, info["currency"], trip.traveler_profile.dietary_restrictions))),
    ("activities", "r_activities", _per_city(lambda hub, trip, c, info: research.research_activities(
        hub, c, info["currency"], trip.traveler_profile.activity_preferences))),
    ("weather", "r_weather", _per_city(lambda hub, trip, c, info: research.research_weather(hub, c))),
]


def build_graph():
    g = StateGraph(GraphState)
    g.add_node("understand", understand)
    g.add_node("answer", answer)
    g.add_node("check_requirements", check_requirements)
    g.add_node("ask", ask)
    g.add_node("propose_route", propose_route)
    g.add_node("apply_feedback", apply_feedback)
    g.add_node("research_setup", research_setup)
    for domain, key, fn in BRANCHES:
        g.add_node(f"research_{domain}", _branch(domain, key, fn))
    g.add_node("collect", collect)
    g.add_node("plan", plan)
    g.add_node("validate", validate)
    g.add_node("repair", repair_node)
    g.add_node("finalize", finalize)
    g.add_node("critic", critic_node)
    g.add_node("respond", respond)

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


async def run_turn(trip: TripState, message: str = "", preset_actions: list[Action] | None = None,
                   route_decision: str | None = None) -> tuple[TripState, str]:
    if message:
        trip.conversation.append(ChatMessage(role="user", content=message))
    net.start_turn()
    trace.start(trip)
    trip.metadata["suggestions"] = []
    started = time.perf_counter()
    result = await get_graph().ainvoke(
        {"trip": trip, "message": message, "preset_actions": preset_actions or [], "route_decision": route_decision},
        {"recursion_limit": 80},
    )
    trip = result["trip"]
    reply = result.get("reply", "")
    trip.metadata["last_turn_ms"] = round((time.perf_counter() - started) * 1000)
    trip.conversation.append(ChatMessage(role="assistant", content=reply))
    return trip, reply


async def run_turn_stream(trip: TripState, message: str = "", preset_actions: list[Action] | None = None,
                          route_decision: str | None = None):
    """Same as run_turn, but yields live progress: every graph node and every MCP tool call as it completes.

    Yields dicts: {"type": "node", "node": ...}, {"type": "tool", "server", "tool", "ok", "ms"},
    and finally {"type": "done", "trip": TripState, "reply": str}.
    """
    import asyncio

    if message:
        trip.conversation.append(ChatMessage(role="user", content=message))
    net.start_turn()
    trace.start(trip)
    trip.metadata["suggestions"] = []
    started = time.perf_counter()
    queue: asyncio.Queue = asyncio.Queue()
    hub = get_hub()

    turn_id = uuid.uuid4().hex

    def on_tool(event: dict) -> None:
        if event.get("turn") != turn_id:
            return  # another user's turn: never leaked into this stream
        queue.put_nowait({"type": "tool", **{k: v for k, v in event.items() if k != "turn"}})

    final: dict = {}

    async def runner() -> None:
        try:
            async for mode, chunk in get_graph().astream(
                    {"trip": trip, "message": message, "preset_actions": preset_actions or [], "route_decision": route_decision},
                    {"recursion_limit": 80}, stream_mode=["updates", "values"]):
                if mode == "updates":
                    for node in chunk:
                        queue.put_nowait({"type": "node", "node": node, "ms": round((time.perf_counter() - started) * 1000)})
                else:
                    final.update(chunk)
        except Exception as exc:  # surfaced to the UI instead of a silent hang
            log.exception("turn failed: %s", net.redact(str(exc)))  # details stay in the server log
            queue.put_nowait({"type": "error", "message": "Something went wrong while planning - please try again."})
        finally:
            queue.put_nowait(None)

    hub.listeners.append(on_tool)
    token = CURRENT_TURN.set(turn_id)  # copied into the runner task and every node/tool call it starts
    try:
        task = asyncio.create_task(runner())
    finally:
        CURRENT_TURN.reset(token)
    try:
        while (event := await queue.get()) is not None:
            yield event
    finally:
        hub.listeners.remove(on_tool)
        await task
    if "trip" not in final:
        return
    trip = final["trip"]
    reply = final.get("reply", "")
    trip.metadata["last_turn_ms"] = round((time.perf_counter() - started) * 1000)
    trip.conversation.append(ChatMessage(role="assistant", content=reply))
    yield {"type": "done", "trip": trip, "reply": reply}
