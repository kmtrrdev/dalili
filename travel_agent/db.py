"""Database connection: SQLite by default (development, tests), PostgreSQL when DATABASE_URL is set (production).

Store and Accounts speak a small, portable subset of SQL with sqlite3's API (`?` placeholders, `execute`,
`executescript`, `with conn:` transactions). For PostgreSQL this module wraps a psycopg connection behind that same
API, so the rest of the code doesn't change: placeholders become `%s`, SQLite-only DDL is translated, and a dropped
connection (idle timeout, server restart) is reopened transparently.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)


def database_url() -> str:
    return os.getenv("DATABASE_URL", "")


def connect(path: str):
    """A sqlite3-compatible connection: PostgreSQL if DATABASE_URL is a postgres URL, else SQLite at `path`."""
    url = database_url()
    if url.startswith(("postgres://", "postgresql://")):
        return PgConnection(url)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path, check_same_thread=False)


_DDL = [
    (re.compile(r"INTEGER PRIMARY KEY AUTOINCREMENT", re.I), "BIGSERIAL PRIMARY KEY"),
]


def _pg_sql(sql: str) -> str:
    for pattern, repl in _DDL:
        sql = pattern.sub(repl, sql)
    return sql.replace("?", "%s")  # the queries never contain a literal '?'


class PgConnection:
    """psycopg connection behind the sqlite3 API used by Store / Accounts (autocommit; `with conn:` = transaction)."""

    def __init__(self, url: str):
        import psycopg  # only needed in production

        self._psycopg = psycopg
        self._url = url
        self._conn = None
        self._tx = []
        self._open()

    def _open(self) -> None:
        self._conn = self._psycopg.connect(self._url, autocommit=True, connect_timeout=15)

    def _run(self, sql: str, params=()):
        try:
            return self._conn.execute(_pg_sql(sql), tuple(params))
        except self._psycopg.OperationalError:
            if self._tx:  # inside a transaction: can't silently retry half of it
                raise
            log.warning("database connection lost, reconnecting")
            self._open()
            return self._conn.execute(_pg_sql(sql), tuple(params))

    def execute(self, sql: str, params=()):
        return self._run(sql, params)

    def executescript(self, script: str) -> None:
        for stmt in (s.strip() for s in script.split(";")):
            if stmt:
                self._run(stmt)

    def __enter__(self):
        if self._conn.closed:
            self._open()
        tx = self._conn.transaction()
        tx.__enter__()
        self._tx.append(tx)
        return self

    def __exit__(self, exc_type, exc, tb):
        tx = self._tx.pop()
        return tx.__exit__(exc_type, exc, tb)
