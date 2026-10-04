"""HTTP API + static UI.

Run:  uvicorn travel_agent.api:app --reload
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import llm, seo, tripbook
from .auth import GUEST_COOKIE, GUEST_RE, SESSION_COOKIE, SESSION_DAYS, Accounts, AuthError, Identity, new_guest_id
from .config import PROJECT_DIR, settings
from .mcp_hub import SERVERS, get_hub
from .nlu import Action
import httpx

from .service import TravelAgentService

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
# httpx logs full request URLs at INFO, and several providers take the API key as a query
# parameter - keep keys out of the logs.
for noisy in ("httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

app = FastAPI(title="Dalili", version="0.1.0",
              description="Plans, researches, optimizes and validates complete trips. It never books anything.")
service = TravelAgentService()
accounts = Accounts(service.store)
FRONTEND = PROJECT_DIR / "frontend"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def web_basics(request: Request, call_next):
    """Cross-site request guard, the guest cookie, security headers and UI revalidation."""
    path = request.url.path
    # A state-changing API call must come from this site (SameSite cookies already block most cross-site
    # requests; this also covers browsers and cases where they don't).
    origin = request.headers.get("origin")
    if request.method in UNSAFE and path.startswith("/api/") and origin:
        from urllib.parse import urlsplit

        if urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
    # Everyone gets a guest id, so trips have an owner before (or without) an account.
    # The mobile app keeps its own guest id and sends it as a header instead of a cookie.
    header_guest = request.headers.get("x-guest-id")
    guest = header_guest if header_guest and GUEST_RE.match(header_guest) else request.cookies.get(GUEST_COOKIE)
    new_guest = None
    if not guest or not GUEST_RE.match(guest):
        new_guest = guest = new_guest_id()
    request.state.guest_id = guest
    response = await call_next(request)
    if new_guest:
        response.set_cookie(GUEST_COOKIE, new_guest, max_age=365 * 86400, httponly=True, samesite="lax",
                            secure=request.url.scheme == "https", path="/")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if not path.endswith("/book"):
        response.headers.setdefault("X-Frame-Options", "DENY")
    # Make browsers re-check the page, CSS and JS on every load (ETag keeps unchanged files cheap),
    # so a stale cached stylesheet never gets mixed with a newer page.
    if path == "/" or path.startswith("/static/") or path.endswith("/book"):
        response.headers["Cache-Control"] = "no-cache"
    if path.startswith("/api/auth") or path.startswith("/api/me"):
        response.headers["Cache-Control"] = "no-store"
    return response


def _session_token(request: Request) -> str | None:
    """The browser sends its session in a cookie; the mobile app sends it as `Authorization: Bearer <token>`."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.cookies.get(SESSION_COOKIE)


def identity(request: Request) -> Identity:
    """The caller: the signed-in user (session cookie or bearer token) or the guest id."""
    user = accounts.session_user(_session_token(request))
    if user:
        return Identity(id=user["id"], user=user)
    return Identity(id=request.state.guest_id)


def signed_in(who: Identity = Depends(identity)) -> Identity:
    if not who.signed_in:
        raise HTTPException(401, "Sign in to continue")
    return who


@app.exception_handler(AuthError)
async def auth_error(_request: Request, exc: AuthError):
    return JSONResponse({"detail": str(exc), "field": exc.field}, status_code=exc.status)


class ChatIn(BaseModel):
    message: str
    trip_id: str | None = None
    route_decision: Literal["accept"] | None = None  # the "Plan this route" button


class SuggestIn(BaseModel):
    budget: float
    currency: str = "USD"
    origin: str = ""
    travelers: int = 1
    duration: Literal["weekend", "week", "two_weeks"] = "week"
    month: int | None = None
    start_date: date | None = None  # exact dates replace month + duration
    end_date: date | None = None
    interests: list[str] = []
    occasion: Literal["solo", "couple", "honeymoon", "family", "friends"] | None = None
    direct_only: bool = False
    max_flight_hours: float | None = None
    notes: str = ""
    lang: Literal["en", "ar"] = "en"
    destination: str = ""  # optional "To": a country / region or a city; empty = anywhere


