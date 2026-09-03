"""Read-only SQL connector with guardrails (SQLite, PostgreSQL, MySQL).

Every query is:
  * **read-only** — only ``SELECT`` / ``WITH`` statements are accepted; a single
    statement only (no stacked queries), enforced before execution *and* by the
    backend (SQLite ``query_only`` pragma / read-only mode, a read-only
    transaction on Postgres and MySQL).
  * **parameterized** — values are bound, never string-formatted. Authors may
    write ``:name`` on every backend; it is translated to the driver's
    ``%(name)s`` style where needed.
  * **bounded** — a row limit is always applied, and a statement timeout guards
    against runaway queries.

SQLite support is stdlib-only (offline-testable); Postgres uses ``psycopg`` and
MySQL ``pymysql`` (both lazy imports).

The connector can also *describe* the database it points at — tables, columns
and a few sample rows — which is what lets a non-engineer connect a database
and have the assistant understand it without anyone writing SQL first.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import decimal
import re
import sqlite3
import time
from urllib.parse import parse_qs, unquote, urlsplit

from ..errors import KaragError

_READ_ONLY_START = re.compile(r"^\s*(?:--[^\n]*\n|\s)*(select|with)\b", re.IGNORECASE)
# ``:name`` placeholders (not ``::type`` casts, not ``:=``)
_NAMED = re.compile(r"(?<![:\w]):([a-zA-Z_]\w*)(?!\s*=)")
_IDENT = re.compile(r"^[A-Za-z_][\w$]*$")

SQLITE = "sqlite"
POSTGRES = "postgres"
MYSQL = "mysql"


class ReadOnlyViolation(KaragError):
    """A query that is not a single read-only statement was rejected."""


def assert_read_only(sql: str) -> None:
    if not _READ_ONLY_START.match(sql):
        raise ReadOnlyViolation("only SELECT/WITH queries are allowed")
    # forbid statement stacking: a ';' anywhere except trailing whitespace
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise ReadOnlyViolation("multiple statements are not allowed")


def to_pyformat(sql: str) -> str:
    """``:name`` → ``%(name)s`` for the DB-API drivers that want it."""
    return _NAMED.sub(r"%(\1)s", sql)


def parse_mysql_dsn(dsn: str) -> dict:
    """``mysql://user:pass@host:3306/db?ssl=1`` → pymysql connect kwargs."""
    parts = urlsplit(dsn)
    if parts.scheme not in ("mysql", "mariadb"):
        raise KaragError("mysql dsn must start with mysql://")
    if not parts.hostname or not parts.path.strip("/"):
        raise KaragError("mysql dsn needs a host and a database name")
    query = parse_qs(parts.query)
    kwargs: dict = {
        "host": parts.hostname,
        "port": parts.port or 3306,
        "user": unquote(parts.username or ""),
        "password": unquote(parts.password or ""),
        "database": parts.path.strip("/"),
        "charset": "utf8mb4",
    }
    if query.get("ssl", ["0"])[0].lower() in ("1", "true", "require"):
        kwargs["ssl"] = {"ssl": True}
    return kwargs


