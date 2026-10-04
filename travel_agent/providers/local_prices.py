"""Verified local prices from free sources (no SerpApi credits).

1. Entry tickets and restaurant prices: Wikivoyage *listings* ({{see|name=...|price=€20, reduced €10|lastedit=...}}),
   from the city article and its district articles. A price counts only when it carries an explicit currency
   (or says "free"); every one keeps its original text and the date it was last edited.
2. Public-transport tickets, taxi tariffs and fixed airport fares: read from the Wikivoyage "Get in" /
   "Get around" text by the model, and accepted ONLY when the model returns a verbatim quote that is really
   in the text and contains the number. Without a model, nothing is extracted (no guesses).

Wikivoyage is community-edited: prices are shown with their source and edit date, never as live quotes.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, Field

from .. import llm, net
from ..utils import haversine_km

log = logging.getLogger(__name__)

WIKIVOYAGE = "https://en.wikivoyage.org/w/api.php"
MAX_DISTRICTS = 30
LISTING_TYPES = {"see", "do", "eat", "drink", "buy"}

# Currency markers -> ISO code. None = "the local currency" (dirham, krone... names shared by several countries).
CURRENCY_TOKENS: list[tuple[str, str | None]] = [
    ("e£", "EGP"), ("le", "EGP"), ("l.e.", "EGP"), ("egp", "EGP"), ("€", "EUR"), ("eur", "EUR"), ("euro", "EUR"),
    ("£", "GBP"), ("gbp", "GBP"), ("₺", "TRY"), ("tl", "TRY"), ("try", "TRY"), ("lira", "TRY"), ("us$", "USD"),
    ("usd", "USD"), ("aed", "AED"), ("sar", "SAR"), ("sr", "SAR"), ("qar", "QAR"), ("kwd", "KWD"), ("mad", "MAD"),
    ("dh", None), ("dhs", None), ("dirham", None), ("chf", "CHF"), ("¥", "JPY"), ("yen", "JPY"), ("jpy", "JPY"),
    ("₹", "INR"), ("rs", "INR"), ("inr", "INR"), ("฿", "THB"), ("thb", "THB"), ("baht", "THB"), ("kč", "CZK"),
    ("czk", "CZK"), ("ft", "HUF"), ("huf", "HUF"), ("zł", "PLN"), ("pln", "PLN"), ("kr", None), ("dkk", "DKK"),
    ("sek", "SEK"), ("nok", "NOK"), ("lei", "RON"), ("ron", "RON"), ("jd", "JOD"), ("jod", "JOD"), ("dinar", None),
    ("rm", "MYR"), ("myr", "MYR"), ("s$", "SGD"), ("sgd", "SGD"), ("hk$", "HKD"), ("hkd", "HKD"), ("a$", "AUD"),
    ("aud", "AUD"), ("c$", "CAD"), ("cad", "CAD"), ("r$", "BRL"), ("brl", "BRL"), ("peso", None), ("rp", "IDR"),
    ("idr", "IDR"), ("₫", "VND"), ("vnd", "VND"), ("₩", "KRW"), ("krw", "KRW"), ("gel", "GEL"), ("₾", "GEL"),
    ("amd", "AMD"), ("azn", "AZN"), ("₼", "AZN"), ("tnd", "TND"), ("lbp", "LBP"), ("omr", "OMR"), ("bhd", "BHD"),
    ("$", "USD"),  # local dollars when the local currency is a dollar (see parse_price)
]
FREE_RE = re.compile(r"^\s*(free|no charge|gratis|no entrance fee|no admission)", re.I)
NUM = r"\d{1,3}(?:[ ,.]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"


# ---------------------------------------------------------------------------
# Wikitext: brace-aware template parsing
# ---------------------------------------------------------------------------

def _templates(text: str) -> list[str]:
    """Bodies of top-level {{...}} templates (nested templates stay inside their parent)."""
    out, depth, start, i = [], 0, 0, 0
    while i < len(text) - 1:
        pair = text[i:i + 2]
        if pair == "{{":
            if depth == 0:
                start = i + 2
            depth += 1
            i += 2
            continue
        if pair == "}}" and depth:
            depth -= 1
            if depth == 0:
                out.append(text[start:i])
            i += 2
            continue
        i += 1
    return out


def _split_top(body: str) -> list[str]:
    """Split a template body on '|' that are not inside nested {{ }} or [[ ]]."""
    parts, depth, cur = [], 0, []
    i = 0
    while i < len(body):
        two = body[i:i + 2]
        if two in ("{{", "[["):
            depth += 1
            cur.append(two)
            i += 2
            continue
        if two in ("}}", "]]") and depth:
            depth -= 1
            cur.append(two)
            i += 2
            continue
        if body[i] == "|" and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(body[i])
        i += 1
    parts.append("".join(cur))
    return parts


def _clean(value: str) -> str:
    """Wikitext -> plain text: {{EGP|550}} -> 'EGP 550', [[a|b]] -> 'b', drop HTML and bold/italics."""
    v = re.sub(r"\{\{\s*([A-Za-z]{3})\s*\|\s*([^}|]+)[^}]*\}\}", r"\1 \2", value)  # currency templates
    v = re.sub(r"\{\{[^{}]*\}\}", "", v)
    v = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"<[^>]+>", "", v).replace("'''", "").replace("''", "").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", v).strip()


def parse_listing(body: str) -> dict[str, Any] | None:
    parts = _split_top(body)
    kind = parts[0].strip().lower()
    fields: dict[str, str] = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            fields[k.strip().lower()] = v.strip()
    if kind in ("listing", "marker"):
        kind = fields.get("type", "").strip().lower()
    if kind not in LISTING_TYPES or not fields.get("name"):
        return None
    try:
        lat, lon = float(fields.get("lat") or "x"), float(fields.get("long") or "x")
    except ValueError:
        lat = lon = None
    return {"kind": kind, "name": _clean(fields["name"]), "alt": _clean(fields.get("alt", "")),
            "price_text": _clean(fields.get("price", "")), "lat": lat, "lon": lon,
            "lastedit": (fields.get("lastedit") or "").strip()[:10] or None, "url": fields.get("url") or None}


def parse_price(text: str, local_currency: str) -> tuple[float | None, str | None, bool]:
    """The standard adult price: (amount, currency, is_free). Only with an explicit currency marker."""
    t = (text or "").strip()
    if not t:
        return None, None, False
    if FREE_RE.search(t):
        return 0.0, local_currency, True
    low = t.lower()
    # Every currency marker in the text; the FIRST one names the standard price ("€27 + 50 TL boat" -> €27).
    marks: list[tuple[int, int, str]] = []
    for tok, code in sorted(CURRENCY_TOKENS, key=lambda kv: -len(kv[0])):
        word = tok.replace(".", "").isalpha()  # word tokens only as whole words; symbols anywhere
        pat = rf"(?<![a-z]){re.escape(tok)}(?![a-z])" if word else re.escape(tok)
        for m in re.finditer(pat, low):
            if any(s <= m.start() < e for s, e, _ in marks):
                continue  # part of a longer marker already found ("us$", "e£")
            if tok == "$":
                cur = local_currency if local_currency.endswith("D") else "USD"
            else:
                cur = code or local_currency
            marks.append((m.start(), m.end(), cur))
    for start, end, cur in sorted(marks):
        # the number right next to the marker (before or after it: "€20", "20€", "550 LE", "LE550")
        best, dist = None, 99
        for n in re.finditer(NUM, t):
            d = min(abs(n.start() - end), abs(start - n.end()))
            if d < dist:
                best, dist = n.group(0), d
        if best is None or dist > 3:
            continue
        raw = best.replace(" ", "")
        if re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw):
            raw = re.sub(r"[.,]", "", raw)  # thousands separators
        try:
            return float(raw.replace(",", ".")), cur, False
        except ValueError:
            continue
    return None, None, False  # a bare number without a currency is not certain enough


async def _wikitext(title: str) -> tuple[str, str]:
    data = await net.fetch_json("wikivoyage", WIKIVOYAGE, {"action": "parse", "page": title, "prop": "wikitext",
                                                          "format": "json", "redirects": 1}, ttl_s=30 * net.DAY)
    p = data.get("parse") or {}
    return p.get("title", title), (p.get("wikitext") or {}).get("*", "")


async def listings(city: str, country: str = "") -> list[dict[str, Any]]:
    """Every see/do/eat/drink/buy listing of the city article and its district articles."""
    try:
        title, text = await _wikitext(city)
        if len(text) < 2000 and country:
            title, text = await _wikitext(f"{city} ({country})")
    except net.ProviderError as exc:
        log.warning("Wikivoyage listings for %s unavailable: %s", city, exc)
        return []
    pages = [(title, text)]
    districts = list(dict.fromkeys(re.findall(r"\[\[(%s/[^\]|#]+)" % re.escape(title), text)))[:MAX_DISTRICTS]
    gate = asyncio.Semaphore(5)

    async def one(t: str):
        async with gate:
            try:
                return await _wikitext(t)
            except net.ProviderError:
                return t, ""

    pages += await asyncio.gather(*(one(d) for d in districts))
    out = []
    for page_title, wt in pages:
        for body in _templates(wt):
            item = parse_listing(body)
            if item:
                item["page"] = f"https://en.wikivoyage.org/wiki/{page_title.replace(' ', '_')}"
                out.append(item)
    return out


# ---------------------------------------------------------------------------
# Matching a researched place to a listing
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    # Keep words like "museum": "Acropolis Museum" and "Acropolis" are different tickets.
    return " ".join(w for w in s.split() if w not in ("the", "of", "and"))


TYPE_WORDS = {"museum", "gallery", "church", "cathedral", "basilica", "palace", "park", "garden", "gardens", "tower",
              "temple", "mosque", "market", "square", "station", "house", "theatre", "theater", "castle", "hill", "site",
              "archaeological", "library", "stadium", "bridge", "beach", "island", "fort", "fortress", "monastery", "zoo"}


def _contained(a: str, b: str) -> bool:
    """One name inside the other ("Colosseum" / "Colosseum Rome"), unless the extra words make it a different
    place ("Acropolis" vs "Acropolis Museum")."""
    short, long_ = sorted((a, b), key=len)
    if len(short) < 6 or short not in long_:
        return False
    extra = set(long_.split()) - set(short.split())
    return len(extra) <= 2 and not (extra & TYPE_WORDS)


def match(name: str, lat: float, lon: float, items: list[dict], kinds: set[str]) -> dict | None:
    """The listing for this place: same name (or alias), and near it when the listing has coordinates."""
    target = _norm(name)
    if len(target) < 3:
        return None
    best, best_score = None, 0.0
    for it in items:
        if it["kind"] not in kinds:
            continue
        for label in filter(None, (it["name"], it.get("alt"))):
            cand = _norm(label)
            if not cand or (set(cand.split()) ^ set(target.split())) & TYPE_WORDS:
                continue  # a type word on one side only: a different place (site vs its museum)
            ratio = difflib.SequenceMatcher(None, target, cand).ratio()
            contained = _contained(target, cand)
            near = it["lat"] is not None and haversine_km(lat, lon, it["lat"], it["lon"]) <= 0.35
            far = it["lat"] is not None and haversine_km(lat, lon, it["lat"], it["lon"]) > 2.0
            if far:
                continue
            score = ratio + (0.15 if contained else 0) + (0.1 if near else 0)
            ok = ratio >= 0.9 or (contained and (near or it["lat"] is None)) or (ratio >= 0.72 and near)
            if ok and score > best_score:
                best, best_score = it, score
    return best


# ---------------------------------------------------------------------------
# Transport tariffs quoted from the guide text
# ---------------------------------------------------------------------------

class Quoted(BaseModel):
    amount: float
    currency: str = Field(description="ISO 4217 code, e.g. EUR")
    quote: str = Field(description="The exact sentence fragment from the text that states this price, copied verbatim")


class AirportFare(Quoted):
    airport: str = Field(description="Airport name or code as written")
    mode: Literal["taxi", "bus", "train", "metro", "shuttle"]
    destination: str = Field(default="city centre", description="Where the fare goes to, as written")


class Tariffs(BaseModel):
    transit_single_ticket: Quoted | None = Field(default=None, description="One standard single-ride city ticket (adult)")
    transit_day_pass: Quoted | None = Field(default=None, description="24-hour / 1-day city pass (adult)")
    taxi_flag_fall: Quoted | None = Field(default=None, description="Taxi base fare / flag fall / minimum start")
    taxi_per_km: Quoted | None = Field(default=None, description="Taxi price per km (daytime tariff)")
    airport_fares: list[AirportFare] = Field(default_factory=list, description="Fixed fares between airport and city")


TARIFF_SYSTEM = (
    "Extract public transport and taxi PRICES stated in this travel-guide text. Only prices literally written in the "
    "text - never estimate or use outside knowledge. For each value, copy into 'quote' the exact clause of the text "
    "that states it, verbatim (same spelling and symbols), long enough to show WHAT the price is for - at least 6 "
    "words, e.g. 'The Leonardo Express costs €14 each way', not just '€14'. If a value is not stated, leave it null. "
    "Use daytime / standard adult fares; skip prices the text marks as old. transit_single_ticket and the day pass "
    "are for rides WITHIN the city (metro, bus, tram, city ferry) - never an intercity or international train, coach, "
    "ferry or flight fare (e.g. 'a single from Sofia is €26' is NOT a city ticket). At most one airport fare per mode "
    "(taxi, bus, train...) and airport. Currency as an ISO code (€ -> EUR, LE / E£ -> EGP, TL -> TRY, etc.)."
)
FIELD_WORDS = {
    "transit_single_ticket": r"ticket|single|ride|fare|metro|subway|bus|tram|underground|journey",
    "transit_day_pass": r"day|24|pass|daily",
    "taxi_flag_fall": r"taxi|cab|flag|start|base|minimum",
    "taxi_per_km": r"taxi|cab|km|kilomet",
}
MODE_WORDS = {"taxi": r"taxi|cab", "bus": r"bus|coach", "train": r"train|express|rail",
              "metro": r"metro|subway|underground|line", "shuttle": r"shuttle|bus|transfer"}
STALE_YEAR = re.compile(r"\b(19\d\d|200\d|201\d)\b")


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip().lower()


def _verified(q: Quoted | None, source: str, about: str = "") -> bool:
    """A quoted price is accepted only if the quote is really in the text, states that number, says what it is
    for (`about`: words that must appear), and isn't marked as an old price."""
    if q is None or q.amount <= 0 or not q.quote.strip():
        return False
    quote = _squash(q.quote)
    if len(quote) < 20 or quote not in _squash(source) or STALE_YEAR.search(quote):
        return False
    if about and not re.search(about, quote):
        return False
    numbers = {float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d{1,2})?", quote)}
    return any(abs(n - q.amount) < 0.01 for n in numbers)


