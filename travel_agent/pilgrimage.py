"""Umrah trips, and Hajj guidance: what changes when the journey is a pilgrimage.

- Makkah and Madinah are recognised by where they are (near the two Holy Mosques), whatever the spelling.
- The hotel's walk to the Holy Mosque leads the hotel choice (the planner's anchor).
- The sacred sites are a fixed list, placed with Wikipedia's coordinates (MCP knowledge.get_sacred_sites). On an Umrah
  trip the Umrah itself (ihram, tawaf, sa'i) is planned on the first days in Makkah, and the visit to the Prophet's
  Mosque in Madinah - both forced into the plan, never squeezed out by sightseeing.
- Every day carries the five prayer times (Aladhan, Umm al-Qura); the Hijri dates bring the season notes (Ramadan,
  the Hajj season).
Religious guidance is never written by the model: the guide is fixed text (the Hajj & Umrah page), and the Hajj itself
is never planned - it goes through official channels only.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from .models import GeoPoint, Metadata, Money, Place, TripPlan
from .providers import wiki
from .utils import WEEKDAYS, haversine_km

HOLY = {
    "makkah": {"name": "Masjid al-Haram", "name_ar": "المسجد الحرام", "city": "Makkah", "city_ar": "مكة المكرمة",
               "lat": 21.4225, "lon": 39.8262},
    "madinah": {"name": "Al-Masjid an-Nabawi", "name_ar": "المسجد النبوي", "city": "Madinah",
                "city_ar": "المدينة المنورة", "lat": 24.4672, "lon": 39.6111},
}
HOLY_RADIUS_KM = 15
ALL_DAY = [["00:00", "23:59"]]
COOL_HOURS = [["05:00", "10:00"], ["16:00", "21:00"]]  # climbs and open-air sites: before the heat, or after Asr
RITUAL = "ritual"  # category of the Umrah / the Prophet's Mosque visit: planned only on an Umrah trip

# The sacred sites (English Wikipedia title -> what the plan shows). Notes state only well-established practice.
SITES: dict[str, list[dict]] = {
    "makkah": [
        {"title": "Great Mosque of Mecca", "ritual": True, "minutes": 180, "hours": ALL_DAY,
         "name": "Umrah: tawaf and sa'i at Masjid al-Haram", "name_ar": "العمرة: الطواف والسعي في المسجد الحرام",
         "notes": "Ihram is entered at the miqat before reaching Makkah (on the plane for most flights). Tawaf: seven "
                  "circuits around the Kaaba starting from the Black Stone corner, then two rak'ahs behind Maqam "
                  "Ibrahim and Zamzam water; sa'i: seven laps between Safa and Marwah starting at Safa; then shaving "
                  "or trimming the hair. Late at night or before Fajr is cooler and calmer. Book the Umrah in the "
                  "Nusuk app. Step by step: the Hajj & Umrah guide."},
        {"title": "Jabal al-Nour", "minutes": 150, "hours": COOL_HOURS, "name": "Jabal al-Nour (Cave of Hira)",
         "name_ar": "جبل النور (غار حراء)",
         "notes": "A steep climb of about an hour to the Cave of Hira, where the first revelation came. Go early "
                  "morning or after Asr, with water and good shoes."},
        {"title": "Jabal Thawr", "minutes": 180, "hours": COOL_HOURS, "name": "Jabal Thawr (Cave of Thawr)",
         "name_ar": "جبل ثور (غار ثور)",
         "notes": "Where the Prophet ﷺ and Abu Bakr sheltered during the Hijrah; a long, hard climb - start early."},
        {"title": "Mount Arafat", "minutes": 75, "hours": COOL_HOURS, "name": "Arafat (Jabal al-Rahmah)",
         "name_ar": "عرفات (جبل الرحمة)", "notes": "The plain of the Day of Arafah, about 20 km from the Haram."},
        {"title": "Mina", "minutes": 45, "hours": COOL_HOURS, "name": "Mina", "name_ar": "منى",
         "notes": "The valley of tents and the Jamarat, used during the days of Hajj."},
        {"title": "Muzdalifah", "minutes": 30, "hours": COOL_HOURS, "name": "Muzdalifah", "name_ar": "مزدلفة",
         "notes": "Between Mina and Arafat, where pilgrims spend the night after Arafah."},
        {"title": "Masjid Aisha", "minutes": 45, "hours": ALL_DAY, "name": "Masjid Aisha (Tan'eem)",
         "name_ar": "مسجد السيدة عائشة (التنعيم)",
         "notes": "The nearest miqat for someone already in Makkah who wants to enter ihram for another Umrah."},
    ],
    "madinah": [
        {"title": "Al-Masjid an-Nabawi", "ritual": True, "minutes": 120, "hours": ALL_DAY,
         "name": "Prayer at Al-Masjid an-Nabawi and greeting the Prophet ﷺ",
         "name_ar": "الصلاة في المسجد النبوي والسلام على النبي ﷺ",
         "notes": "Praying in the Prophet's Mosque and sending peace upon the Prophet ﷺ and his two companions. "
                  "A visit to Ar-Rawdah needs a time booked in the Nusuk app."},
        {"title": "Quba Mosque", "minutes": 60, "hours": ALL_DAY, "name": "Quba Mosque", "name_ar": "مسجد قباء",
         "notes": "The first mosque built in Islam. The Prophet ﷺ used to visit it every Saturday."},
        {"title": "Masjid al-Qiblatayn", "minutes": 40, "hours": ALL_DAY, "name": "Masjid al-Qiblatayn",
         "name_ar": "مسجد القبلتين", "notes": "Where the qibla was changed from Jerusalem to Makkah."},
        {"title": "Mount Uhud", "minutes": 75, "hours": COOL_HOURS, "name": "Mount Uhud and the Martyrs of Uhud",
         "name_ar": "جبل أحد وشهداء أحد", "notes": "The site of the Battle of Uhud and the martyrs' graves."},
        {"title": "Al-Baqi'", "minutes": 30, "hours": [["06:00", "08:30"], ["15:30", "17:30"]],
         "name": "Al-Baqi' cemetery", "name_ar": "مقبرة البقيع",
         "notes": "Usually open for visits after Fajr and after Asr (times vary)."},
    ],
}


def holy_city(lat: float, lon: float) -> str | None:
    """'makkah' / 'madinah' for a place near the Holy Mosque, else None."""
    return next((k for k, h in HOLY.items() if haversine_km(lat, lon, h["lat"], h["lon"]) <= HOLY_RADIUS_KM), None)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


async def sacred_sites(city: str) -> list[dict]:
    """The city's sacred sites as places (Wikipedia's coordinates and picture; the Holy Mosque's own point as the
    fallback for the two mosques)."""
    out = []
    for s in SITES.get(city, []):
        article = await wiki.find_article(s["title"])
        coords = (article or {}).get("coordinates")
        if not coords and not s.get("ritual"):
            continue  # never placed on a guessed point
        lat, lon = (coords["lat"], coords["lon"]) if coords else (HOLY[city]["lat"], HOLY[city]["lon"])
        p = Place(id=f"holy_{city}_{_slug(s['title'])}", name=s["name"], kind="activity",
                  categories=["religious", "landmarks"] + ([RITUAL] if s.get("ritual") else []),
                  location=GeoPoint(lat=lat, lon=lon), rating=5.0, price_level=1,
                  cost_per_person=Money(amount=0.0, currency="SAR", price_type="known", source="Free"),
                  price_known=True, price_checked=True, opening_hours={w: s["hours"] for w in WEEKDAYS},
                  hours_verified=s["hours"] is ALL_DAY, duration_minutes=s["minutes"], indoor=False,
                  popularity="must_see", description=s["name_ar"], notes=s["notes"],
                  website=((article or {}).get("content_urls") or {}).get("desktop", {}).get("page"),
                  thumbnail=((article or {}).get("thumbnail") or {}).get("source"),
                  metadata=Metadata(source="knowledge_mcp", provider="Dalili sacred sites · Wikipedia", confidence=1.0))
        out.append(p.model_dump(mode="json"))
    return out


def umrah_days(places: list[Place], start: date) -> None:
    """The Umrah on the first two days in Makkah: on arrival when there is time, else the next day."""
    for p in places:
        if RITUAL in p.categories and p.id.startswith("holy_makkah"):
            p.dates = [start, start + timedelta(days=1)]


def ritual_ids(places: list[Place]) -> list[str]:
    return [p.id for p in places if RITUAL in p.categories]


def times_line(times: dict[str, str], arabic: bool = False) -> str:
    names = {"Fajr": "الفجر", "Dhuhr": "الظهر", "Asr": "العصر", "Maghrib": "المغرب", "Isha": "العشاء"} if arabic else {}
    return " · ".join(f"{names.get(k, k)} {v}" for k, v in times.items())


def add_prayer_notes(plan: TripPlan, bundles: list, stop_dates: list[tuple[date, date]]) -> None:
    """Each day of the plan gets the five prayer times of the city it is spent in."""
    for d in plan.days:
        # A travel day belongs to the city arrived in (the later stop).
        idx = max((i for i, (a, b) in enumerate(stop_dates) if a <= d.date <= b), default=None)
        if idx is None or idx >= len(bundles):
            continue
        info = bundles[idx].destination_info
        day = (info.get("prayer_times") or {}).get(d.date.isoformat())
        holy = info.get("holy")
        if day and holy:
            line = f"🕌 Prayer times in {holy['city']}: {times_line(day['times'])}"
            if line not in d.notes:
                d.notes.insert(0, line)


def season_notes(bundles: list) -> list[str]:
    """Ramadan and the Hajj season, from the Hijri dates of the trip's days."""
    months: set[tuple[int, int]] = set()
    for b in bundles:
        for day in (b.destination_info.get("prayer_times") or {}).values():
            months.add((day["hijri"]["month"], day["hijri"]["day"]))
    notes = []
    if any(m == 9 for m, _ in months):
        notes.append("The trip falls in Ramadan: the most sought-after time for Umrah - the Haram is at its busiest "
                     "and hotels near it at their highest prices; Taraweeh and Qiyam prayers fill the nights.")
    if any(m == 11 or (m == 12 and d <= 15) for m, d in months):
        notes.append("The dates fall in the Hajj season (Dhu al-Qadah to mid Dhu al-Hijjah): Umrah for visitors is "
                     "usually suspended then - check the Nusuk app before booking anything.")
    return notes


HAJJ_NOTE = ("Hajj can't be booked as a self-planned trip: Hajj permits are issued only through official channels "
             "(for Egyptians, the Ministry of Interior lottery, the Ministry of Social Solidarity or a licensed tourism "
             "company; for many other countries, the Nusuk Hajj platform). Dalili can show you the Hajj guide and the "
             "expected dates, or plan an Umrah - which would you like?")
