"""HTTP API + static UI.

Run:  uvicorn travel_agent.api:app --reload
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import llm, seo, telemetry, tripbook
from .auth import GUEST_COOKIE, GUEST_RE, SESSION_COOKIE, SESSION_DAYS, Accounts, AuthError, Identity, new_guest_id
from .config import PROJECT_DIR, settings, today
from .mcp_hub import SERVERS, get_hub
from . import net, pilgrimage
from .agents import landmark
from .models import PlanningMode
from .providers import aladhan, world_events
import httpx

from .security import MAX_MESSAGE_CHARS, client_ip, is_admin, limit_expensive, limit_light, limit_offers
from .service import TravelAgentService

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
# httpx logs full request URLs at INFO, and several providers take the API key as a query
# parameter - keep keys out of the logs.
for noisy in ("httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    world_events.refresh()  # the Events page's catalogue is checked in the background (~1 min), not on first visit
    yield


app = FastAPI(title="Dalili", version="0.1.0", lifespan=_lifespan,
              description="Plans, researches, optimizes and validates complete trips. It never books anything.")
service = TravelAgentService()
accounts = Accounts(service.store)
FRONTEND = PROJECT_DIR / "frontend"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def web_basics(request: Request, call_next):
    """Request id + access log, cross-site request guard, the guest cookie, security headers and UI revalidation."""
    path = request.url.path
    rid = request.headers.get("x-request-id", "")
    rid = rid if re.fullmatch(r"[A-Za-z0-9-]{8,64}", rid) else uuid.uuid4().hex[:16]
    rid_token = telemetry.REQUEST_ID.set(rid)
    started = time.perf_counter()
    try:
        response = await _handle(request, call_next, path)
    finally:
        telemetry.REQUEST_ID.reset(rid_token)
    response.headers["X-Request-ID"] = rid
    if path.startswith("/api/"):
        # Path only (trip ids are random, no query strings): no personal data in the logs.
        telemetry.log.info(json.dumps({"event": "request", "request_id": rid, "method": request.method, "path": path,
                                       "status": response.status_code,
                                       "ms": round((time.perf_counter() - started) * 1000)}))
    return response


async def _handle(request: Request, call_next, path: str):
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
    if "text/html" in response.headers.get("content-type", ""):
        response = await _with_csp(response, framable=path.endswith("/book"))
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
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


_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", re.S | re.I)


async def _with_csp(response, framable: bool):
    """Content-Security-Policy for an HTML page: scripts only from this site plus the page's own inline scripts
    (allowed by their hash), so an injected <script> or handler from third-party data can never run."""
    body = b"".join([chunk async for chunk in response.body_iterator])
    hashes = []
    for attrs, code in _INLINE_SCRIPT.findall(body.decode("utf-8", "replace")):
        if re.search(r"type=[\"']application/(ld\+)?json", attrs, re.I):
            continue  # data blocks are never executed
        digest = base64.b64encode(hashlib.sha256(code.encode()).digest()).decode()
        hashes.append(f"'sha256-{digest}'")
    policy = "; ".join([
        "default-src 'self'",
        "script-src 'self' " + " ".join(sorted(set(hashes))),
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data: blob: https:",
        "connect-src 'self' https://en.wikipedia.org",
        "object-src 'none'", "base-uri 'self'", "form-action 'self'",
        "frame-ancestors 'self'" if framable else "frame-ancestors 'none'",
    ])
    out = Response(content=body, status_code=response.status_code, media_type=response.media_type)
    out.raw_headers = [(k, v) for k, v in response.raw_headers if k.lower() != b"content-length"] + \
        [(b"content-length", str(len(body)).encode())]
    out.headers["Content-Security-Policy"] = policy
    return out


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
    message: str = Field(max_length=MAX_MESSAGE_CHARS)
    trip_id: str | None = None
    route_decision: Literal["accept"] | None = None  # the "Plan this route" button
    preview: bool = False  # stream the new plan as soon as it is built, before the expert review and the reply


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
    notes: str = Field("", max_length=1000)
    lang: Literal["en", "ar"] = "en"
    destination: str = ""  # optional "To": a country / region or a city; empty = anywhere


class WhatIfIn(BaseModel):
    budget_delta: float | None = None
    budget: float | None = None
    apply: bool = False


class SelectIn(BaseModel):
    mode: PlanningMode


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
async def health(request: Request):
    """Liveness for the platform and CI. Provider / model details only for the operator (X-Admin-Token)."""
    if not is_admin(request):
        return {"status": "ok"}
    keys = {"serpapi": bool(settings.serpapi_key), "openrouteservice": bool(settings.ors_key),
            "opentripmap": bool(settings.opentripmap_key), "geoapify": bool(settings.geoapify_key)}
    return {"status": "ok", "llm": llm.available(), "llm_provider": llm.provider(), "model": llm.model_name(),
            "llm_error": llm.last_error,
            "http_mode": settings.http_mode, "mcp_transport": settings.mcp_transport, "mcp_servers": list(SERVERS),
            "providers_configured": keys}


@app.get("/api/quota")
async def quota(request: Request):
    """SerpApi plan usage (the account endpoint is free and does not count as a search). Operator only."""
    if not is_admin(request):
        raise HTTPException(404, "Not found")
    if not settings.serpapi_key:
        return {"configured": False}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            a = (await c.get("https://serpapi.com/account.json", params={"api_key": settings.serpapi_key})).json()
    except httpx.HTTPError:
        raise HTTPException(502, "SerpApi unreachable")
    return {"configured": True, "plan": a.get("plan_name"), "searches_per_month": a.get("searches_per_month"),
            "searches_left": a.get("total_searches_left"), "used_this_month": a.get("this_month_usage"),
            "per_turn_cap": settings.serpapi_calls_per_turn}


@app.get("/api/mcp/tools")
async def mcp_tools(request: Request):
    if not is_admin(request):
        raise HTTPException(404, "Not found")
    hub = get_hub()
    return {name: await hub.list_tools(name) for name in SERVERS}


@app.post("/api/suggest")
async def suggest_trips(body: SuggestIn, request: Request, who: Identity = Depends(identity)):
    """Trip ideas that fit a budget (real fares and hotel prices from the traveller's airport)."""
    if body.budget <= 0:
        raise HTTPException(400, "Budget must be positive")
    limit_expensive(request, who.id)
    if body.start_date and body.end_date:
        if body.end_date <= body.start_date:
            raise HTTPException(400, "The return date must be after the departure date")
        if body.start_date < today():
            raise HTTPException(400, "The departure date is in the past")
    from .mcp_hub import MCPToolError
    from .suggest import suggest

    taste = None
    try:
        from .recommender import engine

        rec = engine.get()
        if rec is not None:
            trips, act, ints = service.store.list_trips(who.id), accounts.activity(who.id), _interests(who) + body.interests

            async def taste(names: list[str]) -> dict:
                return await rec.affinity(names, trips, act, ints)
    except Exception:  # the recommender is optional
        taste = None
    try:
        return await suggest(get_hub(), body.budget, body.currency, body.origin.strip() or settings.default_origin,
                             body.travelers, body.duration, body.month, body.start_date, body.end_date,
                             body.interests, body.occasion, body.direct_only, body.max_flight_hours, body.notes,
                             body.lang, body.destination, taste=taste)
    except MCPToolError as exc:
        where = "destination" if "destination" in str(exc) else "departure city"
        raise HTTPException(404, f"Couldn't find that {where}")


@app.get("/api/trips/{trip_id}/hotel-offers")
async def hotel_offers(trip_id: str, hotel_id: str, request: Request, who: Identity = Depends(identity)):
    """Where to book a hotel of this trip at the price the plan used: every booking site's live offer for the
    exact dates and guests, each with a direct link to its booking page."""
    limit_offers(request, who.id)  # a GET that spends a live search
    return await _hotel_offers(trip_id, hotel_id, who)


async def _hotel_offers(trip_id: str, hotel_id: str, who: Identity) -> dict:
    from urllib.parse import quote_plus

    from .mcp_hub import MCPToolError

    trip = _trip_or_404(trip_id, who)
    c = trip.trip_contract
    if c is None or trip.research is None:
        raise HTTPException(404, "Trip has no hotels yet")
    # The hotel, and the dates of the city it belongs to (multi-city trips have one hotel per city).
    # Booked for the nights the plan's flights need (a next-day landing checks in a day later), else the trip's dates.
    plan = trip.selected_plan
    stays = [(c.destination, (plan and plan.hotel_check_in) or c.start_date,
              (plan and plan.hotel_check_out) or c.end_date, trip.research.hotels)]
    if c.stops and trip.research.stops:
        planned = {sp.index: sp for sp in plan.stops} if plan else {}
        stays = [(s.name, (planned[i].check_in if i in planned else None) or s.start_date,
                  (planned[i].check_out if i in planned else None) or s.end_date, b.hotels)
                 for i, (s, b) in enumerate(zip(c.stops, trip.research.stops))]
    found = next(((h, city, ci, co) for city, ci, co, pool in stays for h in pool if h.id == hotel_id), None)
    if found is None:
        raise HTTPException(404, "Hotel not found in this trip")
    h, city, ci, co = found
    # Priced per room, as the plan is (rooms x nights): guests per room, not the whole group in one room.
    adults = max(1, -(-c.travelers // c.rooms))
    google = (f"https://www.google.com/travel/search?q={quote_plus(f'{h.name} {city}')}"
              f"&checkin={ci.isoformat()}&checkout={co.isoformat()}")
    base = {"hotel": h.name, "city": city, "check_in": ci.isoformat(), "check_out": co.isoformat(),
            "nights": (co - ci).days, "adults": adults, "rooms": c.rooms, "currency": c.budget.currency.upper(),
            "planned_rate": h.price_per_night.amount, "planned_currency": h.price_per_night.currency,
            "google_hotels": google, "hotel_website": h.link, "offers": [], "images": h.images}
    if not h.property_token:
        return base  # AI-estimated hotel: no live offers, only the search links
    try:
        res = await get_hub().call("hotels", "get_hotel_offers", {
            "property_token": h.property_token, "city": city, "check_in": ci.isoformat(), "check_out": co.isoformat(),
            "adults": adults, "currency": c.budget.currency.upper()})
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
async def hotel_offer_redirect(trip_id: str, hotel_id: str, request: Request, who: Identity = Depends(identity)):
    """One click from the Trip Book: straight to the booking page at the plan's price (Google Hotels if none)."""
    from fastapi.responses import RedirectResponse

    limit_offers(request, who.id)  # a GET that spends a live search
    d = await _hotel_offers(trip_id, hotel_id, who)
    match = next((o for o in d["offers"] if o.get("matches_plan")), None)
    return RedirectResponse(match["link"] if match else d["google_hotels"], status_code=302)


def _prefs(who: Identity) -> dict:
    """The signed-in traveller's account settings (home city, currency) - defaults for a new trip."""
    return (who.user or {}).get("prefs") or {}


def _chat_trip(body: ChatIn, who: Identity) -> str | None:
    """The trip a message continues: only one the caller owns (a stale or foreign id starts a new trip)."""
    if body.trip_id and service.store.owner(body.trip_id) == who.id:
        return body.trip_id
    return None


@app.post("/api/chat")
async def chat(body: ChatIn, request: Request, who: Identity = Depends(identity)):
    if not body.message.strip():
        raise HTTPException(400, "Empty message")
    limit_expensive(request, who.id)
    trip, reply = await service.chat(body.message, _chat_trip(body, who), who.id, body.route_decision, _prefs(who))
    return {"trip_id": trip.trip_id, "reply": reply, "trip": public(trip)}


@app.post("/api/chat/stream")
async def chat_stream(body: ChatIn, request: Request, who: Identity = Depends(identity)):
    """Server-Sent Events: live LangGraph nodes and MCP tool calls, then the final reply + trip."""
    if not body.message.strip():
        raise HTTPException(400, "Empty message")
    limit_expensive(request, who.id)
    trip_id = _chat_trip(body, who)

    async def events():
        async for ev in service.chat_stream(body.message, trip_id, who.id, body.route_decision, _prefs(who)):
            if ev["type"] == "preview":
                if not body.preview:
                    continue
                ev = {"type": "preview", "trip": public(ev["trip"])}
            elif ev["type"] == "done":
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
    if body.mode not in _trip_or_404(trip_id, who).plans:
        raise HTTPException(409, "That plan is not available for this trip yet")
    trip = await service.select_mode(trip_id, body.mode)
    return public(trip)


@app.post("/api/trips/{trip_id}/whatif")
async def what_if(trip_id: str, body: WhatIfIn, request: Request, who: Identity = Depends(identity)):
    if not _trip_or_404(trip_id, who).plans:
        raise HTTPException(409, "This trip has no plan yet")
    limit_expensive(request, who.id)
    if body.budget_delta is None and body.budget is None:
        raise HTTPException(400, "Provide budget_delta or budget")
    return await service.what_if(trip_id, body.budget_delta, body.budget, body.apply)


@app.get("/api/trips/{trip_id}/book", response_class=HTMLResponse)
async def book(trip_id: str, who: Identity = Depends(identity)):
    trip = _trip_or_404(trip_id, who)
    if not trip.selected_plan:
        raise HTTPException(409, "No plan yet")
    return HTMLResponse(tripbook.render_html(trip))


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


@app.post("/api/auth/signup")
async def sign_up(body: SignUpIn, request: Request, response: Response):
    user = accounts.sign_up(body.name, body.email, body.password, guest_id=request.state.guest_id,
                            ip=client_ip(request))
    return _start_session(request, response, user)


@app.post("/api/auth/signin")
async def sign_in(body: SignInIn, request: Request, response: Response):
    user = accounts.sign_in(body.email, body.password, client_ip(request), guest_id=request.state.guest_id)
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
    city: str = Field(max_length=80)


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
    learned = prof.learned.get("activity_preferences") if prof else None
    return picked + (list(learned.value or []) if learned else [])


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
async def similar_places(city: str, request: Request, limit: int = 6):
    limit_light(request)  # an unknown city is embedded on the fly (CPU): bounded per client
    return await _recommender().similar(city[:80], max(1, min(limit, 12)))


@app.get("/api/events")
async def major_events(request: Request, category: str | None = None, country: str | None = None):
    """The Events page: world-famous events in the coming months (checked against Wikipedia, Wikidata and their
    official sites). complete=false while the catalogue is still being checked."""
    limit_light(request)
    found, building = world_events.catalogue()
    if category:
        found = [e for e in found if e.category == category]
    if country:
        found = [e for e in found if e.country_code == country.upper()[:2]]
    return {"complete": not building, "events": [e.model_dump(mode="json") for e in found]}


@app.get("/api/pilgrimage/prayer-times")
async def pilgrimage_prayer_times(request: Request, city: Literal["makkah", "madinah"] = "makkah",
                                  start: date | None = None, days: int = 7):
    """The Hajj & Umrah page: the five prayers in Makkah or Madinah (Umm al-Qura), with the Hijri dates."""
    limit_light(request)
    first = start or today()
    holy = pilgrimage.HOLY[city]
    res = await get_hub().call("knowledge", "get_prayer_times", {
        "lat": holy["lat"], "lon": holy["lon"], "start_date": first.isoformat(),
        "end_date": (first + timedelta(days=max(1, min(days, 14)) - 1)).isoformat()})
    return {"city": city, "method": res.get("method"), "days": res["days"]}


@app.get("/api/pilgrimage/hajj-dates")
async def next_hajj(request: Request):
    """The next Hajj's expected days (8-13 Dhu al-Hijjah) as Gregorian dates."""
    limit_light(request)
    try:
        return await aladhan.hajj_dates(today())
    except (net.ProviderError, KeyError, ValueError) as exc:
        raise HTTPException(503, "Hijri calendar unavailable") from exc


class LandmarkIn(BaseModel):
    # A photo resized by the page (~1280 px JPEG, a few hundred KB): read once, never stored.
    image: str = Field(max_length=3_000_000, pattern=r"^data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$")
    lang: Literal["en", "ar"] = "en"


class LandmarkAskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=500)
    history: list[dict] = Field(default_factory=list, max_length=12)
    lang: Literal["en", "ar"] = "en"


@app.post("/api/landmarks/identify")
async def identify_landmark(body: LandmarkIn, request: Request, who: Identity = Depends(identity)):
    """The landmark in a photo, checked against Wikipedia, with a guide written from its article."""
    limit_expensive(request, who.id)
    return await landmark.identify(body.image, body.lang)


@app.post("/api/landmarks/ask")
async def ask_landmark(body: LandmarkAskIn, request: Request, who: Identity = Depends(identity)):
    """A question about a recognised landmark, answered from its Wikipedia article."""
    limit_expensive(request, who.id)
    out = await landmark.ask(body.title, body.question, body.history, body.lang)
    if out is None:
        raise HTTPException(503, "The guide is unavailable right now")
    return out


@app.get("/api/recommendations/map")
async def taste_map(who: Identity = Depends(identity)):
    return await _recommender().taste_map(service.store.list_trips(who.id), accounts.activity(who.id), _interests(who))


# ---------------------------------------------------------------------------
# Human evaluation (anonymous ratings; summary for the operator)
# ---------------------------------------------------------------------------


class EvaluationIn(BaseModel):
    trip_id: str | None = None
    variant: str = Field("dalili", pattern=r"^[a-z0-9_-]{1,32}$")
    ratings: dict[str, int]
    comment: str = Field("", max_length=1000)


@app.post("/api/evaluations")
async def add_evaluation(body: EvaluationIn, request: Request, who: Identity = Depends(identity)):
    from datetime import datetime, timezone

    from . import evaluation

    limit_light(request)
    ratings = {k: v for k, v in body.ratings.items() if k in evaluation.DIMENSIONS}
    if not ratings or any(not 1 <= v <= 5 for v in ratings.values()):
        raise HTTPException(400, "Ratings are 1-5 for: " + ", ".join(evaluation.DIMENSIONS))
    plan_metrics: dict = {}
    if body.trip_id:
        trip = _trip_or_404(body.trip_id, who)  # only your own trip
        p = trip.selected_plan
        if p:
            plan_metrics = {"mode": p.mode, "score": p.score.total if p.score else None,
                            "requirements_met": p.score.constraint_satisfaction if p.score else None,
                            "valid": p.validation.result if p.validation else None,
                            "price_confidence": p.budget.confidence if p.budget else None}
    service.store.add_evaluation(evaluation.rater_id(who.id), body.trip_id, body.variant, ratings, plan_metrics,
                                 body.comment.strip(), datetime.now(timezone.utc).isoformat())
    return {"saved": True}


@app.get("/api/evaluations/summary")
async def evaluation_summary(request: Request):
    from . import evaluation

    if not is_admin(request):
        raise HTTPException(404, "Not found")
    return evaluation.summary(service.store.evaluations())


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
