"""Read-only SQL connector with guardrails (SQLite + PostgreSQL).

Every query is:
  * **read-only** — only ``SELECT`` / ``WITH`` statements are accepted; a single
    statement only (no stacked queries), enforced before execution *and* by the
    backend (SQLite ``query_only`` pragma / read-only mode, Postgres read-only
    transaction).
  * **parameterized** — values are bound, never string-formatted.
  * **bounded** — a row limit is always applied, and a statement timeout guards
    against runaway queries.

SQLite support is stdlib-only (offline-testable); Postgres uses ``psycopg``
(lazy import).
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
import time

from ..errors import KaragError

_READ_ONLY_START = re.compile(r"^\s*(?:--[^\n]*\n|\s)*(select|with)\b", re.IGNORECASE)


class ReadOnlyViolation(KaragError):
    """A query that is not a single read-only statement was rejected."""


def assert_read_only(sql: str) -> None:
    if not _READ_ONLY_START.match(sql):
        raise ReadOnlyViolation("only SELECT/WITH queries are allowed")
    # forbid statement stacking: a ';' anywhere except trailing whitespace
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise ReadOnlyViolation("multiple statements are not allowed")


class SqlConnector:
    def __init__(
        self,
        *,
        sqlite_path: str | None = None,
        pg_dsn: str | None = None,
        default_row_limit: int = 1000,
        timeout_s: float = 5.0,
    ) -> None:
        if bool(sqlite_path) == bool(pg_dsn):
            raise KaragError("provide exactly one of sqlite_path / pg_dsn")
        self.sqlite_path = sqlite_path
        self.pg_dsn = pg_dsn
        self.default_row_limit = default_row_limit
        self.timeout_s = timeout_s

    async def query(
        self, sql: str, params: dict | None = None, *, row_limit: int | None = None
    ) -> list[dict]:
        assert_read_only(sql)
        limit = row_limit or self.default_row_limit
        params = params or {}
        if self.sqlite_path is not None:
            return await asyncio.to_thread(self._sqlite_query, sql, params, limit)
        return await self._pg_query(sql, params, limit)

    # ---- SQLite (stdlib) ----
    def _sqlite_query(self, sql: str, params: dict, limit: int) -> list[dict]:
        uri = f"file:{self.sqlite_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=self.timeout_s)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            deadline = time.monotonic() + self.timeout_s
            # progress handler aborts a long-running statement (returns non-zero)
            conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10000)
            cur = conn.execute(sql, params)
            rows = cur.fetchmany(limit)
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ---- PostgreSQL (psycopg) ----
    async def _pg_query(self, sql: str, params: dict, limit: int) -> list[dict]:
        try:
            import psycopg  # noqa: PLC0415
            from psycopg.rows import dict_row  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise KaragError("pg connector requires psycopg: pip install 'psycopg[binary]'") from exc

        async with await psycopg.AsyncConnection.connect(
            self.pg_dsn, autocommit=False
        ) as conn:
            await conn.set_read_only(True)
            timeout_ms = int(self.timeout_s * 1000)
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
                await cur.execute(sql, params)
                rows = await cur.fetchmany(limit)
            await conn.rollback()  # read-only; never commit
            return [dict(r) for r in rows]
