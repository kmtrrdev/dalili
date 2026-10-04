"""Planner knobs: every lever the repair loop and the replanner can pull.

The plan builder is a pure function of (contract, profile, research, mode, knobs),
so repairing a plan or applying feedback means adjusting knobs and rebuilding.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlanKnobs(BaseModel):
    max_price_level: int = 4            # restaurants
    price_pressure: int = 0             # 0..3, pushes every choice cheaper
    hotel_max_price_local: float | None = None
    hotel_exclude: list[str] = Field(default_factory=list)
    flight_exclude: list[str] = Field(default_factory=list)
    flight_pins: list[str] = Field(default_factory=list)  # flight ids the traveller chose ("take the direct flight")
    exclude_ids: list[str] = Field(default_factory=list)
    exclude_on_day: dict[int, list[str]] = Field(default_factory=dict)
    activity_cost_cap_local: float | None = None
    density_delta: int = 0               # added to per-day activity capacity
    day_capacity_override: dict[int, int] = Field(default_factory=dict)
    extra_rest: bool = False
    category_limits: dict[str, int] = Field(default_factory=dict)
    category_boost: dict[str, float] = Field(default_factory=dict)
    food_focus: bool = False
    avoid_outdoor_days: list[int] = Field(default_factory=list)
    prefer_taxi: bool = False
    walk_tolerance_override: str | None = None
    transfer_mode: str | None = None     # force "taxi"/"train"/"bus" for airport transfers
    skip_snacks: bool = False            # no optional coffee / dessert stops
    budget_steps: list[str] = Field(default_factory=list)  # budget repairs already applied
    must_include: list[str] = Field(default_factory=list)  # place ids the traveller asked for by name
    expert_picks: list[str] = Field(default_factory=list)  # ids in must_include added by the critic, not the traveller
    meal_requests: dict[str, int] = Field(default_factory=dict)  # restaurant id -> day (0 = any day) to eat there
    signature_picks: list[str] = Field(default_factory=list)  # the destination's signature experiences (experience plan)

    def merged(self, other: "PlanKnobs") -> "PlanKnobs":
        """Combine user-driven adjustments (self) with repair-loop knobs (other)."""
        base = self.model_copy(deep=True)
        base.max_price_level = min(base.max_price_level, other.max_price_level)
        base.price_pressure = max(base.price_pressure, other.price_pressure)
        if other.hotel_max_price_local is not None:
            base.hotel_max_price_local = min(filter(None, [base.hotel_max_price_local, other.hotel_max_price_local]))
        base.hotel_exclude = sorted(set(base.hotel_exclude) | set(other.hotel_exclude))
        base.flight_exclude = sorted(set(base.flight_exclude) | set(other.flight_exclude))
        base.flight_pins = list(dict.fromkeys(base.flight_pins + other.flight_pins))
        base.exclude_ids = sorted(set(base.exclude_ids) | set(other.exclude_ids))
        for day, ids in other.exclude_on_day.items():
            base.exclude_on_day[day] = sorted(set(base.exclude_on_day.get(day, [])) | set(ids))
        if other.activity_cost_cap_local is not None:
            base.activity_cost_cap_local = min(filter(lambda v: v is not None, [base.activity_cost_cap_local, other.activity_cost_cap_local]))
        base.density_delta += other.density_delta
        base.day_capacity_override.update(other.day_capacity_override)
        base.extra_rest = base.extra_rest or other.extra_rest
        for cat, lim in other.category_limits.items():
            base.category_limits[cat] = min(lim, base.category_limits.get(cat, lim))
        for cat, b in other.category_boost.items():
            base.category_boost[cat] = base.category_boost.get(cat, 0) + b
        base.food_focus = base.food_focus or other.food_focus
        base.avoid_outdoor_days = sorted(set(base.avoid_outdoor_days) | set(other.avoid_outdoor_days))
        base.prefer_taxi = base.prefer_taxi or other.prefer_taxi
        base.walk_tolerance_override = other.walk_tolerance_override or base.walk_tolerance_override
        base.transfer_mode = other.transfer_mode or base.transfer_mode
        base.skip_snacks = base.skip_snacks or other.skip_snacks
        base.must_include = list(dict.fromkeys(base.must_include + other.must_include))
        base.expert_picks = list(dict.fromkeys(base.expert_picks + other.expert_picks))
        base.meal_requests = {**base.meal_requests, **other.meal_requests}
        base.signature_picks = list(dict.fromkeys(base.signature_picks + other.signature_picks))
        return base
