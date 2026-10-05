"""Human evaluation: anonymous storage and reproducible statistics."""

from fastapi.testclient import TestClient

from travel_agent import evaluation
from travel_agent.api import app

from .conftest import ROME_REQUEST


def test_ratings_are_anonymous_and_validated(monkeypatch):
    c = TestClient(app)
    trip_id = c.post("/api/chat", json={"message": ROME_REQUEST}).json()["trip_id"]
    good = {d: 4 for d in evaluation.DIMENSIONS}
    assert c.post("/api/evaluations", json={"trip_id": trip_id, "ratings": good}).json()["saved"]
    assert c.post("/api/evaluations", json={"ratings": {"overall": 9}}).status_code == 400
    assert c.post("/api/evaluations", json={"trip_id": "someone-elses", "ratings": good}).status_code == 404
    from travel_agent.api import service
    row = service.store.evaluations()[-1]
    assert len(row["rater"]) == 16 and row["plan"]["score"] is not None  # a hash, never an id; plan metrics kept
    assert c.get("/api/evaluations/summary").status_code == 404           # operator only
    monkeypatch.setenv("DALILI_ADMIN_TOKEN", "t")
    s = c.get("/api/evaluations/summary", headers={"X-Admin-Token": "t"}).json()
    assert s["ratings"] >= 1 and "dalili" in s["variants"]


def test_summary_statistics_are_correct():
    rows = [{"rater": f"r{i}", "variant": v, "ratings": {"overall": x}, "plan": {"score": 60 + x * 5}}
            for i, (v, x) in enumerate([("dalili", 5), ("dalili", 4), ("dalili", 5), ("dalili", 4),
                                        ("baseline", 3), ("baseline", 2), ("baseline", 3), ("baseline", 2)])]
    s = evaluation.summary(rows)
    d = s["variants"]["dalili"]["overall"]
    assert d["n"] == 4 and d["mean"] == 4.5 and d["ci95"][0] < 4.5 < d["ci95"][1]
    cmp = s["dalili_vs_baseline"]["overall"]
    assert cmp["difference"] == 2.0 and cmp["significant_at_95"]
    assert s["tripscore_vs_overall_r"] == 1.0
