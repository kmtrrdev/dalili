"""Write the SEO travel guides (seo/guides/<slug>.json) from the Wikivoyage dataset, in English and Arabic.

The model writes ORIGINAL text grounded in each destination's guide (facts from the guide, our own wording): copying
Wikivoyage verbatim would be duplicate content for search engines, and its licence asks for attribution, which the
pages give. Existing files are skipped, so the script can be stopped and resumed.

    python scripts/build_guides.py               # all destinations
    python scripts/build_guides.py rome paris    # some
    python scripts/build_guides.py --force rome  # rewrite
"""

from __future__ import annotations

import asyncio
import csv
import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from travel_agent import llm  # noqa: E402

DATASET = ROOT / "ml" / "dataset"
OUT = ROOT / "seo" / "guides"
SECTIONS = ["Understand", "Climate", "Get in", "Get around", "See", "Do", "Eat", "Drink", "Buy", "Stay safe", "Respect",
            "Cope", "Talk"]
KEEP = {"Understand": 2500, "Climate": 1200, "Get around": 1800, "See": 5000, "Do": 2200, "Eat": 2500,
        "Stay safe": 1500, "Respect": 1000, "Buy": 800}
CONCURRENCY = 6


class Sight(BaseModel):
    name: str = Field(description="The sight's usual name")
    why: str = Field(description="One or two sentences: what it is and why it's worth it, with one practical tip")


class Food(BaseModel):
    name: str = Field(description="A local dish, drink or food experience")
    note: str = Field(description="One sentence about it")


class FAQ(BaseModel):
    q: str
    a: str = Field(description="2-3 sentences")


class GuideText(BaseModel):
    city_name: str = Field(description="The destination's name in this language")
    country_name: str = Field(description="Its country in this language")
    title: str = Field(description="SEO title, max 60 characters, includes the destination and 'travel guide'")
    meta_description: str = Field(description="Max 155 characters: what the page gives (sights, food, budget, itinerary)")
    h1: str = Field(description="Main heading, e.g. 'Rome travel guide: what to see, eat and know'")
    intro: list[str] = Field(description="2 short paragraphs introducing the destination for a first-time visitor")
    best_time: str = Field(description="When to go and why (seasons, weather, crowds), 2-3 sentences")
    top_sights: list[Sight] = Field(description="The 8 most important sights, most famous first")
    getting_around: str = Field(description="2-3 sentences on transport from the airport and in the city")
    food: list[Food] = Field(description="5 things to eat or drink")
    budget_tips: list[str] = Field(description="4 concrete money-saving tips")
    safety: list[str] = Field(description="3-4 safety and etiquette tips")
    itinerary: list[str] = Field(description="Exactly 3 entries: what to do on day 1, day 2 and day 3")
    faq: list[FAQ] = Field(description="5 questions travellers search for (e.g. how many days, is it expensive, "
                                       "is it safe, best area to stay, how to get from the airport)")


SYSTEM = """You write travel guide pages for Dalili, an AI travel planner, from a Wikivoyage guide you are given.
- Use ONLY facts from the guide text; never invent prices, opening hours, names or numbers. If the guide doesn't say
  something, write general, safe advice without specific figures.
- Write ORIGINAL sentences: never copy phrases from the guide. Friendly, clear, practical; no fluff, no emojis.
- Language: {language}. {style} Every field - including title, h1 and meta_description - is written entirely in
  {language} (only place names may add their English form in brackets).
- Optimise for search naturally: use the destination name and phrases people search ("things to do in X",
  "best time to visit X", "is X expensive"), but never keyword-stuff."""

STYLE = {
    "en": "Plain international English.",
    "ar": "Modern Standard Arabic that reads naturally for Arab travellers (people search in MSA); keep well-known "
          "place names recognisable, adding the English name in brackets the first time when helpful.",
}


def sections(text: str) -> dict[str, str]:
    """Split the cleaned guide into its sections (headings are lines of their own)."""
    body = text.split("=====", 2)[-1] if "=====" in text else text
    body = body.split("===== TOKENS", 1)[0]
    out, current, buf = {"Intro": ""}, "Intro", []
    for line in body.splitlines():
        s = line.strip()
        if s in SECTIONS:
            out[current] = "\n".join(buf).strip()
            current, buf = s, []
        elif s and not s.startswith("====="):
            buf.append(s)
    out[current] = "\n".join(buf).strip()
    return out


def guide_input(row: dict) -> str:
    text = (DATASET / "guides" / f"{row['id']}.txt").read_text(encoding="utf-8")
    sec = sections(text)
    parts = [f"Destination: {row['name']}, {row['country']}", "Intro:\n" + sec.get("Intro", "")[:2000]]
    for name, limit in KEEP.items():
        if sec.get(name):
            parts.append(f"{name}:\n{sec[name][:limit]}")
    return "\n\n".join(parts)


async def write_one(row: dict, sem: asyncio.Semaphore, force: bool) -> str:
    path = OUT / f"{row['id']}.json"
    if path.exists() and not force:
        return f"skip {row['id']}"
    async with sem:
        src = guide_input(row)
        langs = {}
        for lang, language in (("en", "English"), ("ar", "Arabic")):
            text = await llm.parse(SYSTEM.format(language=language, style=STYLE[lang]), src, GuideText, effort="low")
            if text is None or len(text.top_sights) < 4 or len(text.itinerary) < 3:
                return f"FAILED {row['id']} ({lang}): {llm.last_error or 'invalid output'}"
            langs[lang] = text.model_dump()
    doc = {"slug": row["id"], "name": row["name"], "country": row["country"], "tags": row["tags"].split(),
           "source_url": row["source_url"], **langs}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return f"ok {row['id']}"


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    with open(DATASET / "destinations.csv", encoding="utf-8-sig") as f:  # the file starts with a BOM
        rows = [r for r in csv.DictReader(f) if not args or r["id"] in args]
    if not llm.available():
        sys.exit("No model configured (AZURE_AI_KEY / AZURE_AI_ENDPOINT in .env).")
    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0
    for coro in asyncio.as_completed([write_one(r, sem, force) for r in rows]):
        msg = await coro
        done += 1
        print(f"[{done}/{len(rows)}] {msg}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
