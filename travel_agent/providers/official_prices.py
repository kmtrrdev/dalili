"""Prices from the place's own website (free - no SerpApi credits).

Google Maps gives most sights and many restaurants an official website. The price is rarely on the home
page, but the home page links to it ("Tickets", "Horários e preços", "Tarifários 2026", "Biglietti",
"Menu", "Carta"...). We follow the best such link on the same site, turn the pages into text, and the model
extracts:
  - attractions: the standard ADULT entry price;
  - restaurants: the typical main-course price range from the menu.
Every value must come with a verbatim quote that is really on the page and contains the number, or it is
dropped. Pages rendered by JavaScript, PDFs and images yield nothing - never a guess.
"""

from __future__ import annotations

import html as htmllib
import json
import logging
import re
from typing import Literal
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field

from .. import llm, net
from .local_prices import _squash

log = logging.getLogger(__name__)

TICKET_WORDS = r"ticket|tarif|price|prices|pricing|admission|entrance|entry|fees|preco|precos|preço|preços|precio|" \
               r"precios|entradas|prezzi|prezzo|biglietti|biglietto|billet|billets|tarifs|eintritt|preise|fiyat|bilet|" \
               r"bilhete|bilheteira|taquilla|visit|plan-your-visit|opening|horarios|orari"
MENU_WORDS = r"menu|menú|carta|speisekarte|carte|menù|food|dishes|our-menu"
# A number next to a currency: symbols need no word boundary ("17€" at a line end), codes do ("20 EUR", not "TLS").
CURRENCY_NUM = re.compile(r"(?:€|£|\$|₺|Kč|zł|\b(?:EUR|GBP|USD|TL|LE|EGP|AED|SAR|CHF|CZK|kr)\b)\s?\d"
                          r"|\d[\d.,]*\s?(?:€|£|\$|₺|Kč|zł|(?:EUR|GBP|USD|TL|LE|EGP|AED|SAR|CHF|CZK|kr)\b)", re.I)


