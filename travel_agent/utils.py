"""Small deterministic helpers: clock arithmetic, geo distance, script detection."""

from __future__ import annotations

import math
from contextvars import ContextVar
from datetime import date, datetime, timezone

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Provenance of the HTTP response being parsed right now (set by net.py on every return, read by Metadata):
# when it was really fetched (a cache hit keeps its original time) and whether it was served stale.
FETCHED_AT: ContextVar[float | None] = ContextVar("fetched_at", default=None)
SERVED_STALE: ContextVar[bool] = ContextVar("served_stale", default=False)


def fetch_time() -> datetime:
    ts = FETCHED_AT.get()
    return datetime.fromtimestamp(ts, timezone.utc) if ts else datetime.now(timezone.utc)


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


def is_arabic(text: str | None) -> bool:
    """True when the text contains Arabic script (the reply is then written in Egyptian Arabic)."""
    return any("\u0600" <= ch <= "\u06ff" for ch in text or "")


def place_key(text: str | None) -> str:
    """The comparable name of a place the model wrote: 'Bali, Indonesia' and 'bali' are the same city name."""
    t = (text or "").split(",")[0].strip().lower()
    return t[4:] if t.startswith("the ") else t


def same_place(a: str | None, b: str | None) -> bool:
    return bool(place_key(a)) and place_key(a) == place_key(b)


def matches_ref(text: str | None, ref) -> bool:
    """Does 'City' / 'City, Country' name this resolved place? A stated country must agree too ('Bali, Indonesia'
    is not Bali District in Taiwan, whatever its name)."""
    if ref is None or not same_place(text, ref.name):
        return False
    from .providers.geo import country_code

    parts = [x.strip() for x in (text or "").split(",")]
    cc = country_code(parts[-1]) if len(parts) > 1 else None
    return cc is None or cc == (ref.country_code or "").upper()


def open_windows(opening_hours: dict[str, list[list[str]]], d: date) -> list[tuple[int, int]]:
    return [(to_min(a), to_min(b)) for a, b in opening_hours.get(weekday_key(d), [])]


def is_open_for(opening_hours: dict[str, list[list[str]]], d: date, start: int, end: int) -> bool:
    return any(o <= start and end <= c for o, c in open_windows(opening_hours, d))
