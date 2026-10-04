"""Persistence for trip states, traveler profiles and the event log.

SQLite in development and tests; PostgreSQL in production (DATABASE_URL), through db.connect - same SQL.
"""

from __future__ import annotations

import json
import sqlite3
import threading

from . import db
from .config import settings
from .models import TravelerProfile, TripState

SCHEMA = """
CREATE TABLE IF NOT EXISTS trips (
    trip_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
    user_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- BIGSERIAL on PostgreSQL (db.py)
    trip_id TEXT NOT NULL,
    type TEXT NOT NULL,
    at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_trip ON events(trip_id);
"""


def trip_summary(trip_id: str, d: dict, updated: str) -> dict:
    """One row of "My trips": where, when, how much, how good - read from the saved trip JSON."""
    c = d.get("trip_contract") or {}
    draft = d.get("draft") or {}
    stops = [(s.get("ref") or {}) for s in c.get("stops") or []]
    ref = c.get("destination_ref") or {}
    cities = [s.get("name") for s in stops if s.get("name")] or [c.get("destination_name") or c.get("destination")
                                                                  or draft.get("destination")]
    countries = sorted({s.get("country") for s in stops if s.get("country")} or ({ref["country"]} if ref.get("country") else set()))
    plan = (d.get("plans") or {}).get(d.get("selected_mode") or "balanced") or {}
    budget = plan.get("budget") or {}
    days = None
    if c.get("start_date") and c.get("end_date"):
        from datetime import date

        days = (date.fromisoformat(c["end_date"]) - date.fromisoformat(c["start_date"])).days + 1
    return {"trip_id": trip_id, "destination": " → ".join(x for x in cities if x) or None,
            "cities": [x for x in cities if x], "countries": countries,
            "lat": ref.get("lat"), "lon": ref.get("lon"),
            "origin": c.get("origin_city"), "start_date": c.get("start_date"), "end_date": c.get("end_date"),
            "days": days, "travelers": c.get("travelers"), "status": d.get("status"),
            "mode": d.get("selected_mode"), "total": budget.get("total"),
            "currency": budget.get("currency") or (c.get("budget") or {}).get("currency"),
            "budget": (c.get("budget") or {}).get("amount"),
            "score": (plan.get("score") or {}).get("total"), "created_at": d.get("created_at"), "updated_at": updated}


class Store:
    def __init__(self, path: str | None = None):
        self.path = path or settings.db_path
        # SQLite here; PostgreSQL in production when DATABASE_URL is set (an explicit ":memory:" stays SQLite).
        self._conn = sqlite3.connect(":memory:", check_same_thread=False) if self.path == ":memory:" else db.connect(self.path)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def save_trip(self, trip: TripState) -> None:
        with self._lock, self._conn:
            row = self._conn.execute("SELECT data FROM trips WHERE trip_id = ?", (trip.trip_id,)).fetchone()
            known = len(json.loads(row[0]).get("events", [])) if row else 0
            self._conn.execute(
                "INSERT INTO trips(trip_id, user_id, data, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(trip_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                (trip.trip_id, trip.user_id, trip.model_dump_json(), trip.updated_at.isoformat()),
            )
            for ev in trip.events[known:]:
                self._conn.execute("INSERT INTO events(trip_id, type, at, data) VALUES (?, ?, ?, ?)",
                                   (trip.trip_id, ev.type, ev.at.isoformat(), json.dumps(ev.data, default=str)))

    def load_trip(self, trip_id: str) -> TripState | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM trips WHERE trip_id = ?", (trip_id,)).fetchone()
        return TripState.model_validate_json(row[0]) if row else None

    def list_trips(self, user_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT trip_id, data, updated_at FROM trips WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)
            ).fetchall()
        return [trip_summary(trip_id, json.loads(data), updated) for trip_id, data, updated in rows]

    def owner(self, trip_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT user_id FROM trips WHERE trip_id = ?", (trip_id,)).fetchone()
        return row[0] if row else None

    def delete_trip(self, trip_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM events WHERE trip_id = ?", (trip_id,))
            self._conn.execute("DELETE FROM trips WHERE trip_id = ?", (trip_id,))

    def reassign(self, src_user: str, dst_user: str) -> int:
        """Move every trip (and, if the destination has none, the learned profile) from one owner to another:
        a guest signing up keeps what they planned."""
        with self._lock, self._conn:
            rows = self._conn.execute("SELECT trip_id, data FROM trips WHERE user_id = ?", (src_user,)).fetchall()
            for trip_id, data in rows:
                d = json.loads(data)
                d["user_id"] = dst_user
                self._conn.execute("UPDATE trips SET user_id = ?, data = ? WHERE trip_id = ?",
                                   (dst_user, json.dumps(d), trip_id))
            prof = self._conn.execute("SELECT data FROM profiles WHERE user_id = ?", (src_user,)).fetchone()
            has = self._conn.execute("SELECT 1 FROM profiles WHERE user_id = ?", (dst_user,)).fetchone()
            if prof and not has:
                self._conn.execute("INSERT INTO profiles(user_id, data) VALUES (?, ?)", (dst_user, prof[0]))
            self._conn.execute("DELETE FROM profiles WHERE user_id = ?", (src_user,))
        return len(rows)

    def delete_user_data(self, user_id: str) -> None:
        with self._lock, self._conn:
            ids = [r[0] for r in self._conn.execute("SELECT trip_id FROM trips WHERE user_id = ?", (user_id,))]
            for trip_id in ids:
                self._conn.execute("DELETE FROM events WHERE trip_id = ?", (trip_id,))
            self._conn.execute("DELETE FROM trips WHERE user_id = ?", (user_id,))
            self._conn.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,))

    def save_profile(self, user_id: str, profile: TravelerProfile) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO profiles(user_id, data) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET data = excluded.data",
                (user_id, profile.model_dump_json()),
            )

    def load_profile(self, user_id: str) -> TravelerProfile | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
        return TravelerProfile.model_validate_json(row[0]) if row else None

    def events(self, trip_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT type, at, data FROM events WHERE trip_id = ? ORDER BY id", (trip_id,)).fetchall()
        return [{"type": t, "at": at, "data": json.loads(d)} for t, at, d in rows]