def page_text(html: str, limit: int = 20000) -> str:
    """Visible text of an HTML page (scripts, styles and tags removed)."""
    t = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmllib.unescape(t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()[:limit]


def _same_site(a: str, b: str) -> bool:
    ha, hb = (urlparse(a).hostname or "").lower(), (urlparse(b).hostname or "").lower()
    base = lambda h: ".".join(h.split(".")[-2:])  # noqa: E731 - registered domain, roughly
    return bool(ha and hb) and base(ha) == base(hb)


def price_links(html: str, base_url: str, kind: str, limit: int = 2) -> list[str]:
    """The same-site links most likely to hold prices (tickets / menu), best first."""
    words = MENU_WORDS if kind == "restaurant" else TICKET_WORDS
    scored: dict[str, int] = {}
    for m in re.finditer(r'<a\b[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        href, label = m.group(1).strip(), re.sub(r"<[^>]+>", " ", m.group(2))
        url = urljoin(base_url, href)
        if not url.startswith("http") or not _same_site(url, base_url) or url.lower().endswith((".pdf", ".jpg", ".png")):
            continue
        text = f"{href} {label}".lower()
        score = len(re.findall(words, text))
        if re.search(r"price|pre[cç]o|precio|prezz|tarif|preise|fiyat|menu|menú|carta", text):
            score += 2  # strongest words
        if score:
            scored[url] = max(scored.get(url, 0), score)
    return [u for u, _ in sorted(scored.items(), key=lambda kv: -kv[1])][:limit]


class OfficialPrice(BaseModel):
    found: bool = Field(description="True only if the text states the price asked for")
    amount: float | None = Field(default=None, description=(
        "Attraction: the standard adult entry price. Restaurant: the LOWEST typical main-course price"))
    amount_max: float | None = Field(default=None, description="Restaurant only: the HIGHEST typical main-course price")
    currency: str | None = Field(default=None, description="ISO code, e.g. EUR")
    quote: str | None = Field(default=None, description="The exact text fragment stating the (lowest) price, verbatim")
    quote_max: str | None = Field(default=None, description="Restaurant only: the exact fragment stating the highest price")
    what: str = Field(default="", description="What the price is for, e.g. 'adult ticket 2026', 'mains'")
    free: bool = Field(default=False, description="True if entry is explicitly free for adults")


SYSTEM = {
    "attraction": (
        "You read an official website of a tourist attraction. Find the STANDARD ADULT entry ticket price for a "
        "regular visit (not child, senior, student, family, group, guided-tour or combo prices). Copy the exact "
        "fragment of the text that states it into 'quote', verbatim. If the text states free entry for adults, set "
        "free=true. If the text doesn't state an adult price, found=false. Never use outside knowledge."),
    "restaurant": (
        "You read a restaurant's website/menu page. From the MAIN COURSES (mains / pratos principais / secondi / "
        "platos principales), give the lowest and highest typical price, each with its exact verbatim fragment. "
        "Ignore drinks, desserts and set menus unless there are no mains. If no menu prices are on the page, "
        "found=false. Never use outside knowledge."),
}


def _num_in(quote: str, amount: float) -> bool:
    nums = []
    for n in re.findall(r"\d[\d.,]*", quote):
        n = n.rstrip(".,")
        if re.fullmatch(r"\d{1,3}([.,]\d{3})+", n):
            n = re.sub(r"[.,]", "", n)
        try:
            nums.append(float(n.replace(",", ".")))
        except ValueError:
            pass
    return any(abs(x - amount) < 0.01 for x in nums)


REDUCED = re.compile(r"child|kid|infant|senior|s[ée]nior|student|estudante|estudiante|studente|jovem|joven|youth|junior|"
                     r"crian[çc]a|ni[ñn]o|bambin|ridott|reduc|reduz|family|fam[ií]lia|group|grupo|school|escola", re.I)
ADULT = re.compile(r"adult|adulto|adulte|erwachsen|general|normal|standard|full|inteiro|intero|entero|individual", re.I)


def verify(out: OfficialPrice, text: str, kind: str) -> OfficialPrice | None:
    """Keep the extraction only if every stated number is quoted verbatim from the page (and, for a ticket,
    the quote isn't a child / senior / student / family price)."""
    src = _squash(text)
    if kind == "attraction" and out.quote and REDUCED.search(out.quote) and not ADULT.search(out.quote):
        return None
    if out.free and kind == "attraction" and out.quote and len(out.quote) >= 8 and _squash(out.quote) in src:
        return out.model_copy(update={"amount": 0.0})
    if not out.found or not out.amount or out.amount <= 0 or not out.quote or not out.currency:
        return None
    if len(out.quote.strip()) < 3 or _squash(out.quote) not in src or not _num_in(out.quote, out.amount):
        return None
    if kind == "restaurant" and out.amount_max:
        if not out.quote_max or _squash(out.quote_max) not in src or not _num_in(out.quote_max, out.amount_max) \
                or out.amount_max < out.amount:
            out = out.model_copy(update={"amount_max": None, "quote_max": None})
    return out


async def official_price(name: str, kind: Literal["attraction", "restaurant"], website: str) -> dict | None:
    """{amount, amount_max?, currency, quote, page, what, free} from the place's own website, or None."""
    if not llm.available() or not website:
        return None
    try:
        home = await net.fetch_page(website)
    except net.ProviderError as exc:
        log.info("official site %s unavailable: %s", website, exc)
        return None
    pages = [(home["url"], page_text(home["html"]))]
    for link in price_links(home["html"], home["url"], kind):
        try:
            p = await net.fetch_page(link)
            pages.insert(0, (p["url"], page_text(p["html"])))  # the price page first
        except net.ProviderError:
            continue
    for url, text in pages:
        if len(text) < 80 or not CURRENCY_NUM.search(text):
            continue  # no price on this page (or a JavaScript-only page)
        out = await llm.parse(SYSTEM[kind], json.dumps({"place": name, "page": url, "text": text[:14000]},
                                                       ensure_ascii=False), OfficialPrice)
        good = verify(out, text, kind) if out else None
        if good:
            return {"amount": good.amount, "amount_max": good.amount_max, "currency": (good.currency or "").upper(),
                    "quote": good.quote, "quote_max": good.quote_max, "what": good.what, "free": good.free, "page": url}
    return None
