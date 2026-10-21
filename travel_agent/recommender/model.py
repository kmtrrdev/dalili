"""Classic text tools next to the fine-tuned encoder (NumPy only):

- TF-IDF: the baseline the encoder is measured against, and the candidates for each place's "known for" words
  (finetune.known_for re-ranks them by meaning);
- PCA: the 2-D taste map.
"""

from __future__ import annotations

from collections import Counter

import numpy as np

# Foreign articles and saint prefixes that read as noise in "known for".
KEYWORD_SKIP = {"des", "du", "les", "der", "die", "das", "und", "del", "della", "dei", "agio", "agia", "agios", "san",
                "santa", "sao", "sant", "ville", "calle", "bce", "gods"}


class TfIdf:
    """TF-IDF vectors (sublinear term frequency, smoothed idf, unit length), written from scratch."""

    def __init__(self, min_df: int = 2):
        self.min_df = min_df

    def fit(self, docs: list[list[str]]) -> "TfIdf":
        df = Counter(w for d in docs for w in set(d))
        self.vocab = sorted(w for w, n in df.items() if n >= self.min_df)
        self.w2i = {w: i for i, w in enumerate(self.vocab)}
        self.df = np.array([df[w] for w in self.vocab])
        n = len(docs)
        self.idf = np.array([np.log((1 + n) / (1 + df[w])) + 1.0 for w in self.vocab])
        self.X = np.vstack([self.transform(d) for d in docs])
        return self

    def transform(self, tokens: list[str]) -> np.ndarray:
        v = np.zeros(len(self.vocab))
        for w, c in Counter(tokens).items():
            i = self.w2i.get(w)
            if i is not None:
                v[i] = 1.0 + np.log(c)
        v *= self.idf
        n = np.linalg.norm(v)
        return v / n if n else v


def distinctive_words(tf: TfIdf, docs: list[list[str]], k: int = 4) -> list[list[str]]:
    """What each place is "known for": its highest-weighted words among those found in several guides (so they
    describe the place - "volcanic", "caldera" - rather than name its streets) but not in most of them."""
    n = len(docs)
    usable = (tf.df >= 4) & (tf.df <= 0.35 * n) & np.array([w not in KEYWORD_SKIP for w in tf.vocab])
    W = np.where(usable, tf.X, -np.inf)
    return [[tf.vocab[j] for j in np.argsort(-row)[:k]] for row in W]


def pca_2d(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """2-D projection for the taste map: returns (points, mean, components)."""
    mu = X.mean(axis=0)
    _, _, vt = np.linalg.svd(X - mu, full_matrices=False)
    comps = vt[:2]
    return (X - mu) @ comps.T, mu, comps
