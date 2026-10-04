"""Chat replies. Claude phrases them from structured facts only; templates otherwise."""

from __future__ import annotations

import json
import math
from typing import Any

from pydantic import BaseModel, Field

from . import knowledge, llm
from .memory import recent_turns
from .models import Money, TripPlan, TripState


def money(amount: float, currency: str) -> str:
    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency.upper())
    return f"{symbol}{amount:,.0f}" if symbol else f"{amount:,.0f} {currency}"


def plan_facts(trip: TripState) -> dict[str, Any]:
    c = trip.trip_contract
    plan = trip.selected_plan
    if c is None or plan is None:
        return {}
    b = plan.budget
    expert = {n.lower() for n in trip.metadata.get("expert_added", [])}
    facts: dict[str, Any] = {
        "destination": c.destination_name, "dates": f"{c.start_date:%b %d} - {c.end_date:%b %d, %Y}",
        "travelers": c.travelers, "hotel_rooms": c.rooms, "selected_mode": plan.mode,
        "departs_from": c.origin_city,
        "flies_home_to": c.return_city or c.origin_city,
        "trip_score": plan.score.total if plan.score else None,
        "total": money(b.total, b.currency) if b else None, "budget": money(c.budget.amount, c.budget.currency),
        "within_budget": plan.within_budget,
        "remaining": money(b.remaining, b.currency) if b else None,
        "validation": plan.validation.result if plan.validation else None,
        "warnings": [v.message for v in plan.validation.violations if v.severity == "warning"][:4] if plan.validation else [],
        "errors": [v.message for v in plan.validation.errors][:4] if plan.validation else [],
        "hotel": {"name": plan.hotel.name, "area": plan.hotel.neighborhood, "why": plan.explanations.get("hotel", [])[:4]} if plan.hotel else None,
        "outbound": plan.outbound_flight.flight_number + f" {plan.outbound_flight.depart_at:%H:%M}->{plan.outbound_flight.arrive_at:%H:%M}" if plan.outbound_flight else None,
        "return": plan.return_flight.flight_number + f" {plan.return_flight.depart_at:%H:%M}->{plan.return_flight.arrive_at:%H:%M}" if plan.return_flight else None,
        "days": [f"Day {d.day}: {d.title}" for d in plan.days],
        "modes": {m: {"total": money(p.budget.total, p.budget.currency) if p.budget else None,
                      "score": p.score.total if p.score else None, "within_budget": p.within_budget}
                  for m, p in trip.plans.items()},
        "changes": trip.last_changes, "assumptions": trip.assumptions,
        "day_trips_in_plan": [i.title for d in plan.days for i in d.items if i.kind == "activity" and i.place_id
                              and (p := trip.research.place(i.place_id)) and p.day_trip],
        "overnight_side_trip_ideas": overnight_ideas(trip),
        "repairs": plan.repair_log[-5:],
        "places_you_asked_for": {name: (f"Day {day}" if day else "could not be fitted") for name, day in plan.requested.items()
                                 if name.lower() not in expert},
        "highlights_added_by_expert_review": {name: f"Day {day}" for name, day in plan.requested.items()
                                              if name.lower() in expert and day},
        "ai_estimated_data": ai_estimated(trip),
    }
    arabic = any("؀" <= ch <= "ۿ" for ch in latest_user_message(trip))
    if b:
        # One unambiguous line, so the reply can't flip "over" and "under".
        if not (trip.draft.find_cheapest and not trip.draft.budget_amount):  # then 'cheapest_trip_search' says it
            facts["budget_status"] = (f"WITHIN budget: {money(b.remaining, b.currency)} left" if plan.within_budget
                                      else f"OVER budget by {money(b.total - c.budget.amount, b.currency)}")
        facts["cost_breakdown"] = {(COST_AR[k] if arabic else k): money(getattr(b, k), b.currency)
                                   for k in ("flights", "hotel", "food", "activities", "transport") if getattr(b, k)}
    facts["day_by_day"] = {day_label(d.day, d.date, arabic): [f"{i.start} {i.title}" for i in d.items
                                                              if i.kind in ("activity", "flight")]
                           for d in plan.days}
    facts.update(budget_reality(trip))
    facts.update(flight_alternatives(trip))
    missing = famous_not_in_plan(trip)
    if missing:
        facts["famous_places_not_in_plan"] = missing
    if trip.draft.find_cheapest and trip.metadata.get("found_budget"):
        for k in ("budget", "remaining", "within_budget"):  # the traveller gave no budget: nothing is "left over"
            facts.pop(k, None)
        cheapest = trip.plans.get("budget")
        facts["cheapest_trip_search"] = {
            "the_traveller_asked_for": "the cheapest possible trip (no budget given)",
            "cheapest_good_plan_costs": money(cheapest.budget.total, c.budget.currency) if cheapest and cheapest.budget else None,
            "budget_set_to": money(trip.metadata["found_budget"], c.budget.currency),
            "what_more_money_buys": {m: money(p.budget.total, p.budget.currency) for m, p in trip.plans.items()
                                     if m != "budget" and p.budget},
        }
    if plan.stops:
        facts["multi_city_route"] = [
            {"city": s.name, "country": s.country, "nights": s.nights, "dates": f"{s.start_date:%b %d} - {s.end_date:%b %d}",
             "hotel": s.hotel.name if s.hotel else None,
             "arrive_by": _leg_text(s.arrival) if s.arrival else None} for s in plan.stops]
        facts["journey_legs"] = [_leg_text(f) for f in plan.legs]
        facts.pop("hotel", None)
    return facts


