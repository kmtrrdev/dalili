"""Application service: sessions, persistence, what-if comparisons, mode selection."""

from __future__ import annotations

from . import preferences, whatif
from .config import settings
from .models import PLANNING_MODES, ChatMessage, PlanningMode, TripState
from .nlu import Action
from .store import Store
from .utils import is_arabic
from .workflow import run_turn, run_turn_stream

# Per-turn working keys that must never be saved with a trip that moved on (a comparison is only on the table until
# the next change).
_WHATIF_KEYS = ("pending_whatif", "pending_whatif_summary", "apply_whatif", "hypothetical", "budget_preview")


def _drop_pending(trip: TripState) -> None:
    for k in _WHATIF_KEYS:
        trip.metadata.pop(k, None)


class TravelAgentService:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()

    def new_trip(self, user_id: str = "default", prefs: dict | None = None) -> TripState:
        """A new trip starts from the traveller's preference memory (never from another trip's one-off choices) and
        their account settings: where they usually fly from and their currency (defaults a message overrides)."""
        trip = TripState(user_id=user_id, traveler_profile=preferences.fresh_profile(self.store.load_profile(user_id)))
        prefs = prefs or {}
        if prefs.get("home_city"):
            trip.metadata["home_city"] = prefs["home_city"]
        if prefs.get("currency"):
            trip.metadata["home_currency"] = prefs["currency"]
        mode = trip.traveler_profile.learned.get("preferred_mode")
        if mode and mode.value in PLANNING_MODES and preferences.confidence(mode) >= settings.preference_apply_threshold:
            trip.selected_mode = mode.value  # the plan type this traveller keeps choosing is shown first
        return trip

    def get(self, trip_id: str) -> TripState | None:
        return self.store.load_trip(trip_id)

    def _load_or_new(self, trip_id: str | None, user_id: str, prefs: dict | None = None) -> TripState:
        return (self.get(trip_id) if trip_id else None) or self.new_trip(user_id, prefs)

    def _save(self, trip: TripState) -> None:
        self.store.save_trip(trip)
        # Only the preference memory goes to the account, merged by recency - one trip's choices or the critic's
        # edits never overwrite who the traveller is.
        self.store.save_profile(trip.user_id, preferences.long_term(self.store.load_profile(trip.user_id),
                                                                    trip.traveler_profile))

    async def chat(self, message: str, trip_id: str | None = None, user_id: str = "default",
                   route_decision: str | None = None, prefs: dict | None = None) -> tuple[TripState, str]:
        trip = self._load_or_new(trip_id, user_id, prefs)
        # Every turn runs on a copy; what happens to the real trip is settled afterwards from the AI's reading of the
        # message (apply the change, keep it as a what-if comparison, or accept a pending comparison).
        work, reply = await run_turn(trip.model_copy(deep=True), message, route_decision=route_decision)
        return self._settle(trip, work, message, reply)

    async def chat_stream(self, message: str, trip_id: str | None = None, user_id: str = "default",
                          route_decision: str | None = None, prefs: dict | None = None):
        """Streaming variant of chat(): yields live node/tool events, then {"type": "done", ...}."""
        trip = self._load_or_new(trip_id, user_id, prefs)
        async for event in run_turn_stream(trip.model_copy(deep=True), message, route_decision=route_decision):
            if event["type"] == "done":
                settled, reply = self._settle(trip, event["trip"], message, event["reply"])
                event = {"type": "done", "trip": settled, "reply": reply}
            yield event

    def _keep_concurrent_choice(self, original: TripState, work: TripState) -> None:
        """A plan card picked while the turn was running is kept (unless the turn itself switched plans)."""
        latest = self.get(original.trip_id)
        if latest is None or latest.selected_mode == original.selected_mode:
            return
        if work.selected_mode == original.selected_mode and latest.selected_mode in work.plans:
            work.selected_mode = latest.selected_mode
            work.metadata["mode_observed"] = latest.metadata.get("mode_observed")
            if "preferred_mode" in latest.traveler_profile.learned:
                work.traveler_profile.learned["preferred_mode"] = latest.traveler_profile.learned["preferred_mode"]

    def _settle(self, original: TripState, work: TripState, message: str, reply: str) -> tuple[TripState, str]:
        arabic = is_arabic(message)
        pending = original.metadata.get("pending_whatif")
        if work.metadata.pop("apply_whatif", False) and pending:
            # The traveller accepted the comparison: switch to the version planned last turn.
            applied = TripState.model_validate(pending)
            _drop_pending(applied)
            head = "تمام، طبّقت التغيير:" if arabic else "Done - I applied that change:"
            reply = head + "\n\n" + "\n".join(f"- {c}" for c in applied.last_changes)
            applied.conversation = list(original.conversation) + [ChatMessage(role="user", content=message),
                                                                  ChatMessage(role="assistant", content=reply)]
            self._save(applied)
            return applied, reply
        if work.metadata.pop("hypothetical", False) and original.plans and work.plans and work.status == "planned":
            # A what-if: show the comparison, keep the real plan until the traveller accepts.
            # The same comparison the API returns: every plan, validity, requirements, changes, what was searched.
            lines = ["**مقارنة - لسه ماتطبقتش**" if arabic else "**What-if comparison** (not applied yet)"]
            lines += whatif.lines(whatif.compare(original, work), arabic)
            lines.append("\nلو عايز تطبّقها قولي **نفّذها**، أو كمّل كلام والخطة تفضل زي ما هي." if arabic else
                         "\nSay **apply it** to switch to this version, or keep chatting to leave the plan as is.")
            reply = "\n".join(lines)
            _drop_pending(work)
            original.metadata["pending_whatif"] = work.model_dump(mode="json")
            original.metadata["pending_whatif_summary"] = ("; ".join(lines[1:-1]))[:500]
            original.conversation += [ChatMessage(role="user", content=message),
                                      ChatMessage(role="assistant", content=reply)]
            self._save(original)
            return original, reply
        # A normal turn: the copy becomes the trip; any older comparison is no longer on the table.
        _drop_pending(work)
        self._keep_concurrent_choice(original, work)
        self._save(work)
        return work, reply

    async def what_if(self, trip_id: str, budget_delta: float | None = None, budget: float | None = None,
                      apply: bool = False) -> dict:
        trip = self.get(trip_id)
        if trip is None or not trip.plans:
            raise KeyError(trip_id)
        asked = {"delta": budget_delta, "budget": budget, "base": trip.updated_at.isoformat()}
        preview = trip.metadata.get("budget_preview") or {}
        if apply and {k: preview.get(k) for k in asked} == asked:
            # "Apply" saves exactly the version that was just compared - never a fresh replan that could differ.
            copy = TripState.model_validate(preview["trip"])
        else:
            action = (Action(action="adjust_budget", amount=budget_delta) if budget_delta is not None
                      else Action(action="set_budget", amount=budget))
            copy, _ = await run_turn(trip.model_copy(deep=True), "", preset_actions=[action])
        _drop_pending(copy)
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
        else:
            # Kept aside (the plan itself is unchanged) so that Apply can save this very version.
            trip.metadata["budget_preview"] = {**asked, "trip": copy.model_dump(mode="json")}
            self.store.save_trip(trip)
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
            if trip.metadata.get("mode_observed"):
                # The earlier choice in this trip is withdrawn before the new one counts.
                preferences.withdraw(trip.traveler_profile, "preferred_mode", trip.metadata["mode_observed"])
            preferences.observe(trip.traveler_profile, "preferred_mode", mode, f"chose the {mode} plan")
            trip.metadata["mode_observed"] = mode
        self._save(trip)
        return trip

    async def replan(self, trip_id: str, actions: list[Action]) -> tuple[TripState, str]:
        trip = self.get(trip_id)
        if trip is None:
            raise KeyError(trip_id)
        trip, reply = await run_turn(trip, "", preset_actions=actions)
        _drop_pending(trip)
        self._save(trip)
        return trip, reply