class WhatIfIn(BaseModel):
    budget_delta: float | None = None
    budget: float | None = None
    apply: bool = False


class SelectIn(BaseModel):
    mode: Literal["balanced", "budget", "comfort", "experience"]


class ReplanIn(BaseModel):
    actions: list[Action]


def public(trip) -> dict:
    """Trip JSON for the UI. Per-city research bundles of a multi-city trip are already merged
    into the top-level research, so they are left out to keep the payload small."""
    return trip.model_dump(mode="json", exclude={"research": {"stops"}})


def _trip_or_404(trip_id: str, who: Identity):
    """The trip, only for its owner. Someone else's trip answers exactly like a missing one (no id probing)."""
    trip = service.get(trip_id)
    if trip is None or trip.user_id != who.id:
        raise HTTPException(404, "Trip not found")
    return trip


@app.get("/api/health")
async def health():
    keys = {"serpapi": bool(settings.serpapi_key), "openrouteservice": bool(settings.ors_key),
            "opentripmap": bool(settings.opentripmap_key), "geoapify": bool(settings.geoapify_key)}
    return {"status": "ok", "llm": llm.available(), "llm_provider": llm.provider(), "model": llm.model_name(),
            "llm_error": llm.last_error,
            "http_mode": settings.http_mode, "mcp_transport": settings.mcp_transport, "mcp_servers": list(SERVERS),
            "providers_configured": keys}


@app.get("/api/quota")
async def quota():
    """SerpApi plan usage (the account endpoint is free and does not count as a search)."""
    if not settings.serpapi_key:
        return {"configured": False}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            a = (await c.get("https://serpapi.com/account.json", params={"api_key": settings.serpapi_key})).json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"SerpApi unreachable: {exc}")
    return {"configured": True, "plan": a.get("plan_name"), "searches_per_month": a.get("searches_per_month"),
            "searches_left": a.get("total_searches_left"), "used_this_month": a.get("this_month_usage"),
            "per_turn_cap": settings.serpapi_calls_per_turn}


@app.get("/api/mcp/tools")
async def mcp_tools():
    hub = get_hub()
    return {name: await hub.list_tools(name) for name in SERVERS}


class ParseIn(BaseModel):
    text: str


@app.post("/api/parse")
async def parse_request(body: ParseIn):
    """Understand a free-text trip description (any language) without starting a trip: the home page turns it
    into editable fields. Model only - no live searches, no trip is created."""
    from .nlu import interpret

    if not body.text.strip():
        raise HTTPException(400, "Empty text")
    interp, _ = await interpret(body.text[:1000], False, {}, {"has_plan": False})
    r = interp.requirements
    dests = r.destinations or ([r.destination] if r.destination else [])
    return {"source": interp.source, "origin": r.origin_city, "destinations": dests,
            "nights": r.nights_per_destination if len(r.nights_per_destination) == len(dests) else [],
            "region": r.region, "start_date": r.start_date, "end_date": r.end_date, "days": r.duration_days,
            "month": r.travel_month,
            "travelers": r.travelers, "budget": r.budget_amount, "currency": r.budget_currency,
            "interests": r.activity_preferences, "must_visit": r.must_visit, "direct_only": r.direct_flights_only,
            "dietary": r.dietary_restrictions}


