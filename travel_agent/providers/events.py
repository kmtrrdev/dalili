"""Local events during the trip dates: Google Events (SerpApi), with Google Search's events block as fallback."""

from __future__ import annotations

import logging
import re
from datetime import date

from .. import net
from ..config import settings
from ..models import GeoPoint, Metadata, Money, Place
from ..utils import WEEKDAYS, weekday_key
from .places import _clock, _pid, classify

log = logging.getLogger(__name__)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _event_date(text: str, start: date, end: date) -> date | None:
    """Accepts "Oct 14", "Wed, Oct 14" (Events API) and "14 Oct" (Google Search events block)."""
    m = re.search(r"([A-Za-z]{3})[a-z]*\.? (\d{1,2})\b", text or "")
    if m and m.group(1).lower()[:3] in MONTHS:
        month, day = MONTHS[m.group(1).lower()[:3]], int(m.group(2))
    else:
        m = re.search(r"\b(\d{1,2}) ([A-Za-z]{3})", text or "")
        if not m or m.group(2).lower()[:3] not in MONTHS:
            return None
        month, day = MONTHS[m.group(2).lower()[:3]], int(m.group(1))
    for year in (start.year, end.year):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if start <= d <= end:
            return d
    return None


def _event_times(when: str) -> tuple[int, int] | None:
    text = (when or "").replace(" ", " ").replace("–", "-")
    m = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:AM|PM)?)\s*-\s*(\d{1,2}(?::\d{2})?\s*(?:AM|PM))", text, re.I)
    if m:
        suf = re.search(r"(AM|PM)", m.group(2), re.I).group(1)
        s = _clock(m.group(1), None if re.search(r"AM|PM", m.group(1), re.I) else suf)
        e = _clock(m.group(2), None)
        if s is not None and e is not None:
            return s, e if e > s else 23 * 60 + 59
    m = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:AM|PM))", text, re.I)
    if m:
        s = _clock(m.group(1), None)
        if s is not None:
            return s, min(s + 120, 23 * 60 + 59)
    return None


async def _raw_events(city: str) -> list[dict]:
    try:
        data = await net.serpapi("google_events", net.DAY, q=f"Events in {city}", hl=settings.language)
        return data.get("events_results") or []
    except net.ProviderError as exc:
        if "Unsupported" not in str(exc):
            raise
        log.info("google_events not available on this SerpApi plan; using Google Search events")
    data = await net.serpapi("google", net.DAY, q=f"events in {city}", hl=settings.language)
    return data.get("events_results") or []


async def events(city: str, center: GeoPoint, start: date, end: date) -> list[Place]:
    out = []
    for ev in await _raw_events(city):
        if not isinstance(ev, dict):
            continue
        raw_date = ev.get("date")
        if isinstance(raw_date, dict):  # Google Events API shape
            date_text, when = raw_date.get("start_date") or raw_date.get("when", ""), raw_date.get("when", "")
        else:  # Google Search events block: {"date": "31 Oct", "time": "9:00 PM"}
            date_text, when = str(raw_date or ""), str(ev.get("time") or "")
        d = _event_date(date_text, start, end)
        if d is None:
            continue
        times = _event_times(when)
        verified = times is not None
        s, e = times or (20 * 60, 22 * 60)
        cats, indoor, _, _, _ = classify([ev.get("title", "")], ev.get("description", "") or "")
        title = ev.get("title", "Event")
        if re.search(r"concert|music|jazz|opera|festival|live", title, re.I):
            cats = sorted(set(cats) | {"music", "nightlife", "culture"})
        hours = {w: [] for w in WEEKDAYS}
        hours[weekday_key(d)] = [[f"{s // 60:02d}:{s % 60:02d}", f"{e // 60:02d}:{e % 60:02d}"]]
        ticket = (ev.get("ticket_info") or [{}])[0] if isinstance(ev.get("ticket_info"), list) else {}
        venue = ev.get("venue") if isinstance(ev.get("venue"), dict) else {}
        out.append(Place(
            id=_pid("e", title + d.isoformat()), name=title, kind="activity", categories=cats + ["event"],
            location=center, rating=float(venue.get("rating") or 4.3), price_level=2,
            cost_per_person=Money(amount=30.0, currency="USD", price_type="estimated"), price_known=False,
            opening_hours=hours, hours_verified=verified, dates=[d], duration_minutes=max(45, min(e - s, 180)),
            indoor=True, popularity="local_favorite",
            description=(ev.get("description") or ev.get("source") or "")[:240], address=", ".join(ev.get("address") or []) if isinstance(ev.get("address"), list) else "",
            website=ticket.get("link") or ev.get("link"),
            notes=f"One-off event on {d:%a %d %b}. Venue: {venue.get('name', 'see link')}. "
                  "Ticket price estimated - check the event page.",
            metadata=Metadata(source="activities_mcp", provider="Google Events (SerpApi)", confidence=0.6,
                              source_url=ev.get("link")),
        ))
    return out
