"""Train, evaluate and save the destination model.

    python -m travel_agent.recommender.train           # train with the chosen settings, evaluate, save
    python -m travel_agent.recommender.train --tune    # first compare several settings on the validation split

Writes ml/models/recommender.npz (the model) and ml/models/recommender_report.json (metrics + loss curve).
The same pipeline, step by step with charts, is in ml/recommender.ipynb.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone

import numpy as np

from ..config import PROJECT_DIR
from . import catalog, corpus, evaluate
from .catalog import INTERESTS
from .interests import seed_tokens
from .model import Config, Doc2Vec, TfIdf, pca_2d, unit

MODEL_DIR = PROJECT_DIR / "ml" / "models"
MODEL_PATH = MODEL_DIR / "recommender.npz"
REPORT_PATH = MODEL_DIR / "recommender_report.json"
MIN_TOKENS = 150  # a guide shorter than this is too thin to learn a place from

# Settings compared by --tune (on the validation split only).
GRID = [
    Config(),
    Config(epochs=30),
    Config(epochs=30, dim=64, window=3),
    Config(epochs=30, dim=128, negative=8),
    Config(epochs=30, sample=1e-4),
]


def interest_matrix(vectors: np.ndarray, index: dict[str, int]) -> np.ndarray:
    """One unit vector per interest: the mean of its seed words' unit vectors."""
    rows = []
    for name in INTERESTS:
        ids = [index[w] for w in seed_tokens(name) if w in index]
        rows.append(unit(unit(vectors[ids]).mean(axis=0)) if ids else np.zeros(vectors.shape[1]))
    return np.vstack(rows)


def doc_freq(model: Doc2Vec, docs: list[list[str]]) -> np.ndarray:
    """In how many guides each vocabulary word appears (used to pick descriptive "known for" words)."""
    df = np.zeros(len(model.vocab), dtype=np.int32)
    for d in docs:
        df[np.unique(model.encode(d))] += 1
    return df


def scores(model: Doc2Vec, dests, part) -> dict:
    """Similarity P@5 and interest MAP / P@10 on one split, for both ways of building interest vectors."""
    X = unit(model.D)
    out = {"sim_p@5": evaluate.similarity_p_at_k(X, dests, queries=part)}
    for space, vecs in (("input", model.W), ("output", model.C)):
        r = evaluate.interest_scores(X, interest_matrix(vecs, model.w2i), dests, subset=part)
        out[f"{space}_map"], out[f"{space}_p@10"] = r["map"], r["p@10"]
    out["best_space"] = "output" if out["output_map"] > out["input_map"] else "input"
    out["objective"] = (out["sim_p@5"] + out[f"{out['best_space']}_map"]) / 2
    return out


def _tune_one(job) -> tuple[dict, int]:
    """Train one candidate setting and score it on the validation split (runs in a worker process)."""
    cfg, docs, dests, val = job
    t0 = time.time()
    m = Doc2Vec(Config(**cfg)).fit(docs, log=lambda *_: None)
    return scores(m, dests, val), round(time.time() - t0)