@app.post("/api/suggest")
async def suggest_trips(body: SuggestIn):
    """Trip ideas that fit a budget (real fares and hotel prices from the traveller's airport)."""
    if body.budget <= 0:
        raise HTTPException(400, "Budget must be positive")
    if body.start_date and body.end_date:
        if body.end_date <= body.start_date:
            raise HTTPException(400, "The return date must be after the departure date")
        if body.start_date < date.today():
            raise HTTPException(400, "The departure date is in the past")
    from .mcp_hub import MCPToolError
    from .suggest import suggest

    try:
        return await suggest(get_hub(), body.budget, body.currency, body.origin.strip() or settings.default_origin,
                             body.travelers, body.duration, body.month, body.start_date, body.end_date,
                             body.interests, body.occasion, body.direct_only, body.max_flight_hours, body.notes,
                             body.lang, body.destination)
    except MCPToolError as exc:
        where = "destination" if "destination" in str(exc) else "departure city"
        raise HTTPException(404, f"Couldn't find that {where}")


@app.get("/api/trips/{trip_id}/hotel-offers")
async def hotel_offers(trip_id: str, hotel_id: str, who: Identity = Depends(identity)):
    """Where to book a hotel of this trip at the price the plan used: every booking site's live offer for the
    exact dates and guests, each with a direct link to its booking page."""
    from urllib.parse import quote_plus

    from .mcp_hub import MCPToolError

    trip = _trip_or_404(trip_id, who)
    c = trip.trip_contract
    if c is None or trip.research is None:
        raise HTTPException(404, "Trip has no hotels yet")
    # The hotel, and the dates of the city it belongs to (multi-city trips have one hotel per city).
    stays = [(c.destination, c.start_date, c.end_date, trip.research.hotels)]
    if c.stops and trip.research.stops:
        stays = [(s.name, s.start_date, s.end_date, b.hotels) for s, b in zip(c.stops, trip.research.stops)]
    found = next(((h, city, ci, co) for city, ci, co, pool in stays for h in pool if h.id == hotel_id), None)
    if found is None:
        raise HTTPException(404, "Hotel not found in this trip")
    h, city, ci, co = found
    google = (f"https://www.google.com/travel/search?q={quote_plus(f'{h.name} {city}')}"
              f"&checkin={ci.isoformat()}&checkout={co.isoformat()}")
    base = {"hotel": h.name, "city": city, "check_in": ci.isoformat(), "check_out": co.isoformat(),
            "nights": (co - ci).days, "adults": c.travelers, "currency": c.budget.currency.upper(),
            "planned_rate": h.price_per_night.amount, "planned_currency": h.price_per_night.currency,
            "google_hotels": google, "hotel_website": h.link, "offers": [], "images": h.images}
    if not h.property_token:
        return base  # AI-estimated hotel: no live offers, only the search links
    try:
        res = await get_hub().call("hotels", "get_hotel_offers", {
            "property_token": h.property_token, "city": city, "check_in": ci.isoformat(), "check_out": co.isoformat(),
            "adults": c.travelers, "currency": c.budget.currency.upper()})
    except MCPToolError:
        return base
    offers = res.get("offers") or []
    # The offer that matches the price the plan used (closest nightly rate).
    if offers:
        best = min(offers, key=lambda o: abs(o["rate_per_night"] - h.price_per_night.amount))
        best["matches_plan"] = True
    return {**base, "offers": offers, "hotel_website": res.get("hotel_website") or h.link,
            "images": res.get("images") or h.images, "description": res.get("description")}


@app.get("/api/trips/{trip_id}/hotel-offers/go")
async def hotel_offer_redirect(trip_id: str, hotel_id: str, who: Identity = Depends(identity)):
    """One click from the Trip Book: straight to the booking page at the plan's price (Google Hotels if none)."""
    from fastapi.responses import RedirectResponse

    d = await hotel_offers(trip_id, hotel_id, who)
    match = next((o for o in d["offers"] if o.get("matches_plan")), None)
    return RedirectResponse(match["link"] if match else d["google_hotels"], status_code=302)


def _chat_trip(body: ChatIn, who: Identity) -> str | None:
    """The trip a message continues: only one the caller owns (a stale or foreign id starts a new trip)."""
    if body.trip_id and service.store.owner(body.trip_id) == who.id:
        return body.trip_id
    return None


