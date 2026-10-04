"""Training text: the Wikivoyage guide of each destination, cleaned and tokenised (no NLP library).

Only the sections that describe what a place is like are kept (Understand, See, Do, Buy, Eat, Drink);
logistics (Get in, Sleep, Connect...) read the same everywhere and would only add noise. Place and
country names are removed so the model learns what a place *feels* like, not where it is.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata

from .. import net
from .catalog import Destination

WIKIVOYAGE = "https://en.wikivoyage.org/w/api.php"
KEEP = {"Understand", "See", "Do", "Buy", "Eat", "Drink"}
MAX_TOKENS = 6000

STOPWORDS = set("""
a about above after again against all almost also although always am among an and any are around as at be
became because been before being below between both but by can could did do does doing done down during each
either else even ever every few for from further get gets getting go goes going gone got had has have having he
her here hers herself him himself his how however i if in into is it its itself just least less like made make
makes many may me might more most much must my myself near need never new next no nor not now of off often on
once one only or other others otherwise our ours ourselves out over own per perhaps quite rather really same
see seen several she should since so some something sometimes still such than that the their theirs them
themselves then there these they this those though through thus to too toward towards under until up upon us
use used using usually very via was way we well were what whatever when where whether which while who whom
whose why will with within without would yet you your yours yourself yourselves de la el le del los las di da
two three four five six seven eight nine ten first second third st km m pm am mon tue wed thu fri sat sun
jan feb mar apr jun jul aug sep sept oct nov dec january february march april june july august september
october november december daily open closed hours tel fax email www http https com org html us eur usd
also available along across away back best better big come day days end find free full good great high including
just large long lot lots main many much number part people place places right small take time top town city
well year years area areas local located location left known various several well different few whole
understand eat drink buy north south east west northern southern eastern western central name found
try visit visitor visitors tourist tourists popular include includes including offer offers center centre
jpg jpeg png svg gif file thumb thumbnail upright gallery caption px image images alt denoted
""".split())

_TOKEN = re.compile(r"[a-z]+(?:'[a-z]+)?")


def normalise(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def tokenize(text: str, banned: set[str] = frozenset()) -> list[str]:
    """Lowercase words, no stopwords, no names of places, no 1-2 letter fragments, simple plural folding."""
    out = []
    for w in _TOKEN.findall(normalise(text)):
        w = w.replace("'s", "").replace("'", "")
        if len(w) < 3 or w in STOPWORDS or w in banned:
            continue
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 5 and w.endswith(("ches", "shes", "sses", "xes", "zes")):
            w = w[:-2]
        elif len(w) > 4 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
            w = w[:-1]
        out.append(w)
    return out


def banned_words(catalog: list[Destination]) -> set[str]:
    words: set[str] = set()
    for d in catalog:
        for name in (d.name, d.country, d.wikivoyage):
            words |= {w for w in re.findall(r"[a-z]+", normalise(name)) if len(w) >= 3}
    return words - {"lake", "national", "park", "island", "islands", "bay", "desert", "sea", "falls", "riviera",
                    "highland", "highlands", "coast", "city", "dead", "great", "barrier", "reef", "grand", "canyon",
                    "new", "oasis", "valley"}


def keep_sections(text: str) -> str:
    parts = re.split(r"\n==+ *([^=\n]+?) *==+\n", "\n" + text)
    kept = [parts[0]]
    current = None
    for i in range(1, len(parts) - 1, 2):
        head, body = parts[i].strip(), parts[i + 1]
        if head in KEEP or head.split(" ")[0] in KEEP:
            current = head
        elif re.match(r"^(Get in|Get around|Sleep|Connect|Stay safe|Stay healthy|Cope|Go next|Respect|Talk|"
                      r"Districts|Regions|Cities|Other destinations|Learn|Work|Climate|Contact)", head):
            current = None
        if current:  # sub-headings ("Museums", "Beaches") stay with the section they belong to
            kept.append(head + "\n" + body)
    return "\n".join(kept)


BATCH = 50  # the MediaWiki API returns the text of up to 50 pages in one request

LISTING = re.compile(r"^\s*(see|do|eat|drink|buy|sleep|go|listing|marker)\s*\|", re.I)


def _template(body: str) -> str:
    """Replace one innermost {{template}}: a listing keeps its name and description, anything else goes."""
    if LISTING.match(body):
        params = {}
        for part in body.split("|")[1:]:
            k, _, v = part.partition("=")
            params[k.strip().lower()] = v.strip()
        return f"\n{params.get('name', '')}. {params.get('content', '')}\n"
    return ""


def wikitext_to_text(src: str) -> str:
    """Plain text from wikitext (headings kept, so keep_sections can still split the guide)."""
    s = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    s = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", " ", s, flags=re.S | re.I)
    # Links first: "[[castle|fortress]]" inside a listing would otherwise split its parameters at the "|".
    s = re.sub(r"\[\[(?:File|Image):[^\[\]]*(?:\[\[[^\]]*\]\][^\[\]]*)*\]\]", " ", s, flags=re.I)
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
    for _ in range(8):  # innermost templates first, until none are left
        s, n = re.subn(r"\{\{([^{}]*)\}\}", lambda m: _template(m.group(1)), s)
        if not n:
            break
    s = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", s)
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\{\||\|\}|^\s*[|!].*$", " ", s, flags=re.M)  # table markup
    return s


async def fetch_guides(titles: list[str]) -> dict[str, str]:
    """Plain text of many guides, BATCH per request (cached 120 days): title as asked -> text ("" if missing).
    Few, large requests keep well inside Wikimedia's rate limits."""
    out: dict[str, str] = {}
    for i in range(0, len(titles), BATCH):
        chunk = titles[i:i + BATCH]
        params = {"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                  "titles": "|".join(chunk), "format": "json", "formatversion": 2, "redirects": 1}
        for attempt in range(4):
            try:
                data = await net.fetch_json("wikivoyage", WIKIVOYAGE, params, ttl_s=120 * net.DAY)
                break
            except net.ProviderError as exc:
                if "429" not in str(exc) or attempt == 3:
                    raise
                await asyncio.sleep(30 * (attempt + 1))
        q = data.get("query") or {}
        alias = {x["from"]: x["to"] for x in (q.get("normalized") or []) + (q.get("redirects") or [])}
        pages = {p["title"]: ((p.get("revisions") or [{}])[0].get("slots") or {}).get("main", {}).get("content", "")
                 for p in q.get("pages", [])}
        for t in chunk:
            final = t
            for _ in range(3):
                final = alias.get(final, final)
            out[t] = wikitext_to_text(pages.get(final, "") or "")
    return out


WIKIPEDIA = "https://en.wikipedia.org/w/api.php"


async def fetch_banners(titles: list[str], wiki: str = "wikivoyage") -> dict[str, str]:
    """The lead photo of each guide (Wikivoyage picks a travel photo, not a map or flag): title -> 640px image URL.
    Only JPEG photos count (maps, flags and logos are SVG / PNG)."""
    out: dict[str, str] = {}
    api = WIKIVOYAGE if wiki == "wikivoyage" else WIKIPEDIA
    for i in range(0, len(titles), BATCH):
        chunk = titles[i:i + BATCH]
        try:
            data = await net.fetch_json(wiki, api, {
                "action": "query", "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 640, "pilimit": BATCH,
                "titles": "|".join(chunk), "format": "json", "formatversion": 2, "redirects": 1}, ttl_s=120 * net.DAY)
        except net.ProviderError:
            continue
        q = data.get("query") or {}
        alias = {x["from"]: x["to"] for x in (q.get("normalized") or []) + (q.get("redirects") or [])}
        thumbs = {p["title"]: (p.get("thumbnail") or {}).get("source") for p in q.get("pages", [])}
        for t in chunk:
            final = t
            for _ in range(3):
                final = alias.get(final, final)
            src = thumbs.get(final)
            if src and re.search(r"\.jpe?g", src, re.I):
                out[t] = src
    return out


async def fetch_guide(title: str) -> str:
    return (await fetch_guides([title])).get(title, "")


async def build(catalog: list[Destination]) -> dict[str, list[str]]:
    """id -> tokens, for every destination (empty when its guide could not be fetched)."""
    banned = banned_words(catalog)
    texts = await fetch_guides([d.wikivoyage for d in catalog])
    return {d.id: tokenize(keep_sections(texts.get(d.wikivoyage, "")), banned)[:MAX_TOKENS] for d in catalog}


def tokens_for_text(text: str, catalog: list[Destination]) -> list[str]:
    """Tokens of a new guide (a city outside the catalog), cleaned exactly like the training text."""
    return tokenize(keep_sections(text), banned_words(catalog))[:MAX_TOKENS]
