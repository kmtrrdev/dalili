"""Turn understanding: chat message -> structured requirements / feedback / replan actions.

Two interchangeable implementations produce the same `TurnInterpretation`:
- Claude (structured outputs) when credentials are configured;
- a deterministic rule-based parser otherwise (also used by tests and evals).
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from . import llm
from .config import settings
from .config import today as _today


# ---------------------------------------------------------------------------
# Schema (shared by both interpreters; kept flat for structured outputs)
# ---------------------------------------------------------------------------

Intent = Literal["plan_request", "update_requirements", "feedback", "question", "smalltalk", "off_topic"]

# What Dalili talks about. Shared by every prompt that can answer the traveller, so the scope is the same everywhere.
SCOPE_RULE = """Scope: you are a travel planner. In scope: trips and destinations - flights, hotels, restaurants and food,
sights, events, transport, weather, budget and prices, currency, visas and entry rules, safety, local customs,
language tips, packing, and anything else about travelling or about places to visit (e.g. a football match or a
stadium tour in the city the traveller visits is in scope). Out of scope: general knowledge, people and celebrities,
sports results, news, politics, coding, homework, health or legal advice not about travel, and anything else not about
travelling. Greetings and thanks are fine."""
ActionName = Literal[
    "reduce_density", "increase_density", "more_free_time", "later_start", "cheaper", "upgrade", "more_food",
    "fewer_category", "more_category", "avoid_noise", "change_hotel", "change_flight", "extend_trip", "shorten_trip",
    "set_budget", "adjust_budget", "less_walking", "more_nightlife", "prefer_hidden_gems", "replace_item",
    "weather_adjust", "select_mode", "add_place", "choose_flight",
]


class Requirements(BaseModel):
    origin_city: str | None = Field(default=None, description=(
        "Where the traveller departs from, as a city or country in English "
        "(e.g. 'from Saudi Arabia' / 'من السعودية' -> 'Saudi Arabia', 'flying out of Jeddah' -> 'Jeddah')"))
    origin_airport: str | None = Field(default=None, description="IATA code, e.g. CAI")
    return_to: str | None = Field(default=None, description=(
        "Only when the trip should END in a different city than it starts (open-jaw): the city to fly home to, in "
        "English. 'from Riyadh to Istanbul, then back to Cairo' / 'ارجع على القاهرة' -> 'Cairo'. Not a destination: "
        "no nights there."))
    rooms: int | None = Field(default=None, description=(
        "Hotel rooms, only if the traveller says: 'all three in one room' / 'في غرفة واحدة' -> 1, 'two rooms' -> 2"))
    destination: str | None = Field(default=None, description="City name")
    destinations: list[str] = Field(default_factory=list, description=(
        "Multi-city / multi-country trip only: every city or country the user wants to visit, in visit order "
        "(e.g. ['Italy', 'France', 'Spain']). Empty for a single-destination trip."))
    nights_per_destination: list[int] = Field(default_factory=list, description=(
        "Only if the user said how long to stay in each place: nights per entry of destinations, same order."))
    region: str | None = Field(default=None, description=(
        "A region instead of countries/cities, when the user wants you to choose (e.g. 'Europe', 'Southeast Asia')."))
    start_date: str | None = Field(default=None, description="YYYY-MM-DD")
    end_date: str | None = Field(default=None, description="YYYY-MM-DD, last day of the trip")
    duration_days: int | None = Field(default=None, description=(
        "Total trip length in DAYS when the traveller states it in days ('a week' -> 7, 'خليها 4 أيام' -> 4)"))
    nights: int | None = Field(default=None, description=(
        "Total trip length in NIGHTS when the traveller states it in nights ('3 nights' / 'خليهم تلت ليالي' -> 3). "
        "Absolute, never a difference: the code computes the dates. If they give both ('3 nights, 4 days'), "
        "nights wins."))
    travel_month: int | None = Field(default=None, description=(
        "1-12, only when the user names a month without exact dates (e.g. 'in November' / 'في نوفمبر')"))
    travelers: int | None = None
    budget_amount: float | None = None
    budget_currency: str | None = Field(default=None, description="ISO code: USD, EUR, EGP, ...")
    budget_is_hard_limit: bool | None = None
    wants_cheapest: bool | None = Field(default=None, description=(
        "True when the traveller wants the cheapest possible trip or asks what the minimum cost is, instead of (or "
        "without) giving a budget: 'cheapest budget possible', 'أرخص بادجت ممكن', 'start from how much?', 'هتبدأ من كام', "
        "'what's the least I can spend'"))
    must_have: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    must_visit: list[str] = Field(default_factory=list, description=(
        "Specific, named places the user firmly wants (e.g. 'Vatican Museums', 'Pyramids of Giza', 'Sagrada "
        "Familia'), in English: 'I must see', 'I want to visit', 'لازم', 'عايز ازور'. Not categories like 'museums' and "
        "not the destination city itself."))
    wish_list: list[str] = Field(default_factory=list, description=(
        "Named places mentioned softly - 'maybe', 'if there is time', 'would be nice', 'لو فيه وقت', 'ممكن' - in "
        "English. Planned when they fit, never at the cost of other plans. Never also in must_visit."))
    priorities: list[Literal["cost", "time_in_city", "comfort", "sights", "food", "less_walking", "relaxed_schedule"]] = \
        Field(default_factory=list, description=(
            "Only what the traveller SAYS matters most, most important first ('the cheaper the better' -> cost, "
            "'I want as much time there as possible' -> time_in_city, 'comfort matters most' -> comfort). Empty if "
            "they don't say."))
    travel_style: Literal["relaxed", "moderate", "active", "very_active"] | None = None
    food_preferences: list[str] = Field(default_factory=list, description="Lowercase cuisines, e.g. italian, seafood")
    dietary_restrictions: list[str] = Field(default_factory=list, description="vegetarian, vegan, ...")
    activity_preferences: list[str] = Field(default_factory=list, description=(
        "history, art, museums, food, photography, shopping, nightlife, nature, relaxation, romantic, architecture, "
        "family, beach (use 'beach' when the user loves the sea, swimming, snorkelling, diving or beaches)"))
    avoid_categories: list[str] = Field(default_factory=list)
    walking_tolerance: Literal["low", "medium", "high"] | None = None
    transport_preference: Literal["walk", "mixed", "public_transport", "taxi"] | None = Field(default=None, description=(
        "How the traveller likes to get around between sights: walk, mixed (walk nearby, transport for far), "
        "public_transport or taxi"))
    preferred_wake_up_time: str | None = Field(default=None, description="HH:MM")
    hotel_style: str | None = None
    min_hotel_stars: float | None = None
    direct_flights_only: bool | None = None
    avoid_early_flights: bool | None = None
    nightlife_interest: Literal["low", "medium", "high"] | None = None
    noise_tolerance: Literal["low", "medium", "high"] | None = None
    prefer_hidden_gems: bool | None = None
    planning_mode: Literal["balanced", "budget", "comfort", "experience"] | None = None


class FeedbackNote(BaseModel):
    feedback_type: Literal["hotel", "flight", "restaurant", "activity", "itinerary", "budget", "general"]
    entity_name: str | None = None
    sentiment: Literal["positive", "negative", "neutral"] = "neutral"
    attribute: str | None = None
    severity: float = 0.5


class Action(BaseModel):
    action: ActionName
    category: str | None = None
    day: int | None = Field(default=None, description="1-based trip day, if the user named one")
    amount: float | None = Field(default=None, description="Numeric value: budget amount/delta, days, count")
    text: str | None = Field(default=None, description="Free value: wake-up time HH:MM, item name, mode name")


class TurnInterpretation(BaseModel):
    intent: Intent
    requirements: Requirements = Field(default_factory=Requirements)
    feedback: list[FeedbackNote] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    question: str | None = None
    route_change_request: str | None = Field(default=None, description=(
        "Only when a plan already exists and the user wants to change the ROUTE itself: add or drop a city/region where "
        "they will SPEND NIGHTS, move nights between cities or change the order (e.g. 'add a few days in Sharm El "
        "Sheikh'). Summarise the request in English. Not for changes inside a day, and NOT for flying home to a "
        "different city with no stay there - that is requirements.return_to."))
    route_decision: Literal["accept", "change"] | None = Field(default=None, description=(
        "Only when a route proposal is pending (see context): 'accept' if the user agrees or lets you decide, "
        "'change' if they want something different (cities, nights, order, adding/dropping a place)."))
    hypothetical: bool = Field(default=False, description=(
        "True when the change is a question to compare, not to apply yet: 'what if my budget were $500 more?', "
        "'لو زودت الميزانية 500 هيحصل ايه؟', 'how much would it cost with 2 more days?'"))
    apply_pending: bool = Field(default=False, description=(
        "True when the user accepts the what-if comparison the assistant just showed ('apply it', 'تمام نفذها')"))
    source: str = "rules"


# ---------------------------------------------------------------------------
# Rule-based interpreter
# ---------------------------------------------------------------------------

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9
NUM_WORDS = {"one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
             "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "couple": 2}
CURRENCY_WORDS = {"$": "USD", "usd": "USD", "dollar": "USD", "dollars": "USD", "€": "EUR", "eur": "EUR", "euro": "EUR",
                  "euros": "EUR", "£": "GBP", "gbp": "GBP", "egp": "EGP", "le": "EGP", "egyptian pounds": "EGP",
                  "pounds": "GBP", "try": "TRY", "lira": "TRY", "sar": "SAR", "riyal": "SAR", "aed": "AED", "dirham": "AED"}

INTEREST_WORDS = {
    "food": ["food", "foodie", "eat", "culinary", "cuisine", "gastronom"],
    "photography": ["photo", "camera", "instagram"],
    "museums": ["museum"],
    "art": ["art ", "arts", "painting", "gallery", "galleries"],
    "history": ["history", "historic", "ancient", "ruins"],
    "culture": ["culture", "cultural", "local life"],
    "shopping": ["shopping", "shop", "market"],
    "nightlife": ["nightlife", "bars", "party", "clubbing"],
    "nature": ["nature", "park", "garden", "outdoors"],
    "relaxation": ["relax", "chill", "slow travel", "unwind"],
    "beach": ["beach", "the sea", "swimming", "snorkel", "diving", "seaside"],
    "romantic": ["romantic", "honeymoon", "anniversary"],
    "architecture": ["architecture", "buildings", "churches", "mosques"],
    "family": ["kids", "children", "family"],
    "music": ["music", "jazz", "concert"],
}
CUISINES = ["italian", "french", "turkish", "seafood", "pizza", "street food", "kebab", "meze", "vegan", "vegetarian",
            "coffee", "dessert", "gelato", "baklava", "wine", "steak", "middle eastern", "ottoman", "roman"]


def _num(tok: str) -> int | None:
    tok = tok.lower().strip()
    if tok.isdigit():
        return int(tok)
    return NUM_WORDS.get(tok)


NOT_PLACES = set(MONTHS) | {"the", "a", "an", "my", "our", "me", "us", "i", "we", "you", "it", "this", "that", "next", "early",
                               "late", "october", "summer", "winter", "spring", "autumn", "fall", "week", "weekend", "days",
                               "day", "budget", "total", "two", "three", "four", "hi", "hello", "please", "make", "remove",
                               "add", "what", "how", "cheaper", "more", "less", "trip", "holiday", "vacation", "travel",
                               "visit", "relaxed", "relax", "food", "photography", "museums", "art", "history", "city",
                               "want", "would", "like", "love", "go", "going", "fly", "flying", "stay", "love", "mid",
                               "end", "beginning", "sometime", "somewhere", "anywhere", "warm", "sunny", "cheap", "nice", "beautiful",
                               "beach", "cold", "romantic", "quiet"}
STOP_AFTER = {"for", "from", "with", "on", "in", "and", "during", "at", "by", "budget", "under", "starting", "between",
              "next", "this", "to", "around", "about", "?", ".", ",", "we", "i", "it", "is", "that"}
PLACE_WORD = r"[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ'\-]*"


def _place_phrase(words: list[str], skip_leading: bool = False) -> str | None:
    out = []
    if skip_leading:  # "to visit Italy", "to go to Rome"
        while words and words[0].lower().strip(".,!?") in NOT_PLACES:
            words = words[1:]
    for w in words:
        lw = w.lower().strip(".,!?")
        if lw in STOP_AFTER or lw in MONTHS or any(ch.isdigit() for ch in lw):
            break
        out.append(w.strip(".,!?"))
        if len(out) == 3:
            break
    while out and out[-1].lower() in NOT_PLACES:
        out.pop()
    if not out or out[0].lower() in NOT_PLACES:
        return None
    return " ".join(out)


def extract_places(text: str, allow_bare: bool = True) -> tuple[str | None, str | None]:
    """(destination phrase, origin phrase) - resolved later against real geocoding."""
    dest = origin = None
    m = re.search(rf"\b(?:from|flying from|leaving from|departing from|based in|live in)\s+((?:{PLACE_WORD}\s*){{1,3}})", text, re.I)
    if m:
        origin = _place_phrase(m.group(1).split())
    candidates = []
    # Overlapping matches so "want to go to barcelona" still finds "barcelona".
    for m in re.finditer(rf"(?=\b(?:to|in|visit|visiting|explore|see|trip to|holiday in|vacation in|go to|fly to|travel to)\s+((?:{PLACE_WORD}\s*){{1,3}}))", text, re.I):
        cand = _place_phrase(m.group(1).split(), skip_leading=True)
        if cand and (origin is None or cand.lower() != origin.lower()) and cand not in candidates:
            candidates.append(cand)
    if candidates:
        dest = next((c for c in candidates if c[0].isupper()), candidates[0])
    elif allow_bare:
        # "Paris Oct 20-25 ...", "Tokyo, 10 days" - a leading capitalised place name.
        words = text.split()[:3]
        if words and words[0][:1].isupper():
            dest = _place_phrase(words)
    return dest, origin


REGIONS = {"europe", "asia", "africa", "america", "south america", "north america", "latin america", "middle east",
           "the middle east", "scandinavia", "the balkans", "balkans", "the gulf", "gulf", "southeast asia", "oceania",
           "caribbean", "the caribbean", "mediterranean", "the mediterranean"}
LIST_SEP = r"\s*(?:,\s*(?:and\s+|then\s+)?|\s+and\s+|\s*&\s*|\s+then\s+|\s*->\s*|\s*→\s*|\s*\+\s*)"
NIGHT_WORDS = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)"


def extract_destination_list(text: str) -> tuple[list[str], list[int]]:
    """Multi-city / multi-country trips: ("Italy, France and Spain" | "3 nights in Rome, 2 in Paris") -> places, nights."""
    # "3 nights in Rome, 2 nights in Florence and 4 in Paris"
    per = re.findall(rf"\b{NIGHT_WORDS}\s*(?:nights?|days?)?\s+in\s+((?:{PLACE_WORD}\s*){{1,3}})", text, re.I)
    places, nights = [], []
    for n, phrase in per:
        name = _place_phrase(phrase.split())
        if name and name.lower() not in REGIONS and name.lower() not in [p.lower() for p in places]:
            places.append(name)
            nights.append(_num(n) or 0)
    if len(places) >= 2:
        return places, nights
    best: list[str] = []
    # Runs of words joined by spaces / list separators; digits and other punctuation end a run.
    for m in re.finditer(rf"({PLACE_WORD}(?:(?:\s+|\s*,\s*|\s*&\s*|\s*->\s*|\s*→\s*|\s*\+\s*){PLACE_WORD})+)", text):
        parts = [p for p in re.split(LIST_SEP, m.group(1)) if p and p.strip()]
        names = []
        for p in parts:
            words = p.split()
            # "tour of Italy" / "visit Rome": drop the lead-in words before the first place
            while words and (words[0].lower() in NOT_PLACES or words[0].lower() in STOP_AFTER
                             or words[0].lower() in ("tour", "across", "through", "explore", "see", "visit", "visiting",
                                                     "of", "europe", "road", "grand", "multi-city", "cities", "countries")):
                words = words[1:]
            name = _place_phrase(words)
            if not name or name.lower() in REGIONS or not name[0].isupper():
                continue
            if name.lower() not in [x.lower() for x in names]:
                names.append(name)
        if len(names) == 2 and not re.search(r"\band\b|&|\bthen\b|->|→|\+", m.group(1).split(names[0], 1)[-1], re.I):
            continue  # "Barcelona, Spain" is one place, not a tour
        if len(names) > len(best):
            best = names
    return (best, []) if len(best) >= 2 else ([], [])


NAME_WORD = r"[A-Z][\w'’\-]*"
NAME_JOIN = r"(?:of|de|di|da|del|della|delle|dello|dei|degli|la|le|el|al|the|and|du|des|do|dos|das|van|von|der|y|&)"
PLACE_NAME = rf"{NAME_WORD}(?:\s+(?:{NAME_JOIN}\s+)?{NAME_WORD}){{0,5}}"
VISIT_TRIGGER = (r"\b(?:add|include|visit|visiting|see|go to|stop at|check out|put|squeeze in|must see|must-see|"
                 r"have to see|want to see|want to visit|don'?t miss)\s+(?:the\s+)?")


def named_places(text: str, exclude: list[str] | None = None) -> list[str]:
    """Capitalised place names after a visit verb: "add the Vatican Museums", "I want to see Sagrada Familia"."""
    skip = {x.lower() for x in (exclude or []) if x}
    out: list[str] = []
    for m in re.finditer(VISIT_TRIGGER + rf"({PLACE_NAME})", text):
        name = re.sub(rf"\s+(?:and|&)$", "", m.group(1)).strip(" .,!?")
        # A list: "see the Louvre and the Eiffel Tower"
        parts = re.split(r"\s*,\s*|\s+and\s+(?:the\s+)?|\s*&\s*", name)
        for part in parts:
            part = part.strip()
            low = part.lower()
            if (len(part) < 3 or low in skip or low in NOT_PLACES or low in REGIONS or low in MONTHS
                    or low.split()[0] in NOT_PLACES or any(low == c.lower() for c in CUISINES)):
                continue
            if part not in out:
                out.append(part)
    return out


def _parse_money(raw: str) -> float:
    raw = raw.replace(",", "").strip()
    mult = 1000 if raw.lower().endswith("k") else 1
    return float(raw.rstrip("kK")) * mult


def _next_date(month: int, day: int, today: date) -> date:
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if d >= today:
            return d
    return date(today.year + 1, month, min(day, 28))


def parse_dates(text: str, today: date) -> tuple[date | None, date | None, int | None, str | None]:
    """Returns (start, end, duration_days, assumption_note)."""
    t = text.lower()
    note = None
    iso = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", t)
    start = end = None
    if iso:
        start = date.fromisoformat(iso[0])
        if len(iso) > 1:
            end = date.fromisoformat(iso[1])
    month_names = "|".join(sorted(MONTHS, key=len, reverse=True))
    if start is None:
        # "October 12-19", "Oct 12 to Oct 19", "from October 12 to 19"
        m = re.search(rf"\b({month_names})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*(?:-|to|until|till|–)\s*(?:({month_names})\.?\s+)?(\d{{1,2}})(?:st|nd|rd|th)?)?", t)
        if m:
            m1 = MONTHS[m.group(1)]
            start = _next_date(m1, int(m.group(2)), today)
            if m.group(4):
                m2 = MONTHS[m.group(3)] if m.group(3) else m1
                end = date(start.year + (1 if m2 < m1 else 0), m2, int(m.group(4)))
        else:
            # "12-19 October", "12 October", "12th of October"
            m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*(?:-|to|–)\s*(\d{{1,2}})(?:st|nd|rd|th)?)?\s+(?:of\s+)?({month_names})\b", t)
            if m:
                mo = MONTHS[m.group(3)]
                start = _next_date(mo, int(m.group(1)), today)
                if m.group(2):
                    end = date(start.year, mo, int(m.group(2)))
    duration = None
    m = re.search(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen)[\s-]*(day|days|night|nights)\b", t)
    if m:
        n = _num(m.group(1))
        if n:
            duration = n + 1 if m.group(2).startswith("night") else n
    elif re.search(r"\b(a|one) week\b", t):
        duration = 7
    elif re.search(r"\btwo weeks\b|\bfortnight\b", t):
        duration = 14
    elif "long weekend" in t:
        duration = 4
    elif "weekend" in t:
        duration = 3
    if start is None:
        if "tomorrow" in t:
            start = today + timedelta(days=1)
        elif "next week" in t:
            start = today + timedelta(days=7 - today.weekday())
        elif "next month" in t:
            nm = date(today.year + (today.month == 12), today.month % 12 + 1, 10)
            start, note = nm, f"I assumed you start on {nm:%B} 10."
        else:
            m = re.search(rf"\b(?:in|during|this|next)\s+({month_names})\b", t)
            if m:
                start = _next_date(MONTHS[m.group(1)], 10, today)
                note = f"I assumed your trip starts on {start:%B} 10 - tell me the exact dates if you know them."
    return start, end, duration, note


def parse_budget(text: str) -> tuple[float | None, str | None, bool | None]:
    t = text.lower().replace("—", " ")
    sym = r"([$€£])"
    word = r"(usd|dollars?|eur|euros?|gbp|egp|egyptian pounds|pounds|le|try|lira|sar|riyals?|aed|dirhams?)"
    amount = r"(\d[\d,]*(?:\.\d+)?\s?k?)"
    patterns = [
        rf"{sym}\s?{amount}",
        rf"{amount}\s?{word}\b",
        rf"(?:budget|spend|under|up to|maximum|max|have)\D{{0,12}}?{amount}",
    ]
    for i, pat in enumerate(patterns):
        m = re.search(pat, t)
        if not m:
            continue
        if i == 0:
            cur, val = CURRENCY_WORDS[m.group(1)], _parse_money(m.group(2))
        elif i == 1:
            val, w = _parse_money(m.group(1)), m.group(2)
            cur = CURRENCY_WORDS.get(w, CURRENCY_WORDS.get(w.rstrip("s"), "USD"))
        else:
            val, cur = _parse_money(m.group(1)), None
            if val < 100:  # "under 5 days" etc. are not budgets
                continue
        hard = None
        if re.search(r"\b(hard limit|strict|can't exceed|cannot exceed|must not exceed|max|maximum|under|at most)\b", t):
            hard = True
        elif re.search(r"\b(flexible|around|about|roughly|approximately|soft)\b", t):
            hard = False
        return val, cur, hard
    return None, None, None


def parse_travelers(text: str) -> int | None:
    t = text.lower()
    m = re.search(r"\bfamily of (\d+|two|three|four|five|six)\b", t)
    if m:
        return _num(m.group(1))
    m = re.search(r"\b(\d+|two|three|four|five|six|seven|eight)\s+(?:of us|people|persons|travell?ers|adults|friends|guests|pax)\b", t)
    if m:
        n = _num(m.group(1)) or 1
        kids = re.search(r"\b(\d+|one|two|three|four)\s+(?:kids|children)\b", t)
        return n + (_num(kids.group(1)) or 0 if kids else 0)
    m = re.search(r"\bfor (two|three|four|five|six|\d)\b(?!\s*(?:-|\s)?(?:day|days|night|nights|week|weeks|hours?))", t)
    if m:
        return _num(m.group(1))
    if re.search(r"\bwith my (wife|husband|partner|girlfriend|boyfriend|fianc[eé]e?|friend|mother|mom|father|dad|sister|brother|son|daughter)\b", t) \
            or re.search(r"\b(honeymoon|as a couple|my wife and i|my husband and i|two of us)\b", t):
        return 2
    if re.search(r"\b(solo|alone|by myself|just me|on my own)\b", t):
        return 1
    return None


def _wake_time(t: str) -> str | None:
    m = re.search(r"(?:wake up|start|get up)[^.]{0,20}?(?:before|until|after|at)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if m:
        h = int(m.group(1)) + (12 if m.group(3) == "pm" and int(m.group(1)) < 12 else 0)
        return f"{h:02d}:{m.group(2) or '00'}"
    if re.search(r"(don'?t|do not|not|hate)[^.]{0,20}(wake up early|waking up early|getting up early|early mornings?|early starts?)"
                 r"|not a morning person|sleep in|late riser", t):
        return "09:30"
    if re.search(r"early riser|morning person|early start", t):
        return "07:30"
    return None


def extract_requirements(text: str, today: date, allow_bare_place: bool = True) -> tuple[Requirements, list[str]]:
    t = " " + text.lower() + " "
    r = Requirements()
    notes: list[str] = []
    r.destination, origin = extract_places(text, allow_bare_place)
    if r.destination and r.destination.lower() in REGIONS:
        r.region, r.destination = r.destination, None
    if not r.region:
        m = re.search(r"\b(" + "|".join(sorted((x for x in REGIONS if not x.startswith("the ")), key=len, reverse=True)) + r")\b", t)
        r.region = m.group(1).title() if m else None
    stops, nights = extract_destination_list(text)
    stops = [s for s in stops if not origin or s.lower() != origin.lower()]
    if len(stops) >= 2:
        r.destinations, r.destination = stops, stops[0]
        r.nights_per_destination = nights if len(nights) == len(stops) else []
    if origin:
        if re.fullmatch(r"[A-Z]{3}", origin):
            r.origin_airport = origin
        r.origin_city = origin
    start, end, duration, note = parse_dates(text, today)
    r.start_date = start.isoformat() if start else None
    r.end_date = end.isoformat() if end else None
    r.duration_days = duration
    if note:
        notes.append(note)
    r.budget_amount, r.budget_currency, r.budget_is_hard_limit = parse_budget(text)
    r.travelers = parse_travelers(text)

    for interest, words in INTEREST_WORDS.items():
        if any(re.search(rf"\b{re.escape(w.strip())}", t) for w in words):
            r.activity_preferences.append(interest)
    for c in CUISINES:
        if re.search(rf"\b{c}\b", t) and c not in ("vegan", "vegetarian"):
            r.food_preferences.append(c.replace(" ", "_"))
    for diet in ("vegetarian", "vegan"):
        if re.search(rf"\b(i am|i'm|we are|we're|strictly|only)?\s*{diet}\b", t) and re.search(rf"\b{diet}\b", t):
            r.dietary_restrictions.append(diet)

    avoid_m = re.findall(r"\b(?:no|fewer|less|avoid|hate|don'?t like|skip)\s+(museums?|shopping|nightlife|history|art|churches|crowds|tours)", t)
    for a in avoid_m:
        cat = {"museum": "museums", "churches": "architecture"}.get(a.rstrip("s"), a if a.endswith("s") else a)
        if cat == "crowds":
            r.prefer_hidden_gems = True
            continue
        r.avoid_categories.append(cat)
        if cat in r.activity_preferences:
            r.activity_preferences.remove(cat)
    if re.search(r"(don'?t|do not|not|hate)[^.]{0,25}(walk|walking)|limited mobility|bad knees|less walking|minimal walking", t):
        r.walking_tolerance = "low"
    elif re.search(r"love walking|like to walk|enjoy walking|walk a lot", t):
        r.walking_tolerance = "high"
    r.preferred_wake_up_time = _wake_time(t)
    if re.search(r"\b(relax|relaxed|relaxing|chill|slow|easy[- ]going|laid[- ]back)\b", t):
        r.travel_style = "relaxed"
    elif re.search(r"\b(packed|see as much|see everything|very active|intense)\b", t):
        r.travel_style = "very_active"
    elif re.search(r"\b(active|busy)\b", t):
        r.travel_style = "active"
    for style in ("boutique", "luxury", "budget hotel", "classic"):
        if style in t:
            r.hotel_style = style.replace(" hotel", "")
    m = re.search(r"(\d)[\s-]?star", t)
    if m:
        r.min_hotel_stars = float(m.group(1))
    if re.search(r"\b(direct|non-?stop)\b", t):
        r.direct_flights_only = True
    if re.search(r"(no|hate|avoid|don'?t (like|want))[^.]{0,15}early flights?|no red[- ]eye", t):
        r.avoid_early_flights = True
    if "nightlife" in r.activity_preferences:
        r.nightlife_interest = "high"
    if re.search(r"\b(quiet|peaceful|noise)\b", t):
        r.noise_tolerance = "low"
    if re.search(r"hidden gems?|less touristy|off the beaten|like a local|non[- ]touristy", t):
        r.prefer_hidden_gems = True
    if re.search(r"\b(cheapest|cheap trip|tight budget|budget trip|backpack)", t):
        r.planning_mode = "budget"
        if not r.budget_amount and re.search(r"cheapest (possible|trip|budget)|as cheap as possible|minimum (cost|budget)", t):
            r.wants_cheapest = True
    elif re.search(r"\b(comfortable|comfort|luxury|luxurious)\b", t):
        r.planning_mode = "comfort"
    r.must_visit = named_places(text, exclude=[r.destination or "", origin or ""] + r.destinations)
    m = re.findall(r"(?:must see|must-see|definitely want to|must include|have to see)\s+(?:the\s+)?([a-z' ]{3,40}?)(?:[,.]|$| and )", t)
    r.must_have += [x.strip() for x in m if not any(x.strip() in v.lower() for v in r.must_visit)]
    if "food" in r.activity_preferences and re.search(r"food experience|cooking|food tour|culinary", t):
        r.must_have.append("food experiences")
    return r, notes


FEEDBACK_RULES: list[tuple[str, ActionName]] = [
    (r"too (crowded|packed|busy|much|tiring|intense)|exhausted|tired|overwhelming|slow (it|things) down|lighter", "reduce_density"),
    (r"more (activities|things to do|sights)|too (empty|slow|boring)|pack more", "increase_density"),
    (r"more (free|down|rest) ?time|more time to relax|more breaks", "more_free_time"),
    (r"(don'?t|do not|not) want to (wake|get) up before|later start|start (the day )?later|sleep in", "later_start"),
    (r"cheaper|too expensive|reduce (the )?cost|save money|lower (the )?cost|less expensive", "cheaper"),
    (r"upgrade|more luxur|nicer hotel|splurge|better hotel", "upgrade"),
    (r"more food|food experiences|more (restaurants|eating)|foodie", "more_food"),
    (r"more nightlife|more bars|go out more|night ?life", "more_nightlife"),
    (r"noisy|noise|too loud|quieter", "avoid_noise"),
    (r"(different|change|another|switch) (the )?hotel|don'?t like the hotel", "change_hotel"),
    (r"(different|change|another|switch) (the )?flight|later flight|no early flight|direct flight", "change_flight"),
    (r"less walking|too much walking|walk less|feet hurt", "less_walking"),
    (r"hidden gems?|less touristy|off the beaten|like a local", "prefer_hidden_gems"),
    (r"\brain|weather|storm", "weather_adjust"),
]


def extract_feedback(text: str, place_names: dict[str, str]) -> tuple[list[Action], list[FeedbackNote]]:
    t = text.lower()
    actions: list[Action] = []
    notes: list[FeedbackNote] = []
    day = None
    m = re.search(r"\bday (\d+)\b", t)
    if m:
        day = int(m.group(1))
    for pat, action in FEEDBACK_RULES:
        if re.search(pat, t):
            a = Action(action=action, day=day)
            if action == "later_start":
                a.text = _wake_time(t) or "10:00"
            actions.append(a)

    # Budget changes: "increase my budget by $300", "budget is only $1,700", "set budget to 2500"
    m = re.search(r"(increase|raise|add|decrease|reduce|lower|cut)\s+(?:my |the )?budget\s+by\s+([$€£])?\s?(\d[\d,]*\s?k?)", t)
    if m:
        delta = _parse_money(m.group(3))
        actions.append(Action(action="adjust_budget", amount=delta if m.group(1) in ("increase", "raise", "add") else -delta))
    else:
        m = re.search(r"budget\s+(?:is|of|to|=)?\s*(?:only|now|just)?\s*([$€£])?\s?(\d[\d,]*\s?k?)", t)
        if m and ("budget" in t) and _parse_money(m.group(2)) >= 100:
            actions.append(Action(action="set_budget", amount=_parse_money(m.group(2))))
    actions = [a for a in actions if not (a.action == "cheaper" and any(x.action in ("adjust_budget", "set_budget") for x in actions))]

    # Category changes: "fewer museums", "remove two museums", "more history"
    for verb, act in (("fewer|less|remove|no more|drop|skip", "fewer_category"), ("more|add", "more_category")):
        for m in re.finditer(rf"\b(?:{verb})\s+(?:(\d+|one|two|three)\s+)?(museums?|churches|shopping|history|art|tours|nature|parks|photography|culture)\b", t):
            cat = {"museum": "museums", "churches": "architecture", "parks": "nature", "tours": "experience"}.get(
                m.group(2).rstrip("s") if m.group(2) != "museums" else "museum", m.group(2))
            actions.append(Action(action=act, category=cat, amount=float(_num(m.group(1)) or 1) if m.group(1) else None))

    # Trip length: "stay two more days", "add 2 days", "one day shorter"
    m = re.search(r"(?:stay|add|extend[^.]{0,10}by)\s+(\d+|one|two|three|four)\s+(?:more\s+)?(?:extra\s+)?(day|days|night|nights)", t) \
        or re.search(r"(\d+|one|two|three|four)\s+more\s+(day|days|night|nights)", t)
    if m:
        actions.append(Action(action="extend_trip", amount=float(_num(m.group(1)) or 1)))
    m = re.search(r"(\d+|one|two|three)\s+(?:day|days|night|nights)\s+(?:shorter|less|fewer)|leave (?:a|one) day earlier", t)
    if m:
        actions.append(Action(action="shorten_trip", amount=float(_num(m.group(1)) if m.lastindex else 1)))

    # Planning mode selection: "go with the comfort plan"
    m = re.search(r"\b(balanced|budget|comfort|experience) (plan|option|version)\b", t)
    if m and re.search(r"\b(go with|choose|pick|select|take|prefer|use)\b", t):
        actions.append(Action(action="select_mode", text=m.group(1)))

    # Named places to add: "add the Vatican Museums", "I also want to see Sagrada Familia"
    for name in named_places(text):
        if not re.search(rf"\b(remove|skip|drop|replace|don'?t want|no)\b[^.]{{0,20}}{re.escape(name)}", text, re.I):
            actions.append(Action(action="add_place", text=name))

    # Named item removal: "remove the Colosseum", "skip Hagia Sophia"
    for pid, name in place_names.items():
        short = name.lower().split(" (")[0].split(" & ")[0]
        if short and re.search(rf"\b(remove|skip|drop|replace|don'?t want|no)\b[^.]{{0,20}}{re.escape(short)}", t):
            actions.append(Action(action="replace_item", text=pid))

    # Structured feedback notes
    sentiment = "negative" if re.search(r"\b(but|too|not|didn'?t|hate|bad|noisy|dirty|expensive|crowded)\b", t) else (
        "positive" if re.search(r"\b(great|love|loved|amazing|perfect|nice|good)\b", t) else "neutral")
    if "hotel" in t:
        attr = next((a for a in ("noise", "location", "price", "cleanliness", "breakfast", "room") if a[:4] in t), None)
        if "noisy" in t or "loud" in t:
            attr = "noise"
        notes.append(FeedbackNote(feedback_type="hotel", sentiment="negative" if attr == "noise" else sentiment,
                                  attribute=attr, severity=0.8 if attr == "noise" else 0.5))
    if any(a.action in ("reduce_density", "more_free_time", "increase_density") for a in actions):
        notes.append(FeedbackNote(feedback_type="itinerary", sentiment="negative", attribute="density", severity=0.7))
    if any(a.action in ("cheaper", "set_budget", "adjust_budget") for a in actions):
        notes.append(FeedbackNote(feedback_type="budget", sentiment="neutral", attribute="price", severity=0.6))
    if any(a.action == "less_walking" for a in actions):
        notes.append(FeedbackNote(feedback_type="itinerary", sentiment="negative", attribute="walking", severity=0.7))
    return actions, notes


QUESTION_RE = re.compile(r"^(what|how|where|when|which|is|are|do|does|can|should|why)\b.*\?\s*$|\?\s*$")


def interpret_rules(text: str, has_plan: bool, place_names: dict[str, str], today: date) -> tuple[TurnInterpretation, list[str]]:
    req, notes = extract_requirements(text, today, allow_bare_place=not has_plan)
    actions, fb = extract_feedback(text, place_names) if has_plan else ([], [])
    if has_plan:
        # Once a plan exists, "to wake up" / "to my plan" are not destinations: a new place must be a proper name.
        if req.destination and not req.destination[:1].isupper():
            req.destination = None
        # "increase my budget by $1000": the amount is the action's delta, not a new total budget (its currency
        # stays: the workflow converts a delta or total given in another currency).
        if any(a.action in ("adjust_budget", "set_budget") for a in actions):
            req.budget_amount = None
    has_req = any(v not in (None, [], "") for k, v in req.model_dump().items())
    if has_plan and actions:
        intent: Intent = "feedback"
    elif QUESTION_RE.search(text.strip().lower()) and not (req.budget_amount or req.start_date or req.duration_days):
        intent = "question"
    elif has_req:
        intent = "update_requirements" if has_plan else "plan_request"
    elif has_plan and fb:
        intent = "feedback"
    else:
        intent = "smalltalk"
    hypothetical = has_plan and bool(WHAT_IF_RE.match(text))
    apply_pending = has_plan and bool(APPLY_RE.match(text))
    return TurnInterpretation(intent=intent, requirements=req, feedback=fb, actions=actions,
                              question=text if intent == "question" else None, hypothetical=hypothetical,
                              apply_pending=apply_pending, source="rules"), notes


# Offline test harness only (the model decides this in production).
WHAT_IF_RE = re.compile(r"^\s*(what if|what would happen if|how about if|suppose)\b", re.I)
APPLY_RE = re.compile(r"^\s*(yes|yep|sure|ok|okay|apply( it)?|do it|go ahead|let'?s do (it|that)|sounds good)\b[.! ]*$", re.I)


# ---------------------------------------------------------------------------
# Claude interpreter
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the requirement-understanding component of an AI travel planner.
The planner researches and plans trips; it never books anything.

Convert the user's latest message into the TurnInterpretation schema.

- Extract only what the user actually said or clearly implied. Leave everything else null/empty; never invent budgets, dates or preferences.
- Resolve relative dates ("next month", "October 12-19") against today's date given below, and output ISO dates. The end date is the last day of the trip.
- Destinations can be any city or country in the world. Return the name as the user wrote it (in English).
- Multi-city / multi-country trips ("a Europe tour: Italy, France and Spain", "Rome then Paris then Barcelona", "3 nights in Rome and 2 in Florence"): put every place in visit order in `destinations` (cities, or countries as the user named them; for a country you may use its best-known city), set `destination` to the first one, and fill `nights_per_destination` only if the user gave per-place lengths. Leave `destinations` empty for a single-destination trip. Never put a region such as "Europe" in the list.
- The user may write in Arabic (including Egyptian dialect); always output English place names.
- Countries are fine as destinations: keep them as countries ("Spain"), do NOT replace a country by one city - the planner designs the route with the user. If the user names only a region and wants you to choose ("a Europe tour, you decide"), set region and leave destinations empty.
- If the context has a pending_route_proposal: set route_decision to 'accept' when the user agrees or lets you decide, or 'change' when they ask for something different. For 'change', only fill destinations if the user lists the exact cities they now want.
- A city or resort town the user wants to include (e.g. 'Sharm El Sheikh', 'Luxor') is a destination, not a must_visit place: put it in destinations (keep any countries too). must_visit is for sights and landmarks.
- Specific named places the user wants to see ("I want to visit the Vatican Museums", "عايز ازور الأهرامات", "add Sagrada Familia"): before a plan exists put them in requirements.must_visit; once a plan exists use one add_place action per place with text = the place's usual English name. Categories ("more museums") are not add_place.
- Travelers: "with my wife" = 2, "family of four" = 4. Rooms only when said: "three of us in one room" -> rooms = 1.
- Flying home to a different city than the departure one ("from Riyadh to Istanbul, then back to Cairo", "عايز ارجع
  على القاهرة مش الرياض"): requirements.return_to = that city. It is NOT a new destination and NOT a route change.
- "The cheapest budget possible", "أرخص بادجت ممكنة", "هتبدأ من كام", "what's the least it can cost": set
  wants_cheapest = true and planning_mode = "budget", and leave budget_amount empty - the planner finds the minimum.
- If a plan already exists and the user reacts to it ("too crowded", "make it cheaper", "remove two museums", "I don't want to wake up before 10", "increase my budget by $300", "stay two more days"), set intent=feedback and list the concrete actions. Use adjust_budget with a signed amount for relative budget changes and set_budget for absolute ones. Use later_start with text=HH:MM. Use fewer_category/more_category with a lowercase category and amount = how many. Use replace_item with text = the exact item name.
- Also record structured feedback notes, e.g. "the hotel was great but noisy" -> hotel, negative, attribute noise, severity 0.8.
- Read the intent behind casual wording, in any language or dialect - don't wait for exact phrases:
  - "add more things", "ضيف حاجات تانية", "the day is empty", "I want to see more", "pack it" -> increase_density.
  - The traveller describing themselves ("I'm active", "انا راجل اكتيف", "بحب ازور اماكن كتير", "I like to see a lot")
    -> requirements.travel_style = "very_active" (or "active" when milder) AND, if a plan exists, increase_density.
  - "add all the famous landmarks / the top sights / معالم المدينة كلها" -> increase_density plus more_category with
    category "landmarks". Only add_place for places the user actually names, each with text = its English name.
  - Getting around: "I'll walk between nearby places and take transport for far ones" -> requirements.transport_preference
    = "mixed"; "I love walking" -> "walk" (walking_tolerance high); "public transport / مواصلات" -> "public_transport";
    "taxi / Uber / I don't want to walk" -> "taxi" (walking_tolerance low). Never use select_mode for this.
  - "too much / tiring / مرهق" -> reduce_density; "cheaper / ارخص" -> cheaper; "earlier / later flight" -> change_flight.
  - select_mode only when the user picks one of the plan modes (balanced, budget, comfort, experience).
  - "raise my budget to what it really costs / زوّد الميزانية للتكلفة الحقيقية" -> set_budget with amount = the
    context's plan_total rounded up to a round number.
  - A currency other than the trip's ("بالجنيه", "in euros", "100 ألف جنيه") -> requirements.budget_currency = its ISO
    code. A currency alone ("خليها بالجنيه المصري") is only budget_currency: the code converts the amount at today's
    rate - never convert it yourself.
- If a plan exists and the message asks to change it, use intent=feedback with actions (requirements may also be set).
  Express ONLY what the user asked for: never add changes of your own (a budget change is just the budget - the
  planner decides how to use the money).
- intent=question when the user asks for information about travel rather than changing the trip.
- A hypothetical change to compare, not apply yet ("what if my budget were $500 more?", "لو زودت يومين هتبقى بكام؟"):
  express the change normally and set hypothetical = true. If the context shows a pending_what_if and the user accepts
  it ("apply it", "تمام نفذها", "ok go with that"), set apply_pending = true.
- intent=off_topic when the message is outside the travel scope below (e.g. "who is Messi?", "write me Python code").
""" + SCOPE_RULE + """
- The context's recent_conversation holds the last few messages (oldest first). Use it to resolve references to what was just said ("the second one", "that hotel", "yes, do that", "نفس المكان", "اللي قلته") into concrete values or actions.
  - When the latest message picks one of the options the assistant just offered ("the second one", "the first", "التاني", "الأولاني", "the Venice one"), treat it as a plan_request / update_requirements and fill the fields from that option: its destinations in order, nights_per_destination, and anything else the option specified.
  - Only the latest user message is being answered. Facts already in the draft or contract stay as they are: do not re-extract them from older messages."""