@app.post("/api/chat")
async def chat(body: ChatIn, who: Identity = Depends(identity)):
    if not body.message.strip():
        raise HTTPException(400, "Empty message")
    trip, reply = await service.chat(body.message, _chat_trip(body, who), who.id, body.route_decision)
    return {"trip_id": trip.trip_id, "reply": reply, "trip": public(trip)}


@app.post("/api/chat/stream")
async def chat_stream(body: ChatIn, who: Identity = Depends(identity)):
    """Server-Sent Events: live LangGraph nodes and MCP tool calls, then the final reply + trip."""
    if not body.message.strip():
        raise HTTPException(400, "Empty message")
    trip_id = _chat_trip(body, who)

    async def events():
        async for ev in service.chat_stream(body.message, trip_id, who.id, body.route_decision):
            if ev["type"] == "done":
                ev = {"type": "done", "trip_id": ev["trip"].trip_id, "reply": ev["reply"],
                      "trip": public(ev["trip"])}
            yield f"data: {json.dumps(ev, default=str)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/trips")
async def list_trips(who: Identity = Depends(identity)):
    return service.store.list_trips(who.id)


@app.get("/api/trips/{trip_id}")
async def get_trip(trip_id: str, who: Identity = Depends(identity)):
    return public(_trip_or_404(trip_id, who))


@app.delete("/api/trips/{trip_id}")
async def delete_trip(trip_id: str, who: Identity = Depends(identity)):
    _trip_or_404(trip_id, who)
    service.store.delete_trip(trip_id)
    return {"deleted": trip_id}


@app.post("/api/trips/{trip_id}/select")
async def select(trip_id: str, body: SelectIn, who: Identity = Depends(identity)):
    _trip_or_404(trip_id, who)
    trip = await service.select_mode(trip_id, body.mode)
    return public(trip)


@app.post("/api/trips/{trip_id}/whatif")
async def what_if(trip_id: str, body: WhatIfIn, who: Identity = Depends(identity)):
    _trip_or_404(trip_id, who)
    if body.budget_delta is None and body.budget is None:
        raise HTTPException(400, "Provide budget_delta or budget")
    return await service.what_if(trip_id, body.budget_delta, body.budget, body.apply)


@app.post("/api/trips/{trip_id}/replan")
async def replan(trip_id: str, body: ReplanIn, who: Identity = Depends(identity)):
    _trip_or_404(trip_id, who)
    trip, reply = await service.replan(trip_id, body.actions)
    return {"trip_id": trip.trip_id, "reply": reply, "trip": public(trip)}


@app.get("/api/trips/{trip_id}/events")
async def events(trip_id: str, who: Identity = Depends(identity)):
    _trip_or_404(trip_id, who)
    return service.store.events(trip_id)


@app.get("/api/trips/{trip_id}/book", response_class=HTMLResponse)
async def book(trip_id: str, who: Identity = Depends(identity)):
    trip = _trip_or_404(trip_id, who)
    if not trip.selected_plan:
        raise HTTPException(409, "No plan yet")
    return HTMLResponse(tripbook.render_html(trip))


@app.get("/api/trips/{trip_id}/book.md", response_class=PlainTextResponse)
async def book_md(trip_id: str, who: Identity = Depends(identity)):
    trip = _trip_or_404(trip_id, who)
    if not trip.selected_plan:
        raise HTTPException(409, "No plan yet")
    return PlainTextResponse(tripbook.render_markdown(trip), media_type="text/markdown")


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


class SignUpIn(BaseModel):
    name: str
    email: str
    password: str


class SignInIn(BaseModel):
    email: str
    password: str


class ProfileIn(BaseModel):
    name: str | None = None
    interests: list[str] | None = None
    home_city: str | None = None
    currency: str | None = None
    lang: Literal["en", "ar"] | None = None


class PasswordIn(BaseModel):
    current: str
    new: str


class DeleteAccountIn(BaseModel):
    password: str


