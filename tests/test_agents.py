"""The AI agents (review analyst, concierge, critic) with a scripted model over recorded real data."""

import json

import anyio
import pytest

from travel_agent import llm
from travel_agent.agents import concierge, critic, review_analyst
from travel_agent.models import ReviewInsights, TripState
from travel_agent.nlu import Action
from travel_agent.narrative import plan_facts
from travel_agent.workflow import EXPERT_PICK, run_turn

from .conftest import ROME_REQUEST


@pytest.fixture(scope="module")
def rome():
    trip, _ = anyio.run(run_turn, TripState(), ROME_REQUEST)
    return trip


def scripted(monkeypatch, handler):
    """A fake model: handler(system, payload_dict, schema) -> instance | None. Free text is left to templates."""
    calls = []

    async def parse(system, user, schema, max_tokens=16000, effort=None, timeout=None):
        payload = json.loads(user) if user.strip().startswith("{") else user
        calls.append((schema.__name__, payload))
        return handler(system, payload, schema)

    async def text(system, user, max_tokens=4000, effort=None, timeout=None):
        return None

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "parse", parse)
    monkeypatch.setattr(llm, "text", text)
    return calls


# ---------------------------------------------------------------- review analyst

def test_review_analyst_keeps_only_real_quotes_and_clamps_scores(monkeypatch):
    reviews = [{"rating": 5, "snippet": "Spotless rooms and lovely staff."},
               {"rating": 3, "snippet": "Street noise at night was loud, bring earplugs."},
               {"rating": 4, "snippet": "Great location near the metro."}]
    scripted(monkeypatch, lambda s, p, schema: ReviewInsights(
        summary="Clean, central, can be noisy.", pros=["clean", "location"], cons=["street noise"],
        aspects={"cleanliness": 7, "quietness": 0.2}, noise_level="moderate",
        noise_evidence=["Street noise at night was loud", "The disco next door kept us awake"]))
    out = anyio.run(review_analyst.analyze, "Hotel Test", reviews)
    assert out.reviews_read == 3 and out.noise_level == "moderate"
    assert out.noise_evidence == ["Street noise at night was loud"]  # the invented quote is dropped
    assert out.aspects == {"cleanliness": 5.0, "quietness": 1.0}


def test_review_analyst_needs_a_model_and_enough_reviews(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)
    assert anyio.run(review_analyst.analyze, "H", [{"snippet": "ok"}] * 5) is None


# ---------------------------------------------------------------- concierge (ReAct)

def test_concierge_reasons_calls_tools_and_grounds_the_answer(monkeypatch, rome):
    trip = rome.model_copy(deep=True)
    day2 = trip.selected_plan.days[1]
    script = iter([
        concierge.Step(thought="I need day 2's schedule.", tool="plan_lookup", args={"day": 2}),
        concierge.Step(thought="Now the forecast for that day.", tool="weather", args={"day": 2}),
        concierge.Step(thought="Enough to answer.", tool="final_answer", answer="Day 2 is fine.",
                       follow_ups=["Make day 2 lighter", "", "Add more food on day 2", "x", "y"]),
    ])
    calls = scripted(monkeypatch, lambda s, p, schema: next(script))
    res = anyio.run(concierge.answer, trip, "What am I doing on day 2 and will it rain?")
    assert res.answer == "Day 2 is fine." and res.steps == 3
    assert res.follow_ups == ["Make day 2 lighter", "Add more food on day 2", "x"]  # blanks dropped, max 3
    # Each step sees the real observations of the previous ones.
    last_payload = calls[-1][1]
    obs = [s["observation"] for s in last_payload["steps_so_far"]]
    assert day2.title in obs[0] and len(obs) == 2
    kinds = [s["kind"] for s in trip.metadata["agent_trace"] if s["agent"] == "concierge"]
    assert kinds.count("tool") == 2 and kinds.count("observation") == 2 and kinds[-1] == "answer"


