"""Typed trip constraints: every requirement with its priority, source, confidence and evidence.

Derived - never invented - from three places, in order of authority:
  1. explicit  - what the traveller said in this trip (the draft, with the words it came from);
  2. learned   - what the traveller's preference memory knows (preferences.py), weaker than (1);
  3. default   - a value the system had to assume because nothing was said (always flagged as an assumption).

Priority follows the strength of what was said, not the field: "I must see the Vatican" is hard, "the Vatican if
there's time" is a preference; a dietary restriction is hard; a pace or wake-up time is a preference. Nothing the
traveller didn't say becomes hard.

The planner already enforces these through its contract, knobs and profile; this module gives them one explicit,
explainable shape that the validators, the conflict resolver (conflicts.py) and the reply all read.
"""

from __future__ import annotations

from typing import Any

from . import preferences
from .models import Constraint, TripContract, TripState


def _c(cid: str, ctype: str, value: Any, priority: str, source: str, reason: str, *, unit: str | None = None,
       evidence: str | None = None, confidence: float = 1.0, flexibility: str = "negotiable",
       created_from: str = "requirements") -> Constraint:
    return Constraint(id=cid, type=ctype, value=value, unit=unit, priority=priority, source=source,  # type: ignore[arg-type]
                      confidence=confidence, flexibility=flexibility, reason=reason,  # type: ignore[arg-type]
                      evidence=[evidence] if evidence else [], created_from=created_from)


