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
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from .config import settings

# httpx / httpcore log full request URLs at INFO, and several providers take the API key as a
# query parameter: keep them quiet for every entry point (server, scripts, tests, evals).
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

log = logging.getLogger(__name__)

SECRET_PARAMS = {"api_key", "apikey", "apiKey", "key", "Authorization"}

# Live SerpApi calls made during the current chat turn (for the per-turn quota guard). A plain
# process-level counter: LangGraph runs research branches as separate tasks, which would not
# share a contextvar.
_serpapi_calls = 0
_turn_cap = settings.serpapi_calls_per_turn


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
        with self.lock, self.conn:
            self.conn.execute("INSERT INTO http_log(service, url, at, cached, ms) VALUES (?, ?, ?, ?, ?)",
                              (service, url, time.time(), int(cached), ms))

    def live_calls_since(self, service: str, since: float) -> int:
        with self.lock:
            return self.conn.execute("SELECT COUNT(*) FROM http_log WHERE service = ? AND cached = 0 AND at >= ?",
                                     (service, since)).fetchone()[0]


_cache: _Cache | None = None
_client: httpx.AsyncClient | None = None


def cache() -> _Cache:
    global _cache
    if _cache is None:
        _cache = _Cache(settings.http_cache_path)
    return _cache


_clients: dict[int, httpx.AsyncClient] = {}


def _http() -> httpx.AsyncClient:
    """One client per event loop (an httpx client cannot be shared across loops)."""
    if _client is not None:  # injected by tests
        return _client
    loop_id = id(asyncio.get_running_loop())
    client = _clients.get(loop_id)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=settings.http_timeout, follow_redirects=True,
                                   headers={"User-Agent": "ai-travel-agent/0.2 (graduation project)"})
        _clients[loop_id] = client
    return client


def cache_key(method: str, url: str, params: dict | None, body: Any = None) -> str:
    clean = {k: v for k, v in (params or {}).items() if k not in SECRET_PARAMS and v is not None}
    raw = json.dumps([method.upper(), url, clean, body], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def start_turn() -> None:
    """Reset the per-turn SerpApi counter (called at the start of each chat turn)."""
    global _serpapi_calls, _turn_cap
    _serpapi_calls = 0
    _turn_cap = settings.serpapi_calls_per_turn


def allow_extra_calls(n: int) -> None:
    """A multi-city trip researches several cities in one turn: raise this turn's cap."""
    global _turn_cap
    _turn_cap = max(_turn_cap, settings.serpapi_calls_per_turn + max(0, n))


def serpapi_calls_this_turn() -> int:
    return _serpapi_calls


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
        return hit[0]
    if mode == "replay":
        raise ReplayMiss(f"{service}: no recorded response for {url} {json.dumps({k: v for k, v in params.items() if k not in SECRET_PARAMS})}")
    global _serpapi_calls
    if service == "serpapi":
        if not settings.serpapi_key:
            raise ProviderError("SERPAPI_API_KEY is not configured")
        if _serpapi_calls >= _turn_cap:
            if hit is not None:  # stale beats nothing when the quota guard trips
                log.warning("SerpApi per-turn cap reached; serving stale cache for %s", url)
                return hit[0]
            raise QuotaExceeded(f"SerpApi per-turn call cap ({_turn_cap}) reached")
        _serpapi_calls += 1
    started = time.perf_counter()
    try:
        resp = await _http().request(method, url, params=params, json=json_body, headers=headers)
    except httpx.HTTPError as exc:
        if hit is not None:
            log.warning("%s unreachable, serving stale cache: %s", service, redact(str(exc)))
            return hit[0]
        raise ProviderError(f"{service} unreachable: {exc}") from exc
    ms = (time.perf_counter() - started) * 1000
    cache().log(service, url, False, ms)
    if resp.status_code == 400 and service == "serpapi" and "Unsupported" in resp.text:
        cache().put(key, service, url, params, resp.json())  # engine not on this plan: remember it
        raise ProviderError(f"SerpApi: {resp.json().get('error')}")
    if resp.status_code >= 400:
        if hit is not None:
            log.warning("%s returned %s, serving stale cache", service, resp.status_code)
            return hit[0]
        raise ProviderError(f"{service} HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if service == "serpapi" and isinstance(data, dict) and data.get("error"):
        # SerpApi reports "no results" as an error; that is a valid, cacheable answer.
        if "hasn't returned any results" not in data["error"]:
            raise ProviderError(f"SerpApi: {data['error']}")
    cache().put(key, service, url, params, data)
    return data


BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36 "
              "(Dalili travel planner; reads published prices)")
MAX_PAGE_BYTES = 1_500_000


def _public_http_url(url: str) -> bool:
    """Only public http(s) pages: no local / private hosts (the URLs come from third-party data)."""
    from ipaddress import ip_address
    from urllib.parse import urlparse

    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    host = u.hostname.lower()
    if host in ("localhost",) or host.endswith((".local", ".internal")):
        return False
    try:
        ip = ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
    except ValueError:
        return True  # a domain name


async def fetch_page(url: str, ttl_s: float = 30 * 86400) -> dict[str, Any]:
    """An HTML page (cached like any API response): {"url": final url, "html": text}. Raises ProviderError."""
    if not _public_http_url(url):
        raise ProviderError(f"refused to fetch {url}")
    key = cache_key("GET", url, None, "page")
    mode = settings.http_mode
    hit = cache().get(key) if mode in ("cache", "replay") else None
    if hit is not None and (mode == "replay" or time.time() - hit[1] < ttl_s):
        return hit[0]
    if mode == "replay":
        raise ReplayMiss(f"page: no recorded response for {url}")
    started = time.perf_counter()
    try:
        resp = await _http().get(url, headers={"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml",
                                               "Accept-Language": "en,*;q=0.5"}, timeout=12)
    except httpx.HTTPError as exc:
        if hit is not None:
            return hit[0]
        raise ProviderError(f"page unreachable: {type(exc).__name__}") from exc
    cache().log("page", url, False, (time.perf_counter() - started) * 1000)
    ctype = resp.headers.get("content-type", "")
    if resp.status_code >= 400 or "html" not in ctype:
        raise ProviderError(f"page HTTP {resp.status_code} ({ctype.split(';')[0] or 'unknown type'})")
    page = {"url": str(resp.url), "html": resp.text[:MAX_PAGE_BYTES]}
    cache().put(key, "page", url, {}, page)
    return page


async def serpapi(engine: str, ttl_s: float, **params: Any) -> dict:
    return await fetch_json("serpapi", "https://serpapi.com/search.json",
                            {"engine": engine, "api_key": settings.serpapi_key, **params}, ttl_s=ttl_s)


HOUR = 3600
DAY = 24 * HOUR
