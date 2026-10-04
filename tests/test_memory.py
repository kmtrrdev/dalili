from travel_agent.memory import MAX_CHARS, TURNS, recent_turns
from travel_agent.models import ChatMessage, TripState


def _trip(*msgs):
    t = TripState()
    t.conversation = [ChatMessage(role=r, content=c) for r, c in msgs]
    return t


def test_recent_turns_keep_the_last_messages_before_the_current_one():
    n = TURNS + 4
    t = _trip(*[("user" if i % 2 == 0 else "assistant", f"message {i}") for i in range(n)], ("user", "the second one"))
    turns = recent_turns(t)
    assert [x["text"] for x in turns] == [f"message {i}" for i in range(n - TURNS, n)]   # oldest first, current excluded
    assert turns[-1]["role"] == "assistant"


def test_long_replies_are_trimmed_and_whitespace_collapsed():
    t = _trip(("assistant", "Day 1:\n\n" + "word " * 400), ("user", "ok"))
    (only,) = recent_turns(t)
    assert len(only["text"]) <= MAX_CHARS + 1 and only["text"].endswith("…") and "\n" not in only["text"]


def test_a_new_trip_has_no_memory_yet():
    assert recent_turns(_trip(("user", "A week in Rome"))) == []
