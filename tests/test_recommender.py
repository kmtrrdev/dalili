import numpy as np
import pytest
from fastapi.testclient import TestClient

from travel_agent.recommender import corpus, evaluate
from travel_agent.recommender.catalog import INTERESTS, load
from travel_agent.recommender.model import Config, Doc2Vec, TfIdf, scatter_add, sigmoid, unit
from travel_agent.recommender.train import MODEL_PATH


def test_scatter_add_sums_repeated_rows():
    M = np.zeros((5, 3), dtype=np.float32)
    idx = np.array([1, 3, 1, 1])
    rows = np.arange(12, dtype=np.float32).reshape(4, 3)
    scatter_add(M, idx, rows)
    expected = np.zeros((5, 3), dtype=np.float32)
    np.add.at(expected, idx, rows)
    assert np.allclose(M, expected)


def test_sigmoid_is_stable():
    assert np.allclose(sigmoid(np.array([-1000.0, 0.0, 1000.0])), [0.0, 0.5, 1.0])


def test_tokenizer_cleans_text():
    toks = corpus.tokenize("The beaches of Santorini's caldera are STUNNING, with 3 cafés.", banned={"santorini"})
    assert toks == ["beach", "caldera", "stunning", "cafe"]


def test_wikitext_keeps_listing_descriptions():
    src = "== See ==\n* {{see | name=Old Fort | content=A '''huge''' [[castle|fortress]] by the sea.}}\n{{pagebanner|x.jpg}}"
    text = corpus.wikitext_to_text(src)
    assert "Old Fort. A huge fortress by the sea." in text and "pagebanner" not in text


def test_doc2vec_learns_topics_from_scratch():
    """Two kinds of place written in different words: the trained vectors must group them apart."""
    rng = np.random.default_rng(0)
    beach = "beach sand swim coral snorkel lagoon island surf sea sunset".split()
    ski = "ski slope piste snow lift chalet snowboard winter alpine glacier".split()
    common = "hotel restaurant museum street market cafe".split()

    def doc(words):
        return list(rng.choice(words + common, 400))

    docs = [doc(beach) for _ in range(6)] + [doc(ski) for _ in range(6)]
    m = Doc2Vec(Config(dim=24, epochs=12, batch=256, min_count=1, window=3)).fit(docs, log=lambda *_: None)
    assert m.history[-1] < m.history[0]  # the loss goes down
    X = unit(m.D)
    S = X @ X.T
    same = np.mean([S[i, j] for i in range(12) for j in range(12) if i != j and (i < 6) == (j < 6)])
    other = np.mean([S[i, j] for i in range(6) for j in range(6, 12)])
    assert same > other + 0.2
    # a new guide about skiing lands next to the ski places
    v = unit(m.infer(doc(ski)))
    assert (X[6:] @ v).mean() > (X[:6] @ v).mean()


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
