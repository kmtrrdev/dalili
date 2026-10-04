"""Critic agent: self-reflection over a finished plan (the "reviewer" in a generate -> critique -> refine loop).

The deterministic validators prove a plan is *feasible* (budget, hours, walking, overlaps). The critic judges
whether it is *good*, like an experienced travel planner would:
- Is an iconic sight of the destination missing while weaker ones are in?
- Is a day overloaded (or empty), or is the pace wrong for this traveller?
- Are outdoor visits scheduled on the rainiest day while indoor ones sit on a sunny day?
- Does the plan honour what the traveller asked for (interests, food, must-visit places)?
- Is the day order sensible (e.g. heavy museum day right after a long flight)?

Each issue may carry ONE fix expressed as an existing planner action. Safe fixes (whitelisted below, all
grounded in researched data) are applied automatically and the plan is rebuilt, re-validated and re-scored;
the refined plan is kept only if it is at least as good (no new failures, TripScore not lower by more than
a point). Other issues become one-tap suggestions for the traveller. One reflection round per new plan.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

from .. import llm
from ..engine.ranking import fame
from ..models import TripState
from ..nlu import Action
from . import trace
from .context import plan_summary, profile_summary

log = logging.getLogger(__name__)

# Actions the critic may apply on its own: they only re-plan over researched data (no new searches).
SAFE_ACTIONS = {"reduce_density", "more_free_time", "less_walking", "more_food", "fewer_category", "more_category",
                "add_place", "replace_item"}
MAX_AUTO_FIXES = 3


class Issue(BaseModel):
    severity: Literal["high", "medium", "low"]
    day: int | None = None
    problem: str = Field(description="What is wrong, one short sentence in English")
    problem_ar: str = Field(default="", description="The same sentence in Egyptian Arabic")
    fix: Action | None = Field(default=None, description=(
        "One planner action that fixes it, or null. add_place: text = exact name from 'unused_top_places'. "
        "replace_item: text = exact title of an activity in the plan. fewer_category / more_category: category "
        "= one of museums, history, art, food, nature, beach, shopping, nightlife, architecture, religious. "
        "reduce_density: day = the overloaded day."))
    suggestion: str = Field(default="", description=(
        "The fix as a short request the traveller could send, in their language (Arabic if they write Arabic)"))


class Critique(BaseModel):
    quality: int = Field(description="0-100: how good this plan is for this traveller, as an expert would judge")
    verdict: str = Field(description="One sentence overall verdict in English")
    verdict_ar: str = Field(default="", description="The same verdict in Egyptian Arabic")
    strengths: list[str] = Field(default_factory=list, description="Up to 3 short strengths, English")
    issues: list[Issue] = Field(default_factory=list, description="At most 5, most important first")


SYSTEM = """You are a senior travel planner reviewing a day-by-day trip plan made by a junior planner (an algorithm)
for a specific traveller. Hard constraints (budget, opening hours, walking limits, time overlaps) were already
checked by code - do NOT re-check arithmetic. Judge QUALITY like an expert:
1. Iconic, must-see sights of the destination that are missing while weaker ones are included (only name places
   from 'unused_top_places' - never invent places).
2. Overloaded or empty days, and pace vs the traveller's style; a heavy day right after arrival.
3. Weather: outdoor visits on rainy days while indoor ones sit on dry days.
4. Fit: the traveller's interests, food wishes and explicit requests (see 'traveller' and 'recent_messages').
5. Variety: the same kind of place repeated too much.
Never contradict what the traveller explicitly asked for. Report only real, important issues (0 is fine for a
great plan). Give each fixable issue exactly one fix using the allowed actions; otherwise fix = null.
Budget gaps caused by flights or the hotel are handled elsewhere: never suggest dropping the destination's iconic
sights to save money. Never replace or remove a world-famous landmark (e.g. the Eiffel Tower, the Colosseum) - if a day
is too full, drop or move a weaker stop instead. Write *_ar fields in natural Egyptian Arabic, and every 'suggestion' in the language given by
'write_suggestions_in'."""


def _candidates(trip: TripState, limit: int = 14) -> list[dict]:
    """Well-known researched places the plan doesn't use (what the critic may propose adding)."""
    p, r = trip.selected_plan, trip.research
    if not p or not r:
        return []
    used = {i.place_id for d in p.days for i in d.items if i.place_id}
    excluded = set(trip.excluded_ids)
    # Overnight ideas (Milan from Rome) can't be added to a day: they're suggested separately, never by the critic.
    pool = [x for x in r.attractions if x.id not in used and x.id not in excluded and not x.dates
            and "overnight_trip" not in x.categories]
    pool.sort(key=lambda x: -(x.reviews_count or 0) * (x.rating or 4.0))
    return [{"name": x.name, "categories": x.categories[:3], "rating": x.rating, "reviews": x.reviews_count,
             "indoor": x.indoor, "day_trip": x.day_trip or None} for x in pool[:limit]]


async def review(trip: TripState) -> Critique | None:
    if not llm.available() or trip.selected_plan is None:
        return None
    msgs = [m.content[:400] for m in trip.conversation if m.role == "user"][-4:]
    arabic = any("؀" <= ch <= "ۿ" for ch in (msgs[-1] if msgs else ""))
    payload = {"plan": plan_summary(trip), "traveller": profile_summary(trip), "recent_messages": msgs,
               "write_suggestions_in": "Egyptian Arabic" if arabic else "English",
               "unused_top_places": _candidates(trip),
               "validator_warnings": [v.message for v in (trip.selected_plan.validation.violations
                                                          if trip.selected_plan.validation else [])][:8]}
    trace.step(trip, "critic", "thought", "Reviewing the plan as a senior travel planner.")
    out = await llm.parse(SYSTEM, json.dumps(payload, ensure_ascii=False, default=str), Critique)
    if out is None:
        return None
    out.quality = max(0, min(100, out.quality))
    out.issues = out.issues[:5]
    trace.step(trip, "critic", "decision", f"Quality {out.quality}/100 - {out.verdict}",
               issues=[f"[{i.severity}] {i.problem}" for i in out.issues])
    return out


def safe_fixes(trip: TripState, critique: Critique) -> list[tuple[Issue, Action]]:
    """The fixes the critic may apply without asking: whitelisted and grounded in the plan / research."""
    plan, r = trip.selected_plan, trip.research
    titles = {i.title.lower() for d in (plan.days if plan else []) for i in d.items if i.kind == "activity"}
    names = {x.name.lower() for x in (r.attractions if r else [])}
    # The destination's icons are never removed on the critic's own initiative (the traveller can still ask).
    icons = {x.name.lower() for x in (r.attractions if r else []) if fame(x) >= 0.8}
    out: list[tuple[Issue, Action]] = []
    for issue in critique.issues:
        a = issue.fix
        if a is None or issue.severity == "low" or a.action not in SAFE_ACTIONS:
            continue
        if a.action == "add_place" and (a.text or "").lower() not in names:
            continue  # only places we have real data for
        if a.action == "replace_item" and ((a.text or "").lower() not in titles or (a.text or "").lower() in icons):
            continue
        if a.action in ("fewer_category", "more_category") and not a.category:
            continue
        if a.action == "reduce_density" and not a.day:
            continue
        out.append((issue, a))
        if len(out) == MAX_AUTO_FIXES:
            break
    return out
