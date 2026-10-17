"""Budget engine: all money math is deterministic and done in the user's currency."""

from __future__ import annotations

import statistics

from ..models import BudgetBreakdown, Money, Place, PlanningMode, TripContract, TripPlan, trust_class

# How reliable each evidence class is when judging the total (a mapping of evidence strength, not a travel rule):
# a published price is the price, a calculation from published inputs is close, an estimate is a guess with a basis,
# a category default is close to unknown.
TRUST_WEIGHT = {"verified": 1.0, "calculated": 0.85, "estimated": 0.5, "unknown": 0.2}


def to_user(m: Money, fx: dict[str, float], user_currency: str) -> float:
    if m.currency.upper() == user_currency.upper():
        return m.amount
    return m.amount * fx.get(m.currency.upper(), 1.0)


def compute_budget(plan: TripPlan, contract: TripContract, fx: dict[str, float], buffer_ratio: float) -> BudgetBreakdown:
    cur = contract.budget.currency
    b = BudgetBreakdown(currency=cur, limit=contract.budget.amount, hard_limit=contract.budget.hard_limit)
    trust = {k: 0.0 for k in TRUST_WEIGHT}
    fixed = 0.0  # published flight fares and hotel rates: the price itself, nothing to buffer

    def count(m: Money, amount: float, booked: bool = False) -> None:
        nonlocal fixed
        trust[trust_class(m)] += amount
        if booked and trust_class(m) == "verified":
            fixed += amount

    if plan.stops:
        # Multi-city: every leg once (trains / coaches are ground transport) and each city's hotel for its nights.
        for f in plan.legs:
            cost = to_user(f.price_per_person, fx, cur) * contract.travelers
            count(f.price_per_person, cost, booked=True)
            b.stale_sources += int(f.metadata.stale)
            if f.mode == "flight":
                b.flights += cost
            else:
                b.transport += cost
        for s in plan.stops:
            if s.hotel:
                cost = to_user(s.hotel.price_per_night, fx, cur) * s.nights * contract.rooms
                b.hotel += cost
                count(s.hotel.price_per_night, cost, booked=True)
                b.stale_sources += int(s.hotel.metadata.stale)
    else:
        for f in (plan.outbound_flight, plan.return_flight):
            if f:
                cost = to_user(f.price_per_person, fx, cur) * contract.travelers
                b.flights += cost
                count(f.price_per_person, cost, booked=True)
                b.stale_sources += int(f.metadata.stale)
        if plan.hotel:
            b.hotel = to_user(plan.hotel.price_per_night, fx, cur) * contract.nights * contract.rooms
            count(plan.hotel.price_per_night, b.hotel, booked=True)
            b.stale_sources += int(plan.hotel.metadata.stale)

    for day in plan.days:
        day_total = 0.0
        for item in day.items:
            cost = to_user(item.cost, fx, cur)
            leg = to_user(item.transport_from_previous.cost, fx, cur) if item.transport_from_previous else 0.0
            if item.kind in ("meal", "activity", "transfer") and cost:
                count(item.cost, cost)
            if leg:
                count(item.transport_from_previous.cost, leg)
            if item.kind == "meal":
                b.food += cost
            elif item.kind == "activity":
                b.activities += cost
            elif item.kind == "transfer":
                b.transport += cost
            b.transport += leg
            day_total += cost + leg
        day.estimated_cost = Money(amount=round(day_total, 2), currency=cur, price_type="estimated")
        b.daily_spending[day.date.isoformat()] = round(day_total, 2)

    subtotal = b.flights + b.hotel + b.food + b.activities + b.transport
    b.by_trust = {k: round(v, 2) for k, v in trust.items()}
    counted = sum(trust.values())
    if counted:
        # Evidence-based: the cost-weighted reliability of every price in the total, lowered when a flight or hotel
        # price had to come from an expired cache.
        b.confidence = round(sum(TRUST_WEIGHT[k] * v for k, v in trust.items()) / counted * 0.9 ** b.stale_sources, 2)
    # The buffer covers what can still move: meals, tickets, transport, tips and extras, and any estimated fare. A
    # published airfare or nightly rate is the price: buffering it too made plans that fit "over budget" when most of
    # the cost was a live airfare.
    b.buffer = max(0.0, subtotal - fixed) * buffer_ratio
    b.total = subtotal + b.buffer
    b.remaining = b.limit - b.total
    for k in ("flights", "hotel", "food", "activities", "transport", "buffer", "total", "remaining"):
        setattr(b, k, round(getattr(b, k), 2))
    if b.total <= b.limit:
        b.status = "PASS"
    else:
        b.status = "FAIL" if b.hard_limit else "WARN"
    b.notes = [
        f"Buffer of {buffer_ratio:.0%} on meals, tickets and transport covers price changes, tips and small "
        "extras (published flight fares and hotel rates carry none).",
        "Flight and hotel prices were retrieved at planning time and can change before you book.",
        "Food and activity costs are per-person estimates multiplied by the number of travelers.",
    ]
    return b


def estimate_daily_user(restaurants: list[Place], attractions: list[Place], mode: PlanningMode, travelers: int,
                        activities_per_day: int, transit_fare_user: float, fx) -> float:
    """Rough per-day spend (user currency, whole group) used before the itinerary exists."""
    def user(p: Place) -> float:
        return p.cost_per_person.amount * fx(p.cost_per_person.currency)

    def median_price(meal: str, max_level: int) -> float:
        prices = [user(r) for r in restaurants if meal in r.meal_types and r.price_level <= max_level]
        return statistics.median(prices) if prices else 0.0

    max_level = {"budget": 2, "balanced": 3, "comfort": 4, "experience": 4}[mode]
    food_pp = median_price("breakfast", 2) + median_price("lunch", max_level) * 0.8 + median_price("dinner", max_level) + median_price("coffee", 2)
    tickets = [user(a) for a in attractions]
    avg_ticket = statistics.mean(tickets) if tickets else 0.0
    return (food_pp + avg_ticket * activities_per_day * 0.7) * travelers + transit_fare_user * 3 * travelers