def _start_session(request: Request, response: Response, user: dict) -> dict:
    token = accounts.create_session(user["id"], request.headers.get("user-agent", ""))
    if request.headers.get("x-client") == "mobile":
        # The app stores the token in the phone's secure storage; web pages never see it (HttpOnly cookie).
        return {"user": user, "token": token}
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/")
    return {"user": user}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@app.post("/api/auth/signup")
async def sign_up(body: SignUpIn, request: Request, response: Response):
    user = accounts.sign_up(body.name, body.email, body.password, guest_id=request.state.guest_id)
    return _start_session(request, response, user)


@app.post("/api/auth/signin")
async def sign_in(body: SignInIn, request: Request, response: Response):
    user = accounts.sign_in(body.email, body.password, _client_ip(request), guest_id=request.state.guest_id)
    return _start_session(request, response, user)


@app.post("/api/auth/signout")
async def sign_out(request: Request, response: Response):
    accounts.end_session(_session_token(request))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"signed_out": True}


@app.get("/api/auth/me")
async def me(who: Identity = Depends(identity)):
    return {"user": who.user}


@app.patch("/api/me")
async def update_me(body: ProfileIn, who: Identity = Depends(signed_in)):
    from .recommender.catalog import INTERESTS

    prefs = {}
    if body.interests is not None:
        prefs["interests"] = [i for i in dict.fromkeys(body.interests) if i in INTERESTS]
    if body.home_city is not None:
        prefs["home_city"] = body.home_city.strip()[:80]
    if body.currency is not None:
        if body.currency.upper() not in {"USD", "EUR", "EGP", "SAR", "AED", "KWD", "QAR", "GBP"}:
            raise AuthError("Unsupported currency.", "currency")
        prefs["currency"] = body.currency.upper()
    if body.lang is not None:
        prefs["lang"] = body.lang
    return {"user": accounts.update_profile(who.id, body.name, prefs)}


@app.post("/api/me/password")
async def change_password(body: PasswordIn, request: Request, who: Identity = Depends(signed_in)):
    accounts.change_password(who.id, body.current, body.new, _session_token(request))
    return {"changed": True}


@app.delete("/api/me")
async def delete_me(body: DeleteAccountIn, response: Response, who: Identity = Depends(signed_in)):
    accounts.delete_account(who.id, body.password)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"deleted": True}


@app.get("/api/me/dashboard")
async def dashboard(who: Identity = Depends(signed_in)):
    """Everything the dashboard shows: stats, trips, and what the recommender knows about the user."""
    from .config import today

    trips = service.store.list_trips(who.id)
    planned = [t for t in trips if t["status"] == "planned"]
    now = today().isoformat()
    upcoming = sorted((t for t in planned if (t["start_date"] or "") >= now), key=lambda t: t["start_date"])
    totals: dict[str, float] = {}
    for t in planned:
        if t["total"] and t["currency"]:
            totals[t["currency"]] = round(totals.get(t["currency"], 0) + t["total"], 2)
    scores = [t["score"] for t in planned if t["score"] is not None]
    act = accounts.activity(who.id)
    return {
        "user": who.user,
        "stats": {"trips": len(trips), "planned": len(planned),
                  "countries": len({c for t in planned for c in t["countries"]}),
                  "cities": len({c for t in planned for c in t["cities"]}),
                  "days": sum(t["days"] or 0 for t in planned),
                  "avg_score": round(sum(scores) / len(scores)) if scores else None,
                  "planned_totals": totals, "searches": sum(1 for a in act if a["kind"] == "search")},
        "next_trip": upcoming[0] if upcoming else None,
        "trips": trips,
        "dismissed": sorted({a["city"] for a in act if a["kind"] == "dismiss"}),
    }


# ---------------------------------------------------------------------------
# Recommendations (the from-scratch destination model)
# ---------------------------------------------------------------------------


class ActivityIn(BaseModel):
    kind: Literal["search", "view", "dismiss", "like"]
    city: str


