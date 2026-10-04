"""Long-term preference memory: stated vs inferred, evidence, contradiction, decay, and what reaches the account."""

from datetime import UTC, datetime, timedelta

from travel_agent import preferences
from travel_agent.models import LearnedPreference, TravelerProfile, TripState
from travel_agent.nlu import Action, FeedbackNote
from travel_agent.replanner import apply_actions, learn_from_feedback
from travel_agent.service import TravelAgentService
from travel_agent.store import Store


def test_stated_preferences_are_trusted_and_never_overridden_by_behaviour():
    p = TravelerProfile()
    preferences.state(p, "walking_tolerance", "high")
    for _ in range(5):
        preferences.observe(p, "walking_tolerance", "low", "complained about walking")
    assert p.learned["walking_tolerance"].value == "high"
    assert preferences.confidence(p.learned["walking_tolerance"]) == preferences.STATED_CONFIDENCE


def test_one_complaint_is_a_hint_two_are_a_habit():
    p = TravelerProfile()
    preferences.observe(p, "noise_tolerance", "low", "street noise at night")
    assert preferences.confidence(p.learned["noise_tolerance"]) < 0.5
    assert preferences.apply(p) == [] and p.noise_tolerance == "medium"
    preferences.observe(p, "noise_tolerance", "low", "noisy again")
    assert preferences.confidence(p.learned["noise_tolerance"]) >= 0.5
    assert "noise_tolerance" in preferences.apply(p) and p.noise_tolerance == "low"


def test_contradicting_behaviour_weakens_then_replaces_a_preference():
    p = TravelerProfile()
    for _ in range(2):
        preferences.observe(p, "travel_style", "active", "asked for more")
    strong = preferences.confidence(p.learned["travel_style"])
    preferences.observe(p, "travel_style", "relaxed", "asked for less")
    assert p.learned["travel_style"].value == "active" and preferences.confidence(p.learned["travel_style"]) < strong
    preferences.observe(p, "travel_style", "relaxed", "asked for less again")
    assert p.learned["travel_style"].value == "active"  # a tie keeps the old habit
    preferences.observe(p, "travel_style", "relaxed", "and again")
    assert p.learned["travel_style"].value == "relaxed"  # more evidence against than for: the habit changed


def test_old_behaviour_fades():
    lp = LearnedPreference(value="low", support=3, updated_at=datetime.now(UTC))
    old = lp.model_copy(update={"updated_at": datetime.now(UTC) - timedelta(days=720)})
    assert preferences.confidence(old) < preferences.confidence(lp) / 4


def test_explicit_choice_in_this_trip_wins_over_memory():
    p = TravelerProfile(walking_tolerance="high", explicit_fields=["walking_tolerance"])
    for _ in range(3):
        preferences.observe(p, "walking_tolerance", "low", "tired")
    preferences.apply(p)
    assert p.walking_tolerance == "high"


def test_feedback_learns_but_the_critic_does_not():
    trip = TripState()
    learn_from_feedback(trip, [FeedbackNote(feedback_type="hotel", sentiment="negative", attribute="noise", severity=1.0)],
                        "too noisy")
    assert trip.traveler_profile.learned["noise_tolerance"].support == 1.0
    apply_actions(trip, [Action(action="increase_density")], by_traveller=False)  # an expert fix
    assert "travel_style" not in trip.traveler_profile.learned
    assert "travel_style" not in trip.traveler_profile.explicit_fields


def test_only_the_memory_reaches_the_account_and_merges_by_recency():
    svc = TravelAgentService(Store(":memory:"))
    a = svc.new_trip("u1")
    preferences.state(a.traveler_profile, "dietary_restrictions", ["vegetarian"])
    a.traveler_profile.walking_tolerance = "high"  # a one-off choice for this trip
    a.traveler_profile.explicit_fields = ["walking_tolerance"]
    svc._save(a)
    b = svc.new_trip("u1")
    assert b.traveler_profile.dietary_restrictions == ["vegetarian"]  # remembered
    assert b.traveler_profile.walking_tolerance == "medium"            # not carried over
    preferences.observe(b.traveler_profile, "noise_tolerance", "low", "noisy")
    svc._save(b)
    stored = svc.store.load_profile("u1")
    assert set(stored.learned) == {"dietary_restrictions", "noise_tolerance"}
