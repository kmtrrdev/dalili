"""Request-level protections: who the client really is (behind the proxy), cost limits, admin-only details.

Rate limits protect the expensive endpoints (each chat turn spends model tokens and live searches). They are kept
per process in memory - with several replicas each enforces its own window, which still bounds abuse; a shared store
(Redis) would make them global. Limits are configuration, not travel logic.
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from collections import deque

from fastapi import HTTPException, Request


def client_ip(request: Request) -> str:
    """The real client address. Azure's ingress appends the address it saw to X-Forwarded-For, so the right-most
    entry is the one a client cannot forge (anything to its left came from the client)."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        last = fwd.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Sliding-window limits: at most `limit` events per `window_s` for each key."""

    def __init__(self, limit: int, window_s: float, max_keys: int = 50_000):
        self.limit, self.window_s, self.max_keys = limit, window_s, max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> float | None:
        """Record one event; returns None if allowed, else the seconds until the next one is allowed."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                if len(self._hits) >= self.max_keys:  # bounded memory: forget the oldest windows
                    for k in list(self._hits)[: self.max_keys // 10]:
                        del self._hits[k]
                q = self._hits[key] = deque()
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                return round(self.window_s - (now - q[0]), 1)
            q.append(now)
            return None


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# Expensive work (model + live searches): per traveller (account or guest id) and per IP address.
TURNS_PER_IDENTITY = RateLimiter(env_int("DALILI_TURNS_PER_10MIN", 30), 600)
TURNS_PER_IP = RateLimiter(env_int("DALILI_TURNS_PER_IP_10MIN", 90), 600)
LIGHT_PER_IP = RateLimiter(env_int("DALILI_LIGHT_PER_IP_MIN", 120), 60)
# Live booking-offer lookups (one paid search per hotel, cached): looser than turns, but never unlimited.
OFFERS_PER_IDENTITY = RateLimiter(env_int("DALILI_OFFERS_PER_10MIN", 40), 600)

MAX_MESSAGE_CHARS = env_int("DALILI_MAX_MESSAGE_CHARS", 4000)


def _limit(pairs: tuple[tuple[RateLimiter, str], ...]) -> None:
    for limiter, key in pairs:
        wait = limiter.hit(key)
        if wait is not None:
            raise HTTPException(429, f"Too many requests - please wait {int(wait) + 1} seconds.",
                                headers={"Retry-After": str(int(wait) + 1)})


def limit_expensive(request: Request, identity_id: str) -> None:
    _limit(((TURNS_PER_IDENTITY, identity_id), (TURNS_PER_IP, client_ip(request))))


def limit_offers(request: Request, identity_id: str) -> None:
    _limit(((OFFERS_PER_IDENTITY, identity_id), (LIGHT_PER_IP, client_ip(request))))


def limit_light(request: Request) -> None:
    wait = LIGHT_PER_IP.hit(client_ip(request))
    if wait is not None:
        raise HTTPException(429, "Too many requests - please slow down.", headers={"Retry-After": str(int(wait) + 1)})


def is_admin(request: Request) -> bool:
    """Operational details (provider status, quota, internal tools) need DALILI_ADMIN_TOKEN in X-Admin-Token."""
    token = os.getenv("DALILI_ADMIN_TOKEN", "")
    given = request.headers.get("x-admin-token", "")
    return bool(token) and hmac.compare_digest(token, given)
