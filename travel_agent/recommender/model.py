"""Destination embeddings trained from scratch (NumPy only - no ML library).

The model is Doc2Vec in its PV-DBOW form (Le & Mikolov, 2014) trained jointly with skip-gram word vectors
(Mikolov et al., 2013), using negative sampling:

- every destination d has a vector D[d]; every word w has an input vector W[w] and an output vector C[w];
- a destination vector must predict the words of its guide:      maximise  log σ(D[d]·C[w])
- a word vector must predict the words around it (window):       maximise  log σ(W[w]·C[c])
- k random "negative" words (drawn ∝ frequency^0.75) must not:   maximise  Σ log σ(-D[d]·C[n])

Because destinations and words predict through the same output vectors C, they end up in one space:
Santorini lands near Mykonos, and the word "beach" lands near both. That shared space powers similarity
("places like Rome"), interest matching ("I love beaches") and each user's taste vector.

Training is plain mini-batch SGD with the gradients written out by hand (see `_step`), a linearly decaying
learning rate and frequent-word subsampling. A trained model can embed a guide it never saw (`infer`).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * x))  # numerically stable for large |x|


def unit(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.maximum(n, 1e-9)


def scatter_add(M: np.ndarray, idx: np.ndarray, rows: np.ndarray) -> None:
    """M[idx] += rows, summing repeated indices (a sort + segment sum: much faster than np.add.at)."""
    order = np.argsort(idx, kind="stable")
    s = idx[order]
    starts = np.flatnonzero(np.r_[True, s[1:] != s[:-1]])
    M[s[starts]] += np.add.reduceat(rows[order], starts, axis=0)


@dataclass
class Config:
    dim: int = 96            # embedding size
    window: int = 4          # max skip-gram context on each side (sampled 1..window per word)
    negative: int = 6        # negative samples per positive pair (effective weight)
    shared_negatives: int = 64  # negatives drawn per batch and shared by all its examples
    epochs: int = 15
    lr: float = 0.025        # start learning rate, decays linearly to min_lr
    min_lr: float = 0.0001
    batch: int = 2048
    min_count: int = 3       # rarer words are dropped from the vocabulary
    sample: float = 1e-3     # frequent-word subsampling threshold
    seed: int = 7


@dataclass
class Doc2Vec:
    cfg: Config = field(default_factory=Config)
    vocab: list[str] = field(default_factory=list)
    counts: np.ndarray | None = None
    D: np.ndarray | None = None      # destination vectors (n_docs, dim)
    W: np.ndarray | None = None      # word input vectors (V, dim)
    C: np.ndarray | None = None      # word output vectors (V, dim)
    history: list[float] = field(default_factory=list)   # mean loss per epoch

    # -- data ------------------------------------------------------------------
    def build_vocab(self, docs: list[list[str]]) -> None:
        c = Counter(w for d in docs for w in d)
        words = sorted((w for w, n in c.items() if n >= self.cfg.min_count), key=lambda w: (-c[w], w))
        self.vocab = words
        self.counts = np.array([c[w] for w in words], dtype=np.float64)
        self.w2i = {w: i for i, w in enumerate(words)}

    @property
    def w2i(self) -> dict[str, int]:
        if not hasattr(self, "_w2i") or len(self._w2i) != len(self.vocab):
            self._w2i = {w: i for i, w in enumerate(self.vocab)}
        return self._w2i

    @w2i.setter
    def w2i(self, v: dict[str, int]) -> None:
        self._w2i = v

    def encode(self, tokens: list[str]) -> np.ndarray:
        m = self.w2i
        return np.array([m[t] for t in tokens if t in m], dtype=np.int64)

    def _keep_prob(self) -> np.ndarray:
        f = self.counts / self.counts.sum()
        s = self.cfg.sample
        return np.minimum(1.0, (np.sqrt(f / s) + 1.0) * (s / f))

    def _neg_cdf(self) -> np.ndarray:
        p = self.counts ** 0.75
        return np.cumsum(p / p.sum())

    def _epoch_pairs(self, encoded: list[np.ndarray], rng: np.random.Generator, words: bool = True):
        """(input row, target word) pairs for one epoch, shuffled. Input rows: docs first, then words."""
        keep = self._keep_prob()
        n_docs = len(encoded)
        ins, outs = [], []
        for d, toks in enumerate(encoded):
            if toks.size == 0:
                continue
            t = toks[rng.random(toks.size) < keep[toks]]
            if t.size < 2:
                continue
            ins.append(np.full(t.size, d, dtype=np.int64))   # PV-DBOW: the doc predicts each of its words
            outs.append(t)
            if not words:
                continue
            b = rng.integers(1, self.cfg.window + 1, t.size)  # dynamic window per centre word
            for o in range(1, self.cfg.window + 1):
                fwd = b[:-o] >= o
                ins.append(n_docs + t[:-o][fwd]); outs.append(t[o:][fwd])
                bwd = b[o:] >= o
                ins.append(n_docs + t[o:][bwd]); outs.append(t[:-o][bwd])
        i, o = np.concatenate(ins), np.concatenate(outs)
        perm = rng.permutation(i.size)
        return i[perm], o[perm]

    # -- training ----------------------------------------------------------------
    @staticmethod
    def _step(IN: np.ndarray, OUT: np.ndarray, ii: np.ndarray, tt: np.ndarray, nn: np.ndarray, lr: float,
              neg_weight: float, update_out: bool = True) -> float:
        """One SGD step of negative sampling on a batch; returns the summed loss.

        ii: input rows (B,), tt: true target words (B,), nn: negative words shared by the whole batch (K,).
        Every example is pushed away from all K negatives, each weighted k/K, which in expectation equals k
        private negatives per example - but turns the work into dense matrix products (fast)."""
        h = IN[ii]                                   # (B, d)
        o_pos = OUT[tt]                              # (B, d)
        o_neg = OUT[nn]                              # (K, d)
        s_pos = sigmoid(np.einsum("bd,bd->b", h, o_pos))
        s_neg = sigmoid(h @ o_neg.T)                 # (B, K)
        loss = -np.log(s_pos + 1e-7).sum() - neg_weight * np.log(1.0 - s_neg + 1e-7).sum()
        # d loss / d score:  σ(s)-1 for the true word,  σ(s) for each negative
        g_pos = (s_pos - 1.0) * lr                   # (B,)
        g_neg = s_neg * (lr * neg_weight)            # (B, K)
        grad_h = g_pos[:, None] * o_pos + g_neg @ o_neg
        if update_out:
            scatter_add(OUT, tt, -g_pos[:, None] * h)
            scatter_add(OUT, nn, -(g_neg.T @ h))
        scatter_add(IN, ii, -grad_h)
        return float(loss)

    def fit(self, docs: list[list[str]], log=print) -> "Doc2Vec":
        cfg = self.cfg
        rng = np.random.default_rng(cfg.seed)
        self.build_vocab(docs)
        encoded = [self.encode(d) for d in docs]
        V, n_docs, dim = len(self.vocab), len(docs), cfg.dim
        IN = ((rng.random((n_docs + V, dim)) - 0.5) / dim).astype(np.float32)
        OUT = np.zeros((V, dim), dtype=np.float32)
        cdf = self._neg_cdf()
        # Total steps, for the learning-rate schedule (pair count varies a little per epoch).
        est = sum(self._epoch_pairs(encoded, np.random.default_rng(0))[0].size for _ in range(1))
        total, done = est * cfg.epochs, 0
        self.history = []
        for ep in range(cfg.epochs):
            ii_all, tt_all = self._epoch_pairs(encoded, rng)
            loss_sum, n = 0.0, 0
            for s in range(0, ii_all.size, cfg.batch):
                ii, tt = ii_all[s:s + cfg.batch], tt_all[s:s + cfg.batch]
                nn = np.minimum(np.searchsorted(cdf, rng.random(cfg.shared_negatives)), V - 1)
                lr = max(cfg.min_lr, cfg.lr * (1.0 - done / total))
                loss_sum += self._step(IN, OUT, ii, tt, nn, lr, cfg.negative / cfg.shared_negatives)
                n += ii.size
                done += ii.size
            self.history.append(loss_sum / max(n, 1))
            log(f"epoch {ep + 1:2d}/{cfg.epochs}  pairs {n:,}  loss {self.history[-1]:.4f}")
        self.D, self.W, self.C = IN[:n_docs], IN[n_docs:], OUT
        return self

    def infer(self, tokens: list[str], epochs: int = 60, seed: int = 11) -> np.ndarray | None:
        """Embed a new guide: train only its own vector against the frozen output vectors."""
        toks = self.encode(tokens)
        if toks.size < 20:
            return None
        rng = np.random.default_rng(seed)
        IN = ((rng.random((1, self.cfg.dim)) - 0.5) / self.cfg.dim).astype(self.C.dtype)
        cdf, keep = self._neg_cdf(), self._keep_prob()
        V = len(self.vocab)
        for ep in range(epochs):
            t = toks[rng.random(toks.size) < keep[toks]]
            if t.size == 0:
                continue
            lr = self.cfg.lr * (1.0 - ep / epochs) + self.cfg.min_lr
            for s in range(0, t.size, self.cfg.batch):
                tt = t[s:s + self.cfg.batch]
                nn = np.minimum(np.searchsorted(cdf, rng.random(self.cfg.shared_negatives)), V - 1)
                self._step(IN, self.C, np.zeros(tt.size, dtype=np.int64), tt, nn, lr,
                           self.cfg.negative / self.cfg.shared_negatives, update_out=False)
        return IN[0]

    # -- persistence -------------------------------------------------------------
    def to_arrays(self) -> dict[str, np.ndarray]:
        return {"vocab": np.array(self.vocab), "counts": self.counts, "D": self.D.astype(np.float32),
                "W": self.W.astype(np.float32), "C": self.C.astype(np.float32),
                "history": np.array(self.history), "cfg": np.array(list(vars(self.cfg).values()), dtype=np.float64),
                "cfg_keys": np.array(list(vars(self.cfg).keys()))}

    @classmethod
    def from_arrays(cls, a) -> "Doc2Vec":
        cfg = Config(**{k: (int(v) if float(v).is_integer() and k not in ("lr", "min_lr", "sample") else float(v))
                        for k, v in zip(a["cfg_keys"].tolist(), a["cfg"].tolist())})
        m = cls(cfg=cfg, vocab=a["vocab"].tolist(), counts=a["counts"], D=a["D"].astype(np.float64),
                W=a["W"].astype(np.float64), C=a["C"].astype(np.float64), history=a["history"].tolist())
        return m


class TfIdf:
    """The baseline the trained model is compared with: TF-IDF vectors (also written from scratch)."""

    def __init__(self, min_df: int = 2):
        self.min_df = min_df

    def fit(self, docs: list[list[str]]) -> "TfIdf":
        df = Counter(w for d in docs for w in set(d))
        self.vocab = sorted(w for w, n in df.items() if n >= self.min_df)
        self.w2i = {w: i for i, w in enumerate(self.vocab)}
        n = len(docs)
        self.idf = np.array([np.log((1 + n) / (1 + df[w])) + 1.0 for w in self.vocab])
        self.X = np.vstack([self.transform(d) for d in docs])
        return self

    def transform(self, tokens: list[str]) -> np.ndarray:
        v = np.zeros(len(self.vocab))
        for w, c in Counter(tokens).items():
            i = self.w2i.get(w)
            if i is not None:
                v[i] = 1.0 + np.log(c)           # sublinear term frequency
        v *= self.idf
        n = np.linalg.norm(v)
        return v / n if n else v


def pca_2d(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """2-D projection for the taste map: returns (points, mean, components)."""
    mu = X.mean(axis=0)
    _, _, vt = np.linalg.svd(X - mu, full_matrices=False)
    comps = vt[:2]
    return (X - mu) @ comps.T, mu, comps
