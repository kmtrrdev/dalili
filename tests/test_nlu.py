from datetime import date

import pytest

from travel_agent.nlu import extract_places, interpret_rules, named_places, parse_budget, parse_dates
from travel_agent.research import match_place

TODAY = date(2026, 9, 27)


def test_named_places_are_extracted():
    assert named_places("Please add the Vatican Museums to my plan") == ["Vatican Museums"]
    assert named_places("I also want to see Sagrada Familia and Park Güell") == ["Sagrada Familia", "Park Güell"]
    assert named_places("I want to visit Rome and Paris", exclude=["Rome", "Paris"]) == []
    assert named_places("add more food experiences") == []
    assert named_places("add 2 more days") == []
    r, _ = interpret_rules("add the Vatican Museums", True, {}, TODAY)
    assert r.intent == "feedback" and [(a.action, a.text) for a in r.actions] == [("add_place", "Vatican Museums")]
    assert req("7 days in Rome from October 12, $3000, I want to see the Trevi Fountain").must_visit == ["Trevi Fountain"]


def test_match_place_is_fuzzy(rome_research):
    colosseum = next(a for a in rome_research.attractions if a.name == "Colosseum")
    assert match_place("the colosseum", rome_research.attractions) is colosseum
    assert match_place("Eiffel Tower", rome_research.attractions) is None


def req(text):
    r, _ = interpret_rules(text, False, {}, TODAY)
    return r.requirements


@pytest.mark.parametrize("text,dest,origin", [
    ("I want to visit Italy for 8 days with my wife", "Italy", None),
    ("7 days in Rome from October 12 for two", "Rome", None),
    ("Paris Oct 20-25 for two, 5000 EUR", "Paris", None),
    ("trip to New York from Cairo in December", "New York", "Cairo"),
    ("We want to go to barcelona next month", "barcelona", None),
    ("Tokyo, 10 days, from Dubai, budget 5000 USD", "Tokyo", "Dubai"),
    ("I want to go somewhere warm in December", None, None),
    ("I love food and photography", None, None),
])
def test_place_extraction_is_open_world(text, dest, origin):
    assert extract_places(text) == (dest, origin)


def test_concept_example():
    r = req("I have $2,000 for 7 days in Rome. I like Italian food, photography, museums, and relaxed days. "
            "I don't want to wake up early and I don't like walking for long distances.")
    assert r.destination == "Rome" and r.duration_days == 7 and r.budget_amount == 2000
    assert "italian" in r.food_preferences and {"photography", "museums"} <= set(r.activity_preferences)
    assert r.walking_tolerance == "low" and r.travel_style == "relaxed" and r.preferred_wake_up_time >= "09:00"


@pytest.mark.parametrize("text,expected", [
    ("Paris Oct 12-19", ("2026-10-12", "2026-10-19")),
    ("from 3 to 9 November", ("2026-11-03", "2026-11-09")),
    ("2026-12-01 to 2026-12-05", ("2026-12-01", "2026-12-05")),
])
def test_date_ranges(text, expected):
    s, e, _, _ = parse_dates(text, TODAY)
    assert (s.isoformat(), e.isoformat()) == expected


@pytest.mark.parametrize("text,amount,cur", [
    ("under $1,500", 1500, "USD"), ("budget of 2.5k", 2500, None), ("I can spend 40000 EGP", 40000, "EGP"), ("€1800 max", 1800, "EUR"),
])
def test_budgets(text, amount, cur):
    a, c, _ = parse_budget(text)
    assert a == amount and c == cur


@pytest.mark.parametrize("text,travelers", [("for two", 2), ("family of 4", 4), ("3 friends", 3), ("solo trip", 1), ("for 7 days", None)])
def test_travelers(text, travelers):
    assert req(f"Rome {text}").travelers == travelers


@pytest.mark.parametrize("text,action", [
    ("Today's itinerary is too crowded", "reduce_density"), ("Make it cheaper.", "cheaper"),
    ("Remove two museums", "fewer_category"), ("I want more nightlife.", "more_nightlife"),
    ("I don't want to wake up before 10.", "later_start"), ("What if I increase my budget by $300?", "adjust_budget"),
    ("My budget is only $1,700", "set_budget"), ("I want to stay two more days", "extend_trip"),
    ("Add more food experiences.", "more_food"), ("Let's go with the comfort plan", "select_mode"),
])
def test_feedback_actions(text, action):
    r, _ = interpret_rules(text, True, {}, TODAY)
    assert r.intent == "feedback" and any(a.action == action for a in r.actions)


def test_feedback_does_not_change_destination():
    r, _ = interpret_rules("Remove the Colosseum please", True, {"a_x": "Colosseum"}, TODAY)
    assert r.requirements.destination is None
    assert any(a.action == "replace_item" and a.text == "a_x" for a in r.actions)
