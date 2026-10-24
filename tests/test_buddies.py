"""Travel buddies: matched by place and dates, private by default, moderated, with ideas from the members' plans."""

import secrets
from datetime import date

import pytest
from fastapi.testclient import TestClient

from travel_agent import buddies as bd
from travel_agent.models import (Budget, DayPlan, ItineraryItem, PlaceRef, TravelerProfile, TripContract, TripPlan,
                                 TripState)
from travel_agent.store import Store

ROME = PlaceRef(name="Rome", country="Italy", country_code="IT", lat=41.9, lon=12.5)


def _trip(start: date, end: date, interests=("food", "history"), place=ROME) -> TripState:
    t = TripState(traveler_profile=TravelerProfile(activity_preferences=list(interests)))
    t.trip_contract = TripContract(destination=place.name, destination_ref=place, start_date=start, end_date=end,
                                   budget=Budget(amount=2000, currency="USD"))
    return t


def _user(name="Mona Hassan") -> dict:
    return {"id": "u_" + secrets.token_hex(4), "name": name}


@pytest.fixture
def b():
    return bd.Buddies(Store(":memory:"))


def test_overlapping_travellers_meet_and_others_wait_for_their_own_group(b):
    a, c, far = _user("Mona Hassan"), _user("Omar Khaled"), _user("Sara Ali")
    g1, created = b.join(_trip(date(2026, 11, 3), date(2026, 11, 9)), 0, a)
    g2, _ = b.join(_trip(date(2026, 11, 7), date(2026, 11, 12)), 0, c)  # 3 days together
    g3, _ = b.join(_trip(date(2026, 12, 1), date(2026, 12, 5)), 0, far)  # same city, another month
    assert created and g1 == g2 and g3 != g1
    group = b.group(g1, a["id"])
    assert [m["name"] for m in group["members"]] == ["Mona H.", "Omar K."]  # never a full name
    assert set(group["members"][0]) == {"id", "name", "you", "days_together", "from", "to", "interests"}  # no hotel
    assert group["members"][1]["days_together"] == 3


def test_women_only_groups_are_separate(b):
    g1, _ = b.join(_trip(date(2026, 11, 3), date(2026, 11, 9)), 0, _user(), women_only=True)
    g2, _ = b.join(_trip(date(2026, 11, 3), date(2026, 11, 9)), 0, _user())
    g3, _ = b.join(_trip(date(2026, 11, 4), date(2026, 11, 8)), 0, _user(), women_only=True)
    assert g1 != g2 and g3 == g1


def test_the_preview_counts_travellers_and_what_they_share(b):
    b.join(_trip(date(2026, 11, 3), date(2026, 11, 9), ("food", "art")), 0, _user())
    me = _trip(date(2026, 11, 5), date(2026, 11, 10), ("food", "history"))
    city = b.preview(me, "u_me")[0]
    assert city["travellers"] == 1 and city["shared_interests"] == ["food"] and city["group_id"] is None


def test_reports_blocks_and_the_rate_limit_keep_it_safe(b):
    a, c, d = _user(), _user(), _user()
    gid, _ = b.join(_trip(date(2026, 11, 3), date(2026, 11, 9)), 0, a)
    b.join(_trip(date(2026, 11, 3), date(2026, 11, 9)), 0, c)
    b.join(_trip(date(2026, 11, 3), date(2026, 11, 9)), 0, d)
    bad = b.post(gid, c["id"], "send me money first")
    assert b.report(bad, a["id"], "scam") is False and b.report(bad, d["id"], "scam") is True  # two reports hide it
    assert all(m["id"] != bad for m in b.group(gid, a["id"])["messages"])
    b.post(gid, c["id"], "hello")
    b.block(a["id"], c["id"])
    assert all(m["user"] != c["id"] for m in b.group(gid, a["id"])["messages"])  # blocked: gone for the blocker only
    assert any(m["user"] == c["id"] for m in b.group(gid, d["id"])["messages"])
    with pytest.raises(bd.BuddyError) as err:
        for _ in range(bd.RATE[0] + 1):
            b.post(gid, d["id"], "hi")
    assert err.value.status == 429
    with pytest.raises(bd.BuddyError):
        b.group(gid, _user()["id"])  # not a member: nothing to read


def test_meetup_ideas_come_from_the_members_own_plans():
    def planned(pid: str, title: str) -> TripState:
        t = _trip(date(2026, 11, 3), date(2026, 11, 9))
        t.plans = {"balanced": TripPlan(mode="balanced", days=[DayPlan(day=2, date=date(2026, 11, 4), title="x", items=[
            ItineraryItem(start="10:00", end="12:00", kind="activity", title=title, place_id=pid)])])}
        return t

    trips = {"t1": planned("p1", "Colosseum"), "t2": planned("p1", "Colosseum")}
    members = [{"name": "Mona H.", "trip_id": "t1", "start": date(2026, 11, 3), "end": date(2026, 11, 9), "interests": []},
               {"name": "Omar K.", "trip_id": "t2", "start": date(2026, 11, 4), "end": date(2026, 11, 6), "interests": []}]
    assert bd.meetup_ideas(members, trips) == ["🧭 Mona H. & Omar K. are both at Colosseum on Wed 04 Nov - go together?"]


def test_joining_needs_an_account():
    from travel_agent.api import app

    c = TestClient(app)
    assert c.post("/api/buddies/join", json={"trip_id": "t_x"}).status_code == 401
    assert c.get("/api/buddies/groups").status_code == 401
