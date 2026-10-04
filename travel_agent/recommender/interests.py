"""Words that describe each interest. An interest's vector is the mean of these words' learned vectors."""

from __future__ import annotations

from .catalog import INTERESTS
from .corpus import tokenize

SEEDS = {
    "beach": "beach beaches sand snorkelling snorkeling swimming coast island sea diving surf lagoon coral seaside",
    "culture": "museum gallery art theatre festival cathedral architecture opera tradition painting exhibition",
    "history": "ancient ruins century medieval roman castle fortress temple empire archaeological palace historic",
    "nature": "hiking trail mountain forest lake waterfall wildlife valley scenery glacier canyon birds",
    "ski": "ski skiing slopes piste snowboard lift snow winter chairlift runs",
    "food": "restaurant cuisine dish dishes food market wine seafood cafe taste cooking",
    "nightlife": "bar bars club clubs nightlife pub cocktail dance party music live",
    "shopping": "shopping mall malls boutique souk bazaar shops brands store outlet",
    "relax": "spa relax relaxing resort massage pool quiet sunset peaceful thermal retreat",
    "adventure": "trekking climbing rafting paragliding diving safari kayaking canyon desert zipline",
}

assert set(SEEDS) == set(INTERESTS)


def seed_tokens(interest: str) -> list[str]:
    return sorted(set(tokenize(SEEDS[interest])))