def _jsonable(value):
    """Sample values as JSON-safe scalars, so a schema can travel over HTTP."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} bytes>"
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (_dt.date, _dt.datetime, _dt.time)):
        return value.isoformat()
    if isinstance(value, _dt.timedelta):
        return value.total_seconds()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class SqlConnector:
    def __init__(
        self,
        *,
        sqlite_path: str | None = None,
        pg_dsn: str | None = None,
        mysql_dsn: str | None = None,
        default_row_limit: int = 1000,
        timeout_s: float = 5.0,
    ) -> None:
        given = [x for x in (sqlite_path, pg_dsn, mysql_dsn) if x]
        if len(given) != 1:
            raise KaragError("provide exactly one of sqlite_path / pg_dsn / mysql_dsn")
        self.sqlite_path = sqlite_path
        self.pg_dsn = pg_dsn
        self.mysql_dsn = mysql_dsn
        self.default_row_limit = default_row_limit
        self.timeout_s = timeout_s

    @property
    def backend(self) -> str:
        if self.sqlite_path is not None:
            return SQLITE
        if self.pg_dsn is not None:
            return POSTGRES
        return MYSQL

    async def query(
        self, sql: str, params: dict | None = None, *, row_limit: int | None = None
    ) -> list[dict]:
        assert_read_only(sql)
        limit = row_limit or self.default_row_limit
        params = params or {}
        if self.sqlite_path is not None:
            return await asyncio.to_thread(self._sqlite_query, sql, params, limit)
        if self.pg_dsn is not None:
            return await self._pg_query(to_pyformat(sql), params, limit)
        return await asyncio.to_thread(self._mysql_query, to_pyformat(sql), params, limit)

    async def test(self) -> None:
        """Open a connection and run the cheapest possible statement."""
        await self.query("SELECT 1 AS ok", row_limit=1)

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
            self.pg_dsn, autocommit=False, connect_timeout=int(self.timeout_s) or 5
        ) as conn:
            await conn.set_read_only(True)
            timeout_ms = int(self.timeout_s * 1000)
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
                await cur.execute(sql, params)
                rows = await cur.fetchmany(limit)
            await conn.rollback()  # read-only; never commit
            return [dict(r) for r in rows]

    # ---- MySQL / MariaDB (pymysql) ----
    def _mysql_query(self, sql: str, params: dict, limit: int) -> list[dict]:
        try:
            import pymysql  # noqa: PLC0415
            from pymysql.cursors import DictCursor  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise KaragError("mysql connector requires pymysql: pip install pymysql") from exc

        kwargs = parse_mysql_dsn(self.mysql_dsn or "")
        conn = pymysql.connect(
            **kwargs,
            cursorclass=DictCursor,
            connect_timeout=int(self.timeout_s) or 5,
            read_timeout=int(self.timeout_s) or 5,
            autocommit=False,
        )
        try:
            with conn.cursor() as cur:
                # The server refuses writes for the rest of this session.
                cur.execute("SET SESSION TRANSACTION READ ONLY")
                timeout_ms = int(self.timeout_s * 1000)
                for stmt in (
                    f"SET SESSION MAX_EXECUTION_TIME={timeout_ms}",  # MySQL ≥ 5.7.8
                    f"SET SESSION max_statement_time={self.timeout_s}",  # MariaDB
                ):
                    try:
                        cur.execute(stmt)
                        break
                    except Exception:  # noqa: BLE001 — the other dialect's knob
                        continue
                conn.begin()
                cur.execute(sql, params)
                rows = cur.fetchmany(limit)
            conn.rollback()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ---- describing the database ------------------------------------------

    def quote(self, name: str) -> str:
        if not _IDENT.match(name):
            raise KaragError(f"unsafe identifier {name!r}")
        return f"`{name}`" if self.backend == MYSQL else f'"{name}"'

    async def introspect(self, *, max_tables: int = 60, sample_rows: int = 3) -> dict:
        """Tables, columns, an estimated row count and a few sample rows.

        Read-only like everything else here, and bounded: at most
        ``max_tables`` tables and ``sample_rows`` rows each, so a warehouse
        with thousands of tables does not turn into a thousand queries.
        """
        if self.backend == SQLITE:
            tables = await self._sqlite_tables()
        elif self.backend == POSTGRES:
            tables = await self._pg_tables()
        else:
            tables = await self._mysql_tables()

        out: list[dict] = []
        for t in tables[:max_tables]:
            try:
                sample = await self.query(
                    f"SELECT * FROM {t['qualified']} LIMIT {int(sample_rows)}",
                    row_limit=sample_rows,
                )
            except Exception:  # noqa: BLE001 — a view we may not read; keep going
                sample = []
            out.append({
                "name": t["name"],
                "schema": t.get("schema", ""),
                "kind": t.get("kind", "table"),
                "columns": t["columns"],
                "row_estimate": t.get("rows"),
                "sample": [{k: _jsonable(v) for k, v in row.items()} for row in sample],
            })
        return {
            "backend": self.backend,
            "tables": out,
            "truncated": len(tables) > max_tables,
            "table_count": len(tables),
        }

    async def _sqlite_tables(self) -> list[dict]:
        rows = await self.query(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view')"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name",
            row_limit=1000,
        )
        tables = []
        for r in rows:
            name = r["name"]
            if not _IDENT.match(name):
                continue
            cols = await self.query(
                "SELECT name, type FROM pragma_table_info(:t)", {"t": name}, row_limit=500
            )
            count = None
            if r["type"] == "table":
                try:
                    c = await self.query(f"SELECT COUNT(*) AS n FROM {self.quote(name)}", row_limit=1)
                    count = int(c[0]["n"]) if c else None
                except Exception:  # noqa: BLE001
                    count = None
            tables.append({
                "name": name, "kind": r["type"], "qualified": self.quote(name),
                "columns": [{"name": c["name"], "type": (c["type"] or "").lower()} for c in cols],
                "rows": count,
            })
        return tables

    async def _pg_tables(self) -> list[dict]:
        rows = await self.query(
            "SELECT table_schema, table_name, table_type FROM information_schema.tables"
            " WHERE table_schema NOT IN ('pg_catalog','information_schema')"
            " AND table_type IN ('BASE TABLE','VIEW') ORDER BY table_schema, table_name",
            row_limit=1000,
        )
        tables = []
        for r in rows:
            schema, name = r["table_schema"], r["table_name"]
            if not (_IDENT.match(schema) and _IDENT.match(name)):
                continue
            cols = await self.query(
                "SELECT column_name, data_type FROM information_schema.columns"
                " WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position",
                {"s": schema, "t": name}, row_limit=500,
            )
            est = None
            try:
                e = await self.query(
                    "SELECT reltuples::bigint AS n FROM pg_class c JOIN pg_namespace n"
                    " ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname = :t",
                    {"s": schema, "t": name}, row_limit=1,
                )
                est = int(e[0]["n"]) if e and e[0]["n"] is not None and e[0]["n"] >= 0 else None
            except Exception:  # noqa: BLE001
                est = None
            if est is None:
                # never analysed (reltuples = -1): a table that young is small
                # enough to count, and the statement timeout bounds it anyway
                try:
                    c = await self.query(
                        f"SELECT COUNT(*) AS n FROM {self.quote(schema)}.{self.quote(name)}", row_limit=1
                    )
                    est = int(c[0]["n"]) if c else None
                except Exception:  # noqa: BLE001
                    est = None
            tables.append({
                "name": name, "schema": schema,
                "kind": "view" if r["table_type"] == "VIEW" else "table",
                "qualified": f"{self.quote(schema)}.{self.quote(name)}",
                "columns": [{"name": c["column_name"], "type": c["data_type"]} for c in cols],
                "rows": est,
            })
        return tables

    async def _mysql_tables(self) -> list[dict]:
        rows = await self.query(
            "SELECT table_name AS name, table_type AS kind, table_rows AS n"
            " FROM information_schema.tables WHERE table_schema = DATABASE()"
            " ORDER BY table_name",
            row_limit=1000,
        )
        tables = []
        for r in rows:
            name = r["name"]
            if not _IDENT.match(name):
                continue
            cols = await self.query(
                "SELECT column_name AS name, data_type AS type FROM information_schema.columns"
                " WHERE table_schema = DATABASE() AND table_name = :t ORDER BY ordinal_position",
                {"t": name}, row_limit=500,
            )
            tables.append({
                "name": name,
                "kind": "view" if str(r["kind"]).upper() == "VIEW" else "table",
                "qualified": self.quote(name),
                "columns": [{"name": c["name"], "type": c["type"]} for c in cols],
                "rows": int(r["n"]) if r.get("n") is not None else None,
            })
        return tables
