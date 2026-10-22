import secrets

from fastapi.testclient import TestClient

from travel_agent.api import accounts, app, service
from travel_agent.auth import GUEST_COOKIE, SESSION_COOKIE, hash_password, verify_password
from travel_agent.models import TripState

PASSWORD = "travel2026"


def _client() -> TestClient:
    c = TestClient(app)
    c.get("/api/auth/me")  # receives a guest cookie
    return c


def _email() -> str:
    return f"user_{secrets.token_hex(4)}@example.com"


def _signup(c: TestClient, email: str | None = None, name: str = "Mona") -> dict:
    r = c.post("/api/auth/signup", json={"name": name, "email": email or _email(), "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["user"]


def test_password_hashing():
    h = hash_password("s3cret-pass")
    assert h.startswith("scrypt$") and "s3cret-pass" not in h
    assert verify_password("s3cret-pass", h)
    assert not verify_password("wrong-pass1", h)
    assert hash_password("same1234") != hash_password("same1234")  # random salt


def test_signup_signin_signout():
    c = _client()
    email = _email()
    user = _signup(c, email.upper())
    assert user["email"] == email  # normalised
    assert SESSION_COOKIE in c.cookies
    assert c.get("/api/auth/me").json()["user"]["id"] == user["id"]
    assert c.post("/api/auth/signout").json()["signed_out"]
    assert c.get("/api/auth/me").json()["user"] is None
    r = c.post("/api/auth/signin", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["id"] == user["id"]


def test_signup_validation():
    c = _client()
    bad = [({"name": "", "email": _email(), "password": PASSWORD}, "name"),
           ({"name": "A", "email": "not-an-email", "password": PASSWORD}, "email"),
           ({"name": "A", "email": _email(), "password": "short1"}, "password"),
           ({"name": "A", "email": _email(), "password": "onlyletters"}, "password")]
    for body, field in bad:
        r = c.post("/api/auth/signup", json=body)
        assert r.status_code == 400 and r.json()["field"] == field
    email = _email()
    _signup(c, email)
    r = _client().post("/api/auth/signup", json={"name": "B", "email": email, "password": PASSWORD})
    assert r.status_code == 409


def test_wrong_password_is_generic_and_rate_limited():
    c = _client()
    email = _email()
    _signup(c, email)
    c.post("/api/auth/signout")
    unknown = c.post("/api/auth/signin", json={"email": _email(), "password": PASSWORD})
    wrong = c.post("/api/auth/signin", json={"email": email, "password": "nope12345"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]  # doesn't reveal which emails exist
    for _ in range(4):
        c.post("/api/auth/signin", json={"email": email, "password": "nope12345"})
    r = c.post("/api/auth/signin", json={"email": email, "password": PASSWORD})
    assert r.status_code == 429  # locked for a while, even with the right password
    accounts.by_email.reset(email)


def test_trips_are_private_and_move_with_the_guest():
    guest = _client()
    gid = guest.cookies[GUEST_COOKIE]
    trip = TripState(user_id=gid)
    service.store.save_trip(trip)
    assert guest.get(f"/api/trips/{trip.trip_id}").status_code == 200

    stranger = _client()
    assert stranger.get(f"/api/trips/{trip.trip_id}").status_code == 404
    assert stranger.delete(f"/api/trips/{trip.trip_id}").status_code == 404
    assert stranger.get(f"/api/trips/{trip.trip_id}/book").status_code == 404

    user = _signup(guest)  # signing up keeps the trips planned as a guest
    assert service.store.owner(trip.trip_id) == user["id"]
    assert [t["trip_id"] for t in guest.get("/api/trips").json()] == [trip.trip_id]
    assert guest.delete(f"/api/trips/{trip.trip_id}").status_code == 200
    assert service.get(trip.trip_id) is None


def test_cross_site_post_is_blocked():
    c = _client()
    r = c.post("/api/auth/signin", json={"email": _email(), "password": PASSWORD},
               headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_account_settings_password_and_delete():
    c = _client()
    email = _email()
    _signup(c, email)
    r = c.patch("/api/me", json={"name": "Mona Ali", "interests": ["beach", "nope", "food"], "currency": "egp"})
    assert r.status_code == 200
    u = r.json()["user"]
    assert u["name"] == "Mona Ali" and u["prefs"]["interests"] == ["beach", "food"] and u["prefs"]["currency"] == "EGP"

    other_device = _client()
    other_device.post("/api/auth/signin", json={"email": email, "password": PASSWORD})
    assert c.post("/api/me/password", json={"current": "wrong", "new": "newpass2026"}).status_code == 401
    assert c.post("/api/me/password", json={"current": PASSWORD, "new": "newpass2026"}).status_code == 200
    assert c.get("/api/auth/me").json()["user"] is not None            # this device stays signed in
    assert other_device.get("/api/auth/me").json()["user"] is None     # others are signed out

    dash = c.get("/api/me/dashboard").json()
    assert dash["stats"]["trips"] == 0 and dash["user"]["email"] == email
    assert c.request("DELETE", "/api/me", json={"password": "wrong"}).status_code == 401
    assert c.request("DELETE", "/api/me", json={"password": "newpass2026"}).status_code == 200
    assert c.get("/api/auth/me").json()["user"] is None
    assert c.post("/api/auth/signin", json={"email": email, "password": "newpass2026"}).status_code == 401


def test_mobile_app_uses_a_bearer_token_and_a_guest_header():
    app_client = TestClient(app)          # no cookies are relied on: every call carries headers
    guest = "g_" + secrets.token_urlsafe(18)
    trip = TripState(user_id=guest)
    service.store.save_trip(trip)
    h = {"X-Client": "mobile", "X-Guest-Id": guest}
    assert app_client.get(f"/api/trips/{trip.trip_id}", headers=h).status_code == 200
    r = app_client.post("/api/auth/signup", json={"name": "App", "email": _email(), "password": PASSWORD}, headers=h)
    body = r.json()
    assert r.status_code == 200 and body["token"] and SESSION_COOKIE not in r.cookies   # token in the body, no cookie
    auth = {"Authorization": f"Bearer {body['token']}", "X-Client": "mobile"}
    fresh = TestClient(app)
    assert fresh.get("/api/auth/me", headers=auth).json()["user"]["id"] == body["user"]["id"]
    assert [t["trip_id"] for t in fresh.get("/api/trips", headers=auth).json()] == [trip.trip_id]  # guest trip moved
    assert fresh.post("/api/auth/signout", headers=auth).status_code == 200
    assert fresh.get("/api/auth/me", headers=auth).json()["user"] is None


def test_dashboard_requires_sign_in():
    assert _client().get("/api/me/dashboard").status_code == 401
