"""Application service: sessions, persistence, what-if comparisons, mode selection."""

from __future__ import annotations

from . import preferences, whatif
from .models import ChatMessage, PlanningMode, TripState
from .nlu import Action
from .config import settings
from .store import Store
from .workflow import run_turn, run_turn_stream


class TravelAgentService:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()

    def new_trip(self, user_id: str = "default") -> TripState:
        """A new trip starts from the traveller's preference memory (never from another trip's one-off choices)."""
        trip = TripState(user_id=user_id, traveler_profile=preferences.fresh_profile(self.store.load_profile(user_id)))
        mode = trip.traveler_profile.learned.get("preferred_mode")
        if mode and mode.value in ("balanced", "budget", "comfort", "experience") \
                and preferences.confidence(mode) >= settings.preference_apply_threshold:
            trip.selected_mode = mode.value  # the plan type this traveller keeps choosing is shown first
        return trip

    def get(self, trip_id: str) -> TripState | None:
        return self.store.load_trip(trip_id)

    def _save(self, trip: TripState) -> None:
        self.store.save_trip(trip)
        # Only the preference memory goes to the account, merged by recency - one trip's choices or the critic's
        # edits never overwrite who the traveller is.
        self.store.save_profile(trip.user_id, preferences.long_term(self.store.load_profile(trip.user_id),
                                                                    trip.traveler_profile))

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
            # The same comparison the API returns: every plan, validity, requirements, changes, what was searched.
            lines = ["**مقارنة - لسه ماتطبقتش**" if arabic else "**What-if comparison** (not applied yet)"]
            lines += whatif.lines(whatif.compare(original, work), arabic)
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
        cmp = whatif.compare(trip, copy)
        result = {
            # (kept for existing clients) per-mode totals before / after
            "before": {m: v["before"] for m, v in cmp["plans"].items() if v["before"]},
            "after": {m: v["after"] for m, v in cmp["plans"].items() if v["after"]},
            **{k: v for k, v in cmp.items() if k != "plans"},
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
        # Selections are evidence about the traveller (used once repeated; see new_trip).
        # One trip counts once (its latest choice), however often the cards are clicked.
        if trip.metadata.get("mode_observed") != mode:
            lp = trip.traveler_profile.learned.get("preferred_mode")
            if trip.metadata.get("mode_observed") and lp and lp.source == "inferred":
                # The earlier choice in this trip is withdrawn before the new one counts.
                if lp.value == trip.metadata["mode_observed"]:
                    lp.support = max(0.0, lp.support - 1)
                else:
                    lp.against = max(0.0, lp.against - 1)
            preferences.observe(trip.traveler_profile, "preferred_mode", mode, f"chose the {mode} plan")
            trip.metadata["mode_observed"] = mode
        self._save(trip)
        return trip

    async def replan(self, trip_id: str, actions: list[Action]) -> tuple[TripState, str]:
        trip = self.get(trip_id)
        if trip is None:
            raise KeyError(trip_id)
        trip, reply = await run_turn(trip, "", preset_actions=actions)
        self._save(trip)
        return trip, reply
