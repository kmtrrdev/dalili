"""Small deterministic helpers: clock arithmetic, geo distance, stable hashing."""

from __future__ import annotations

import hashlib
import math
from datetime import date

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def to_hhmm(minutes: int) -> str:
    minutes = max(0, min(int(round(minutes)), 24 * 60 - 1))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def round_up(minutes: int, step: int = 5) -> int:
    return int(math.ceil(minutes / step) * step)


def weekday_key(d: date) -> str:
    return WEEKDAYS[d.weekday()]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def stable_int(*parts: object) -> int:
    """Deterministic pseudo-random integer (same inputs -> same output across runs)."""
    raw = "|".join(str(p) for p in parts).encode()
    return int(hashlib.sha256(raw).hexdigest()[:12], 16)


def stable_unit(*parts: object) -> float:
    return (stable_int(*parts) % 10_000) / 10_000.0


def open_windows(opening_hours: dict[str, list[list[str]]], d: date) -> list[tuple[int, int]]:
    return [(to_min(a), to_min(b)) for a, b in opening_hours.get(weekday_key(d), [])]


def is_open_for(opening_hours: dict[str, list[list[str]]], d: date, start: int, end: int) -> bool:
    return any(o <= start and end <= c for o, c in open_windows(opening_hours, d))