COST_AR = {"flights": "الطيران", "hotel": "الفندق", "food": "الأكل", "activities": "تذاكر الأماكن", "transport": "المواصلات"}
AR_DAYS = ["الاتنين", "التلات", "الأربع", "الخميس", "الجمعة", "السبت", "الحد"]
AR_MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


def day_label(n: int, d, arabic: bool) -> str:
    """'Day 1 (Wed 14 Oct)' or 'اليوم 1 (الأربع 14 أكتوبر)': labels the model can copy as they are."""
    if arabic:
        return f"اليوم {n} ({AR_DAYS[d.weekday()]} {d.day} {AR_MONTHS[d.month - 1]})"
    return f"Day {n} ({d:%a %d %b})"


def _user_amount(trip: TripState, m) -> float:
    cur = trip.trip_contract.budget.currency.upper()
    return m.amount * (1.0 if m.currency.upper() == cur else trip.research.fx_rates.get(m.currency.upper(), 1.0))


def _ground_hours(o, r) -> float:
    return max(0.0, (r.depart_at - o.arrive_at).total_seconds() / 3600 - 3.25)  # minus airport time both ends


def flight_alternatives(trip: TripState) -> dict[str, Any]:
    """The chosen flights in context: what the cheapest, the most-time and a direct option would cost and give."""
    plan, r, c = trip.selected_plan, trip.research, trip.trip_contract
    if not plan or not r or plan.stops or not plan.outbound_flight or not plan.return_flight:
        return {}
    o0, r0 = plan.outbound_flight, plan.return_flight
    cur = c.budget.currency
    chosen_fare = _user_amount(trip, o0.price_per_person) + _user_amount(trip, r0.price_per_person)
    chosen_hours = _ground_hours(o0, r0)
    pairs = [(o, b, _user_amount(trip, o.price_per_person) + _user_amount(trip, b.price_per_person))
             for o in r.flights_outbound for b in r.flights_return if b.depart_at > o.arrive_at]
    pairs += [(rt.outbound, rt.inbound, _user_amount(trip, rt.total_per_person)) for rt in r.round_trips]
    if not pairs:
        return {}

    def describe(o, b, fare) -> dict[str, Any]:
        tag = "round-trip ticket" if o.id.endswith("_rt") else ("direct both ways" if o.stops == 0 and b.stops == 0 else
                                                                 f"{o.stops + b.stops} stop(s) in total")
        return {"flights": f"{o.airline} {o.flight_number} (lands {o.arrive_at:%H:%M}) + {b.airline} {b.flight_number} "
                           f"(leaves {b.depart_at:%H:%M})",
                "fare_per_person": money(fare, cur), "vs_chosen": f"{'+' if fare >= chosen_fare else '-'}"
                                                                  f"{money(abs(fare - chosen_fare), cur)}",
                "hours_in_destination": round(_ground_hours(o, b)), "type": tag}

    out: dict[str, Any] = {"chosen_flights": {**describe(o0, r0, chosen_fare), "why": plan.explanations.get("outbound_flight", [])[:3]}}
    seen = {(o0.id, r0.id)}
    alts = []
    cheapest = min(pairs, key=lambda x: x[2])
    most_time = max(pairs, key=lambda x: (_ground_hours(x[0], x[1]), -x[2]))
    direct = min((x for x in pairs if x[0].stops == 0 and x[1].stops == 0), key=lambda x: x[2], default=None)
    for label, x in (("the cheapest", cheapest), ("the most hours in the city", most_time), ("the cheapest direct", direct)):
        if x and (x[0].id, x[1].id) not in seen:
            seen.add((x[0].id, x[1].id))
            alts.append({"option": label, **describe(*x)})
    if alts:
        out["flight_alternatives"] = alts
    out["flight_hours_note"] = f"The chosen flights give about {round(chosen_hours)} usable hours in the destination."
    return out


