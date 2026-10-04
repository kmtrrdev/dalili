"""Personal recommendations from the trained destination model.

A user's taste is built from what they did, each signal weighted and fading with age (half-life 60 days):

    planned a trip there      1.0        liked a suggestion        1.0
    searched for it           0.6        opened its card           0.35
    dismissed it             -0.5        each interest they picked 0.8 (through the interest vectors)

    score(place) = 0.65 · cos(taste of places, place) + 0.35 · mean over picked interests of cos(interest, place)

Places the user already planned or dismissed are never suggested. Each suggestion carries its main reason
(the signal that contributed most) and the words the model associates most with it ("known for").
A city outside the catalog is embedded on the fly from its Wikivoyage guide (Doc2Vec inference).
"""

from __future__ import annotations

import logging
import math
import re
import threading
import unicodedata
from datetime import datetime, timezone

import numpy as np

from . import catalog, corpus
from .catalog import INTERESTS
from .model import Doc2Vec, unit
from .train import MODEL_PATH, REPORT_PATH, interest_matrix

log = logging.getLogger(__name__)
INFERRED_MAX = 2000  # technical limit: cities embedded on the fly kept in memory

WEIGHTS = {"planned": 1.0, "like": 1.0, "search": 0.6, "view": 0.35, "dismiss": -0.5}
INTEREST_WEIGHT = 0.8
HALF_LIFE_DAYS = 60
PLACE_SHARE = 0.65
# Country / region guides lead with a map or flag: show a photo of a place that represents them instead.
PHOTO_STAND_IN = {"Seychelles": "Mahé", "Cyprus": "Paphos", "Mauritius": "Grand Baie", "Madagascar": "Nosy Be",
                  "Bhutan": "Paro", "Jamaica": "Negril", "Costa Rica": "Manuel Antonio National Park",
                  "Hawaii": "Waikiki", "Albanian Riviera": "Himara", "Al-Ula": "Hegra", "Goa": "Palolem",
                  "Mallorca": "Palma de Mallorca", "Jeju": "Seogwipo", "Busan": "Haeundae"}
# Foreign articles and saint prefixes that read as noise in "known for".
KEYWORD_SKIP = {"des", "du", "les", "der", "die", "das", "und", "del", "della", "dei", "agio", "agia", "agios", "san",
                "santa", "sao", "sant", "ville", "calle", "bce", "gods"}