def test_concierge_is_forced_to_answer_after_max_steps(monkeypatch, rome):
    trip = rome.model_copy(deep=True)

    def handler(s, payload, schema):
        if payload.get("instruction"):
            return concierge.Step(thought="Wrapping up.", tool="final_answer", answer="Here is what I found.")
        return concierge.Step(thought="Look again.", tool="plan_lookup", args={})

    scripted(monkeypatch, handler)
    res = anyio.run(concierge.answer, trip, "Tell me everything")
    assert res.answer == "Here is what I found." and res.steps == concierge.MAX_STEPS


def test_concierge_falls_back_without_a_model(monkeypatch, rome):
    monkeypatch.setattr(llm, "available", lambda: False)
    assert anyio.run(concierge.answer, rome, "Do I need to tip?") is None


# ---------------------------------------------------------------- critic (self-reflection)

def test_critic_only_auto_applies_safe_grounded_fixes(rome):
    trip = rome.model_copy(deep=True)
    # A full plan may use every researched sight: free one so the critic has a real, unused place to propose.
    day = next(d for d in trip.selected_plan.days if sum(i.kind == "activity" for i in d.items) > 1)
    day.items.remove(next(i for i in day.items if i.kind == "activity"))
    real = critic._candidates(trip)[0]["name"]
    from travel_agent.engine.ranking import icon_ids
    icons = set(icon_ids(trip.research.attractions))  # the critic may never swap out an icon
    in_plan = next(i.title for d in trip.selected_plan.days for i in d.items if i.kind == "activity" and i.place_id not in icons)
    crit = critic.Critique(quality=70, verdict="ok", issues=[
        critic.Issue(severity="high", problem="Missing icon", fix=Action(action="add_place", text=real)),
        critic.Issue(severity="high", problem="Invented", fix=Action(action="add_place", text="Palazzo Imaginario")),
        critic.Issue(severity="low", problem="Minor", fix=Action(action="more_food")),
        critic.Issue(severity="medium", problem="Hotel", fix=Action(action="change_hotel")),  # not whitelisted
        critic.Issue(severity="medium", problem="Swap", fix=Action(action="replace_item", text=in_plan)),
    ])
    fixes = critic.safe_fixes(trip, crit)
    assert [(a.action, a.text) for _, a in fixes] == [("add_place", real), ("replace_item", in_plan)]


def test_critic_refines_a_new_plan_and_verifies_it(monkeypatch):
    chosen = {}

    def handler(system, payload, schema):
        if schema is critic.Critique:
            name = payload["unused_top_places"][0]["name"]
            chosen["name"] = name
            return critic.Critique(quality=72, verdict="Solid, but an iconic sight is missing.", issues=[
                critic.Issue(severity="high", problem=f"{name} is missing", fix=Action(action="add_place", text=name),
                             suggestion=f"Add {name}"),
                critic.Issue(severity="medium", problem="Day 3 is long", suggestion="Make day 3 lighter"),
            ])
        return None  # everything else uses the deterministic fallbacks

    calls = scripted(monkeypatch, handler)
    # A relaxed pace leaves famous places unscheduled for the critic to propose (a full pace may use them all).
    trip, reply = anyio.run(run_turn, TripState(), ROME_REQUEST + " A relaxed pace please.")
    assert [c for c, _ in calls].count("Critique") == 1  # one reflection round
    crit = trip.metadata["critique"]
    applied = [i for i in crit["issues"] if i["applied"]]
    trace = [s["text"] for s in trip.metadata["agent_trace"] if s["agent"] == "critic"]
    if applied:  # refinement kept: the place is now in the plan, verified by the second pass
        assert chosen["name"] in trip.selected_plan.requested and trip.selected_plan.requested[chosen["name"]]
        assert any(t.startswith("Refinement kept") for t in trace)
        # It is the expert's pick, not something the traveller asked for.
        item = next(i for d in trip.selected_plan.days for i in d.items if i.title == chosen["name"])
        assert item.explanation[0] == EXPERT_PICK
        facts = plan_facts(trip)
        assert chosen["name"] not in facts["places_you_asked_for"]
        assert chosen["name"] in facts["highlights_added_by_expert_review"]
    else:
        assert any(t.startswith("Refinement rejected") for t in trace)
    assert trip.selected_plan.validation.result == "PASS"
    assert "Make day 3 lighter" in trip.metadata["suggestions"]  # the unapplied idea becomes a one-tap reply
