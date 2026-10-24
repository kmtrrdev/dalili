"""The landmark camera: only places Wikipedia confirms, in the country the model said; answers from the article."""

import anyio
from fastapi.testclient import TestClient

from travel_agent import llm
from travel_agent.agents import landmark
from travel_agent.providers import wiki

PHOTO = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
ARTICLES = {
    "Al-Khazneh": {"title": "Al-Khazneh", "wikibase_item": "Q1", "extract": "A temple in Petra.",
                   "coordinates": {"lat": 30.32, "lon": 35.45}, "content_urls": {"desktop": {"page": "https://w/K"}}},
    "Nabataean architecture": {"title": "Nabataean architecture", "wikibase_item": "Q2", "extract": "A style."},
}
ITEMS = {"Q1": {"claims": {"P17": [{"mainsnak": {"snaktype": "value", "datavalue": {"value": {"id": "Q810"}}}}]},
                "labels": {"ar": {"value": "الخزنة"}}},
         "Q810": {"claims": {"P297": [{"mainsnak": {"snaktype": "value", "datavalue": {"value": "JO"}}}]}},
         "Q2": {}}


def _world(monkeypatch, sighting: landmark.Sighting, calls: list):
    async def parse(system, user, schema, max_tokens=16000, effort=None, timeout=None, images=None):
        calls.append((schema.__name__, images, user))
        if schema is landmark.Sighting:
            return sighting
        if schema is landmark.Guide:
            return landmark.Guide(name="الخزنة", summary="معبد في البتراء.", history=["القرن الأول"], questions=["مين بناها؟"])
        return landmark.Answer(answer="The article says it was carved in the 1st century.")

    async def find(title):
        return ARTICLES.get(title)

    async def entity(qid):
        return ITEMS.get(qid)

    async def text(title, limit=12000):
        return "Al-Khazneh is a temple carved in the 1st century AD."

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "parse", parse)
    monkeypatch.setattr(wiki, "find_article", find)
    monkeypatch.setattr(wiki, "entity", entity)
    monkeypatch.setattr(wiki, "article_text", text)


def test_a_confirmed_landmark_comes_with_a_guide_from_its_article(monkeypatch):
    calls = []
    _world(monkeypatch, landmark.Sighting(recognised=True, title="Al-Khazneh", country_code="JO", city="Petra",
                                          confidence="high"), calls)
    out = anyio.run(landmark.identify, PHOTO, "ar")
    assert out["found"] and out["name"] == "Al-Khazneh" and out["name_ar"] == "الخزنة" and out["country_code"] == "JO"
    assert out["guide"]["name"] == "الخزنة" and out["confidence"] == "high"
    assert calls[0][1] == [PHOTO] and "1st century" in calls[1][2]  # the photo is read; the guide is the article's


def test_a_wrong_country_or_a_non_place_is_never_presented_as_the_answer(monkeypatch):
    calls = []
    _world(monkeypatch, landmark.Sighting(recognised=True, title="Al-Khazneh", country_code="EG",
                                          alternatives=["Nabataean architecture"]), calls)
    out = anyio.run(landmark.identify, PHOTO, "en")
    assert not out["found"] and out["reason"] == "unverified"  # Jordan, not Egypt; a style has no coordinates
    _world(monkeypatch, landmark.Sighting(recognised=False, seen="A cat on a sofa"), calls)
    assert anyio.run(landmark.identify, PHOTO, "en") == {"found": False, "seen": "A cat on a sofa", "reason": "unclear"}


def test_an_alternative_that_checks_out_is_only_a_best_guess(monkeypatch):
    _world(monkeypatch, landmark.Sighting(recognised=True, title="Petra Treasury Temple", country_code="JO",
                                          alternatives=["Al-Khazneh"], confidence="high"), [])
    out = anyio.run(landmark.identify, PHOTO, "en")
    assert out["found"] and out["name"] == "Al-Khazneh" and out["confidence"] == "low"


def test_questions_are_answered_from_the_article(monkeypatch):
    calls = []
    _world(monkeypatch, landmark.Sighting(recognised=False), calls)
    out = anyio.run(landmark.ask, "Al-Khazneh", "When was it built?", [], "en")
    assert out["answer"].startswith("The article says") and "1st century" in calls[-1][2]
    assert anyio.run(landmark.ask, "Not A Real Place", "?", [], "en") is None


def test_the_api_takes_only_a_photo(monkeypatch):
    from travel_agent.api import app

    _world(monkeypatch, landmark.Sighting(recognised=False, seen="x"), [])
    c = TestClient(app)
    assert c.post("/api/landmarks/identify", json={"image": "https://evil.example/x.jpg"}).status_code == 422
    assert c.post("/api/landmarks/identify", json={"image": PHOTO}).json()["reason"] == "unclear"
