"""What-if impact: one comparison of a trip before and after a hypothetical change, used by the chat and the API.

Shows, for every plan: cost, validity, requirements met, quality and price confidence before -> after; for the
selected plan, what changed (hotels, flights or legs, day by day); which constraints changed; and whether the
answer reused the existing research (incremental) or had to search again (and what).
"""

from __future__ import annotations

from typing import Any

from .models import TripPlan, TripState
from .replanner import diff_plans


def _plan_view(p: TripPlan | None) -> dict[str, Any] | None:
    if p is None:
        return None
    s, b = p.score, p.budget
    return {"total": b.total if b else None, "currency": b.currency if b else None,
            "within_budget": p.within_budget, "valid": p.validation.result == "PASS" if p.validation else None,
            "score": s.total if s else None, "requirements_met": s.constraint_satisfaction if s else None,
            "preferences_met": s.preference_satisfaction if s else None,
            "price_confidence": b.confidence if b else None}


def _constraint_changes(before: TripState, after: TripState) -> list[str]:
    old = {c.id: c for c in (before.trip_contract.constraints if before.trip_contract else [])}
    new = {c.id: c for c in (after.trip_contract.constraints if after.trip_contract else [])}
    out = [f"new: {c.type} {c.value}" for k, c in new.items() if k not in old]
    out += [f"removed: {c.type} {c.value}" for k, c in old.items() if k not in new]
    out += [f"changed: {c.type} {old[k].value} -> {c.value}" for k, c in new.items()
            if k in old and (old[k].value != c.value or old[k].priority != c.priority)]
    return out


def compare(before: TripState, after: TripState) -> dict[str, Any]:
    modes = sorted(set(before.plans) | set(after.plans))
    plans = {m: {"before": _plan_view(before.plans.get(m)), "after": _plan_view(after.plans.get(m))} for m in modes}
    b_sel, a_sel = before.selected_plan, after.selected_plan
    delta = (a_sel.budget.total - b_sel.budget.total) if b_sel and a_sel and b_sel.budget and a_sel.budget else None
    days_changed = 0
    if b_sel and a_sel:
        old = {d.day: [i.place_id for i in d.items if i.kind == "activity"] for d in b_sel.days}
        days_changed = sum(1 for d in a_sel.days if old.get(d.day) != [i.place_id for i in d.items if i.kind == "activity"])
        days_changed += abs(len(a_sel.days) - len(b_sel.days))
    refreshed = list(after.metadata.get("refreshed") or [])
    return {
        "selected": {"before": before.selected_mode, "after": after.selected_mode},
        "plans": plans,
        "cost_change": round(delta, 2) if delta is not None else None,
        "days_changed": days_changed,
        "changes": [c for c in diff_plans(b_sel, a_sel) if not c.startswith(("Total cost", "TripScore"))],
        "constraint_changes": _constraint_changes(before, after),
        "replanning": {"kind": "full" if len(refreshed) >= 4 else ("incremental" if not refreshed else "partial"),
                       "searched_again": refreshed},
    }


def lines(cmp: dict[str, Any], arabic: bool) -> list[str]:
    """The comparison as short chat lines (the reply under 'what if ...')."""
    out = []
    sel = cmp["selected"]["after"]
    pv = cmp["plans"].get(sel) or {}
    b, a = pv.get("before") or {}, pv.get("after") or {}
    if b.get("total") is not None and a.get("total") is not None:
        out.append(f"- {'الإجمالي' if arabic else 'Total'}: {b['total']:,.0f} -> {a['total']:,.0f} {a['currency']}")
    if b.get("score") is not None and a.get("score") is not None:
        out.append(f"- TripScore: {b['score']} -> {a['score']}")
    if b.get("within_budget") != a.get("within_budget") and a.get("within_budget") is not None:
        out.append(("- " + ("داخل الميزانية" if a["within_budget"] else "فوق الميزانية")) if arabic else
                   ("- Now within budget" if a["within_budget"] else "- Now over budget"))
    if b.get("requirements_met") is not None and a.get("requirements_met") is not None \
            and b["requirements_met"] != a["requirements_met"]:
        out.append(f"- {'متطلباتك المتحققة' if arabic else 'Requirements met'}: {b['requirements_met']}% -> "
                   f"{a['requirements_met']}%")
    others = [f"{m} {v['after']['total']:,.0f}" for m, v in cmp["plans"].items()
              if m != sel and v.get("after") and v["after"].get("total") is not None]
    if others:
        out.append(f"- {'الخطط التانية' if arabic else 'Other plans'}: " + ", ".join(others))
    out += [f"- {c}" for c in cmp["changes"][:8]]
    r = cmp["replanning"]
    if r["searched_again"]:
        out.append(f"- {'بحثت تاني عن' if arabic else 'Searched again'}: {', '.join(r['searched_again'])}")
    return out
