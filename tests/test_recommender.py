import numpy as np
import pytest
from fastapi.testclient import TestClient

from travel_agent.recommender import corpus, evaluate
from travel_agent.recommender.catalog import INTERESTS, load
from travel_agent.recommender import encoder
from travel_agent.recommender.finetune import MODEL_PATH
from travel_agent.recommender.model import TfIdf, distinctive_words


def test_tokenizer_cleans_text():
    toks = corpus.tokenize("The beaches of Santorini's caldera are STUNNING, with 3 cafés.", banned={"santorini"})
    assert toks == ["beach", "caldera", "stunning", "cafe"]


def test_wikitext_keeps_listing_descriptions():
    src = "== See ==\n* {{see | name=Old Fort | content=A '''huge''' [[castle|fortress]] by the sea.}}\n{{pagebanner|x.jpg}}"
    text = corpus.wikitext_to_text(src)
    assert "Old Fort. A huge fortress by the sea." in text and "pagebanner" not in text


def test_passages_mask_place_and_country_names():
    dests = load()
    text = "Understand\nSantorini is the jewel of Greece, with a caldera and white villages. " + "Beaches and wine. " * 30
    ps = corpus.place_passages(text, ["Santorini"], dests)
    assert ps and "Santorini" not in ps[0] and "Greece" not in ps[0]
    assert "the place" in ps[0] and "the country" in ps[0] and "caldera" in ps[0]


def test_known_for_words_are_distinctive():
    docs = [["caldera", "volcanic", "beach"] * 5 + ["town", "hotel"]] + \
           [["beach", "town", "hotel", f"w{i}"] for i in range(9)] + [["caldera", "volcanic", "town"]] * 3  # in 4 of 13 guides: distinctive, not common
    words = distinctive_words(TfIdf(min_df=1).fit(docs), docs, k=2)
    assert set(words[0]) == {"caldera", "volcanic"}

def test_tfidf_baseline():
    b = TfIdf(min_df=1).fit([["beach", "sand"], ["ski", "snow"], ["beach", "sea"]])
    q = b.transform(["beach"])
    assert np.argmax(b.X @ q) in (0, 2)


def test_evaluation_split_is_stable_and_disjoint():
    dests = load()
    val, test = evaluate.split(dests)
    assert set(val).isdisjoint(test) and len(val) + len(test) == len(dests)
    assert abs(len(val) - len(test)) < len(dests) * 0.2
    v2, _ = evaluate.split(dests)
    assert list(v2) == list(val)


def test_catalog_is_labelled():
    dests = load()
    assert len(dests) >= 200
    for name in INTERESTS:
        assert sum(name in d.tags for d in dests) >= 8, name


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_recommendations_api_learns_from_activity():
    from travel_agent.api import app

    c = TestClient(app)
    assert c.get("/api/recommendations").json()["cold_start"]
    c.post("/api/activity", json={"kind": "search", "city": "Zermatt"})
    c.post("/api/activity", json={"kind": "view", "city": "Chamonix"})
    r = c.get("/api/recommendations?limit=6").json()
    names = [i["name"] for i in r["items"]]
    assert not r["cold_start"] and names
    assert "Zermatt" not in names and "Chamonix" not in names   # never suggested back
    ski = sum("ski" in i["tags"] for i in r["items"])
    assert ski >= 3, names                                      # ski lovers get ski resorts
    assert r["items"][0]["reason"]["type"] in ("search", "view")
    first = names[0]
    c.post("/api/activity", json={"kind": "dismiss", "city": first})
    assert first not in [i["name"] for i in c.get("/api/recommendations?limit=6").json()["items"]]
    sim = c.get("/api/recommendations/similar?city=Kyoto&limit=3").json()
    assert sim["found"] and "Tokyo" in [i["name"] for i in sim["items"]]


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_taste_affinity_ranks_similar_places_higher():
    import anyio

    from travel_agent.recommender import engine

    rec = engine.get()
    assert anyio.run(rec.affinity, ["Chamonix"], [], [], []) == {}  # cold start: no invented taste
    act = [{"kind": "like", "city": "Zermatt", "at": None}, {"kind": "like", "city": "St. Moritz", "at": None}]
    aff = anyio.run(rec.affinity, ["Chamonix", "Maldives", "Nowhere-Town"], [], act, [])
    assert "Nowhere-Town" not in aff                                   # unknown places: no score, not a guess
    assert aff["Chamonix"]["match"] > aff["Maldives"]["match"]          # a ski lover's taste
    assert aff["Chamonix"]["because"]["city"] in ("Zermatt", "St. Moritz")


def test_suggestions_blend_long_term_taste(monkeypatch):
    import anyio

    from travel_agent import suggest as sg

    async def explore(*a, **k):
        return [{"name": "Alpha", "country": "A", "flight_price": 100, "hotel_price": 50},
                {"name": "Beta", "country": "B", "flight_price": 100, "hotel_price": 50}]

    async def resolve(hub, text):
        from travel_agent.models import PlaceRef
        return PlaceRef(name="Cairo", country="Egypt", lat=30, lon=31, airports=["CAI"])

    async def taste(names):
        return {"Beta": {"match": 95, "because": {"type": "similar", "city": "Rome"}}}

    monkeypatch.setattr(sg, "_explore", explore)
    monkeypatch.setattr(sg.research, "resolve_place", resolve)
    out = anyio.run(lambda: sg.suggest(None, 5000, "USD", "Cairo", interests=["culture"], taste=taste))
    beta = next(i for i in out["ideas"] if i["name"] == "Beta")
    assert beta["taste_match"] == 95 and beta["taste_because"]["city"] == "Rome"
    assert out["ideas"][0]["name"] == "Beta"  # same price and request fit: the traveller's taste breaks the tie


@pytest.mark.skipif(not (MODEL_PATH.exists() and encoder.available()), reason="model not trained")
def test_the_served_encoder_reproduces_the_saved_vectors_and_reads_new_guides():
    """The website's ONNX encoder gives the vectors that were evaluated (same text preparation, same pooling), and
    a guide it never saw lands next to places of its kind."""
    import json

    a = np.load(MODEL_PATH, allow_pickle=False)
    ids, X = a["ids"].tolist(), a["X"]
    dests = {d.id: d for d in load()}
    zermatt = dests["zermatt"]
    guides = MODEL_PATH.parent.parent / "dataset" / "guides.jsonl"  # the exported training text: no network in tests
    text = next(r["text"] for r in map(json.loads, guides.read_text(encoding="utf-8").splitlines()) if r["id"] == "zermatt")
    enc = encoder.Encoder()
    v = enc.place(corpus.place_passages(text, [zermatt.name, zermatt.wikivoyage], list(dests.values())))
    assert float(v @ X[ids.index("zermatt")]) > 0.99
    ski = enc.place(["Ski slopes and pistes above the village, chairlifts, snowboarding, apres-ski in the chalets, "
                     "glacier skiing in winter and alpine hiking in summer. " * 4])
    near = [dests[ids[i]] for i in np.argsort(-(X @ ski))[:5]]
    assert sum("ski" in d.tags for d in near) >= 3, [d.name for d in near]
