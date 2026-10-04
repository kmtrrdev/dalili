"""Short-term conversational memory: the last few turns of the chat, for the model to resolve references.

The Trip State (draft, contract, plan, pending questions) is the structured working memory; this adds the
words themselves, so "the second one", "that hotel" or "نفس المكان" can be understood from what was just said.
Long-term memory lives in the traveller profile (learned preferences) and the activity log (recommender).
"""

from __future__ import annotations

from .models import TripState

TURNS = 10           # messages kept (5 exchanges)
MAX_CHARS = 700      # per message: long plan summaries are cut, the start carries the gist


def recent_turns(trip: TripState, n: int = TURNS, exclude_last_user: bool = True) -> list[dict]:
    """The last `n` messages before the one being answered, oldest first: [{"role", "text"}]."""
    msgs = list(trip.conversation)
    if exclude_last_user and msgs and msgs[-1].role == "user":
        msgs = msgs[:-1]  # the current message is passed on its own
    out = []
    for m in msgs[-n:]:
        text = " ".join(m.content.split())
        out.append({"role": m.role, "text": text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "…"})
    return out
