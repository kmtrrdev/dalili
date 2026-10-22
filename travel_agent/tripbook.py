"""Trip Book: the complete travel catalog generated from the trip state.

Rendered as an interactive page in the app's visual language (3D globe cover, per-day
route maps, charts, persistent checklists) that also prints cleanly as a document.
"""

from __future__ import annotations

import html
import json
from collections import OrderedDict
from urllib.parse import quote_plus

from .engine.budget import to_user
from .models import Money, Place, TripPlan, TripState, utcnow
from .narrative import money

SECTIONS = [
    "Trip Overview", "Traveler Profile", "Flights", "Hotel", "Destination Overview", "Daily Itinerary",
    "Restaurants", "Activities", "Transportation", "Budget", "Estimated Daily Spending", "Packing List",
    "Documents Checklist", "Weather Expectations", "Local Tips", "Useful Phrases", "Emergency Information",
    "Maps / Locations", "Alternatives", "Important Notes", "Sources / Data Timestamps",
]

e = html.escape

_P = {
    "plane": "M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z",
    "bed": "M3 18v-7h18v7M3 14h18M7 11V8h4v3",
    "fork": "M7 3v8M5 3v4a2 2 0 0 0 4 0V3M7 11v10M16 3c-2 0-3 3-3 6s1 4 3 4v8",
    "landmark": "M3 21h18M5 21V10M19 21V10M9 21v-7M15 21v-7M12 3l9 5H3z",
    "route": "M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM8 17h6a3 3 0 0 0 0-6h-4a3 3 0 0 1 0-6h6",
    "cloud": "M7 18h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.5 3.5 0 0 0 7 18z",
    "rain": "M7 15h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.5 3.5 0 0 0 7 15zM8 18l-1 3M12 18l-1 3M16 18l-1 3",
    "storm": "M7 15h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.5 3.5 0 0 0 7 15zM13 15l-2 3.5h3L12 22",
    "sun": "M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
    "snow": "M12 2v20M4 7l16 10M4 17L20 7",
    "coins": "M12 3c4 0 7 1.3 7 3s-3 3-7 3-7-1.3-7-3 3-3 7-3zM5 6v6c0 1.7 3 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3 3 7 3s7-1.3 7-3v-6",
    "user": "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
    "book": "M4 5a2 2 0 0 1 2-2h14v16H6a2 2 0 0 0-2 2zM20 19v2H6",
    "globe": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c3 3 4 6 4 9s-1 6-4 9M12 3c-3 3-4 6-4 9s1 6 4 9",
    "bag": "M5 8h14l-1 13H6zM9 8V6a3 3 0 0 1 6 0v2",
    "doc": "M6 3h9l4 4v14H6zM14 3v5h5M9 13h6M9 17h4",
    "chat": "M4 5h16v11H9l-5 4z",
    "alert": "M12 8v5M12 16.5v.5M10.3 3.9L2 18a2 2 0 0 0 1.7 3h16.6A2 2 0 0 0 22 18L13.7 3.9a2 2 0 0 0-3.4 0z",
    "pin": "M12 21s7-6.5 7-12a7 7 0 0 0-14 0c0 5.5 7 12 7 12zM12 11a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
    "swap": "M4 7h13l-3-3M20 17H7l3 3",
    "info": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8h.01",
    "shield": "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM9 12l2 2 4-4",
    "star": "M12 3l2.8 5.8 6.2.9-4.5 4.4 1 6.2L12 17.4 6.5 20.3l1-6.2L3 9.7l6.2-.9z",
    "link": "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
    "walk": "M13 4a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM9 22l2-7 3 3v6M7 13l2-5 4 1 3 4M11 15l-2-3",
    "transit": "M5 17V6a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3v11zM5 12h14M8 17v3M16 17v3",
    "taxi": "M5 16l1.5-5h11L19 16M4 16h16v3H4zM7 19v2M17 19v2",
    "moon": "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
    "clock": "M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
    "print": "M6 9V3h12v6M6 18H4v-7h16v7h-2M8 14h8v7H8z",
    "back": "M15 18l-6-6 6-6",
}
SECTION_ICON = ["star", "user", "plane", "bed", "globe", "route", "fork", "landmark", "transit", "coins", "coins",
                "bag", "doc", "cloud", "info", "chat", "alert", "pin", "swap", "shield", "book"]
KIND_ICON = {"meal": "fork", "activity": "landmark", "transfer": "route", "flight": "plane", "hotel": "bed", "rest": "moon", "free": "clock"}
LEG_ICON = {"walk": "walk", "transit": "transit", "taxi": "taxi", "train": "transit", "bus": "transit"}
BUDGET_COLORS = {"Flights": "#9b8cff", "Hotel": "#3de0d0", "Food": "#ffb454", "Activities": "#ff6b8b", "Transport": "#36b7ff", "Buffer": "#5f6f8f"}


def ic(name: str) -> str:
    return f'<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="{_P.get(name, _P["info"])}"/></svg>'


def weather_icon(cond: str) -> str:
    c = (cond or "").lower()
    if any(k in c for k in ("thunder", "storm", "violent")):
        return "storm"
    if any(k in c for k in ("rain", "drizzle", "shower")):
        return "rain"
    if "snow" in c:
        return "snow"
    if "clear" in c or "sun" in c:
        return "sun"
    return "cloud"


