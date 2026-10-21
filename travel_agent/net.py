"""HTTP layer shared by every provider: persistent cache, record/replay, quota guard.

Modes (TRAVEL_AGENT_HTTP_MODE):
  cache  - serve a cached response younger than its TTL, otherwise call the API and store it (default)
  live   - always call the API (still stores the response)
  replay - never touch the network; serve whatever is cached regardless of age (tests, demos, evals)

API keys are stripped from the cache key and never stored.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .config import settings
from .utils import FETCHED_AT, SERVED_STALE

# httpx / httpcore log full request URLs at INFO, and several providers take the API key as a
# query parameter: keep them quiet for every entry point (server, scripts, tests, evals).
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

log = logging.getLogger(__name__)

SECRET_PARAMS = {"api_key", "apikey", "apiKey", "key", "Authorization"}



@dataclass
class _TurnQuota:
    """Live SerpApi calls of one chat turn and the turn's cap. Each turn has its own (concurrent users never share
    a budget): set once at the start of the turn, the same object is seen by every task the turn starts."""

    calls: int = 0
    cap: int = field(default_factory=lambda: settings.serpapi_calls_per_turn)


_QUOTA: ContextVar[_TurnQuota | None] = ContextVar("serpapi_quota", default=None)


def _quota() -> _TurnQuota:
    q = _QUOTA.get()
    if q is None:  # outside a chat turn (trip ideas, booking offers): this request's own budget
        q = _TurnQuota()
        _QUOTA.set(q)
    return q


def redact(text: str) -> str:
    """Remove every configured API key from a message before it reaches logs, errors or the UI."""
    for secret in (settings.serpapi_key, settings.ors_key, settings.opentripmap_key, settings.geoapify_key, settings.azure_key):
        if secret:
            text = text.replace(secret, "***")
    return text


class ProviderError(RuntimeError):
    """A data provider failed or is not configured. Never replaced by invented data."""

    def __init__(self, message: str):
        super().__init__(redact(str(message)))


class QuotaExceeded(ProviderError):
    pass


class ReplayMiss(ProviderError):
    pass


class _Cache:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock, self.conn:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS http_cache (key TEXT PRIMARY KEY, service TEXT, url TEXT, "
                "params TEXT, body TEXT, fetched_at REAL)")
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS http_log (id INTEGER PRIMARY KEY AUTOINCREMENT, service TEXT, url TEXT, "
                "at REAL, cached INTEGER, ms REAL)")

    def get(self, key: str) -> tuple[Any, float] | None:
        with self.lock:
            row = self.conn.execute("SELECT body, fetched_at FROM http_cache WHERE key = ?", (key,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def put(self, key: str, service: str, url: str, params: dict, body: Any) -> None:
        clean = {k: v for k, v in params.items() if k not in SECRET_PARAMS}  # keys never touch the disk
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO http_cache VALUES (?, ?, ?, ?, ?, ?)",
                (key, service, url, json.dumps(clean, sort_keys=True, default=str), redact(json.dumps(body)), time.time()))

    def log(self, service: str, url: str, cached: bool, ms: float) -> None:
        if settings.http_mode == "replay":
            return  # nothing is fetched live: logging every replayed hit only slows tests and churns the fixture
        with self.lock, self.conn:
            self.conn.execute("INSERT INTO http_log(service, url, at, cached, ms) VALUES (?, ?, ?, ?, ?)",
                              (service, url, time.time(), int(cached), ms))


_cache: _Cache | None = None
_client: httpx.AsyncClient | None = None


def cache() -> _Cache:
    global _cache
    if _cache is None:
        _cache = _Cache(settings.http_cache_path)
    return _cache


_clients: dict[int, httpx.AsyncClient] = {}


# Wikimedia (Wikivoyage, Wikipedia) refuses API calls whose User-Agent gives no way to reach the operator (HTTP 403):
# the site's address (PUBLIC_URL in production) or, failing that, the project's page.
USER_AGENT = f"Dalili/2.0 (+{os.getenv('PUBLIC_URL') or 'https://github.com/kmtrrdev/dalili'}; AI travel planner)"


def _http() -> httpx.AsyncClient:
    """One client per event loop (an httpx client cannot be shared across loops)."""
    if _client is not None:  # injected by tests
        return _client
    loop_id = id(asyncio.get_running_loop())
    client = _clients.get(loop_id)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=settings.http_timeout, follow_redirects=True,
                                   headers={"User-Agent": USER_AGENT})
        _clients[loop_id] = client
    return client


def cache_key(method: str, url: str, params: dict | None, body: Any = None) -> str:
    clean = {k: v for k, v in (params or {}).items() if k not in SECRET_PARAMS and v is not None}
    raw = json.dumps([method.upper(), url, clean, body], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def start_turn() -> None:
    """A fresh SerpApi budget for this chat turn (called before the turn starts any task)."""
    _QUOTA.set(_TurnQuota())


def allow_extra_calls(n: int) -> None:
    """Raise this turn's cap by n (each extra city of a tour, each city's menu searches)."""
    _quota().cap += max(0, n)


def serpapi_calls_this_turn() -> int:
    return _quota().calls


def _served(data: Any, fetched: float, stale: bool = False) -> Any:
    """Record the provenance of what is returned (read by Metadata while the caller parses it)."""
    FETCHED_AT.set(fetched)
    SERVED_STALE.set(stale)
    return data


async def fetch_json(service: str, url: str, params: dict | None = None, *, ttl_s: float, method: str = "GET",
                     json_body: Any = None, headers: dict | None = None) -> Any:
    params = {k: v for k, v in (params or {}).items() if v is not None}
    key = cache_key(method, url, params, json_body)
    mode = settings.http_mode
    hit = cache().get(key) if mode in ("cache", "replay") else None
    if hit is not None and (mode == "replay" or time.time() - hit[1] < ttl_s):
        cache().log(service, url, True, 0.0)
        if isinstance(hit[0], dict) and "Unsupported" in str(hit[0].get("error", "")):
            raise ProviderError(f"SerpApi: {hit[0]['error']}")  # remembered: don't spend a call re-asking
        return _served(hit[0], hit[1])
    if mode == "replay":
        raise ReplayMiss(f"{service}: no recorded response for {url} {json.dumps({k: v for k, v in params.items() if k not in SECRET_PARAMS})}")
    if service == "serpapi":
        if not settings.serpapi_key:
            raise ProviderError("SERPAPI_API_KEY is not configured")
        quota = _quota()
        if quota.calls >= quota.cap:
            if hit is not None:  # stale beats nothing when the quota guard trips
                log.warning("SerpApi per-turn cap reached; serving stale cache for %s", url)
                return _served(hit[0], hit[1], stale=True)
            raise QuotaExceeded(f"SerpApi per-turn call cap ({quota.cap}) reached")
        quota.calls += 1
    started = time.perf_counter()
    try:
        resp = await _http().request(method, url, params=params, json=json_body, headers=headers)
    except httpx.HTTPError as exc:
        if hit is not None:
            log.warning("%s unreachable, serving stale cache: %s", service, redact(str(exc)))
            return _served(hit[0], hit[1], stale=True)
        raise ProviderError(f"{service} unreachable: {type(exc).__name__}") from exc
    ms = (time.perf_counter() - started) * 1000
    cache().log(service, url, False, ms)
    if resp.status_code == 400 and service == "serpapi" and "Unsupported" in resp.text:
        cache().put(key, service, url, params, resp.json())  # engine not on this plan: remember it
        raise ProviderError(f"SerpApi: {resp.json().get('error')}")
    if resp.status_code >= 400:
        if hit is not None:
            log.warning("%s returned %s, serving stale cache", service, resp.status_code)
            return _served(hit[0], hit[1], stale=True)
        log.warning("%s HTTP %s: %s", service, resp.status_code, redact(resp.text[:300]))
        raise ProviderError(f"{service} HTTP {resp.status_code}")  # the body stays in the server log, not the UI
    data = resp.json()
    if service == "serpapi" and isinstance(data, dict) and data.get("error"):
        # SerpApi reports "no results" as an error; that is a valid, cacheable answer.
        if "hasn't returned any results" not in data["error"]:
            raise ProviderError(f"SerpApi: {data['error']}")
    cache().put(key, service, url, params, data)
    return _served(data, time.time())


BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36 "
              "(Dalili travel planner; reads published prices)")
MAX_PAGE_BYTES = 1_500_000


def _public_ip(ip) -> bool:
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified)


def _public_http_url(url: str) -> bool:
    """Only public http(s) pages on standard ports: no local / private hosts (the URLs come from third-party data).
    Syntax only - _resolves_public() also checks where the name really points."""
    from ipaddress import ip_address
    from urllib.parse import urlparse

    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        if u.port not in (None, 80, 443):
            return False
    except ValueError:
        return False
    host = u.hostname.lower().rstrip(".")
    if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        return _public_ip(ip_address(host))
    except ValueError:
        # Not dotted notation - but "2130706433", "0x7f000001" or "0177.0.0.1" are IPv4 addresses in disguise.
        parts = host.split(".")
        return not all(p.isdigit() or p.startswith("0x") for p in parts)


async def _resolves_public(url: str) -> bool:
    """Every address the host name resolves to must be public (blocks DNS names pointing at internal services)."""
    import socket
    from ipaddress import ip_address
    from urllib.parse import urlparse

    host = urlparse(url).hostname or ""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return False
    return bool(infos) and all(_public_ip(ip_address(info[4][0].split("%")[0])) for info in infos)


async def fetch_page(url: str, ttl_s: float = 30 * 86400) -> dict[str, Any]:
    """An HTML page (cached like any API response): {"url": final url, "html": text}. Raises ProviderError."""
    if not _public_http_url(url):
        raise ProviderError(f"refused to fetch {url}")
    key = cache_key("GET", url, None, "page")
    mode = settings.http_mode
    hit = cache().get(key) if mode in ("cache", "replay") else None
    if hit is not None and (mode == "replay" or time.time() - hit[1] < ttl_s):
        return _served(hit[0], hit[1])
    if mode == "replay":
        raise ReplayMiss(f"page: no recorded response for {url}")
    started = time.perf_counter()
    current = url
    try:
        # Redirects are followed by hand, one checked hop at a time: a public page must not bounce the server to an
        # internal address (cloud metadata, a private network).
        for _ in range(5):
            if not _public_http_url(current) or not await _resolves_public(current):
                raise ProviderError(f"refused to fetch {current}")
            req = _http().build_request("GET", current, headers={
                "User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en,*;q=0.5"},
                timeout=12)
            resp = await _http().send(req, stream=True, follow_redirects=False)
            try:
                if resp.is_redirect and resp.headers.get("location"):
                    current = str(resp.url.join(resp.headers["location"]))
                    continue
                ctype = resp.headers.get("content-type", "")
                if resp.status_code >= 400 or "html" not in ctype:
                    raise ProviderError(f"page HTTP {resp.status_code} ({ctype.split(';')[0] or 'unknown type'})")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) >= MAX_PAGE_BYTES:
                        break  # enough to read the prices; never load an unbounded body
                text = body[:MAX_PAGE_BYTES].decode(resp.encoding or "utf-8", errors="replace")
                break
            finally:
                await resp.aclose()
        else:
            raise ProviderError("page: too many redirects")
    except httpx.HTTPError as exc:
        if hit is not None:
            return _served(hit[0], hit[1], stale=True)
        raise ProviderError(f"page unreachable: {type(exc).__name__}") from exc
    cache().log("page", url, False, (time.perf_counter() - started) * 1000)
    page = {"url": current, "html": text}
    cache().put(key, "page", url, {}, page)
    return _served(page, time.time())


async def serpapi(engine: str, ttl_s: float, **params: Any) -> dict:
    return await fetch_json("serpapi", "https://serpapi.com/search.json",
                            {"engine": engine, "api_key": settings.serpapi_key, **params}, ttl_s=ttl_s)


HOUR = 3600
DAY = 24 * HOUR
