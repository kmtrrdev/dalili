from fastapi.testclient import TestClient

from travel_agent import tripbook
from travel_agent.api import app

from .conftest import ROME_REQUEST

client = TestClient(app)


def test_end_to_end_api():
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["http_mode"] in ("replay", "cache")
    data = client.post("/api/chat", json={"message": ROME_REQUEST}).json()
    trip_id = data["trip_id"]
    assert data["trip"]["plans"]["balanced"]["validation"]["result"] == "PASS"

    assert client.post(f"/api/trips/{trip_id}/select", json={"mode": "comfort"}).json()["selected_mode"] == "comfort"

    body = client.post(f"/api/trips/{trip_id}/whatif", json={"budget_delta": -500}).json()
    assert body["budget"] == 3000 and not body["applied"]
    assert client.get(f"/api/trips/{trip_id}").json()["trip_contract"]["budget"]["amount"] == 3500

    r = client.post(f"/api/trips/{trip_id}/replan", json={"actions": [{"action": "more_food"}]})
    assert r.status_code == 200 and r.json()["trip"]["user_knobs"]["food_focus"] is True

    book = client.get(f"/api/trips/{trip_id}/book")
    assert book.status_code == 200
    for title in tripbook.SECTIONS:
        assert title in book.text.replace("&#x2F;", "/")
    assert "Google Flights" in book.text and "Wikivoyage" in book.text
    assert client.get(f"/api/trips/{trip_id}/book.md").text.startswith("# Trip Book")
    assert client.get(f"/api/trips/{trip_id}/events").json()


def test_unknown_trip_404():
    assert client.get("/api/trips/nope").status_code == 404
