"""Stable travel knowledge (RAG layer) from Wikivoyage.

City guide sections (Understand, Get around, Respect, Stay safe, Eat, ...), the phrasebook
for the country's language and emergency information are fetched from Wikivoyage (CC BY-SA),
chunked by paragraph and retrieved with BM25. Dynamic facts (prices, hours, weather) never
come from here - they come from the MCP tools.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from . import net

WIKIVOYAGE = "https://en.wikivoyage.org/w/api.php"
KEEP_SECTIONS = {"Understand": 1500, "Districts": 900, "Get around": 1800, "Talk": 800, "Eat": 1200, "Drink": 700,
                 "Respect": 1500, "Stay safe": 1600, "Cope": 900, "Stay healthy": 700, "Connect": 500}
EMERGENCY_RE = re.compile(r"[^.\n]*\b(emergenc|police|ambulance|fire brigade)[^.\n]*\b\d{2,4}\b[^.\n]*\.?", re.I)

_TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = set("a an the i we you to in on at of for and or is are do does did can should need my our it be with "
                "what how where when which there this that from by as if about any".split())


async def _extract(title: str) -> tuple[str, str]:
    data = await net.fetch_json("wikivoyage", WIKIVOYAGE, {"action": "query", "prop": "extracts", "explaintext": 1,
                                                          "titles": title, "format": "json", "redirects": 1},
                                ttl_s=30 * net.DAY)
    page = next(iter((data.get("query") or {}).get("pages", {}).values()), {})
    return page.get("title", title), page.get("extract", "") or ""


def _sections(text: str) -> tuple[str, dict[str, str]]:
    parts = re.split(r"\n== ([^=\n]+) ==\n", text)
    intro = parts[0].strip()
    sections = {}
    for name, body in zip(parts[1::2], parts[2::2]):
        name = name.strip()
        if name in KEEP_SECTIONS:
            body = re.sub(r"\n=== ?([^=\n]+) ?===\n", r"\n\1: ", body).strip()
            sections[name] = body[: KEEP_SECTIONS[name]]
    return intro, sections


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if 40 <= len(s.strip()) <= 240]


def _phrases(text: str, limit: int = 12) -> list[list[str]]:
    i = text.find("Basics")
    if i < 0:
        return []
    lines = [l.strip() for l in text[i:].split("\n")[1:] if l.strip() and not l.startswith("=")]
    pairs = []
    for en, local in zip(lines[0::2], lines[1::2]):
        if len(en) > 60 or len(local) > 120:
            break
        pairs.append([en.rstrip("."), local])
        if len(pairs) >= limit:
            break
    return pairs


async def destination_guide(city: str, country: str, languages: list[str]) -> dict[str, Any]:
    title, text = await _extract(city)
    if len(text) < 500 and country:
        title, text = await _extract(f"{city} ({country})")
    intro, sections = _sections(text)
    tips = []
    for name in ("Respect", "Stay safe", "Get around", "Cope"):
        tips += _sentences(sections.get(name, ""))[:3]
    emergency = [m.group(0).strip() for m in EMERGENCY_RE.finditer(sections.get("Stay safe", "") + "\n" + sections.get("Cope", ""))][:3]
    phrases: list[list[str]] = []
    phrasebook = None
    for lang in languages[:1]:
        if lang.lower() == "english":
            break
        pb_title, pb_text = await _extract(f"{lang} phrasebook")
        phrases = _phrases(pb_text)
        phrasebook = pb_title if phrases else None
    return {
        "source": "Wikivoyage (CC BY-SA)", "title": title,
        "source_url": f"https://en.wikivoyage.org/wiki/{title.replace(' ', '_')}" if text else None,
        "overview": intro[:900], "sections": sections, "local_tips": tips[:10], "phrases": phrases,
        "phrasebook": phrasebook, "emergency": emergency,
        "emergency_note": "112 connects to emergency services from any mobile phone in the EU and many other countries; "
                          "confirm the local numbers on arrival.",
    }


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def _stem(tok: str) -> str:
    for suffix in ("ing", "ed"):
        if tok.endswith(suffix) and len(tok) > len(suffix) + 2:
            tok = tok[: -len(suffix)]
            if len(tok) > 2 and tok[-1] == tok[-2]:
                tok = tok[:-1]
            return tok
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    if tok.endswith("s") and not tok.endswith("ss") and len(tok) > 3:
        return tok[:-1]
    return tok


def _tokens(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


def chunks(guide: dict[str, Any]) -> list[tuple[str, str]]:
    out = [("overview", guide.get("overview", ""))] if guide.get("overview") else []
    for name, body in (guide.get("sections") or {}).items():
        for para in re.split(r"\n+", body):
            if len(para) > 40:
                out.append((name, para))
    out += [("phrase", f"{en} - {local}") for en, local in guide.get("phrases") or []]
    out += [("emergency", e) for e in guide.get("emergency") or []]
    return out


def search(guide: dict[str, Any], query: str, top_k: int = 4) -> list[dict[str, Any]]:
    docs = chunks(guide)
    if not docs:
        return []
    tokenized = [_tokens(t) for _, t in docs]
    q = _tokens(query)
    n = len(docs)
    avgdl = sum(len(t) for t in tokenized) / n
    df = Counter(tok for toks in tokenized for tok in set(toks))
    scored = []
    for (kind, text), toks in zip(docs, tokenized):
        tf = Counter(toks)
        score = 0.0
        for term in q:
            if term in tf:
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * tf[term] * 2.2 / (tf[term] + 1.2 * (0.25 + 0.75 * len(toks) / max(avgdl, 1)))
        if score > 0:
            scored.append({"kind": kind, "text": text[:600], "score": round(score, 3)})
    scored.sort(key=lambda r: -float(r["score"]))
    return scored[:top_k]
