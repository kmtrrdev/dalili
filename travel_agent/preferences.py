"""Long-term preference memory: what Dalili knows about a traveller across trips.

Two kinds of knowledge, kept apart:
- STATED  - the traveller said it about themselves ("I'm vegetarian", "I hate early flights"). Trusted as is, never
            decays, and only changes when the traveller says something else.
- INFERRED - learned from behaviour (complaints about noise, asking for fuller days, choosing a plan). Each observation
            is evidence for or against a value; confidence is the share of supporting evidence, shrunk while there is
            little of it, and old evidence fades with a half-life.

    confidence(inferred) = mean * n / (n + 1) * 0.5 ** (age_days / half_life)
    mean = (support + 1) / (support + against + 2)        (Beta(1, 1) prior)

One complaint is a hint (0.33); two consistent ones make it a habit (0.5) and the planner starts using it; a
contradiction weakens it. Explicit choices in the current trip always win over anything inferred.
Only this memory is stored on the user's account - one trip's choices (or the critic's edits) never become the
traveller's identity.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .config import settings
from .models import LearnedPreference, TravelerProfile

STATED_CONFIDENCE = 0.9
MAX_EVIDENCE = 8


def _now() -> datetime:
    return datetime.now(UTC)


def confidence(lp: LearnedPreference, now: datetime | None = None) -> float:
    """How sure we are today (stated: fixed; inferred: evidence share, shrunk while thin, fading with age)."""
    if lp.source == "stated":
        return STATED_CONFIDENCE
    n = lp.support + lp.against
    if n <= 0:
        return lp.confidence  # stored before evidence counts existed
    mean = (lp.support + 1) / (n + 2)
    value = mean * n / (n + 1)
    if lp.updated_at is not None:
        age = max(0.0, ((now or _now()) - lp.updated_at).total_seconds() / 86400)
        value *= 0.5 ** (age / max(settings.preference_half_life_days, 1))
    return round(value, 3)


def _touch(lp: LearnedPreference, evidence: str) -> None:
    lp.updated_at = _now()
    if evidence:
        lp.evidence = (lp.evidence + [evidence[:120]])[-MAX_EVIDENCE:]
    lp.confidence = confidence(lp)


def state(profile: TravelerProfile, key: str, value: Any, evidence: str = "stated by the traveller") -> None:
    """The traveller said it: stored as stated (replaces whatever was inferred)."""
    lp = profile.learned.get(key)
    if lp is None or lp.value != value or lp.source != "stated":
        lp = LearnedPreference(value=value, source="stated")
    lp.support += 1
    _touch(lp, evidence)
    profile.learned[key] = lp


def observe(profile: TravelerProfile, key: str, value: Any, evidence: str, weight: float = 1.0) -> LearnedPreference:
    """Behaviour supporting `value` for `key`. Evidence for a different value counts against the old one; the old
    value is replaced only once the new one is better supported. A stated preference is never overridden here."""
    lp = profile.learned.get(key)
    if lp is not None and lp.source == "stated":
        return lp
    if lp is None:
        lp = LearnedPreference(value=value, source="inferred")
    if lp.value == value:
        lp.support += weight
    else:
        lp.against += weight
        if lp.against > lp.support:  # the behaviour changed: the new value takes over with this evidence
            lp = LearnedPreference(value=value, source="inferred", support=weight)
    _touch(lp, evidence)
    profile.learned[key] = lp
    return lp


def withdraw(profile: TravelerProfile, key: str, value: Any) -> None:
    """Take back one unit of earlier inferred evidence for `value` (a choice the traveller then changed)."""
    lp = profile.learned.get(key)
    if lp is None or lp.source != "inferred":
        return
    if lp.value == value:
        lp.support = max(0.0, lp.support - 1)
    else:
        lp.against = max(0.0, lp.against - 1)
    lp.confidence = confidence(lp)


def apply(profile: TravelerProfile, threshold: float | None = None) -> list[str]:
    """Copy confident learned values into the profile fields the planner reads - never over an explicit choice made
    in this trip. Returns the keys applied."""
    limit = settings.preference_apply_threshold if threshold is None else threshold
    applied = []
    for key, lp in profile.learned.items():
        if key in profile.explicit_fields or not hasattr(profile, key) or key not in TravelerProfile.model_fields:
            continue
        if confidence(lp) >= limit:
            try:
                setattr(profile, key, lp.value)
                applied.append(key)
            except ValueError:
                continue  # a stored value the current schema no longer accepts
    return applied


def known(profile: TravelerProfile) -> set[str]:
    """Fields Dalili knows for this traveller: stated in this trip, or confidently learned."""
    return set(profile.explicit_fields) | {k for k, lp in profile.learned.items()
                                           if confidence(lp) >= settings.preference_apply_threshold}


def long_term(stored: TravelerProfile | None, trip_profile: TravelerProfile) -> TravelerProfile:
    """What is saved on the account: only the preference memory, merged by recency (newest evidence wins)."""
    merged = dict(stored.learned) if stored else {}
    for key, lp in trip_profile.learned.items():
        old = merged.get(key)
        if old is None or (lp.updated_at or datetime.min.replace(tzinfo=UTC)) >= (old.updated_at or datetime.min.replace(tzinfo=UTC)):
            merged[key] = lp
    return TravelerProfile(learned=merged)


def fresh_profile(stored: TravelerProfile | None) -> TravelerProfile:
    """A new trip starts from the traveller's memory, not from another trip's one-off choices."""
    p = TravelerProfile(learned=dict(stored.learned) if stored else {})
    apply(p)
    return p
