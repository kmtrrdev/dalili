"""Accounts: sign up, sign in, sessions, guests and the activity log the recommender learns from.

Security choices (standard library only):
- Passwords: scrypt (memory-hard) with a random 16-byte salt per user, compared in constant time.
- Sessions: a random 256-bit token in an HttpOnly, SameSite=Lax cookie; only its SHA-256 is stored, so a leaked
  database cannot be replayed as a login. Sessions slide forward while used and expire after 30 days idle.
- Brute force: failed sign-ins are rate limited per email and per IP address.
- Guests: anyone can plan without an account (a random guest id in a cookie). Signing up or in moves the
  guest's trips to the account.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .store import Store

SESSION_COOKIE = "dalili_session"
GUEST_COOKIE = "dalili_guest"
SESSION_DAYS = 30
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[a-z]{2,}$", re.I)
GUEST_RE = re.compile(r"^g_[A-Za-z0-9_-]{16,40}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    prefs TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    city TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_user ON activity(user_id);
"""

ACTIVITY_KINDS = {"search", "view", "dismiss", "like"}


class AuthError(Exception):
    """A user-facing problem (bad input, wrong password...). `field` points the form at the right input."""

    def __init__(self, message: str, field: str | None = None, status: int = 400):
        super().__init__(message)
        self.field, self.status = field, status


@dataclass
class Identity:
    """Who is calling: a signed-in user, or a guest (user is None)."""
    id: str
    user: dict | None = None

    @property
    def signed_in(self) -> bool:
        return self.user is not None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, key = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(bytes.fromhex(key)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), key)