def derive(trip: TripState, contract: TripContract) -> list[Constraint]:
    d, p = trip.draft, trip.traveler_profile
    said = d.stated
    out: list[Constraint] = []

    # Budget. A stated amount is treated as a limit unless the traveller says it's flexible - and said so openly.
    b = contract.budget
    if d.find_cheapest and not d.budget_amount:
        out.append(_c("budget", "budget_max", round(b.amount, 2), "soft", "inferred",
                      "No budget given: the cheapest good plan sets it; the other plans show what more money buys.",
                      unit=b.currency, evidence=said.get("wants_cheapest"), flexibility="flexible"))
    elif d.budget_amount:
        hard = d.budget_hard_limit is not False
        explicit_limit = d.budget_hard_limit is not None
        out.append(_c("budget", "budget_max", b.amount, "hard" if hard else "soft",
                      "explicit" if explicit_limit else "inferred",
                      ("You said the budget is a firm limit." if d.budget_hard_limit else
                       "You said the budget is flexible." if d.budget_hard_limit is False else
                       "A stated budget is treated as a limit unless you say it can stretch."),
                      unit=b.currency, evidence=said.get("budget_amount"), confidence=1.0 if explicit_limit else 0.8,
                      flexibility="fixed" if d.budget_hard_limit else "negotiable"))

    # Dates, party, rooms, where the trip ends: facts of the trip once stated.
    if d.start_date:
        out.append(_c("dates", "dates", f"{contract.start_date}..{contract.end_date}", "hard", "explicit",
                      "The travel dates you gave.", evidence=said.get("start_date") or said.get("duration_days"),
                      flexibility="fixed"))
    out.append(_c("travelers", "travelers", contract.travelers, "hard",
                  "explicit" if d.travelers else "default",
                  "The number of travellers you gave." if d.travelers else "Not stated - assumed 1 traveller.",
                  evidence=said.get("travelers"), confidence=1.0 if d.travelers else 0.5,
                  flexibility="fixed" if d.travelers else "flexible",
                  created_from="requirements" if d.travelers else "defaults"))
    if d.rooms:
        out.append(_c("rooms", "rooms", d.rooms, "hard", "explicit", "The room arrangement you asked for.",
                      evidence=said.get("rooms"), flexibility="fixed"))
    if contract.return_city:
        out.append(_c("return_city", "return_city", contract.return_city, "hard", "explicit",
                      "You fly home to another city.", evidence=said.get("return_to"), flexibility="fixed"))
    if not d.origin_city:
        out.append(_c("origin", "origin", contract.origin_city, "soft", "default",
                      f"Not stated - assumed you fly from {contract.origin_city}.", confidence=0.5,
                      created_from="defaults"))

    # Places: firm requests are hard, soft mentions are preferences.
    expert = {n.lower() for n in trip.metadata.get("expert_added", [])}
    for name in d.must_visit:
        if name.lower() in expert:
            continue  # the expert review's idea, not the traveller's requirement
        out.append(_c(f"visit:{name.lower()}", "must_visit", name, "hard", "explicit", "A place you asked to visit.",
                      evidence=said.get("must_visit")))
    for name in d.wish_list:
        out.append(_c(f"wish:{name.lower()}", "wish", name, "preference", "explicit",
                      "A place you'd like to see if it fits.", evidence=said.get("wish_list")))
    for cat in sorted(set(p.avoid_categories) | set(d.avoid)):
        explicit = "avoid_categories" in p.explicit_fields or cat in d.avoid
        out.append(_c(f"avoid:{cat}", "avoid_category", cat, "hard" if explicit else "soft",
                      "explicit" if explicit else "learned", "Something you don't want in the plan.",
                      evidence=said.get("avoid_categories") or said.get("avoid")))
    for theme in d.must_have:
        out.append(_c(f"theme:{theme.lower()}", "must_have", theme, "soft", "explicit",
                      "An experience you want the trip to include.", evidence=said.get("must_have")))

    # The traveller: explicit in this trip > learned from earlier trips. Each field keeps its own strength.
    def personal(field: str, ctype: str, priority: str, reason: str, value: Any = None, unit: str | None = None):
        value = getattr(p, field) if value is None else value
        if value in (None, [], ""):
            return
        if field in p.explicit_fields:
            out.append(_c(ctype, ctype, value, priority, "explicit", reason, unit=unit, evidence=said.get(field)))
            return
        lp = p.learned.get(field)
        if lp is not None and preferences.confidence(lp) >= 0.5:
            weaker = {"hard": "soft", "soft": "preference"}.get(priority, priority) if lp.source != "stated" else priority
            out.append(_c(ctype, ctype, lp.value, weaker, "learned", reason + " (remembered from your earlier trips)",
                          unit=unit, evidence=(lp.evidence or [None])[-1], confidence=preferences.confidence(lp),
                          created_from="learned_preferences"))

    personal("dietary_restrictions", "dietary", "hard", "Your dietary needs.")
    personal("walking_tolerance", "walking", "soft", "How much walking suits you.")
    personal("travel_style", "pace", "preference", "Your preferred pace.")
    personal("transport_preference", "transport", "preference", "How you like to get around.")
    personal("preferred_wake_up_time", "wake_time", "preference", "When your days start.", unit="HH:MM")
    personal("noise_tolerance", "noise", "soft", "How sensitive you are to noise.")
    personal("avoid_early_flights", "no_early_flights", "soft", "No early-morning flights.")
    personal("food_preferences", "cuisine", "preference", "Food you love.")
    personal("activity_preferences", "interests", "preference", "What you enjoy.")
    if p.flight_preference == "direct":
        personal("flight_preference", "direct_flights", "hard", "Direct flights only.")
    if "hotel_rating_preference" in p.explicit_fields:
        personal("hotel_rating_preference", "hotel_min_stars", "soft", "The hotel class you asked for.", unit="stars")
    for i, pr in enumerate(d.priorities):
        out.append(_c(f"priority:{pr}", "priority", pr, "preference", "explicit",
                      f"What matters most to you (#{i + 1}).", evidence=said.get("priorities"), confidence=1.0))
    return out


def by_type(contract: TripContract | None, ctype: str) -> list[Constraint]:
    return [c for c in (contract.constraints if contract else []) if c.type == ctype]


def summary(contract: TripContract | None) -> dict[str, Any]:
    """For the reply: what Dalili holds firm, what it prefers, and what it had to assume (to be corrected)."""
    cs = contract.constraints if contract else []

    def line(c: Constraint) -> str:
        v = ", ".join(map(str, c.value)) if isinstance(c.value, list) else c.value
        return f"{c.type}: {v}{' ' + c.unit if c.unit and c.type != 'budget_max' else ''}"

    return {
        "firm": [line(c) for c in cs if c.priority == "hard" and c.source != "default"],
        "assumed_not_stated": [c.reason for c in cs if c.source == "default"],
        "remembered_from_earlier_trips": [line(c) for c in cs if c.source == "learned"],
    }
