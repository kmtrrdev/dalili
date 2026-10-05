"""Hierarchical TripScore (feasibility > requirements > preferences > quality), traveller-driven weights, and the
critic's multi-objective acceptance."""

from travel_agent.engine.knobs import PlanKnobs
from travel_agent.engine.planner import PlanContext, build_plan
from travel_agent.engine.scoring import score_plan, weights_for
from travel_agent.engine.validators import validate_plan
from travel_agent.models import TripScore, TripState, ValidationReport, Violation
from travel_agent.workflow import refinement_verdict


def _plan(contract, research, profile, mode="balanced"):
    p = build_plan(PlanContext(contract=contract, profile=profile, research=research, mode=mode, knobs=PlanKnobs()))
    p.validation = validate_plan(p, contract, profile, research, 0.05)
    return p


def test_a_broken_plan_never_outranks_a_sound_one(rome_research, rome_contract, profile):
    good = _plan(rome_contract, rome_research, profile)
    good.validation = ValidationReport(result="PASS", violations=[])
    bad = good.model_copy(deep=True)
    bad.validation = ValidationReport(result="FAIL", violations=[Violation(check="schedule", severity="error", message="x")])
    s_good = score_plan(good, rome_contract, profile, rome_research, "balanced")
    s_bad = score_plan(bad, rome_contract, profile, rome_research, "balanced")
    assert s_good.feasible and not s_bad.feasible
    assert s_bad.total <= 49 and s_good.rank_key() > s_bad.rank_key()
    # even with the same (or better) experience parts, feasibility decides first
    s_bad_best = s_bad.model_copy(update={"quality": 100, "preference_satisfaction": 100})
    assert s_good.rank_key() > s_bad_best.rank_key()


def test_what_the_traveller_values_reweights_the_score():
    plain = weights_for("balanced", [])
    cost_first = weights_for("balanced", ["cost"])
    comfort_first = weights_for("balanced", ["comfort", "food"])
    assert cost_first["budget_fit"] > plain["budget_fit"]
    assert comfort_first["comfort"] > plain["comfort"] and comfort_first["food"] > plain["food"]
    assert abs(sum(cost_first.values()) - 1) < 1e-3


def _scored(score: TripScore, plan):
    p = plan.model_copy(deep=True)
    p.score = score
    return p


def test_critic_refinement_needs_more_than_a_better_score(rome_research, rome_contract, profile):
    plan = _plan(rome_contract, rome_research, profile)
    trip = TripState(trip_contract=rome_contract, research=rome_research)
    base = score_plan(plan, rome_contract, profile, rome_research, "balanced")
    before = _scored(base, plan)
    better = _scored(base.model_copy(update={"quality": base.quality + 5, "total": base.total + 5}), plan)
    assert refinement_verdict(trip, before, better)[0]
    # better quality but a requirement no longer met: rejected
    worse_req = _scored(base.model_copy(update={"quality": base.quality + 10,
                                                "constraint_satisfaction": base.constraint_satisfaction - 50}), plan)
    ok, why = refinement_verdict(trip, before, worse_req)
    assert not ok and any("requirements" in w for w in why)
    # better quality but a new hard violation: rejected
    broken = worse_req.model_copy(deep=True)
    broken.score = base.model_copy(update={"quality": base.quality + 10})
    broken.validation = ValidationReport(result="FAIL", violations=[Violation(check="schedule", severity="error",
                                                                              message="overlap")])
    assert not refinement_verdict(trip, before, broken)[0]
