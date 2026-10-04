"""The same Store / Accounts code on PostgreSQL (production). Runs only when TEST_DATABASE_URL points at a database:

    docker run -d --name dalili-pg -e POSTGRES_PASSWORD=pw -p 5433:5432 postgres:16
    $env:TEST_DATABASE_URL="postgresql://postgres:pw@localhost:5433/postgres"; python -m pytest tests/test_postgres.py
"""

import os

import pytest

from travel_agent.models import TravelerProfile, TripState

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set TEST_DATABASE_URL to run against PostgreSQL")


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", URL)
    import psycopg

    with psycopg.connect(URL, autocommit=True) as c:  # a clean database for each test
        for table in ("events", "trips", "profiles", "sessions", "activity", "users"):
            c.execute(f"DROP TABLE IF EXISTS {table}")
    from travel_agent.auth import Accounts
    from travel_agent.store import Store

    store = Store("ignored-when-DATABASE_URL-is-set.db")
    return store, Accounts(store)


def test_trips_profiles_and_events(pg):
    store, _ = pg
    trip = TripState(user_id="g_" + "a" * 20)
    trip.emit("trip.created", source="test")
    store.save_trip(trip)
    store.save_trip(trip)  # upsert, events not duplicated
    assert store.load_trip(trip.trip_id).trip_id == trip.trip_id
    assert [e["type"] for e in store.events(trip.trip_id)] == ["trip.created"]
    assert store.list_trips(trip.user_id)[0]["trip_id"] == trip.trip_id
    store.save_profile("u1", TravelerProfile(travel_style="active"))
    assert store.load_profile("u1").travel_style == "active"
    assert store.reassign(trip.user_id, "u2") == 1 and store.owner(trip.trip_id) == "u2"
    store.delete_user_data("u2")
    assert store.load_trip(trip.trip_id) is None


def test_accounts_sessions_and_activity(pg):
    _, accounts = pg
    user = accounts.sign_up("Mo", "test@example.com", "A strong pass 123", guest_id="g_" + "b" * 20)
    token = accounts.create_session(user["id"], "pytest")
    assert accounts.session_user(token)["id"] == user["id"]
    assert accounts.sign_in("test@example.com", "A strong pass 123", "127.0.0.1")["id"] == user["id"]
    accounts.log_activity(user["id"], "search", "Rome")
    assert accounts.activity(user["id"])[0]["city"] == "Rome"
    accounts.delete_account(user["id"], "A strong pass 123")
    assert accounts.session_user(token) is None