def main(tune: bool = False) -> dict:
    started = time.time()
    dests_all = catalog.load()
    print(f"Fetching {len(dests_all)} Wikivoyage guides (cached after the first run)...")
    tokens = asyncio.run(corpus.build(dests_all))
    dests = [d for d in dests_all if len(tokens[d.id]) >= MIN_TOKENS]
    skipped = [d.name for d in dests_all if len(tokens[d.id]) < MIN_TOKENS]
    docs = [tokens[d.id] for d in dests]
    val, test = evaluate.split(dests)
    print(f"{len(docs)} guides, {sum(map(len, docs)):,} tokens; validation {len(val)} / test {len(test)}; "
          f"skipped {skipped}")

    tuning = []
    cfg = Config(epochs=30)
    if tune:
        # Every setting trains in its own process at the same time (one CPU core each).
        import os
        from concurrent.futures import ProcessPoolExecutor

        for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            os.environ[var] = "1"
        print(f"tuning {len(GRID)} settings in parallel on the validation split...", flush=True)
        with ProcessPoolExecutor(max_workers=min(len(GRID), os.cpu_count() or 1)) as pool:
            results = list(pool.map(_tune_one, [(vars(c), docs, dests, val) for c in GRID]))
        best = None
        for c, (s, secs) in zip(GRID, results):
            tuning.append({"config": vars(c), "validation": {k: (round(v, 3) if isinstance(v, float) else v)
                                                             for k, v in s.items()}, "seconds": secs})
            print(f"  {vars(c)}  ->  val sim {s['sim_p@5']:.3f}  map {s[s['best_space'] + '_map']:.3f} "
                  f"({s['best_space']})  [{secs}s]", flush=True)
            if best is None or s["objective"] > best[0]:
                best = (s["objective"], c)
        cfg = best[1]
        print(f"chosen on validation: {vars(cfg)}", flush=True)

    model = Doc2Vec(replace(cfg)).fit(docs)
    val_s, test_s = scores(model, dests, val), scores(model, dests, test)
    space = val_s["best_space"]  # chosen on validation, like every other setting
    X = unit(model.D)
    Q = interest_matrix(model.C if space == "output" else model.W, model.w2i)

    base = TfIdf().fit(docs)
    Qb = np.vstack([base.transform(seed_tokens(n)) for n in INTERESTS])
    test_report = {
        "similar_places_p@5": {"doc2vec": test_s["sim_p@5"],
                               "tfidf": evaluate.similarity_p_at_k(base.X, dests, queries=test),
                               "random": evaluate.similarity_random(dests, queries=test)},
        "interests": {"doc2vec": {"map": test_s[f"{space}_map"], "p@10": test_s[f"{space}_p@10"]},
                      "tfidf": {k: v for k, v in evaluate.interest_scores(base.X, Qb, dests, subset=test).items()
                                if k in ("map", "p@10")},
                      "random": {"map": evaluate.interest_scores(base.X, Qb, dests, subset=test)["random"]}},
    }
    per_tag = evaluate.interest_scores(X, Q, dests, subset=test)["per_interest"]

    points, mu, comps = pca_2d(X)
    MODEL_DIR.mkdir(exist_ok=True)
    np.savez_compressed(MODEL_PATH, **model.to_arrays(), X=X.astype(np.float32), Q=Q.astype(np.float32),
                        df=doc_freq(model, docs),
                        ids=np.array([d.id for d in dests]), names=np.array([d.name for d in dests]),
                        countries=np.array([d.country for d in dests]),
                        tags=np.array([" ".join(d.tags) for d in dests]),
                        pca_points=points.astype(np.float32), pca_mu=mu.astype(np.float32),
                        pca_comps=comps.astype(np.float32))

    def r3(x):
        return {k: r3(v) for k, v in x.items()} if isinstance(x, dict) else round(x, 3) if isinstance(x, float) else x

    report = r3({
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.time() - started, 1),
        "model": "Doc2Vec PV-DBOW + skip-gram, negative sampling (NumPy, from scratch)",
        "config": vars(model.cfg), "interest_space": space,
        "data": {"source": "Wikivoyage guides (CC BY-SA)", "destinations": len(dests), "skipped": skipped,
                 "tokens": int(sum(map(len, docs))), "vocabulary": len(model.vocab),
                 "validation": len(val), "test": len(test)},
        "loss_per_epoch": [round(x, 4) for x in model.history],
        "test": test_report, "validation": val_s,
        "test_per_interest": per_tag, "tuning": tuning,
    })
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["test"], indent=2))
    return report


def add_df() -> None:
    """Add word document frequencies to a model saved without them (no retraining)."""
    a = dict(np.load(MODEL_PATH, allow_pickle=False))
    dests_all = catalog.load()
    tokens = asyncio.run(corpus.build(dests_all))
    by_id = {d.id: tokens[d.id] for d in dests_all}
    m = Doc2Vec.from_arrays(a)
    a["df"] = doc_freq(m, [by_id[i] for i in a["ids"].tolist()])
    np.savez_compressed(MODEL_PATH, **a)
    print("added df for", len(a["df"]), "words")


if __name__ == "__main__":
    if "--add-df" in sys.argv:
        add_df()
    else:
        main(tune="--tune" in sys.argv)