def budget_reality(trip: TripState) -> dict[str, Any]:
    """When the plan is over budget: by how much, why, and what the cheapest possible trip would cost."""
    plan, r, c = trip.selected_plan, trip.research, trip.trip_contract
    if not plan or not plan.budget or plan.within_budget or not r:
        return {}
    from .engine.repair import travel_floor

    b = plan.budget
    facts: dict[str, Any] = {"over_budget_by": money(b.total - c.budget.amount, b.currency)}
    floor = travel_floor(plan, r)
    if floor is not None:
        # Two costs side by side, so the model never mistakes the minimum for a saving.
        facts["flights_plus_hotel_in_this_plan"] = money(b.flights + b.hotel, b.currency)
        facts["minimum_possible_cost_of_flights_plus_hotel"] = money(floor, b.currency)
        if b.flights + b.hotel - floor < 0.03 * floor:
            facts["flights_and_hotel_note"] = "This plan already uses (nearly) the cheapest flights and hotel found."
        if floor > c.budget.amount:
            facts["budget_verdict"] = ("The budget cannot cover even the cheapest flights and hotel found for these "
                                       "dates, so the plan keeps the experience and shows the real minimum.")
    biggest = max(("flights", "hotel", "food", "activities", "transport"), key=lambda k: getattr(b, k))
    arabic = any("؀" <= ch <= "ۿ" for ch in latest_user_message(trip))
    facts["largest_cost"] = f"{COST_AR[biggest] if arabic else biggest}: {money(getattr(b, biggest), b.currency)}"
    facts["realistic_budget_for_this_plan"] = money(math.ceil(b.total / 500) * 500, b.currency)
    insights = r.flight_insights or {}
    if insights.get("cheapest_round_trip"):
        rt = Money(amount=insights["cheapest_round_trip"], currency=c.budget.currency)  # searched in the budget currency
        facts["cheapest_round_trip_ticket_found"] = money(_user_amount(trip, rt), b.currency)
    return facts


def famous_not_in_plan(trip: TripState) -> list[str]:
    """The destination's most-visited sights that didn't make it into the plan (for 'add a day?' suggestions)."""
    plan, r = trip.selected_plan, trip.research
    if not plan or not r:
        return []
    in_plan = {i.place_id for d in plan.days for i in d.items if i.place_id}
    top = sorted((a for a in r.attractions if a.reviews_count and "overnight_trip" not in a.categories),
                 key=lambda a: -a.reviews_count)[:8]
    return [a.name for a in top if a.id not in in_plan][:4]


UNKNOWN_HINTS = {
    "travel_style": "pace: relaxed days or as many sights as possible",
    "transport_preference": "getting around: walking between sights vs public transport / taxis",
    "activity_preferences": "what they enjoy (history, food, art, nightlife, nature, shopping...)",
    "food_preferences": "food they love or want to try",
    "preferred_wake_up_time": "early starts or late mornings",
}


def unknown_preferences(trip: TripState) -> list[str]:
    """Preferences that would change the plan and that the traveller hasn't told us - on this trip or an earlier
    one (long-term memory). The reply model decides whether any is worth asking now."""
    p = trip.traveler_profile
    known = set(p.explicit_fields) | {k for k, lp in p.learned.items() if lp.confidence >= 0.5}
    if p.transport_preference or "walking_tolerance" in known:
        known.add("transport_preference")
    return [hint for field, hint in UNKNOWN_HINTS.items() if field not in known]


