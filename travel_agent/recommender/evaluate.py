"""Offline evaluation against the hand-labelled tags in the catalog (never used for training).

- Similar places:  for each destination, are its 5 nearest neighbours "the same kind of place"?
                   (same main tag, or at least half of the tags shared)                    -> Precision@5
- Interests:       rank every destination for "beach", "ski", ... ; are the tagged ones on top?
                   -> Precision@10 and Mean Average Precision (MAP)
A random ranking is reported next to each number so the scores can be read in context.

The destinations are split in two halves (by a hash of their id, so the split never changes): settings are
chosen on the validation half, and the reported numbers come from the test half the tuning never looked at.
"""

from __future__ import annotations

import zlib

import numpy as np

from .catalog import INTERESTS, Destination


def split(dests: list[Destination]) -> tuple[np.ndarray, np.ndarray]:
    """(validation indices, test indices)."""
    h = np.array([zlib.crc32(d.id.encode()) % 2 for d in dests])
    return np.flatnonzero(h == 0), np.flatnonzero(h == 1)


def _similar(a: Destination, b: Destination) -> bool:
    sa, sb = set(a.tags), set(b.tags)
    return a.tags[0] == b.tags[0] or len(sa & sb) / len(sa | sb) >= 0.5


def similarity_p_at_k(X: np.ndarray, dests: list[Destination], k: int = 5, queries=None) -> float:
    """Neighbours come from every destination; only the `queries` (a split) are scored."""
    S = X @ X.T
    np.fill_diagonal(S, -np.inf)
    q = range(len(dests)) if queries is None else queries
    hits = [sum(_similar(dests[i], dests[j]) for j in np.argsort(-S[i])[:k]) / k for i in q]
    return float(np.mean(hits))


def similarity_random(dests: list[Destination], queries=None) -> float:
    n = len(dests)
    q = range(n) if queries is None else queries
    return float(np.mean([sum(_similar(dests[i], dests[j]) for j in range(n) if j != i) / (n - 1) for i in q]))


def _average_precision(ranked_relevant: np.ndarray) -> float:
    hits = np.cumsum(ranked_relevant)
    prec = hits / np.arange(1, ranked_relevant.size + 1)
    return float((prec * ranked_relevant).sum() / max(ranked_relevant.sum(), 1))


def interest_scores(X: np.ndarray, Q: np.ndarray, dests: list[Destination], k: int = 10, subset=None) -> dict:
    """X: destination vectors (unit), Q: one query vector per interest (unit), in INTERESTS order.
    With `subset`, only those destinations are ranked (a split)."""
    if subset is not None:
        X, dests = X[subset], [dests[i] for i in subset]
    per = {}
    for qi, name in enumerate(INTERESTS):
        rel = np.array([name in d.tags for d in dests], dtype=float)
        if rel.sum() == 0:
            continue
        order = np.argsort(-(X @ Q[qi]))
        per[name] = {"p@10": float(rel[order[:k]].mean()), "ap": _average_precision(rel[order]),
                     "random_p": float(rel.mean())}
    return {"per_interest": per,
            "p@10": float(np.mean([v["p@10"] for v in per.values()])),
            "map": float(np.mean([v["ap"] for v in per.values()])),
            "random": float(np.mean([v["random_p"] for v in per.values()]))}
