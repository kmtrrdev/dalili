"""Weather from Open-Meteo (no key).

Within ~15 days: the live forecast. Further out there is no forecast, so the plan uses the
*observed* weather for the same dates last year (Open-Meteo historical archive), flagged
with low confidence - real data, but a proxy.
"""

from __future__ import annotations

from datetime import date, timedelta

from .. import net
from ..config import today as _today
from ..models import Metadata, WeatherDay

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
# Open-Meteo serves ~16 forecast days counted on its own (UTC) clock; one day of margin avoids
# "end_date out of allowed range" around midnight in time zones ahead of UTC.
FORECAST_HORIZON_DAYS = 14

WMO = {
    0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Rain showers", 81: "Rain showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail",
}


def classify_risk(precip_prob: int, precip_mm: float, condition: str) -> str:
    if "Thunder" in condition or "Heavy" in condition or "Violent" in condition or precip_mm >= 8 or precip_prob >= 75:
        return "high"
    if precip_prob >= 45 or precip_mm >= 2:
        return "medium"
    return "low"


async def forecast(lat: float, lon: float, start: date, end: date) -> list[WeatherDay]:
    data = await net.fetch_json("open-meteo", FORECAST_URL, {
        "latitude": lat, "longitude": lon, "timezone": "auto", "start_date": start.isoformat(), "end_date": end.isoformat(),
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
    }, ttl_s=3 * net.HOUR)
    d = data["daily"]
    out = []
    for i, day in enumerate(d["time"]):
        cond = WMO.get(d["weather_code"][i] or 0, "Mixed")
        prob, mm = int(d["precipitation_probability_max"][i] or 0), float(d["precipitation_sum"][i] or 0)
        out.append(WeatherDay(date=date.fromisoformat(day), condition=cond, temp_min_c=d["temperature_2m_min"][i],
                              temp_max_c=d["temperature_2m_max"][i], precipitation_probability=prob, precipitation_mm=mm,
                              risk=classify_risk(prob, mm, cond),  # type: ignore[arg-type]
                              metadata=Metadata(source="weather_mcp", provider="Open-Meteo forecast", confidence=0.8,
                                                source_url="https://open-meteo.com/")))
    return out


async def last_year(lat: float, lon: float, start: date, end: date) -> list[WeatherDay]:
    def shift(d: date) -> date:
        try:
            return d.replace(year=d.year - 1)
        except ValueError:  # Feb 29
            return d.replace(year=d.year - 1, day=28)
    s, e = shift(start), shift(end)
    data = await net.fetch_json("open-meteo", ARCHIVE_URL, {
        "latitude": lat, "longitude": lon, "timezone": "auto", "start_date": s.isoformat(), "end_date": e.isoformat(),
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
    }, ttl_s=365 * net.DAY)
    d = data["daily"]
    out = []
    for i in range(len(d["time"])):
        cond = WMO.get(d["weather_code"][i] or 0, "Mixed")
        mm = float(d["precipitation_sum"][i] or 0)
        prob = 80 if mm >= 5 else (50 if mm >= 1 else 10)  # derived from what actually happened
        out.append(WeatherDay(date=start + timedelta(days=i), condition=cond, temp_min_c=d["temperature_2m_min"][i],
                              temp_max_c=d["temperature_2m_max"][i], precipitation_probability=prob, precipitation_mm=mm,
                              risk=classify_risk(prob, mm, cond),  # type: ignore[arg-type]
                              metadata=Metadata(source="weather_mcp", provider="Open-Meteo archive (same dates last year)",
                                                confidence=0.35, source_url="https://open-meteo.com/",
                                                notes="No forecast exists this far ahead; showing last year's observed weather.")))
    return out


async def get_weather(lat: float, lon: float, start: date, end: date) -> list[WeatherDay]:
    today = _today()
    horizon = today + timedelta(days=FORECAST_HORIZON_DAYS)
    days: dict[date, WeatherDay] = {}
    if start <= horizon and end >= today:
        try:
            for w in await forecast(lat, lon, max(start, today), min(end, horizon)):
                days[w.date] = w
        except net.ProviderError:
            pass  # forecast refused (e.g. range edge): last year's observed weather below covers the days
    if any(start + timedelta(days=i) not in days for i in range((end - start).days + 1)):
        for w in await last_year(lat, lon, start, end):
            days.setdefault(w.date, w)
    return [days[k] for k in sorted(days)]
