"""Data quality gate and the validators that never let unverifiable data pass silently."""

from datetime import datetime, timedelta, timezone

from travel_agent import data_quality
from travel_agent.engine.knobs import PlanKnobs
from travel_agent.engine.planner import PlanContext, build_plan
from travel_agent.engine.validators import validate_freshness, validate_preferences


def test_bad_coordinates_duplicates_and_outlier_prices_are_removed(rome_research):
    r = rome_research.model_copy(deep=True)
    broken = r.attractions[0].model_copy(update={"id": "bad", "location": r.attractions[0].location.model_copy(
        update={"lat": 0.0, "lon": 0.0})})
    twin = r.attractions[1].model_copy(update={"id": "twin", "reviews_count": 1})
    crazy = r.hotels[0].model_copy(update={"id": "crazy", "name": "Typo Palace",
                                           "price_per_night": r.hotels[0].price_per_night.model_copy(update={"amount": 999999})})
    r.attractions += [broken, twin]
    r.hotels.append(crazy)
    notes = data_quality.check(r)
    ids = {a.id for a in r.attractions}
    assert "bad" not in ids and "twin" not in ids and r.attractions[1].id in ids  # kept the better-documented one
    assert "crazy" not in {h.id for h in r.hotels}
    assert len(notes) >= 3 and all(n in r.errors for n in notes)


def test_unverifiable_dietary_needs_are_flagged(rome_research, rome_contract, profile):
    halal = profile.model_copy(update={"dietary_restrictions": ["halal"]})
    plan = build_plan(PlanContext(contract=rome_contract, profile=halal, research=rome_research, mode="balanced",
                                  knobs=PlanKnobs()))
    msgs = [v.message for v in validate_preferences(plan, rome_contract, halal, rome_research)]
    assert any(m.startswith("Halal options couldn't be verified") for m in msgs)


def test_old_or_stale_prices_are_flagged(rome_research, rome_contract, profile):
    plan = build_plan(PlanContext(contract=rome_contract, profile=profile, research=rome_research, mode="balanced",
                                  knobs=PlanKnobs()))
    plan.hotel.metadata.retrieved_at = datetime.now(timezone.utc)
    plan.hotel.metadata.stale = True
    plan.outbound_flight.metadata.retrieved_at = datetime.now(timezone.utc) - timedelta(days=5)
    msgs = [v.message for v in validate_freshness(plan)]
    assert any("earlier search" in m for m in msgs) and any("5 days ago" in m for m in msgs)
    assert all(v.severity == "warning" for v in validate_freshness(plan))