def ai_estimated(trip: TripState) -> list[str]:
    """Which parts of the selected plan come from the AI fallback (live search was unavailable)."""
    plan, r = trip.selected_plan, trip.research
    if plan is None or r is None:
        return []
    out = []
    legs = plan.legs or [f for f in (plan.outbound_flight, plan.return_flight) if f]
    if any(f.metadata.source == "ai_knowledge" for f in legs):
        out.append("flights")
    hotels = [s.hotel for s in plan.stops if s.hotel] if plan.stops else ([plan.hotel] if plan.hotel else [])
    if any(h.metadata.source == "ai_knowledge" for h in hotels):
        out.append("hotels")
    used = [r.place(i.place_id) for d in plan.days for i in d.items if i.place_id]
    if any(p and p.metadata.source == "ai_knowledge" and p.kind != "restaurant" and p.kind != "cafe" for p in used):
        out.append("sights")
    if any(p and p.metadata.source == "ai_knowledge" and p.kind in ("restaurant", "cafe") for p in used):
        out.append("restaurants")
    return out


def _leg_text(f) -> str:
    what = f"{f.airline} {f.flight_number}" if f.mode == "flight" else f"{f.mode} (estimated time & fare)"
    return f"{f.origin} -> {f.destination} {f.depart_at:%a %d %b %H:%M}, {what}"


def overnight_ideas(trip: TripState) -> list[str]:
    """Famous places too far for a day trip (e.g. Luxor from Cairo), best first."""
    if not trip.research:
        return []
    far = sorted((a for a in trip.research.attractions if "overnight_trip" in a.categories), key=lambda a: -a.reviews_count)
    return [f"{a.name} (~{a.distance_km:.0f} km)" for a in far[:4]]


def _template_plan(trip: TripState) -> str:
    c = trip.trip_contract
    plan = trip.selected_plan
    assert c is not None and plan is not None
    b = plan.budget
    lines = []
    if trip.last_changes:
        lines.append("**What changed**")
        lines += [f"- {x}" for x in trip.last_changes[:8]]
        lines.append("")
    estimated = ai_estimated(trip)
    if estimated:
        lines.append(f"⚠️ Live search was unavailable, so the {', '.join(estimated)} below are AI estimates - "
                     "double-check them before booking.\n")
    lines.append(f"**Your {c.destination_name} trip - {c.start_date:%b %d} to {c.end_date:%b %d} "
                 f"({c.num_days} days, {c.travelers} traveler{'s' if c.travelers > 1 else ''})**")
    if b:
        status = (f"within budget, {money(b.remaining, b.currency)} left" if plan.within_budget
                  else f"**{money(-b.remaining, b.currency)} over budget**")
        lines.append(f"{plan.mode.title()} plan - TripScore **{plan.score.total if plan.score else '-'}/100** - "
                     f"total **{money(b.total, b.currency)}** of {money(c.budget.amount, c.budget.currency)} ({status})")
    if plan.stops:
        lines.append("- Route: " + " → ".join(f"{s.name} ({s.nights} night{'s' if s.nights > 1 else ''})" for s in plan.stops))
        for f in plan.legs:
            lines.append(f"  - {_leg_text(f)}")
        for s in plan.stops:
            if s.hotel:
                lines.append(f"- {s.name} hotel: {s.hotel.name} ({s.hotel.rating}/5, "
                             f"{money(s.hotel.price_per_night.amount, s.hotel.price_per_night.currency)}/night)")
    elif plan.outbound_flight and plan.return_flight:
        o, r = plan.outbound_flight, plan.return_flight
        lines.append(f"- Flights: {o.airline} {o.flight_number} ({o.depart_at:%a %H:%M}) / "
                     f"{r.airline} {r.flight_number} ({r.depart_at:%a %H:%M})")
    if plan.hotel and not plan.stops:
        why = "; ".join(plan.explanations.get("hotel", [])[:3])
        lines.append(f"- Hotel: {plan.hotel.name} ({plan.hotel.neighborhood}, {plan.hotel.rating}/5, "
                     f"{money(plan.hotel.price_per_night.amount, plan.hotel.price_per_night.currency)}/night) - {why}")
    for d in plan.days:
        lines.append(f"- Day {d.day}: {d.title}")
    expert = {n.lower() for n in trip.metadata.get("expert_added", [])}
    asked = {n: d for n, d in plan.requested.items() if n.lower() not in expert}
    if asked:
        lines.append("\n**Places you asked for:** " + "; ".join(
            f"{name} → Day {day}" if day else f"{name} → couldn't fit it" for name, day in asked.items()))
    if len(trip.plans) > 1:
        cmp = " | ".join(f"{m.title()} {money(p.budget.total, p.budget.currency)} (score {p.score.total if p.score else '-'})"
                         f"{'' if p.within_budget else ' over budget'}" for m, p in trip.plans.items() if p.budget)
        lines.append(f"\nPlans compared: {cmp}")
    if plan.validation:
        errs = plan.validation.errors
        warns = [v for v in plan.validation.violations if v.severity == "warning"]
        if errs:
            lines.append("\nStill open: " + "; ".join(v.message for v in errs[:3]))
        elif warns:
            lines.append("\nAll hard checks passed. Heads-up: " + "; ".join(v.message for v in warns[:3]))
        else:
            lines.append("\nEverything checks out: budget, timings, distances, opening hours, your preferences, pace "
                         "and weather.")
    ideas = overnight_ideas(trip)
    if ideas:
        lines.append("\nToo far for a day trip but famous: " + ", ".join(ideas)
                     + ". Want me to plan an overnight side trip?")
    fresh = [a for a in trip.assumptions if a not in trip.last_changes]
    if fresh:
        lines.append("\n" + " ".join(fresh))
    lines.append("\nYou can say things like *make it cheaper*, *fewer museums*, *I don't want to wake up before 10*, "
                 "*what if my budget is $300 more?* - or open the Trip Book.")
    return "\n".join(lines)