async def tariffs(city: str, guide_text: str) -> dict[str, Any] | None:
    """Transport prices quoted from the guide. None without a model or when the guide states none."""
    if not llm.available() or len(guide_text) < 200:
        return None
    out = await llm.parse(TARIFF_SYSTEM, json.dumps({"city": city, "text": guide_text[:30000]}, ensure_ascii=False),
                          Tariffs)
    if out is None:
        return None
    result: dict[str, Any] = {}
    for key in ("transit_single_ticket", "transit_day_pass", "taxi_flag_fall", "taxi_per_km"):
        q = getattr(out, key)
        if _verified(q, guide_text, FIELD_WORDS[key]):
            result[key] = q.model_dump()
    fares, seen = [], set()
    for f in out.airport_fares:
        key = (f.mode, _squash(f.airport)[:20])
        if key not in seen and _verified(f, guide_text, MODE_WORDS.get(f.mode, "")):
            seen.add(key)
            fares.append(f.model_dump())
    result["airport_fares"] = fares[:6]
    rejected = sum(1 for k in ("transit_single_ticket", "transit_day_pass", "taxi_flag_fall", "taxi_per_km")
                   if getattr(out, k) and k not in result) + len(out.airport_fares) - len(result["airport_fares"])
    if rejected:
        log.info("tariffs %s: %d quoted prices rejected (quote not found verbatim)", city, rejected)
    return result if any(result.get(k) for k in result) else None


async def guide_transport_text(city: str, country: str = "") -> str:
    """The full 'Get in' + 'Get around' sections (plain text) of the city article."""
    from ..knowledge import _extract

    try:
        title, text = await _extract(city)
        if len(text) < 500 and country:
            title, text = await _extract(f"{city} ({country})")
    except net.ProviderError:
        return ""
    parts = re.split(r"\n== ([^=\n]+) ==\n", text)
    keep = [body for name, body in zip(parts[1::2], parts[2::2]) if name.strip() in ("Get in", "Get around")]
    return "\n".join(keep)
