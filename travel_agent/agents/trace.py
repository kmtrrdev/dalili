"""Agent trace: what each agent thought and did during the last turn (shown in the AI view of the UI)."""

from __future__ import annotations

import time
from typing import Any

from ..models import TripState

MAX_STEPS = 60


def start(trip: TripState) -> None:
    trip.metadata["agent_trace"] = []


def step(trip: TripState, agent: str, kind: str, text: str, **data: Any) -> None:
    """kind: thought | tool | observation | decision | fix | answer."""
    trace = trip.metadata.setdefault("agent_trace", [])
    if len(trace) < MAX_STEPS:
        trace.append({"agent": agent, "kind": kind, "text": text[:600], "at": round(time.time(), 2),
                      **{k: v for k, v in data.items() if v is not None}})
    trip.emit(f"agent.{agent}.{kind}", text=text[:300], **data)