REPLY_SYSTEM = """You are Dalili (دليلي), a sharp, warm travel planner who researches and plans trips but never books them.
Write the chat reply to the traveller from the JSON facts you are given.

Truth: use only the facts provided - never invent prices, times, places or claims that are not in the JSON.
Language: reply in the same language and dialect as 'traveller_latest_message' (Egyptian Arabic -> natural, fluent
Egyptian Arabic, not formal MSA). Write every sentence fully in that language: only proper names (places, airlines,
flight numbers, hotel names) stay in English. Don't use English words like "Day", "flights", "booking" in Arabic text.
Voice: talk like an experienced friend who knows the city - confident, specific and a little enthusiastic. Never
mention internal tools, servers, models, validators, JSON, "MCP", "API" or "validation FAIL"; say things plainly.
Use 'recent_conversation' to stay consistent with what you already said and to avoid repeating yourself.

Structure (short markdown, roughly 150-250 words - tight, no filler, never repeat a number twice):
1. One bold headline that answers what the traveller just asked. If 'changes' is non-empty, say what changed first;
   if it is empty, don't talk about changes at all.
2. The plan, concretely: use 'day_by_day' to describe each day in one line with its best moments and times
   (e.g. "Day 1: land 07:10, Colosseum at 10:00, Trevi and the Pantheon after lunch"). Don't list every meal.
3. Flights and hotel in one or two lines. Use 'chosen_flights' and say WHY in human terms (e.g. lands early so you get
   a full first day). If 'flight_alternatives' exists, offer the most useful one or two with their price difference
   and what they give (cheaper / more hours / direct) so the traveller can choose.
4. Money, honestly: total vs budget, exactly as 'budget_status' says (over or within). If over budget, explain why in one sentence using 'largest_cost' and
   'cost_breakdown'. If 'budget_verdict' is present, say clearly that even the cheapest flights + hotel found
   ('minimum_possible_cost_of_flights_plus_hotel' - a cost, not a saving) exceed the budget, give
   'realistic_budget_for_this_plan', and offer real options (raise the budget, other dates, fewer days, a nearer
   destination). If 'flights_and_hotel_note' is present, don't offer "cheaper flights" - they already are the cheapest.
   Never pretend the budget fits.
   If 'cheapest_trip_search' is present, the traveller asked for the cheapest trip: lead with the answer - "the
   cheapest good way to do this trip is about X" - say what keeps it cheap (flights, hotel, meals), then one line on
   what the other plans cost and add (upgrades). The traveller gave no budget: never say "within budget",
   "left over" or "over budget" about the cheapest plan.
5. If 'famous_places_not_in_plan' is non-empty, mention them as what an extra day (or a fuller pace) would add.
6. If 'places_you_asked_for' is non-empty, say on which day each one is, or that it couldn't fit and why.
If 'ai_estimated_data' is non-empty, say near the top that live search was unavailable for those parts, so they are AI
estimates to double-check before booking. If 'multi_city_route' is present, show the route city by city first.
If 'overnight_side_trip_ideas' is non-empty, add one line suggesting them as an optional overnight side trip.
If 'self_review' is present, one short line: you double-checked the plan like an experienced planner and what you
improved. Places in 'highlights_added_by_expert_review' were YOUR picks - never say the traveller asked for them.
Mention the TripScore and the other plan modes only briefly (one line), only if useful.
Questions: 'unknown_preferences' lists what you don't know about this traveller yet. If knowing one or two of them
would clearly change this plan, end with one or two short, friendly questions about them. Don't ask what
'recent_conversation' shows you already asked, and don't ask anything if the plan doesn't need it.
At most once, and only if it fits naturally, mention that the traveller makes the bookings.

Also return 'suggestions': 2-4 one-tap replies the traveller is likely to send next, written in their language AS IF
THEY TYPED THEM. Make them specific to this trip, not generic - e.g. answers to the question you just asked
("I'm active - fit in as many sights as possible"), a named famous place that's missing ("Add the Vatican Museums"),
a concrete flight alternative ("Switch to the direct ITA flight"), a real budget move ("Raise my budget to 26,000"),
"Add a day in Rome". Only things the planner can do: change pace, add/remove a named place, change flights or hotel,
change budget, dates or trip length, walking vs transport, food, or ask a question about the trip.
Never generic filler like "make it cheaper" unless the plan is really over budget and it would help.
Dalili plans but never books: no suggestion may ask to book, reserve or pay for anything."""