# A hash to check against when the email is unknown, so a wrong email takes as long as a wrong password
# (response time must not reveal which emails have accounts).
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def clean_email(email: str) -> str:
    email = (email or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise AuthError("Enter a valid email address.", "email")
    return email


def clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not 1 <= len(name) <= 60:
        raise AuthError("Enter your name (up to 60 characters).", "name")
    return name


def check_password_rules(password: str, field: str = "password") -> None:
    if len(password or "") < 8:
        raise AuthError("Use at least 8 characters.", field)
    if len(password) > 128:
        raise AuthError("Use at most 128 characters.", field)
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise AuthError("Mix letters and numbers.", field)


class RateLimiter:
    """Failed attempts per key in a sliding window (in memory: one server process)."""

    def __init__(self, limit: int, window_s: float):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def _trim(self, key: str) -> deque[float]:
        q = self.hits[key]
        while q and time.monotonic() - q[0] > self.window:
            q.popleft()
        return q

    def blocked_for(self, key: str) -> int:
        q = self._trim(key)
        return int(self.window - (time.monotonic() - q[0])) + 1 if len(q) >= self.limit else 0

    def fail(self, key: str) -> None:
        self._trim(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self.hits.pop(key, None)


class Accounts:
    """Users, sessions and activity, in the same database as the trips."""

    def __init__(self, store: Store):
        self.store = store
        self._conn, self._lock = store._conn, store._lock
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)
            self._conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_now().isoformat(),))  # housekeeping
        self.by_email = RateLimiter(5, 15 * 60)
        self.by_ip = RateLimiter(30, 15 * 60)

    # -- users -----------------------------------------------------------------
    @staticmethod
    def _user(row) -> dict | None:
        if not row:
            return None
        uid, email, name, prefs, created, last = row
        return {"id": uid, "email": email, "name": name, "prefs": json.loads(prefs or "{}"),
                "created_at": created, "last_login_at": last}

    _COLS = "id, email, name, prefs, created_at, last_login_at"

    def get_user(self, user_id: str) -> dict | None:
        with self._lock:
            return self._user(self._conn.execute(f"SELECT {self._COLS} FROM users WHERE id = ?", (user_id,)).fetchone())

    def sign_up(self, name: str, email: str, password: str, guest_id: str | None = None) -> dict:
        name, email = clean_name(name), clean_email(email)
        check_password_rules(password)
        uid = "u_" + secrets.token_hex(8)
        now = _now().isoformat()
        with self._lock, self._conn:
            if self._conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                raise AuthError("An account with this email already exists - sign in instead.", "email", 409)
            first = self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            self._conn.execute("INSERT INTO users(id, email, name, password_hash, prefs, created_at, last_login_at) "
                               "VALUES (?, ?, ?, ?, '{}', ?, ?)", (uid, email, name, hash_password(password), now, now))
        if first:
            # Trips planned before accounts existed belong to the first account created on this server.
            self.store.reassign("default", uid)
        if guest_id:
            self.store.reassign(guest_id, uid)
            self._move_activity(guest_id, uid)
        return self.get_user(uid)

    def sign_in(self, email: str, password: str, ip: str, guest_id: str | None = None) -> dict:
        email = (email or "").strip().lower()
        for limiter, key in ((self.by_email, email), (self.by_ip, ip)):
            wait = limiter.blocked_for(key)
            if wait:
                raise AuthError(f"Too many attempts. Try again in {max(1, wait // 60)} min.", None, 429)
        with self._lock:
            row = self._conn.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
        ok = verify_password(password or "", row[1] if row else _DUMMY_HASH) and row is not None
        if not ok:
            self.by_email.fail(email)
            self.by_ip.fail(ip)
            raise AuthError("Email or password is incorrect.", "password", 401)
        self.by_email.reset(email)
        with self._lock, self._conn:
            self._conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_now().isoformat(), row[0]))
        if guest_id:
            self.store.reassign(guest_id, row[0])
            self._move_activity(guest_id, row[0])
        return self.get_user(row[0])

    def update_profile(self, user_id: str, name: str | None = None, prefs: dict | None = None) -> dict:
        user = self.get_user(user_id)
        if user is None:
            raise AuthError("Account not found.", None, 404)
        new_name = clean_name(name) if name is not None else user["name"]
        new_prefs = {**user["prefs"], **(prefs or {})}
        with self._lock, self._conn:
            self._conn.execute("UPDATE users SET name = ?, prefs = ? WHERE id = ?",
                               (new_name, json.dumps(new_prefs), user_id))
        return self.get_user(user_id)

    def change_password(self, user_id: str, current: str, new: str, keep_token: str | None) -> None:
        with self._lock:
            row = self._conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or not verify_password(current or "", row[0]):
            raise AuthError("Your current password is incorrect.", "current", 401)
        check_password_rules(new, "new")
        if current == new:
            raise AuthError("Choose a password different from the current one.", "new")
        with self._lock, self._conn:
            self._conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new), user_id))
            # Every other device is signed out.
            self._conn.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
                               (user_id, _token_hash(keep_token) if keep_token else ""))

    def delete_account(self, user_id: str, password: str) -> None:
        with self._lock:
            row = self._conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or not verify_password(password or "", row[0]):
            raise AuthError("Your password is incorrect.", "password", 401)
        with self._lock, self._conn:
            for table in ("sessions", "activity"):
                self._conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.store.delete_user_data(user_id)

    # -- sessions --------------------------------------------------------------
    def create_session(self, user_id: str, user_agent: str = "") -> str:
        token = secrets.token_urlsafe(32)
        now = _now()
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                               (_token_hash(token), user_id, now.isoformat(),
                                (now + timedelta(days=SESSION_DAYS)).isoformat(), (user_agent or "")[:200]))
        return token

    def session_user(self, token: str | None) -> dict | None:
        if not token or len(token) > 100:
            return None
        h = _token_hash(token)
        with self._lock:
            row = self._conn.execute("SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (h,)).fetchone()
        if not row:
            return None
        expires = datetime.fromisoformat(row[1])
        now = _now()
        if expires <= now:
            self.end_session(token)
            return None
        if expires - now < timedelta(days=SESSION_DAYS - 1):  # sliding expiry, written at most once a day
            with self._lock, self._conn:
                self._conn.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                                   ((now + timedelta(days=SESSION_DAYS)).isoformat(), h))
        return self.get_user(row[0])

    def end_session(self, token: str | None) -> None:
        if token:
            with self._lock, self._conn:
                self._conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

    # -- activity (what the recommender learns from) ---------------------------
    def log_activity(self, user_id: str, kind: str, city: str) -> None:
        city = re.sub(r"\s+", " ", (city or "").strip())[:80]
        if kind not in ACTIVITY_KINDS or not city:
            return
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO activity(user_id, kind, city, at) VALUES (?, ?, ?, ?)",
                               (user_id, kind, city, _now().isoformat()))
            # Keep the most recent 500 events per person.
            self._conn.execute("DELETE FROM activity WHERE user_id = ? AND id NOT IN "
                               "(SELECT id FROM activity WHERE user_id = ? ORDER BY id DESC LIMIT 500)", (user_id, user_id))

    def activity(self, user_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT kind, city, at FROM activity WHERE user_id = ? ORDER BY id",
                                      (user_id,)).fetchall()
        return [{"kind": k, "city": c, "at": at} for k, c, at in rows]

    def undo_dismiss(self, user_id: str, city: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM activity WHERE user_id = ? AND kind = 'dismiss' AND city = ?", (user_id, city))

    def _move_activity(self, src: str, dst: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE activity SET user_id = ? WHERE user_id = ?", (dst, src))


def new_guest_id() -> str:
    return "g_" + secrets.token_urlsafe(18)