async def interpret_llm(text: str, context: dict, today: date) -> TurnInterpretation | None:
    pending = ""
    if context.get("pending_route_proposal"):
        pending = ("IMPORTANT: the assistant just proposed this route and is waiting for the user's answer: "
                   f"{context['pending_route_proposal']}. Set route_decision: 'accept' if the message agrees or lets the "
                   "assistant decide (any short agreement in any language, e.g. 'ok', 'yes', 'تمام', 'ماشي', 'go ahead'), "
                   "or 'change' if it asks for anything different.\n\n")
    user = (f"Today's date: {today.isoformat()}\n"
            f"Current trip context (JSON): {json.dumps(context, default=str)}\n\n"
            f"{pending}User message:\n{text}")
    result = await llm.parse(SYSTEM_PROMPT, user, TurnInterpretation)
    if result is not None:
        result.source = llm.provider() or "llm"
    return result


async def interpret(text: str, has_plan: bool, place_names: dict[str, str], context: dict,
                    today: date | None = None) -> tuple[TurnInterpretation, list[str]]:
    today = today or _today()
    if llm.available():
        result = await interpret_llm(text, context, today)
        if result is not None:
            # The model understands the message (any language); no keyword rules run alongside it.
            return result, []
    if settings.rules_fallback:  # offline test harness only (never in production)
        return interpret_rules(text, has_plan, place_names, today)
    # No guessing with keywords: say the assistant is briefly unavailable instead.
    return TurnInterpretation(intent="smalltalk", source="unavailable"), []