class PlanReply(BaseModel):
    reply: str = Field(description="The chat reply in markdown")
    suggestions: list[str] = Field(default_factory=list, description="2-4 one-tap next messages, in the traveller's language")


def latest_user_message(trip: TripState) -> str:
    return next((m.content for m in reversed(trip.conversation) if m.role == "user"), "")


async def compose_plan_reply(trip: TripState) -> PlanReply:
    """The reply and the next-step suggestions, both written by the model from the facts (template without one)."""
    facts = plan_facts(trip)
    if facts:
        facts["traveller_latest_message"] = latest_user_message(trip)
        facts["recent_conversation"] = recent_turns(trip, n=4)
        facts["unknown_preferences"] = unknown_preferences(trip)
        crit = trip.metadata.get("critique")
        if crit and crit.get("fresh"):
            facts["self_review"] = {"improved": [i["problem"] for i in crit["issues"] if i.get("applied")],
                                    "ideas": [i["suggestion"] or i["problem"] for i in crit["issues"]
                                              if not i.get("applied")][:2]}
    if llm.available() and facts:
        # Empty facts only invite filler ("nothing changed"): leave them out.
        facts = {k: v for k, v in facts.items() if v not in (None, [], {}, "")}
        out = await llm.parse(REPLY_SYSTEM, json.dumps(facts, default=str, ensure_ascii=False), PlanReply)
        if out and out.reply.strip():
            out.suggestions = [s.strip() for s in out.suggestions if s.strip()][:4]
            return out
    return PlanReply(reply=_template_plan(trip))


QUESTIONS_SYSTEM = """You are a friendly travel agent. The traveller's request is missing some details.
Write a short chat reply (under 90 words): one line acknowledging what you already know ('known'), then ask the
'questions' as a short list. Write in the same language (and dialect) as 'traveller_latest_message'. Nothing else.
Never mention internal tools, models or technical terms."""


async def compose_questions_reply(trip: TripState) -> str:
    """The questions, phrased by the model in the traveller's language (template otherwise)."""
    if llm.available() and trip.pending_questions:
        d = trip.draft
        facts = {"traveller_latest_message": latest_user_message(trip), "questions": trip.pending_questions[:3],
                 "known": {"destination": d.destinations or d.destination, "dates": [str(d.start_date), str(d.end_date)],
                           "budget": [d.budget_amount, d.budget_currency], "must_visit": d.must_visit}}
        out = await llm.text(QUESTIONS_SYSTEM, json.dumps(facts, default=str, ensure_ascii=False), max_tokens=1500)
        if out:
            return out
    return compose_questions(trip)


def compose_questions(trip: TripState) -> str:
    qs = trip.pending_questions[:3]
    known = []
    d = trip.draft
    if len(d.destinations) >= 2:
        known.append(" → ".join(x.title() for x in d.destinations))
    elif d.destination:
        known.append(d.destination.title())
    if d.start_date:
        known.append(f"from {d.start_date:%b %d}")
    if d.duration_days:
        known.append(f"{d.duration_days} days")
    if d.budget_amount:
        known.append(money(d.budget_amount, d.budget_currency or "USD"))
    intro = ("Great - so far I have: " + ", ".join(known) + ".") if known else "I'd love to plan this with you."
    return intro + " A couple of things before I research:\n" + "\n".join(f"- {q}" for q in qs)