def _key(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


class Recommender:
    def __init__(self):
        a = np.load(MODEL_PATH, allow_pickle=False)
        self.model = Doc2Vec.from_arrays(a)
        self.X = a["X"].astype(np.float64)
        self.Q = a["Q"].astype(np.float64)                          # interest vectors used for ranking
        self.Q_in = interest_matrix(self.model.W, self.model.w2i)   # interest vectors in the places' space
        self.ids = a["ids"].tolist()
        self.names = a["names"].tolist()
        self.countries = a["countries"].tolist()
        self.tags = [t.split() for t in a["tags"].tolist()]
        self.points = a["pca_points"].astype(np.float64)
        self.mu, self.comps = a["pca_mu"].astype(np.float64), a["pca_comps"].astype(np.float64)
        self.index = {}
        wv = {d.id: d.wikivoyage for d in catalog.load()}
        self._wv = wv
        self.images: dict[str, str] | None = None   # destination id -> banner photo, fetched on first use
        for i, (cid, name) in enumerate(zip(self.ids, self.names)):
            for k in (name, wv.get(cid, name), cid.replace("-", " ")):
                self.index.setdefault(_key(k), i)
        self.keywords = self._keywords(a["df"] if "df" in a.files else None)
        self._inferred: dict[str, np.ndarray | None] = {}
        self._lock = threading.Lock()

    # -- helpers -----------------------------------------------------------------
    def _keywords(self, df: np.ndarray | None, k: int = 4) -> list[list[str]]:
        """The words each place predicts far more than an average place does (its distinctive words). Only words
        found in several guides count, so they describe the place ("volcanic", "caldera") rather than name its
        streets."""
        S = self.model.D @ self.model.C.T                      # how strongly each place predicts each word
        lift = S - S.mean(axis=0, keepdims=True)
        lift[:, self.model.counts < 8] = -np.inf
        if df is not None:
            n = len(self.ids)
            lift[:, (df < 4) | (df > 0.35 * n)] = -np.inf
        skip = [self.model.w2i[w] for w in KEYWORD_SKIP if w in self.model.w2i]
        lift[:, skip] = -np.inf
        return [[self.model.vocab[j] for j in np.argsort(-row)[:k]] for row in lift]

    def find(self, city: str) -> int | None:
        key = _key(city)
        if key in self.index:
            return self.index[key]
        first = _key(city.split(",")[0])
        return self.index.get(first)

    async def vector(self, city: str) -> np.ndarray | None:
        i = self.find(city)
        if i is not None:
            return self.X[i]
        key = _key(city.split(",")[0])
        if key in self._inferred:
            return self._inferred[key]
        vec = None
        try:
            text = await corpus.fetch_guide(city.split(",")[0].strip())
            v = self.model.infer(corpus.tokens_for_text(text, catalog.load()))
            vec = unit(v) if v is not None else None
        except Exception as exc:  # a missing guide just means this city adds no signal
            log.info("no vector for %s: %s", city, exc)
        with self._lock:
            if len(self._inferred) >= INFERRED_MAX:  # bounded memory: forget the oldest inferred cities
                for k in list(self._inferred)[: INFERRED_MAX // 10]:
                    del self._inferred[k]
            self._inferred[key] = vec
        return vec

    async def _load_images(self) -> None:
        """A photo per destination: its Wikivoyage lead photo, else a photo of a representative place (a country's
        guide leads with a map or flag), else the Wikipedia lead photo. Fetched in batches, cached for months."""
        if self.images is not None:
            return
        self.images = {}
        try:
            title = {i: self._wv.get(i, n) for i, n in zip(self.ids, self.names)}
            got = await corpus.fetch_banners(list(title.values()))
            self.images = {i: got[t] for i, t in title.items() if t in got}
            missing = {i: PHOTO_STAND_IN.get(t, t) for i, t in title.items() if i not in self.images}
            if missing:
                more = await corpus.fetch_banners(list(set(missing.values())))
                wiki = await corpus.fetch_banners([t for t in set(missing.values()) if t not in more], wiki="wikipedia")
                for i, t in missing.items():
                    if t in more or t in wiki:
                        self.images[i] = more.get(t) or wiki[t]
        except Exception as exc:  # photos are decoration: the cards fall back to a coloured tile
            log.info("photos unavailable: %s", exc)

    def _item(self, i: int, match: float, reason: dict | None = None) -> dict:
        return {"id": self.ids[i], "name": self.names[i], "country": self.countries[i], "tags": self.tags[i],
                "keywords": self.keywords[i], "match": min(99, round(match)), "reason": reason,
                "image": (self.images or {}).get(self.ids[i])}

    @staticmethod
    def _decay(at: str | None) -> float:
        if not at:
            return 1.0
        try:
            t = datetime.fromisoformat(at.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
        except ValueError:
            return 1.0
        age = max(0.0, (datetime.now(timezone.utc) - t).total_seconds() / 86400)
        return 0.5 ** (age / HALF_LIFE_DAYS)

    # -- the user's taste --------------------------------------------------------
    async def signals(self, trips: list[dict], activity: list[dict]) -> list[dict]:
        """Every weighted place signal: [{kind, city, weight, vec}]."""
        raw = []
        for t in trips:
            for city in t.get("cities") or []:
                raw.append(("planned", city, t.get("updated_at")))
        for a in activity:
            raw.append((a["kind"], a["city"], a["at"]))
        merged: dict[tuple[str, str], dict] = {}
        for kind, city, at in raw:
            w = WEIGHTS.get(kind, 0) * self._decay(at)
            k = (kind if kind == "dismiss" else "pos", _key(city))
            m = merged.get(k)
            if m is None:
                merged[k] = {"kind": kind, "city": city, "weight": w}
            else:  # repeated signals add up, with diminishing returns
                m["weight"] = math.copysign(min(abs(m["weight"]) + abs(w) * 0.5, 2.0), m["weight"])
                if WEIGHTS.get(kind, 0) > WEIGHTS.get(m["kind"], 0):
                    m["kind"] = kind
        out = []
        for s in merged.values():
            vec = await self.vector(s["city"])
            if vec is not None:
                out.append({**s, "vec": vec})
        return out

    def interest_list(self, interests: list[str]) -> list[str]:
        return [i for i in dict.fromkeys(interests) if i in INTERESTS]

    async def recommend(self, trips: list[dict], activity: list[dict], interests: list[str], limit: int = 8) -> dict:
        await self._load_images()
        interests = self.interest_list(interests)
        sig = await self.signals(trips, activity)
        pos = [s for s in sig if s["weight"] > 0]
        if not pos and not interests:
            return {"cold_start": True, "items": [], "taste": [], "based_on": {"places": 0, "interests": 0}}

        # Never suggest a place back to the person who planned, searched, opened or dismissed it.
        exclude = {i for s in sig for i in [self.find(s["city"])] if i is not None}
        n = len(self.ids)
        place_score = np.zeros(n)
        contrib = []  # (reason, per-place contribution)
        if sig:
            taste = sum(s["weight"] * s["vec"] for s in sig)
            if np.linalg.norm(taste) > 1e-9:
                place_score = self.X @ unit(taste)
            for s in pos:
                contrib.append(({"type": s["kind"], "city": s["city"]}, s["weight"] * (self.X @ s["vec"])))
        int_score = np.zeros(n)
        if interests:
            per = np.vstack([self.X @ self.Q[INTERESTS.index(i)] for i in interests])
            int_score = per.mean(axis=0)
            for i, row in zip(interests, per):
                contrib.append(({"type": "interest", "interest": i}, INTEREST_WEIGHT * row))
        if pos and interests:
            score = PLACE_SHARE * place_score + (1 - PLACE_SHARE) * int_score
        else:
            score = place_score if pos else int_score

        # "match" = the share of all places this one beats: an honest, comparable percentage.
        rank = np.argsort(np.argsort(score))
        pct = 100.0 * rank / max(n - 1, 1)
        order = [i for i in np.argsort(-score) if i not in exclude][:limit]
        items = []
        for i in order:
            reason = max(contrib, key=lambda c: c[1][i])[0] if contrib else None
            items.append(self._item(i, pct[i], reason))
        return {"cold_start": False, "items": items, "taste": self.taste(sig, interests),
                "based_on": {"places": len(pos), "interests": len(interests)}}

    def taste(self, sig: list[dict], interests: list[str]) -> list[dict]:
        """How strongly the user's taste leans to each interest (0-100, relative)."""
        parts = [s["weight"] * s["vec"] for s in sig] + [INTEREST_WEIGHT * self.Q_in[INTERESTS.index(i)] for i in interests]
        if not parts:
            return []
        u = unit(sum(parts))
        raw = self.Q_in @ u
        lo, hi = raw.min(), raw.max()
        vals = (raw - lo) / (hi - lo) if hi > lo else np.zeros_like(raw)
        return sorted(({"interest": name, "score": int(round(15 + 85 * v))} for name, v in zip(INTERESTS, vals)),
                      key=lambda x: -x["score"])

    async def similar(self, city: str, limit: int = 6) -> dict:
        await self._load_images()
        vec = await self.vector(city)
        if vec is None:
            return {"city": city, "found": False, "items": []}
        me = self.find(city)
        sims = self.X @ vec
        n = len(self.ids)
        pct = 100.0 * np.argsort(np.argsort(sims)) / max(n - 1, 1)
        order = [i for i in np.argsort(-sims) if i != me][:limit]
        return {"city": city, "found": True, "items": [self._item(i, pct[i], {"type": "similar", "city": city})
                                                        for i in order]}

    async def taste_map(self, trips: list[dict], activity: list[dict], interests: list[str]) -> dict:
        interests = self.interest_list(interests)
        sig = await self.signals(trips, activity)
        parts = [s["weight"] * s["vec"] for s in sig if s["weight"] > 0] + \
                [INTEREST_WEIGHT * self.Q_in[INTERESTS.index(i)] for i in interests]
        me = None
        if parts:
            u = unit(sum(parts))
            me = ((u - self.mu) @ self.comps.T).round(4).tolist()
        mine = {self.find(s["city"]) for s in sig if s["weight"] > 0} - {None}
        return {"points": [{"name": n, "country": c, "tag": t[0], "x": round(float(p[0]), 4), "y": round(float(p[1]), 4),
                            "mine": i in mine}
                           for i, (n, c, t, p) in enumerate(zip(self.names, self.countries, self.tags, self.points))],
                "me": me}


_instance: Recommender | None = None
_failed = False


def get() -> Recommender | None:
    """The loaded model, or None when it has not been trained yet (the site works without it)."""
    global _instance, _failed
    if _instance is None and not _failed:
        if not MODEL_PATH.exists():
            _failed = True
            log.warning("recommender model not found at %s - run: python -m travel_agent.recommender.train", MODEL_PATH)
            return None
        _instance = Recommender()
    return _instance


def report() -> dict | None:
    import json

    return json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else None