def _recommender():
    from .recommender import engine

    rec = engine.get()
    if rec is None:
        raise HTTPException(503, "Recommendations are not available yet")
    return rec


def _interests(who: Identity) -> list[str]:
    """Interests the user picked in their account, plus those learned from their trips."""
    picked = list((who.user or {}).get("prefs", {}).get("interests") or [])
    prof = service.store.load_profile(who.id)
    return picked + (list(prof.activity_preferences) if prof else [])


@app.post("/api/activity")
async def log_activity(body: ActivityIn, who: Identity = Depends(identity)):
    accounts.log_activity(who.id, body.kind, body.city)
    return {"ok": True}


@app.delete("/api/activity/dismiss")
async def undo_dismiss(city: str, who: Identity = Depends(identity)):
    accounts.undo_dismiss(who.id, city)
    return {"ok": True}


@app.get("/api/recommendations")
async def recommendations(limit: int = 8, who: Identity = Depends(identity)):
    rec = _recommender()
    return await rec.recommend(service.store.list_trips(who.id), accounts.activity(who.id), _interests(who),
                               max(1, min(limit, 20)))


@app.get("/api/recommendations/similar")
async def similar_places(city: str, limit: int = 6, who: Identity = Depends(identity)):
    return await _recommender().similar(city[:80], max(1, min(limit, 12)))


@app.get("/api/recommendations/map")
async def taste_map(who: Identity = Depends(identity)):
    return await _recommender().taste_map(service.store.list_trips(who.id), accounts.activity(who.id), _interests(who))


@app.get("/api/recommendations/model")
async def model_report():
    from .recommender import engine

    rep = engine.report()
    if rep is None:
        raise HTTPException(503, "The model has not been trained yet")
    return rep


# ---------------------------------------------------------------------------
# Website pages (search-engine friendly, see seo.py)
# ---------------------------------------------------------------------------


def _base(request: Request) -> str:
    return seo.public_url(str(request.base_url))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return HTMLResponse(seo.index_page("en", _base(request)))


@app.get("/ar", response_class=HTMLResponse)
async def index_ar(request: Request):
    return HTMLResponse(seo.index_page("ar", _base(request)))


@app.get("/guides", response_class=HTMLResponse)
@app.get("/ar/guides", response_class=HTMLResponse)
async def guides_index(request: Request):
    lang = "ar" if request.url.path.startswith("/ar/") else "en"
    return HTMLResponse(seo.guides_index(lang, _base(request)))


@app.get("/guides/{slug}", response_class=HTMLResponse)
@app.get("/ar/guides/{slug}", response_class=HTMLResponse)
async def guide(slug: str, request: Request):
    lang = "ar" if request.url.path.startswith("/ar/") else "en"
    page = seo.guide_page(slug, lang, _base(request))
    if page is None:
        raise HTTPException(404, "No guide for this destination yet")
    return HTMLResponse(page)


@app.get("/privacy", response_class=HTMLResponse)
@app.get("/terms", response_class=HTMLResponse)
@app.get("/ar/privacy", response_class=HTMLResponse)
@app.get("/ar/terms", response_class=HTMLResponse)
async def legal(request: Request):
    path = request.url.path
    return HTMLResponse(seo.legal_page("privacy" if path.endswith("privacy") else "terms",
                                       "ar" if path.startswith("/ar/") else "en", _base(request)))


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots(request: Request):
    return PlainTextResponse(seo.robots(_base(request)))


@app.get("/sitemap.xml")
async def sitemap(request: Request):
    return Response(seo.sitemap(_base(request)), media_type="application/xml")


@app.get("/indexnow.txt", response_class=PlainTextResponse)
async def indexnow_key():
    """IndexNow ownership key (public by design): lets each deploy notify Bing / Yandex of new pages at once."""
    import os

    key = os.getenv("INDEXNOW_KEY")
    if not key:
        raise HTTPException(404, "Not configured")
    return PlainTextResponse(key)


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
