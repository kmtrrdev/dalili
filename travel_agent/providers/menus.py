"""Restaurant menus from a web search: a link to the menu and the price of a typical meal per person.

When neither Google Maps, Wikivoyage nor the restaurant's own site states its prices, we search Google for its
menu ("<name> <city> menu prices"), read the result snippets and the best menu page, and the model works out what a
normal meal costs one person there: a main course and a soft drink (for a café: a drink and a pastry), from the
prices it can actually see. At least two of those prices must be quoted verbatim from the sources, and the menu link
must be one of the search results - otherwise nothing is returned and the place keeps its estimate.
One SerpApi search per restaurant, cached for 30 days.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import quote_plus

from pydantic import BaseModel, Field

from .. import llm, net
from .local_prices import _squash
from .official_prices import CURRENCY_NUM, _num_in, page_text

log = logging.getLogger(__name__)

MENU_HINT = ("menu", "menü", "carta", "price", "fiyat", "prices")


class PricedItem(BaseModel):
    item: str = Field(description="Dish or drink name")
    price: float
    quote: str = Field(description="The exact fragment of the sources stating this price, verbatim")


class MenuEstimate(BaseModel):
    found: bool = Field(description="True only if real menu prices for THIS restaurant are in the sources")
    menu_url: str | None = Field(default=None, description="The source link that best shows this restaurant's menu")
    currency: str | None = Field(default=None, description="ISO code of the menu prices, e.g. TRY")
    items: list[PricedItem] = Field(default_factory=list, description="The prices you based the meal on (2-6)")
    meal_per_person: float | None = Field(default=None, description=(
        "What one person typically pays for a normal meal there: one main course + one soft drink (café: a hot "
        "drink + a pastry or light dish), in the menu currency"))
    basis: str = Field(default="", description="Short: how the meal price was formed, e.g. 'main ~450 + drink 80'")


SYSTEM = (
    "You get web search results (and possibly one menu page) about ONE restaurant, with its address. Use only "
    "sources about THIS restaurant at THIS address - a place with a similar name in another district or city (or "
    "another branch) is a different restaurant: ignore it. Use only prices in ONE currency (the local one), never "
    "mixing currencies. From those prices only (no outside knowledge), work out what a normal meal "
    "costs one person: one typical main course + one soft drink (for a café: a hot drink + a pastry or light dish). "
    "Use mid-range dishes, not the cheapest side or the most expensive platter. Skip prices marked as old (years "
    "before 2024). List the prices you used in 'items', each with its verbatim quote. Pick 'menu_url' from the "
    "given links: the one that best shows the menu. If the sources have no real prices for this restaurant, "
    "found=false.")


def _url(v) -> str | None:
    """A knowledge-panel link: a dict with 'link', or a bare domain like 'lotusrestaurantcafe.com'."""
    v = v.get("link") if isinstance(v, dict) else v
    if not isinstance(v, str) or not v.strip() or " " in v.strip():
        return None
    return v if v.startswith("http") else f"https://{v.strip()}"


def _same_place(a: str, b: str) -> bool:
    a, b = _squash(a), _squash(b)
    return bool(a and b) and (a in b or b in a)


async def menu_price(name: str, city: str, kind: str = "restaurant", address: str = "",
                     local_currency: str = "USD") -> dict | None:
    """{amount, currency, menu_url, basis, google} or None when no real menu prices are found."""
    from .places import parse_price

    area = ", ".join(p.strip() for p in address.split(",")[1:3] if p.strip()) or city  # district, city
    try:
        data = await net.serpapi("google", 30 * net.DAY, q=f"{name} {area} menu", hl="en", num=8)
    except net.ProviderError as exc:
        log.info("menu search %s: %s", name, exc)
        return None
    kg = data.get("knowledge_graph") or {}
    menu_link = _url(kg.get("menu")) if _same_place(kg.get("title", ""), name) else None
    # No menu site in Google's panel: a Google search for this restaurant's menu (photos, delivery apps, reviews).
    menu_link = menu_link or "https://www.google.com/search?q=" + quote_plus(f"{name} {area} menu")
    # Google's own panel for this restaurant: its price range per person ("₺600–1,400") and its menu link.
    if _same_place(kg.get("title", ""), name) and kg.get("price"):
        amount, cur, _ = parse_price(str(kg["price"]), local_currency)
        if amount:
            return {"amount": round(amount, 2), "currency": cur, "menu_url": menu_link,
                    "basis": f"{kg['price']} per person", "google": True}
    if not llm.available():
        return None
    results = [{"link": r.get("link"), "title": r.get("title", ""), "snippet": r.get("snippet", ""),
                "extra": " ".join(str(v) for v in (r.get("rich_snippet") or {}).values())[:400]}
               for r in (data.get("organic_results") or [])[:8] if r.get("link")]
    links = {r["link"] for r in results}
    if menu_link:
        links.add(menu_link)
    sources = json.dumps({"knowledge_panel": {k: kg.get(k) for k in ("title", "price", "menu", "address") if kg.get(k)},
                          "results": results}, ensure_ascii=False, default=str)
    # The best-looking menu page, read in full (many menu sites list every dish with its price).
    page = ""
    for url in [menu_link] + [r["link"] for r in results if any(h in (r["link"] + r["title"]).lower() for h in MENU_HINT)]:
        if not isinstance(url, str):
            continue
        try:
            text = page_text((await net.fetch_page(url))["html"], 12000)
        except net.ProviderError:
            continue
        if CURRENCY_NUM.search(text):
            page = f"\n\nMENU PAGE {url}:\n{text}"
            break
    corpus = sources + page
    if not CURRENCY_NUM.search(corpus):
        return None
    out = await llm.parse(SYSTEM, json.dumps({"restaurant": name, "address": address or city, "type": kind,
                                              "local_currency": local_currency}, ensure_ascii=False)
                          + "\n\nSOURCES:\n" + corpus[:20000], MenuEstimate, effort="low")
    if out is None or not out.found or not out.meal_per_person or out.meal_per_person <= 0 or not out.currency:
        return None
    src = _squash(corpus)
    quoted = [i for i in out.items if i.price > 0 and _squash(i.quote) in src and _num_in(i.quote, i.price)]
    if len(quoted) < 2:
        log.info("menu %s: prices not quoted from the sources, dropped", name)
        return None
    # The meal must be built from what was seen: between the cheapest quoted item and a few dishes' worth.
    lo, hi = min(i.price for i in quoted), max(i.price for i in quoted)
    if not lo <= out.meal_per_person <= hi * 3:
        return None
    url = out.menu_url if out.menu_url in links else menu_link
    return {"amount": round(out.meal_per_person, 2), "currency": out.currency.upper(), "menu_url": url,
            "basis": out.basis[:80] or ", ".join(f"{i.item} {i.price:g}" for i in quoted[:3]), "google": False}
