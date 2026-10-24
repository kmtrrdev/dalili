"""Wikipedia and Wikidata: the article behind a fact (a world event, the landmark in a traveller's photo).

An article found indirectly - by a redirect or a search - counts only when it is about the same subject (same_subject),
so a near miss never passes for the thing asked about.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote

from .. import net
from .local_prices import _squash

SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
API = "https://en.wikipedia.org/w/api.php"
WIKIDATA = "https://www.wikidata.org/w/api.php"


async def summary(title: str) -> dict | None:
    """The article's summary (title, extract, picture, coordinates, Wikidata id), or None for a missing page, a
    disambiguation page or one without a Wikidata item."""
    try:
        data = await net.fetch_json("wikipedia", SUMMARY + quote(title.replace(" ", "_"), safe=""), ttl_s=7 * net.DAY)
    except net.ProviderError:
        return None
    if not isinstance(data, dict) or data.get("type") != "standard" or not data.get("wikibase_item"):
        return None
    return data


def words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", _squash(s)) if w not in {"the", "of", "in", "and", "de", "s", "festival"}}


def same_subject(asked: str, found: str) -> bool:
    """An article found for a title (by redirect or search) is about it: most of the article's name is in the title,
    and it is the same edition - never "Derry" for "Halloween in Derry", "2026 Giro d'Italia" for the 2027 one, or
    the whole season for "2027 Monaco Grand Prix"."""
    a, f = words(asked), words(found)
    if not f or len(f & a) < max(1, (2 * len(f) + 2) // 3):
        return False
    years = lambda s: set(re.findall(r"\b(?:19|20)\d\d\b", s))  # noqa: E731
    return not years(found) or years(found) == years(asked)


async def find_article(title: str) -> dict | None:
    """The article about this title: the page itself (or where it redirects, when that is still the same subject),
    else Wikipedia's search under the same condition."""
    hit = await summary(title)
    if hit is not None:
        return hit if same_subject(title, hit.get("title", "")) else None
    try:
        res = await net.fetch_json("wikipedia", API, {"action": "query", "list": "search", "srsearch": title,
                                                       "srlimit": 1, "format": "json"}, ttl_s=7 * net.DAY)
        found = ((res.get("query") or {}).get("search") or [{}])[0].get("title")
    except (net.ProviderError, AttributeError, IndexError):
        return None
    return await summary(found) if found and same_subject(title, found) else None


async def article_text(title: str, limit: int = 14000) -> str:
    """The article's plain text (what an answer about the place is grounded in); "" when unavailable."""
    try:
        data = await net.fetch_json("wikipedia", API, {"action": "query", "prop": "extracts", "explaintext": 1,
                                                       "redirects": 1, "titles": title, "format": "json"},
                                    ttl_s=7 * net.DAY)
    except net.ProviderError:
        return ""
    pages = ((data or {}).get("query") or {}).get("pages") or {}
    return next((p.get("extract") or "" for p in pages.values()), "")[:limit]


async def entity(qid: str) -> dict | None:
    """The Wikidata item: claims, sitelinks (one per language: how famous it is) and English / Arabic labels."""
    try:
        data = await net.fetch_json("wikidata", WIKIDATA, {"action": "wbgetentities", "ids": qid, "format": "json",
                                                          "props": "claims|sitelinks|labels", "languages": "en|ar"},
                                    ttl_s=7 * net.DAY)
    except net.ProviderError:
        return None
    return (data.get("entities") or {}).get(qid) if isinstance(data, dict) else None


def claim(item: dict, prop: str) -> list:
    return [c["mainsnak"].get("datavalue", {}).get("value") for c in item.get("claims", {}).get(prop, [])
            if c.get("mainsnak", {}).get("snaktype") == "value"]


def day(value) -> date | None:
    """A Wikidata time known to the day ('+2027-06-24T00:00:00Z', precision 11)."""
    if not isinstance(value, dict) or value.get("precision", 0) < 11:
        return None
    try:
        return date.fromisoformat(value["time"][1:11])
    except (KeyError, ValueError):
        return None