def unavailable_reply(message: str) -> str:
    """The model couldn't be reached: say so plainly instead of guessing what the traveller meant."""
    if any("؀" <= ch <= "ۿ" for ch in message):
        return "معلش، مساعد الذكاء الاصطناعي مش متاح دلوقتي لحظات. جرّب تبعت رسالتك تاني بعد شوية."
    return "Sorry - the AI assistant is briefly unavailable. Please send your message again in a moment."


OFF_TOPIC_SYSTEM = """You are Dalili, a travel planner. The traveller asked something outside travel (you are not told
what). In one or two friendly sentences, in the language given by 'language', say you only help with travel - trips,
flights, hotels, restaurants, places to visit - and offer one concrete thing you can do (about 'trip' if present).
No markdown headings."""


async def off_topic_reply(trip: TripState, message: str) -> str:
    """A polite refusal that steers back to travel. The model never sees the off-topic question itself, so it can't
    answer it or slip in facts about it - only the traveller's language."""
    c = trip.trip_contract
    arabic = any("؀" <= ch <= "ۿ" for ch in message)
    if llm.available():
        out = await llm.text(OFF_TOPIC_SYSTEM, json.dumps(
            {"language": "Egyptian Arabic" if arabic else "the traveller's language (English if unsure)",
             "trip": c.destination_name if c else None}, ensure_ascii=False), max_tokens=300, effort="minimal")
        if out:
            return out
    if arabic:
        return "أنا دليلي، متخصص في السفر بس: رحلات وطيران وفنادق ومطاعم وأماكن تزورها. قولي رايح فين وأساعدك تخطط."
    return "I'm Dalili and I only help with travel - trips, flights, hotels, restaurants and places to visit. Where would you like to go?"


ANSWER_SYSTEM = """You answer a traveler's question using ONLY the provided knowledge snippets and trip facts.
If the snippets don't contain the answer, say you don't have verified information on that and suggest checking an official source.
Only answer travel questions; if the question isn't about travel, politely say you only help with travel.
Keep it under 120 words."""


async def answer_question(trip: TripState, question: str) -> str:
    guide = (trip.research.destination_info.get("knowledge") if trip.research else None) or {}
    dest = trip.trip_contract.destination_name if trip.trip_contract else trip.draft.destination
    if not guide:
        return ("I answer destination questions from the trip I'm planning. Tell me where, when and your budget "
                "and I'll research it - then ask me anything about the place.")
    snippets = knowledge.search(guide, question, top_k=4)
    facts: dict[str, Any] = {"destination": dest, "snippets": [s["text"] for s in snippets],
                             "source": guide.get("source_url")}
    if trip.research and "weather" in question.lower():
        facts["forecast"] = [f"{w.date:%a %d}: {w.condition}, {w.temp_min_c:.0f}-{w.temp_max_c:.0f}C, "
                             f"{w.precipitation_probability}% rain ({w.metadata.provider})" for w in trip.research.weather]
    if llm.available():
        out = await llm.text(ANSWER_SYSTEM, json.dumps({"question": question, **facts}))
        if out:
            return out
    if facts.get("forecast"):
        return "Forecast for your dates:\n" + "\n".join(f"- {x}" for x in facts["forecast"])
    if not snippets:
        return f"The {dest} guide I have doesn't cover that - please check an official source."
    src = f"\n\nSource: Wikivoyage ({guide.get('source_url')})" if guide.get("source_url") else ""
    return "From the Wikivoyage guide:\n" + "\n".join(f"- {s['text'][:300]}" for s in snippets[:3]) + src


def greeting() -> str:
    return ("Hi! I'm Dalili, your travel planner. I research real flights, hotels, restaurants, sights, events, transport "
            "and weather, then build a validated day-by-day plan - you make the bookings yourself.\n\n"
            "Tell me where you'd like to go (any city with an airport), when, your budget and what you enjoy. "
            "For example: *7 days in Rome from Oct 12, $2,500 for two, we love food and photography, no early mornings.* "
            "Several cities work too: *a 12-day tour of Italy, France and Spain from Oct 10, €4,000.*")
