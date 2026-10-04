"""Application service: sessions, persistence, what-if comparisons, mode selection."""

from __future__ import annotations

from .models import ChatMessage, LearnedPreference, PlanningMode, TravelerProfile, TripState
from .narrative import money
from .nlu import Action
from .replanner import diff_plans
from .store import Store
from .workflow import run_turn, run_turn_stream


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
        # Every turn runs on a copy; what happens to the real trip is settled afterwards from the AI's reading of the
        # message (apply the change, keep it as a what-if comparison, or accept a pending comparison).
        work, reply = await run_turn(trip.model_copy(deep=True), message, route_decision=route_decision)
        return self._settle(trip, work, message, reply)

    async def chat_stream(self, message: str, trip_id: str | None = None, user_id: str = "default",
                          route_decision: str | None = None):
        """Streaming variant of chat(): yields live node/tool events, then {"type": "done", ...}."""
        trip = self.get(trip_id) if trip_id else None
        trip = trip or self.new_trip(user_id)
        async for event in run_turn_stream(trip.model_copy(deep=True), message, route_decision=route_decision):
            if event["type"] == "done":
                settled, reply = self._settle(trip, event["trip"], message, event["reply"])
                event = {"type": "done", "trip": settled, "reply": reply}
            yield event

    def _settle(self, original: TripState, work: TripState, message: str, reply: str) -> tuple[TripState, str]:
        arabic = any("؀" <= ch <= "ۿ" for ch in message)
        pending = original.metadata.get("pending_whatif")
        if work.metadata.pop("apply_whatif", False) and pending:
            # The traveller accepted the comparison: switch to the version planned last turn.
            applied = TripState.model_validate(pending)
            for k in ("pending_whatif", "pending_whatif_summary", "hypothetical"):
                applied.metadata.pop(k, None)
            head = "تمام، طبّقت التغيير:" if arabic else "Done - I applied that change:"
            reply = head + "\n\n" + "\n".join(f"- {c}" for c in applied.last_changes)
            applied.conversation = list(original.conversation) + [ChatMessage(role="user", content=message),
                                                                  ChatMessage(role="assistant", content=reply)]
            self._save(applied)
            return applied, reply
        if work.metadata.pop("hypothetical", False) and original.plans and work.plans:
            # A what-if: show the comparison, keep the real plan until the traveller accepts.
            before, after = original.selected_plan, work.selected_plan
            changes = [c for c in diff_plans(before, after) if not c.startswith(("Total cost", "TripScore"))]
            lines = ["**مقارنة - لسه ماتطبقتش**" if arabic else "**What-if comparison** (not applied yet)"]
            if before and after and before.budget and after.budget:
                lines.append(f"- {'الإجمالي' if arabic else 'Total'}: {money(before.budget.total, before.budget.currency)}"
                             f" -> {money(after.budget.total, after.budget.currency)}")
                if before.score and after.score:
                    lines.append(f"- TripScore: {before.score.total} -> {after.score.total}")
            lines += [f"- {c}" for c in changes]
            lines.append("\nلو عايز تطبّقها قولي **نفّذها**، أو كمّل كلام والخطة تفضل زي ما هي." if arabic else
                         "\nSay **apply it** to switch to this version, or keep chatting to leave the plan as is.")
            reply = "\n".join(lines)
            for k in ("pending_whatif", "pending_whatif_summary"):
                work.metadata.pop(k, None)
            original.metadata["pending_whatif"] = work.model_dump(mode="json")
            original.metadata["pending_whatif_summary"] = ("; ".join(lines[1:-1]))[:500]
            original.conversation += [ChatMessage(role="user", content=message),
                                      ChatMessage(role="assistant", content=reply)]
            self._save(original)
            return original, reply
        # A normal turn: the copy becomes the trip; any older comparison is no longer on the table.
        for k in ("pending_whatif", "pending_whatif_summary", "apply_whatif"):
            work.metadata.pop(k, None)
        self._save(work)
        return work, reply

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
