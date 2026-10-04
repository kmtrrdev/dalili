"""Application service: sessions, persistence, what-if comparisons, mode selection."""

from __future__ import annotations

import re

from .models import ChatMessage, LearnedPreference, PlanningMode, TravelerProfile, TripState
from .narrative import money
from .nlu import Action
from .replanner import diff_plans
from .store import Store
from .workflow import run_turn, run_turn_stream

WHAT_IF = re.compile(r"^\s*(what if|what would happen if|how about if|suppose)\b", re.I)
APPLY = re.compile(r"^\s*(yes|yep|sure|ok|okay|apply( it)?|do it|go ahead|let'?s do (it|that)|sounds good)\b[.! ]*$", re.I)


def _fresh_profile(stored: TravelerProfile | None) -> TravelerProfile:
    """New trips inherit learned preferences but not trip-specific explicit choices."""
    if stored is None:
        return TravelerProfile()
    p = TravelerProfile(learned=stored.learned)
    for key, lp in stored.learned.items():
        if lp.confidence >= 0.5 and hasattr(p, key):
            setattr(p, key, lp.value)
    return p


class TravelAgentService:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()

    def new_trip(self, user_id: str = "default") -> TripState:
        return TripState(user_id=user_id, traveler_profile=_fresh_profile(self.store.load_profile(user_id)))

    def get(self, trip_id: str) -> TripState | None:
        return self.store.load_trip(trip_id)

    def _save(self, trip: TripState) -> None:
        self.store.save_trip(trip)
        self.store.save_profile(trip.user_id, trip.traveler_profile)

    async def chat(self, message: str, trip_id: str | None = None, user_id: str = "default",
                   route_decision: str | None = None) -> tuple[TripState, str]:
        trip = self.get(trip_id) if trip_id else None
        trip = trip or self.new_trip(user_id)

        pending = trip.metadata.get("pending_whatif")
        if pending and APPLY.match(message):
            applied = TripState.model_validate(pending)
            applied.metadata.pop("pending_whatif", None)
            applied.conversation = trip.conversation
            reply = "Done - I applied that change.\n\n" + "\n".join(f"- {c}" for c in applied.last_changes)
            applied.conversation.append(ChatMessage(role="user", content=message))
            applied.conversation.append(ChatMessage(role="assistant", content=reply))
            self._save(applied)
            return applied, reply
        trip.metadata.pop("pending_whatif", None)

        if WHAT_IF.match(message) and trip.plans:
            return await self._what_if_chat(trip, message)

        trip, reply = await run_turn(trip, message, route_decision=route_decision)
        self._save(trip)
        return trip, reply

    async def chat_stream(self, message: str, trip_id: str | None = None, user_id: str = "default",
                          route_decision: str | None = None):
        """Streaming variant of chat(): yields live node/tool events, then {"type": "done", ...}."""
        trip = self.get(trip_id) if trip_id else None
        trip = trip or self.new_trip(user_id)
        special = (trip.metadata.get("pending_whatif") and APPLY.match(message)) or (WHAT_IF.match(message) and trip.plans)
        if special:
            # Apply / what-if run on copies; stream them as a single step.
            yield {"type": "node", "node": "what_if" if WHAT_IF.match(message) else "apply", "ms": 0}
            trip, reply = await self.chat(message, trip_id, user_id)
            yield {"type": "done", "trip": trip, "reply": reply}
            return
        trip.metadata.pop("pending_whatif", None)
        async for event in run_turn_stream(trip, message, route_decision=route_decision):
            if event["type"] == "done":
                self._save(event["trip"])
            yield event

    async def _what_if_chat(self, trip: TripState, message: str) -> tuple[TripState, str]:
        """Plan the hypothetical on a copy; keep the real trip unchanged until the user confirms."""
        copy = trip.model_copy(deep=True)
        copy, _ = await run_turn(copy, message)
        before, after = trip.selected_plan, copy.selected_plan
        lines = ["**What-if comparison** (not applied yet)"]
        if before and after and before.budget and after.budget:
            lines.append(f"- Total: {money(before.budget.total, before.budget.currency)} -> "
                         f"{money(after.budget.total, after.budget.currency)}")
            if before.score and after.score:
                lines.append(f"- TripScore: {before.score.total} -> {after.score.total}")
        lines += [f"- {c}" for c in diff_plans(before, after) if not c.startswith(("Total cost", "TripScore"))]
        lines.append("\nSay **apply it** to switch to this version, or keep chatting to leave the plan as is.")
        reply = "\n".join(lines)
        copy.metadata.pop("pending_whatif", None)
        trip.metadata["pending_whatif"] = copy.model_dump(mode="json")
        trip.conversation.append(copy.conversation[-2])
        trip.conversation.append(copy.conversation[-1].model_copy(update={"content": reply}))
        self._save(trip)
        return trip, reply

    async def what_if(self, trip_id: str, budget_delta: float | None = None, budget: float | None = None,
                      apply: bool = False) -> dict:
        trip = self.get(trip_id)
        if trip is None or not trip.plans:
            raise KeyError(trip_id)
        action = (Action(action="adjust_budget", amount=budget_delta) if budget_delta is not None
                  else Action(action="set_budget", amount=budget))
        copy = trip.model_copy(deep=True)
        copy, reply = await run_turn(copy, "", preset_actions=[action])
        result = {
            "before": {m: {"total": p.budget.total if p.budget else None, "score": p.score.total if p.score else None,
                           "within_budget": p.within_budget} for m, p in trip.plans.items()},
            "after": {m: {"total": p.budget.total if p.budget else None, "score": p.score.total if p.score else None,
                          "within_budget": p.within_budget} for m, p in copy.plans.items()},
            "changes": diff_plans(trip.selected_plan, copy.selected_plan),
            "budget": copy.trip_contract.budget.amount if copy.trip_contract else None,
            "applied": apply,
        }
        if apply:
            self._save(copy)
        return result

    async def select_mode(self, trip_id: str, mode: PlanningMode) -> TripState:
        trip = self.get(trip_id)
        if trip is None or mode not in trip.plans:
            raise KeyError(trip_id)
        trip.selected_mode = mode
        trip.emit("plan.selected", mode=mode)
        # Selections are a learning signal (low confidence until repeated).
        lp = trip.traveler_profile.learned.get("preferred_mode") or LearnedPreference(value=mode, confidence=0.0)
        lp.confidence = min(0.9, lp.confidence + 0.2) if lp.value == mode else 0.2
        lp.value = mode
        trip.traveler_profile.learned["preferred_mode"] = lp
        self._save(trip)
        return trip

    async def replan(self, trip_id: str, actions: list[Action]) -> tuple[TripState, str]:
        trip = self.get(trip_id)
        if trip is None:
            raise KeyError(trip_id)
        trip, reply = await run_turn(trip, "", preset_actions=actions)
        self._save(trip)
        return trip, reply
