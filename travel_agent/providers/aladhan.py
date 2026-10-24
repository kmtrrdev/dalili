"""Prayer times and Hijri dates (Aladhan, free, no key) by the Umm al-Qura method used in Makkah and Madinah."""

from __future__ import annotations

from datetime import date, timedelta

from .. import net

API = "https://api.aladhan.com/v1"
PRAYERS = ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha")
UMM_AL_QURA = 4


async def hajj_dates(today: date) -> dict:
    """The next Hajj by the Umm al-Qura calendar: 8-13 Dhu al-Hijjah as Gregorian dates (expected - the moon sighting
    can move them by a day)."""
    now = await net.fetch_json("aladhan", f"{API}/gToH/{today:%d-%m-%Y}", {}, ttl_s=net.DAY)
    h = now["data"]["hijri"]
    year = int(h["year"])
    if int(h["month"]["number"]) == 12 and int(h["day"]) > 13:
        year += 1  # this year's Hajj is over
    days = {}
    for day in range(8, 14):
        g = await net.fetch_json("aladhan", f"{API}/hToG/{day:02d}-12-{year}", {}, ttl_s=30 * net.DAY)
        dd, mm, yy = g["data"]["gregorian"]["date"].split("-")
        days[day] = f"{yy}-{mm}-{dd}"
    return {"hijri_year": year, "days": days}


async def prayer_times(lat: float, lon: float, start: date, end: date) -> dict[str, dict]:
    """ISO date -> {"times": {Fajr..Isha: "HH:MM"}, "hijri": {day, month, year, month_en, month_ar}}."""
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    out: dict[str, dict] = {}
    for year, month in sorted({(d.year, d.month) for d in days}):
        data = await net.fetch_json("aladhan", f"{API}/calendar/{year}/{month}",
                                    {"latitude": round(lat, 4), "longitude": round(lon, 4), "method": UMM_AL_QURA},
                                    ttl_s=30 * net.DAY)
        for row in (data or {}).get("data") or []:
            dd, mm, yy = row["date"]["gregorian"]["date"].split("-")
            iso = f"{yy}-{mm}-{dd}"
            if not start.isoformat() <= iso <= end.isoformat():
                continue
            h = row["date"]["hijri"]
            out[iso] = {"times": {p: row["timings"][p].split(" ")[0] for p in PRAYERS},
                        "hijri": {"day": int(h["day"]), "month": int(h["month"]["number"]), "year": int(h["year"]),
                                  "month_en": h["month"]["en"], "month_ar": h["month"]["ar"]}}
    return out
