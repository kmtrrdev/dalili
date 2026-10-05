"""Human evaluation: what travellers rate, stored anonymously, summarised reproducibly.

Each rating covers the dimensions below (1-5). Raters are stored as a salted hash (never an account id or email),
and every rating keeps the rated plan's own metrics (TripScore parts, validity, price confidence) so perceived
quality can be compared with measured quality. `summary()` gives per-variant means with 95% confidence intervals
(Student t) and, when two variants exist (e.g. "dalili" vs a baseline), the difference with a Welch 95% interval.
"""

from __future__ import annotations

import hashlib
import math
import os
import statistics
from typing import Any

DIMENSIONS = ("relevance", "personalization", "trust", "explanations", "itinerary", "usability", "confidence",
              "overall")

# Two-sided 95% Student t critical values by degrees of freedom (1-30; larger df -> 1.96).
_T95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
        2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]


def t95(df: float) -> float:
    if df < 1:
        return float("nan")
    return _T95[int(df) - 1] if df <= 30 else 1.96


def rater_id(identity: str) -> str:
    salt = os.getenv("DALILI_EVAL_SALT", "dalili-human-eval")
    return hashlib.sha256(f"{salt}|{identity}".encode()).hexdigest()[:16]


def _stats(values: list[float]) -> dict[str, Any]:
    n = len(values)
    if not n:
        return {"n": 0}
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if n > 1 else 0.0
    half = t95(n - 1) * sd / math.sqrt(n) if n > 1 else None
    return {"n": n, "mean": round(mean, 2), "sd": round(sd, 2),
            "ci95": [round(mean - half, 2), round(mean + half, 2)] if half is not None else None}


def _welch(a: list[float], b: list[float]) -> dict[str, Any] | None:
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = statistics.variance(a) / len(a), statistics.variance(b) / len(b)
    diff = statistics.fmean(a) - statistics.fmean(b)
    se = math.sqrt(va + vb)
    if se == 0:
        return {"difference": round(diff, 2), "ci95": [round(diff, 2), round(diff, 2)]}
    df = (va + vb) ** 2 / ((va ** 2) / (len(a) - 1) + (vb ** 2) / (len(b) - 1))
    half = t95(df) * se
    return {"difference": round(diff, 2), "ci95": [round(diff - half, 2), round(diff + half, 2)],
            "df": round(df, 1), "significant_at_95": not (diff - half <= 0 <= diff + half)}


def summary(rows: list[dict]) -> dict[str, Any]:
    variants = sorted({r["variant"] for r in rows})
    out: dict[str, Any] = {"ratings": len(rows), "raters": len({r["rater"] for r in rows}), "variants": {}}
    for v in variants:
        sub = [r for r in rows if r["variant"] == v]
        out["variants"][v] = {d: _stats([float(r["ratings"][d]) for r in sub if d in r["ratings"]]) for d in DIMENSIONS}
    if len(variants) == 2 and "dalili" in variants:
        other = next(v for v in variants if v != "dalili")
        out["dalili_vs_" + other] = {
            d: _welch([float(r["ratings"][d]) for r in rows if r["variant"] == "dalili" and d in r["ratings"]],
                      [float(r["ratings"][d]) for r in rows if r["variant"] == other and d in r["ratings"]])
            for d in DIMENSIONS}
    # Does measured quality track perceived quality? (Pearson r between TripScore and the overall rating)
    pairs = [(r["plan"].get("score"), r["ratings"].get("overall")) for r in rows
             if r["plan"].get("score") is not None and r["ratings"].get("overall") is not None]
    if len(pairs) >= 3:
        xs, ys = zip(*pairs)
        if statistics.pstdev(xs) and statistics.pstdev(ys):
            out["tripscore_vs_overall_r"] = round(statistics.correlation(xs, ys), 3)
    return out