def maps_link(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"


def packing_list(trip: TripState, plan: TripPlan) -> dict[str, list[str]]:
    r = trip.research
    c = trip.trip_contract
    assert r is not None and c is not None
    temps = [w.temp_min_c for w in r.weather] + [w.temp_max_c for w in r.weather]
    rainy = any(w.precipitation_probability >= 40 for w in r.weather)
    cold = temps and min(temps) < 12
    hot = temps and max(temps) > 27
    cats = set()
    for d in plan.days:
        for i in d.items:
            p = r.place(i.place_id) if i.place_id else None
            if p:
                cats |= set(p.categories)
    nights = c.nights
    out: dict[str, list[str]] = OrderedDict()
    out["Documents"] = ["Passport (valid 6+ months)", "Visa / e-Visa if required", "Flight details (printed or offline)",
                        "Hotel address in the local language", "Travel insurance policy", "Payment card + some cash"]
    out["Clothing"] = [f"{min(nights, 7)} tops", f"{max(2, min(nights, 7) // 2)} trousers/skirts", "Underwear & socks",
                       "Sleepwear", "Comfortable walking shoes"]
    out["Clothing"] += ["Warm jacket", "Sweater / fleece"] if cold else ["Light jacket for evenings"]
    if hot:
        out["Clothing"] += ["Sun hat", "Breathable clothes"]
    if rainy:
        out["Clothing"] += ["Compact umbrella", "Water-resistant jacket"]
    if "architecture" in cats or "culture" in cats:
        out["Clothing"].append("Scarf / cover-up for religious sites (shoulders and knees covered)")
    out["Electronics"] = ["Phone + charger", "Power adapter (check the plug type for your destination)",
                          "Power bank", "Offline maps downloaded"]
    if "photography" in cats or "photography" in trip.traveler_profile.activity_preferences:
        out["Electronics"] += ["Camera + spare battery", "Memory cards"]
    out["Health"] = ["Personal medication (+ prescriptions)", "Small first-aid kit", "Sunscreen", "Reusable water bottle"]
    out["Activities"] = []
    if any(i.kind == "activity" and i.indoor is False for d in plan.days for i in d.items):
        out["Activities"].append("Daypack")
    if "day_trip" in cats:
        out["Activities"].append("Snacks and water for the day trip")
    if "food" in cats:
        out["Activities"].append("Appetite and an open mind")
    return out


def documents_checklist(trip: TripState) -> list[str]:
    country = trip.research.destination_info.get("country", "your destination") if trip.research else "your destination"
    return [
        "Passport valid for at least 6 months after return",
        f"Check visa / entry requirements for {country} with your nationality",
        "Book flights, hotel and timed-entry tickets yourself (this planner does not book)",
        "Travel insurance covering medical costs",
        "Copies of passport and bookings stored offline",
        "Notify your bank about travel; check card foreign-transaction fees",
    ]


def _cost(m: Money | None, trip: TripState) -> str:
    c = trip.trip_contract
    assert c is not None and trip.research is not None
    if m is None or m.amount == 0:
        # "free" only when a source says so; a zero estimate just means no ticket is usually needed
        return "free" if m is not None and m.price_type == "known" else "<span class='faint'>usually free</span>"
    user = to_user(m, trip.research.fx_rates, c.budget.currency)
    if m.price_type == "estimated":
        est = " <span class='chip est' title='Estimate - no published price'>est.</span>"
    elif m.price_type == "calculated":
        est = f" <span class='chip' title='{e(m.source or 'Official tariff x road distance')}'>tariff</span>"
    else:
        est = f" <span class='chip' title='{e(m.source or 'Published price')}'>✓</span>"
    if m.currency.upper() == c.budget.currency.upper():
        return money(user, c.budget.currency) + est
    return f"{money(user, c.budget.currency)} <span class='faint'>({m.amount:,.0f} {e(m.currency)})</span>{est}"


def _chips(items: list[str], cls: str = "") -> str:
    return "".join(f"<span class='chip {cls}'>{e(x)}</span>" for x in items if x)


def _why(lines: list[str]) -> str:
    out = []
    for w in lines:
        if w.startswith("Trade-off:"):
            out.append(f"<li class='trade'>{e(w.replace('Trade-off: ', ''))}</li>")
        else:
            out.append(f"<li>{e(w)}</li>")
    return f"<ul class='why'>{''.join(out)}</ul>" if out else ""


def _flight_card(f, label: str, why: list[str], trip: TripState) -> str:
    if f is None:
        return ""
    dur = f"{f.duration_minutes // 60}h{f.duration_minutes % 60:02d}"
    stops = "direct" if f.stops == 0 else f"{f.stops} stop" + (f" via {e(f.via)}" if f.via else "")
    return (f"<article class='card flight reveal'><div class='k'>{label}</div>"
            f"<div class='row'><h3>{e(f.airline)}</h3><div class='price'>{_cost(f.price_per_person, trip)}<small>/ person</small></div></div>"
            f"<div class='fline'><div><b>{e(f.origin)}</b><span>{f.depart_at:%H:%M} · {f.depart_at:%a %d %b}</span></div>"
            f"<div class='fbar'><i></i></div><div class='r'><b>{e(f.destination)}</b><span>{f.arrive_at:%H:%M} · {f.arrive_at:%a %d %b}</span></div></div>"
            f"<p class='faint'>{e(f.flight_number)} · {dur} · {stops}{f' · {f.carbon_kg:g} kg CO₂' if f.carbon_kg else ''}</p>"
            + (f"<p class='faint small'>{'<br>'.join(e(s) for s in f.segments)}</p>" if len(f.segments) > 1 else "")
            + f"<p class='faint small'>{e(f.baggage)}</p>{_why(why)}"
            + (f"<a class='btn-link' href='{e(f.booking_url)}' target='_blank' rel='noopener'>{ic('link')}Check &amp; book on Google Flights</a>" if f.booking_url else "")
            + "</article>")


STOP_COLORS = ["#3de0d0", "#8b7bff", "#ff6fa3", "#6fe38a", "#4fb3ff", "#ffd166", "#ffb454"]
LEG_MODE_ICON = {"flight": "plane", "train": "transit", "coach": "transit", "car": "taxi"}


def _leg_chip(f) -> str:
    if f is None:
        return "<span class='rleg'></span>"
    what = f.airline.split(" + ")[0] if f.mode == "flight" else f.mode
    return (f"<span class='rleg {f.mode}' title='{e(f.airline)} {e(f.flight_number)} · {f.depart_at:%a %d %b %H:%M}'>"
            f"{ic(LEG_MODE_ICON.get(f.mode, 'plane'))}<small>{e(what)}</small></span>")


def _ground_card(f, label: str, trip: TripState) -> str:
    dur = f"{f.duration_minutes // 60}h{f.duration_minutes % 60:02d}"
    return (f"<article class='card flight ground reveal'><div class='k'>{label}</div>"
            f"<div class='row'><h3>{ic(LEG_MODE_ICON.get(f.mode, 'transit'))} {e(f.airline)}</h3><div class='price'>{_cost(f.price_per_person, trip)}<small>/ person</small></div></div>"
            f"<div class='fline'><div><b class='city'>{e(f.origin)}</b><span>{f.depart_at:%H:%M} · {f.depart_at:%a %d %b}</span></div>"
            f"<div class='fbar'><i></i></div><div class='r'><b class='city'>{e(f.destination)}</b><span>{f.arrive_at:%H:%M} · {f.arrive_at:%a %d %b}</span></div></div>"
            f"<p class='faint'>{dur} city centre to city centre · {e(f.metadata.provider)}</p>"
            f"<p class='faint small'>{e(f.metadata.notes or '')}</p></article>")


def place_maps_url(p: Place) -> str:
    if p.google_place_id:
        return f"https://www.google.com/maps/place/?q=place_id:{p.google_place_id}"
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(f"{p.name} {p.address}".strip())


def place_links(p: Place) -> str:
    """Where to check a place: its Google Maps page (reviews, photos, live hours), website, reservations."""
    links = [f"<a href='{e(place_maps_url(p))}' target='_blank' rel='noopener'>{ic('pin')}Google Maps</a>"]
    if p.website:
        links.append(f"<a href='{e(p.website)}' target='_blank' rel='noopener'>{ic('globe')}Website</a>")
    if p.booking_url:
        links.append(f"<a href='{e(p.booking_url)}' target='_blank' rel='noopener'>{ic('link')}"
                     f"{'Tickets' if p.kind == 'attraction' else 'Reserve'}</a>")
    return f"<div class='place-links'>{''.join(links)}</div>"


def _hotel_card(h, why: list[str], nights: int, trip: TripState, stay=None, searched: int | None = None) -> str:
    """`stay`: the (check-in, check-out) dates the flights need; `searched`: the nights the rate was searched for -
    when they differ (a next-day landing), the provider's stay total is for other dates and is not shown."""
    c = trip.trip_contract
    tags = ([f"{'★' * h.stars}"] if h.stars else []) + [f"{h.rating}/5 · {h.reviews_count:,} reviews",
            "breakfast included" if h.breakfast_included else "breakfast not listed", h.cancellation_policy,
            f"noise from reviews: {h.noise_level}", h.neighborhood]
    shorter = searched is not None and nights != searched
    dates = f" · {stay[0]:%a %d %b} → {stay[1]:%a %d %b}" if stay and stay[0] and stay[1] and shorter else ""
    return (
        "<article class='card hotel reveal'>"
        + (f"<div class='hotel-img' style=\"background-image:url('{e(h.images[0])}')\"></div>" if h.images else "")
        + f"<div class='hotel-body'><div class='row'><h3>{e(h.name)}</h3><div class='price'>{_cost(h.price_per_night, trip)}<small>/ night</small></div></div>"
        f"<div class='chips'>{_chips(tags)}</div>"
        f"<p class='faint'>{c.rooms} room{'s' if c.rooms > 1 else ''} × {nights} night{'s' if nights > 1 else ''}{dates}"
        f"{' · stay total ' + _cost(h.total_price, trip) if h.total_price and not shorter else ''}"
        f"{' · check-in ' + e(h.check_in_time) if h.check_in_time else ''}{' · check-out ' + e(h.check_out_time) if h.check_out_time else ''}</p>"
        + (f"<blockquote>“{e(h.noise_evidence[0][:280])}”<cite>a recent guest review</cite></blockquote>" if h.noise_evidence else "")
        + _why(why)
        + (f"<p class='faint small'>Amenities: {e(', '.join(h.amenities[:12]))}</p>" if h.amenities else "")
        + "<div class='links'>"
        # Straight to the booking page at the planned price (the live offer for these dates).
        + f"<a class='btn-link' href='/api/trips/{e(trip.trip_id)}/hotel-offers/go?hotel_id={e(h.id)}' target='_blank' rel='noopener'>{ic('link')}Book at this price</a>"
        + (f"<a class='btn-link' href='{e(h.link)}' target='_blank' rel='noopener'>{ic('globe')}Hotel website</a>" if h.link else "")
        + f"<a class='btn-link' href='{maps_link(h.location.lat, h.location.lon)}' target='_blank' rel='noopener'>{ic('pin')}Open in Maps</a></div></div></article>")


def _donut(parts: list[tuple[str, float]], total: float, center_top: str, center_sub: str) -> str:
    r, circ = 78, 2 * 3.14159265 * 78
    off, arcs = 0.0, []
    for name, v in parts:
        length = v / max(total, 1) * circ
        arcs.append(f"<circle cx='100' cy='100' r='{r}' stroke='{BUDGET_COLORS[name]}' "
                    f"data-dash='{max(length - 2, 0):.1f} {circ:.1f}' stroke-dasharray='0 {circ:.1f}' stroke-dashoffset='{-off:.1f}'/>")
        off += length
    return (f"<div class='donut'><svg viewBox='0 0 200 200'>{''.join(arcs)}</svg>"
            f"<div class='dc'><b>{center_top}</b><span>{center_sub}</span></div></div>")


def build_sections(trip: TripState) -> "OrderedDict[str, str]":
    """Section title -> HTML fragment."""
    c, r, plan, p = trip.trip_contract, trip.research, trip.selected_plan, trip.traveler_profile
    if c is None or r is None or plan is None:
        raise ValueError("Trip has no plan yet")
    info = r.destination_info
    kn = info.get("knowledge", {})
    secs = kn.get("sections", {})
    b = plan.budget
    s: "OrderedDict[str, str]" = OrderedDict()

    # 01 Overview -----------------------------------------------------------
    score = plan.score
    bars = ""
    if score:
        labels = {"budget_fit": "Budget fit", "comfort": "Comfort", "food": "Food", "activities": "Activities",
                  "transportation": "Transport", "personal_fit": "Personal fit", "schedule_quality": "Schedule"}
        bars = "<div class='scorebars'>" + "".join(
            f"<div><span>{labels[k]}</span><i><b style='--w:{v}%'></b></i><em>{v}</em></div>"
            for k, v in score.model_dump().items() if k in labels) + "</div>"
    highlights = [i.title for d in plan.days for i in d.items if i.kind == "activity"][:6]
    multi = bool(plan.stops)
    stop_infos = [x.destination_info for x in r.stops] if r.stops else [info]
    if multi:
        where = (f"across <b>{e(', '.join(x.name for x in plan.stops[:-1]))} and {e(plan.stops[-1].name)}</b> "
                 f"({e(' · '.join(dict.fromkeys(x.country for x in plan.stops if x.country)))})")
    else:
        where = f"in <b>{e(display_name(c.destination_name, info.get('country', '')))}</b>, {e(info.get('country', ''))}"
    route = ""
    if multi:
        route = ("<div class='route'>" + f"<span class='rstop home'><b>{e(c.origin_city)}</b><small>home</small></span>" + "".join(
            f"{_leg_chip(plan.legs[i] if i < len(plan.legs) else None)}<a class='rstop' href='#day{x.first_day}' style='--c:{STOP_COLORS[(i + 1) % len(STOP_COLORS)]}'>"
            f"<i>{i + 1}</i><b>{e(x.name)}</b><small>{x.nights} night{'s' if x.nights > 1 else ''} · {x.start_date:%d %b}</small></a>"
            for i, x in enumerate(plan.stops)) + _leg_chip(plan.legs[-1] if plan.legs else None)
            + f"<span class='rstop home'><b>{e(c.origin_city)}</b><small>home</small></span></div>")
    s["Trip Overview"] = route + (
        f"<p class='lead'>{c.num_days} days {where} — "
        f"{c.start_date:%A %d %B} to {c.end_date:%A %d %B %Y}, {c.travelers} traveler{'s' if c.travelers > 1 else ''} from {e(c.origin_city)}. "
        f"The <b>{e(plan.mode)}</b> plan was researched from live data, optimized day by day and validated before this book was made.</p>"
        f"<div class='grid2'><div class='card'><div class='k'>TripScore breakdown</div>{bars}</div>"
        f"<div class='card'><div class='k'>Highlights</div><div class='chips'>{_chips(highlights, 'hl')}</div>"
        f"<div class='k' style='margin-top:16px'>Validation</div><p>{ic('shield')} "
        f"{'All hard checks passed.' if plan.validation and plan.validation.result == 'PASS' else 'Some checks need attention - see Important Notes.'}</p></div></div>")

    # 02 Profile ------------------------------------------------------------
    rows = [("Pace", p.travel_style.replace("_", " ")), ("Days start", p.preferred_wake_up_time),
            ("Walking", p.walking_tolerance), ("Flights", ("direct preferred" if p.flight_preference == "direct" else "any")
                                                + (" · no early departures" if p.avoid_early_flights else "")),
            ("Noise tolerance", p.noise_tolerance), ("Nightlife", p.nightlife_interest)]
    learned = [f"{k.replace('_', ' ')}: {v.value} ({v.confidence:.0%})" for k, v in p.learned.items()]
    s["Traveler Profile"] = (
        "<div class='grid2'><div class='card'><dl class='kv'>" + "".join(f"<dt>{e(k)}</dt><dd>{e(str(v))}</dd>" for k, v in rows) + "</dl></div>"
        f"<div class='card'><div class='k'>Interests</div><div class='chips'>{_chips(p.activity_preferences) or '<span class=faint>-</span>'}</div>"
        f"<div class='k' style='margin-top:12px'>Food</div><div class='chips'>{_chips(p.food_preferences + p.dietary_restrictions) or '<span class=faint>-</span>'}</div>"
        f"<div class='k' style='margin-top:12px'>Must-have / avoid</div><div class='chips'>{_chips(c.must_have, 'ok')}{_chips(p.avoid_categories + c.avoid, 'bad')}</div>"
        + (f"<div class='k' style='margin-top:12px'>Learned from your feedback</div><div class='chips'>{_chips(learned, 'violet')}</div>" if learned else "")
        + "</div></div>")

    # 03 Flights ------------------------------------------------------------
    alt_f = [x for x in r.flights_outbound + r.flights_return
             if x.id in plan.alternatives.get("outbound_flights", []) + plan.alternatives.get("return_flights", [])]
    if multi:
        names = [c.origin_city] + [x.name for x in plan.stops] + [c.origin_city]
        cards = []
        for i, f in enumerate(plan.legs):
            label = f"Leg {i + 1} · {e(names[i])} → {e(names[i + 1])}"
            why = plan.explanations.get("outbound_flight" if i == 0 else "return_flight" if i == len(plan.legs) - 1 else "", [])
            cards.append(_flight_card(f, label, why, trip) if f.mode == "flight" else _ground_card(f, label, trip))
        s["Journey"] = ("<div class='grid2'>" + "".join(cards) + "</div>"
                        "<p class='faint small'>Flights are real Google Flights fares found at planning time. Trains and coaches use "
                        "Google Maps travel times; their departure slots and fares are estimates - check the operator before booking.</p>")
    else:
        s["Flights"] = ("<div class='grid2'>"
                    + _flight_card(plan.outbound_flight, "Outbound", plan.explanations.get("outbound_flight", []), trip)
                    + _flight_card(plan.return_flight, "Return", plan.explanations.get("return_flight", []), trip) + "</div>"
                    + ("<h4>Other options considered</h4><div class='table'><table><tr><th>Direction</th><th>Flight</th><th>Times</th><th>Stops</th><th>Price pp</th></tr>"
                       + "".join(f"<tr><td>{e(x.direction.title())}</td><td>{e(x.airline)} {e(x.flight_number)}</td>"
                                 f"<td>{x.depart_at:%H:%M} → {x.arrive_at:%H:%M}</td><td>{'direct' if x.stops == 0 else x.stops}</td>"
                                 f"<td>{_cost(x.price_per_person, trip)}</td></tr>" for x in alt_f) + "</table></div>" if alt_f else ""))

    # 04 Hotel --------------------------------------------------------------
    h = plan.hotel
    if multi:
        s["Hotels"] = "".join(
            f"<h4 class='cityh' style='--c:{STOP_COLORS[(i + 1) % len(STOP_COLORS)]}'><i>{i + 1}</i>{e(x.name)} · {x.nights} night{'s' if x.nights > 1 else ''} "
            f"<span class='faint'>{x.start_date:%a %d %b} → {x.end_date:%a %d %b}</span></h4>"
            + (_hotel_card(x.hotel, x.explanations, x.hotel_nights, trip, (x.check_in, x.check_out), x.nights)
               if x.hotel else "<p class='faint'>No hotel found for these dates.</p>")
            for i, x in enumerate(plan.stops))
    elif h:
        alt_h = [x for x in r.hotels if x.id in plan.alternatives.get("hotels", [])]
        s["Hotel"] = (
            _hotel_card(h, plan.explanations.get("hotel", []), plan.hotel_nights(c.nights), trip,
                        (plan.hotel_check_in, plan.hotel_check_out), c.nights)
            + ("<h4>Alternatives</h4><div class='table'><table><tr><th>Hotel</th><th>Rating</th><th>Location</th><th>Night</th></tr>"
               + "".join(f"<tr><td>{e(x.name)}</td><td>{x.rating}/5</td><td>{e(x.neighborhood)}</td><td>{_cost(x.price_per_night, trip)}</td></tr>"
                         for x in alt_h) + "</table></div>" if alt_h else ""))

    # 05 Destination --------------------------------------------------------
    if multi:
        blocks = []
        for i, (x, inf) in enumerate(zip(plan.stops, stop_infos)):
            k = inf.get("knowledge", {})
            sx = k.get("sections", {})
            blocks.append(
                f"<h4 class='cityh' style='--c:{STOP_COLORS[(i + 1) % len(STOP_COLORS)]}'><i>{i + 1}</i>{e(x.name)} <span class='faint'>{e(x.country)}</span></h4>"
                f"<p class='lead{' dropcap' if i == 0 else ''}'>{e(k.get('overview', ''))}</p>"
                + "".join(f"<details class='card acc'><summary>{e(name)} · {e(x.name)}</summary><p>{e(sx[name][:1200])}{'…' if len(sx[name]) > 1200 else ''}</p></details>"
                          for name in ("Understand", "Eat") if sx.get(name))
                + (f"<p class='faint small'>Source: <a href='{e(k['source_url'])}' target='_blank' rel='noopener'>{e(k.get('source', 'Wikivoyage'))}</a></p>" if k.get("source_url") else ""))
        s["Destination Overview"] = "".join(blocks)
    else:
        s["Destination Overview"] = (
        f"<p class='lead dropcap'>{e(kn.get('overview', ''))}</p>"
        + "".join(f"<details class='card acc'><summary>{e(name)}</summary><p>{e(secs[name][:1400])}{'…' if len(secs[name]) > 1400 else ''}</p></details>"
                  for name in ("Understand", "Districts", "Eat", "Drink") if secs.get(name))
        + (f"<p class='faint small'>Source: <a href='{e(kn['source_url'])}' target='_blank' rel='noopener'>{e(kn.get('source', 'Wikivoyage'))}</a></p>" if kn.get("source_url") else ""))

    # 06 Itinerary ----------------------------------------------------------
    days_html = []
    for d in plan.days:
        w = d.weather
        n = 0
        rows_ = []
        for i in d.items:
            leg = i.transport_from_previous
            if leg and i.kind != "transfer":
                rows_.append(f"<div class='leg'>{ic(LEG_ICON.get(leg.mode, 'route'))}{leg.minutes} min {e(leg.mode)} · {leg.distance_km:.1f} km"
                             + (f" · {_cost(leg.cost, trip)}" if leg.cost.amount else "") + "</div>")
            numbered = i.location is not None and i.kind in ("activity", "meal")
            if numbered:
                n += 1
            extra = []
            if i.explanation:
                extra.append(f"<b>Why:</b> {' · '.join(e(x) for x in i.explanation[:4])}")
            if i.notes:
                extra.append(e(i.notes))
            if i.alternatives:
                extra.append(f"<b>Alternatives:</b> {e(', '.join(i.alternatives))}")
            dot = str(n) if numbered else ic(KIND_ICON.get(i.kind, "info"))
            rows_.append(f"<div class='ti {i.kind}'><span class='dot'>{dot}</span><div class='th'><time>{i.start}–{i.end}</time>"
                         f"<span class='cost'>{_cost(i.cost, trip) if i.cost.amount else ''}</span></div>"
                         f"<div class='tt'>{e(i.title)}"
                         + (" <span class='chip amber'>★ you asked</span>" if i.explanation[:1] == ["You asked to visit this place"] else "")
                         + "</div>"
                         + (f"<details class='more'><summary>details</summary>{'<br>'.join(extra)}</details>" if extra else "") + "</div>")
        meta = [f"<span class='chip'>{ic(weather_icon(w.condition))}{e(w.condition)} · {w.temp_min_c:.0f}–{w.temp_max_c:.0f}°C</span>" if w else "",
                f"<span class='chip'>{ic('walk')}{d.walking_km:.1f} km walking</span>",
                f"<span class='chip'>{ic('coins')}{money(d.estimated_cost.amount, d.estimated_cost.currency)}</span>"]
        stop_i = next((k for k, x in enumerate(plan.stops) if x.name == d.city), None) if multi else None
        city_tag = ""
        if stop_i is not None:
            city_tag = (f" · <span class='citytag' style='--c:{STOP_COLORS[(stop_i + 1) % len(STOP_COLORS)]}'>"
                        f"{'✈ travel day → ' if d.travel_day else ''}{e(d.city)}</span>")
        days_html.append(
            f"<article class='daycard reveal{' travel' if d.travel_day else ''}' id='day{d.day}'><header><div class='dnum'><span>Day</span><b>{d.day:02d}</b></div>"
            f"<div><p class='eyebrow'>{d.date:%A · %d %B}{city_tag}</p><h3>{e(d.title)}</h3><div class='chips'>{''.join(meta)}</div></div></header>"
            + "".join(f"<p class='note'>{ic('alert')}{e(x)}</p>" for x in d.notes)
            + f"<div class='daygrid'><div class='daymap' data-day='{d.day}'></div><div class='timeline'>{''.join(rows_)}</div></div></article>")
    s["Daily Itinerary"] = ("<nav class='daynav'>" + "".join(
        f"<a href='#day{d.day}'>Day {d.day}<span>{d.date:%a %d}{(' · ' + e(d.city)) if multi and d.city else ''}</span></a>" for d in plan.days)
                            + "</nav>" + "".join(days_html))

    # 07 Restaurants --------------------------------------------------------
    used: dict[str, tuple[Place, set[str]]] = {}
    for d in plan.days:
        for i in d.items:
            if i.kind == "meal" and i.place_id:
                pl = r.place(i.place_id)
                if pl:
                    used.setdefault(pl.id, (pl, set()))[1].add(i.meal_type or "")
    s["Restaurants"] = "<div class='cards'>" + "".join(
        f"<article class='card mini reveal'><div class='row'><h4>{e(pl.name)}</h4><span class='rating'>{ic('star')}{pl.rating}</span></div>"
        f"<div class='chips'>{_chips(sorted(m), 'amber')}{_chips(pl.cuisine[:3])}{"<span class='chip'>reserve</span>" if pl.requires_reservation else ''}</div>"
        f"<p class='faint small'>{e(pl.neighborhood or pl.address[:60])} · ~{_cost(pl.cost_per_person, trip)} pp</p>"
        f"{place_links(pl)}</article>"
        for pl, m in used.values()) + "</div>"

    # 08 Activities ---------------------------------------------------------
    planned = {i.place_id for d in plan.days for i in d.items if i.kind == "activity"}
    groups = OrderedDict([("Must see", "must_see"), ("Popular", "popular"), ("Local favorites", "local_favorite"), ("Hidden gems", "hidden_gem")])
    act = []
    for label, key in groups.items():
        items = [a for a in r.attractions if a.popularity == key and "overnight_trip" not in a.categories]
        if items:
            act.append(f"<h4>{label}</h4><div class='cards'>" + "".join(
                f"<article class='card mini reveal {'inplan' if a.id in planned else ''}'>"
                f"<div class='row'><h4>{e(a.name)}</h4>{"<span class='chip ok'>in plan</span>" if a.id in planned else ''}</div>"
                f"<p class='faint small'>{a.duration_minutes} min · {_cost(a.cost_per_person, trip)} pp"
                f"{' · day trip ' + format(a.distance_km, '.0f') + ' km' if a.day_trip else ''}"
                f"{' · book ahead' if a.requires_reservation else ''}</p>"
                f"<p class='small'>{e((a.description or '')[:160])}</p>{place_links(a)}</article>" for a in items) + "</div>")
    far = [a for a in r.attractions if "overnight_trip" in a.categories]
    if far:
        act.append("<h4>Worth an overnight side trip</h4><div class='chips'>" + _chips([f"{a.name} · ~{a.distance_km:.0f} km" for a in far], "violet") + "</div>")
    s["Activities"] = "".join(act)

    # 09 Transportation -----------------------------------------------------
    legs = [i.transport_from_previous for d in plan.days for i in d.items if i.transport_from_previous]
    by_mode: dict[str, int] = {}
    for leg in legs:
        by_mode[leg.mode] = by_mode.get(leg.mode, 0) + 1
    s["Transportation"] = (
        "<div class='cards'>" + "".join(
            f"<article class='card mini reveal'><div class='row'><h4>{ic('taxi' if t.mode == 'taxi' else 'transit')}{e(t.name)}</h4></div>"
            f"<p class='big'>~{t.minutes} min</p><p class='faint small'>{_cost(t.cost_per_person, trip) + ' per person' if t.cost_per_person else _cost(t.cost_per_vehicle, trip) + ' per vehicle'}</p>"
            f"<p class='small'>{e(t.notes)}</p></article>" for t in r.airport_transfers) + "</div>"
        f"<div class='chips' style='margin:14px 0'>{_chips([f'{n} × {m}' for m, n in by_mode.items()])}</div>"
        + (f"<details class='card acc'><summary>Getting around (Wikivoyage)</summary><p>{e(secs.get('Get around', '')[:1600])}</p></details>" if secs.get("Get around") else ""))

    # 10-11 Budget ----------------------------------------------------------
    if b:
        parts = [(k, v) for k, v in (("Flights", b.flights), ("Hotel", b.hotel), ("Food", b.food), ("Activities", b.activities),
                                     ("Transport", b.transport), ("Buffer", b.buffer)) if v > 0]
        pct = min(100, b.total / max(b.limit, 1) * 100)
        s["Budget"] = (
            f"<div class='budget'>{_donut(parts, b.total, money(b.total, b.currency), 'of ' + money(b.limit, b.currency))}"
            "<div class='legend'>" + "".join(f"<div><i style='background:{BUDGET_COLORS[k]}'></i><span>{k}</span><b>{money(v, b.currency)}</b></div>" for k, v in parts)
            + f"<div class='meter'><i class='{'over' if b.remaining < 0 else ''}' style='--w:{pct:.0f}%'></i></div>"
            f"<p class='{'ok' if b.remaining >= 0 else 'bad'}'>{'Within budget - ' + money(b.remaining, b.currency) + ' left' if b.remaining >= 0 else 'Over budget by ' + money(-b.remaining, b.currency)}</p></div></div>"
            + "".join(f"<p class='faint small'>{e(n)}</p>" for n in b.notes))
        days = list(b.daily_spending.items())
        mx = max([v for _, v in days] + [1])
        s["Estimated Daily Spending"] = ("<div class='bars'>" + "".join(
            f"<div><em>{money(v, b.currency)}</em><i style='--h:{v / mx * 100:.0f}%'></i><span>{k[5:]}</span></div>" for k, v in days)
            + "</div><p class='faint small'>Excludes flights and hotel (paid up front).</p>")

    # 12-13 Checklists ------------------------------------------------------
    def checklist(group: str, items: list[str]) -> str:
        return "".join(f"<label class='check'><input type='checkbox' data-key='{e(group)}:{e(x)}'><span></span>{e(x)}</label>" for x in items)

    s["Packing List"] = ("<p class='faint small'>Tick items as you pack - this page remembers them.</p><div class='cards'>" + "".join(
        f"<div class='card mini'><h4>{e(k)}</h4>{checklist(k, v)}</div>" for k, v in packing_list(trip, plan).items() if v) + "</div>")
    s["Documents Checklist"] = f"<div class='card'>{checklist('docs', documents_checklist(trip))}</div>"

    # 14 Weather ------------------------------------------------------------
    s["Weather Expectations"] = ("<div class='wx'>" + "".join(
        f"<div class='wxc {weather_icon(w.condition)} reveal'><span>{w.date:%a %d}</span>{ic(weather_icon(w.condition))}"
        f"<b>{w.temp_max_c:.0f}°<small> {w.temp_min_c:.0f}°</small></b><span>{e(w.condition)}</span><span>{w.precipitation_probability}% rain</span></div>"
        for w in r.weather) + "</div>"
        f"<p class='faint small'>Source: {e(r.weather[0].metadata.provider) if r.weather else '-'}"
        f"{'. Dates beyond the 15-day forecast show last year’s observed weather.' if any(w.metadata.confidence < 0.6 for w in r.weather) else ''}</p>")

    # 15-17 Knowledge -------------------------------------------------------
    if multi:
        # One knowledge block per city / country of the journey.
        tips, phr, sos = [], [], []
        seen_books, seen_countries = set(), set()
        for x, inf in zip(plan.stops, stop_infos):
            k = inf.get("knowledge", {})
            if k.get("local_tips"):
                tips.append(f"<h4>{e(x.name)}</h4><div class='cards'>" + "".join(
                    f"<div class='card mini tip reveal'>{ic('info')}<p>{e(t)}</p></div>" for t in k["local_tips"][:4]) + "</div>")
            book = k.get("phrasebook")
            if k.get("phrases") and book not in seen_books:
                seen_books.add(book)
                phr.append(f"<h4>{e(', '.join(inf.get('languages', [])) or x.country)} <span class='faint'>· {e(x.country)}</span></h4>"
                           "<div class='phrases'>" + "".join(f"<div class='phrase reveal'><span>{e(a)}</span><b>{e(b_)}</b></div>"
                                                             for a, b_ in k["phrases"][:10]) + "</div>")
            if x.country not in seen_countries:
                seen_countries.add(x.country)
                sos.append(f"<div class='card sos'>{ic('alert')}<div><h4>{e(x.country)}</h4>" + "".join(f"<p>{e(y)}</p>" for y in k.get("emergency", []))
                           + f"<p>{e(k.get('emergency_note', ''))}</p></div></div>")
        s["Local Tips"] = "".join(tips) + "<p class='faint small'>From Wikivoyage.</p>"
        s["Useful Phrases"] = "".join(phr) or "<p class='faint'>No phrasebook was found for these countries.</p>"
        s["Emergency Information"] = "".join(sos) + "<p class='faint small'>Save your embassy's contact details and each hotel's address before you travel.</p>"
    else:
        s["Local Tips"] = ("<div class='cards'>" + "".join(f"<div class='card mini tip reveal'>{ic('info')}<p>{e(t)}</p></div>" for t in kn.get("local_tips", [])) + "</div>"
                           + (f"<details class='card acc'><summary>Respect</summary><p>{e(secs['Respect'][:1400])}</p></details>" if secs.get("Respect") else "")
                           + "<p class='faint small'>From Wikivoyage.</p>")
        langs = ", ".join(info.get("languages", [])) or "the local language"
        phrases = kn.get("phrases", [])
        s["Useful Phrases"] = (f"<p>Language: <b>{e(langs)}</b></p>"
                               + ("<div class='phrases'>" + "".join(f"<div class='phrase reveal'><span>{e(a)}</span><b>{e(b_)}</b></div>" for a, b_ in phrases) + "</div>"
                                  + f"<p class='faint small'>From the Wikivoyage {e(kn.get('phrasebook') or '')}.</p>"
                                  if phrases else "<p class='faint'>English is widely used for travel here, or no phrasebook was found.</p>"))
        em = kn.get("emergency", [])
        s["Emergency Information"] = (f"<div class='card sos'>{ic('alert')}<div>" + "".join(f"<p>{e(x)}</p>" for x in em)
                                      + f"<p>{e(kn.get('emergency_note', ''))}</p><p class='faint small'>Save your embassy's contact details and your hotel address before you travel.</p></div></div>"
                                      + (f"<details class='card acc'><summary>Stay safe (Wikivoyage)</summary><p>{e(secs['Stay safe'][:1400])}</p></details>" if secs.get("Stay safe") else ""))

    # 18 Maps ---------------------------------------------------------------
    hotels_all = [x.hotel for x in plan.stops if x.hotel] if multi else ([h] if h else [])
    places = [(f"Hotel · {x.name}", x.location.lat, x.location.lon) for x in hotels_all]
    seen = set()
    for d in plan.days:
        for i in d.items:
            if i.place_id and i.location and i.place_id not in seen:
                seen.add(i.place_id)
                places.append((i.title.split(" - ")[-1], i.location.lat, i.location.lon))
    s["Maps / Locations"] = "<div class='linkgrid'>" + "".join(
        f"<a href='{maps_link(la, lo)}' target='_blank' rel='noopener'>{ic('pin')}<span>{e(n)}</span></a>" for n, la, lo in places) + "</div>"

    # 19 Alternatives -------------------------------------------------------
    alt_rows = "".join(
        f"<tr class='{'sel' if m == trip.selected_mode else ''}'><td>{e(m.title())}</td><td>{money(x.budget.total, x.budget.currency) if x.budget else '-'}</td>"
        f"<td>{x.score.total if x.score else '-'}</td><td>{'yes' if x.within_budget else 'no'}</td>"
        f"<td>{e(' · '.join(y.hotel.name for y in x.stops if y.hotel)) if x.stops else (e(x.hotel.name) if x.hotel else '-')}</td></tr>"
        for m, x in trip.plans.items())
    indoor = [a.name for a in r.attractions if a.indoor][:6]
    s["Alternatives"] = ("<div class='table'><table><tr><th>Plan</th><th>Total</th><th>TripScore</th><th>In budget</th><th>Hotel</th></tr>" + alt_rows + "</table></div>"
                         f"<h4>Rain plan</h4><div class='chips'>{_chips(indoor)}</div>")

    # 20 Notes --------------------------------------------------------------
    notes = ["Nothing has been booked. Use the details here to book directly with each provider.",
             "Prices and availability were retrieved at planning time and change often - re-check before booking.",
             "Opening hours can change on holidays; timed-entry sights must be reserved in advance.",
             *(v.message for v in (plan.validation.violations if plan.validation else [])), *trip.assumptions]
    s["Important Notes"] = "<ul class='notes'>" + "".join(f"<li>{e(x)}</li>" for x in notes) + "</ul>"

    # 21 Sources ------------------------------------------------------------
    sources: dict[str, tuple[str, float]] = {}  # provider -> (retrieved, confidence); internals stay hidden
    ents = (r.flights_outbound[:1] + r.flights_return[:1] + r.hotels[:1] + r.restaurants[:1] + r.attractions
            + r.weather[:1] + r.airport_transfers[:1])
    for ent in ents:
        m = ent.metadata
        sources[m.provider] = (m.retrieved_at.isoformat(timespec="minutes"), m.confidence)
    if r.fx_metadata:
        m = r.fx_metadata
        sources[m.provider] = (m.retrieved_at.isoformat(timespec="minutes"), m.confidence)
    s["Sources / Data Timestamps"] = (
        "<div class='table'><table><tr><th>Source</th><th>Updated (UTC)</th><th>Confidence</th></tr>" + "".join(
            f"<tr><td>{e(prov)}</td><td>{at.replace('T', ' ')[:16]}</td><td><i class='conf' style='--w:{conf * 100:.0f}%'></i>{conf:.0%}</td></tr>"
            for prov, (at, conf) in sources.items()) + f"</table></div><p class='faint small'>Trip Book generated {utcnow():%Y-%m-%d %H:%M} UTC.</p>")
    return s


def display_name(name: str, country: str) -> str:
    """City name without a trailing country ("Riyadh Saudi Arabia" -> "Riyadh")."""
    if country and name.lower().endswith(" " + country.lower()):
        return name[: -len(country)].strip()
    return name


def _book_data(trip: TripState) -> dict:
    c, plan = trip.trip_contract, trip.selected_plan
    ref = lambda x: {"lat": x.lat, "lon": x.lon, "name": display_name(x.name, x.country)} if x else None  # noqa: E731
    hot = lambda h: {"lat": h.location.lat, "lon": h.location.lon, "name": h.name} if h else None  # noqa: E731
    by_city = {x.name: x for x in plan.stops}
    days = []
    for d in plan.days:
        stop = by_city.get(d.city)
        pts, n = [], 0
        for i in d.items:
            if i.location and i.kind in ("activity", "meal"):
                n += 1
                pts.append({"lat": i.location.lat, "lon": i.location.lon, "n": n, "kind": i.kind, "title": f"{i.start} · {i.title}"})
        if d.travel_day and stop:
            # Moving day: map the arrival city's part (the journey itself is on the globe).
            pts = [p for p in pts if abs(p["lat"] - stop.location.lat) + abs(p["lon"] - stop.location.lon) < 1.0]
        days.append({"day": d.day, "points": pts, "hotel": hot(stop.hotel) if stop else None,
                     "center": {"lat": stop.location.lat, "lon": stop.location.lon} if stop else None})
    center = trip.research.destination_info.get("center")
    stops = [{"lat": x.location.lat, "lon": x.location.lon, "name": x.name} for x in plan.stops] or [ref(c.destination_ref)]
    return {"trip_id": trip.trip_id, "origin": ref(c.origin_ref), "dest": ref(c.destination_ref), "stops": stops,
            "hotel": hot(plan.hotel), "center": center, "days": days}


def render_html(trip: TripState) -> str:
    c, plan = trip.trip_contract, trip.selected_plan
    assert c is not None and plan is not None
    sections = build_sections(trip)
    b, score = plan.budget, plan.score
    toc = "".join(f"<a href='#s{n}' data-target='s{n}'><em>{n:02d}</em>{ic(SECTION_ICON[n - 1])}<span>{e(t)}</span></a>"
                  for n, t in enumerate(sections, 1))
    body = "".join(
        f"<section class='sec' id='s{n}'><header class='sech'><span class='secn'>{n:02d}</span>{ic(SECTION_ICON[n - 1])}<h2>{e(t)}</h2></header>{frag}</section>"
        for n, (t, frag) in enumerate(sections.items(), 1))
    circ = 2 * 3.14159265 * 52
    ring = (f"<div class='ring'><svg viewBox='0 0 120 120'><circle class='bg' cx='60' cy='60' r='52'/>"
            f"<circle class='fg' cx='60' cy='60' r='52' stroke-dasharray='{circ:.1f}' stroke-dashoffset='{circ:.1f}' "
            f"data-target='{circ * (1 - (score.total if score else 0) / 100):.1f}'/></svg><b>{score.total if score else '-'}</b><span>TripScore</span></div>")
    country = trip.research.destination_info.get("country", "")
    city = display_name(c.destination_name, country)
    if plan.stops:
        city = " · ".join(x.name for x in plan.stops)
        country = " · ".join(dict.fromkeys(x.country for x in plan.stops if x.country))
    kpis = (f"<div class='kpi'><span>Total</span><b>{money(b.total, b.currency)}</b><em>of {money(c.budget.amount, c.budget.currency)}</em></div>"
            f"<div class='kpi'><span>Days</span><b>{c.num_days}</b><em>{c.nights} nights</em></div>"
            f"<div class='kpi'><span>Travelers</span><b>{c.travelers}</b><em>from {e(c.origin_city)}</em></div>"
            f"<div class='kpi'><span>Plan</span><b>{e(plan.mode.title())}</b><em>{'validated' if plan.validation and plan.validation.result == 'PASS' else 'check notes'}</em></div>")
    data = json.dumps(_book_data(trip)).replace("</", "<\\/")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dalili · Trip Book · {e(city)}</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<meta name="description" content="Trip Book for {e(c.destination_name)}: itinerary, flights, hotel, budget and travel info.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/vendor/leaflet.css"><link rel="stylesheet" href="/static/book.css">
<script type="importmap">{{"imports":{{"three":"/static/vendor/three.module.min.js","three/addons/":"/static/vendor/"}}}}</script>
<script>try{{const s=localStorage.getItem("theme");document.documentElement.dataset.theme=s||(matchMedia("(prefers-color-scheme: light)").matches?"light":"dark")}}catch(_){{document.documentElement.dataset.theme="dark"}}</script>
</head><body>
<canvas id="globe" aria-hidden="true"></canvas><div id="globeLabels" class="globe-labels" aria-hidden="true"></div>
<div class="progress" aria-hidden="true"><i id="progress"></i></div>
<header class="cover">
  <div class="cover-inner">
    <a class="back" href="/">{ic('back')}Back to planner</a><button class="theme-btn" id="themeToggle" type="button" aria-label="Light / dark mode">{ic('sun').replace('class="i"', 'class="i i-sun"')}{ic('moon').replace('class="i"', 'class="i i-moon"')}</button>
    <p class="eyebrow">Trip Book · planned by Dalili · not a booking</p>
    <h1{" class='multi'" if plan.stops else ""}>{e(city)}<span>{e(country)}</span></h1>
    <p class="dates">{c.start_date:%a %d %b} → {c.end_date:%a %d %b %Y}</p>
    <div class="cover-kpis">{ring}<div class="kpis">{kpis}</div></div>
    <div class="cover-actions"><a class="btn primary" href="#s6">{ic('route')}Day by day</a>
      <button class="btn" type="button" id="printBook">{ic('print')}Print / save PDF</button></div>
  </div>
  <a class="scroll-hint" href="#s1" aria-label="Scroll to the book"><span></span></a>
</header>
<div class="book">
  <nav class="toc" aria-label="Contents"><div class="toc-title">Contents</div>{toc}</nav>
  <main>{body}<footer class="end">{ic('globe')}<p>Have a wonderful trip to {e(city)}.<br><span class="faint">Everything here was researched live and validated; bookings are yours to make.</span></p></footer></main>
</div>
<script id="book-data" type="application/json">{data}</script>
<script src="/static/vendor/leaflet.js"></script>
<script type="module" src="/static/js/book.js"></script>
</body></html>"""

