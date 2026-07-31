"""Connector registry — the stored, tenant-owned definitions of *where* data lives.

The concept doc's §6 gives exactly two ways to connect a company's data, both
read-only and both wrapped as skills: a **view** on the database, or a **limited
API**. A :class:`ConnectorSpec` is the stored form of one of those endpoints, so
a technical specialist can register a data source once (through the API/UI) and
then build any number of skills on top of it — without editing Python.

Secrets never live in this store in the clear if you don't want them to: any
config value may be written as ``env:NAME`` and is resolved from the process
environment at connection time. Whatever *is* stored is redacted on read
(:meth:`ConnectorSpec.to_public_dict`) so a DSN or bearer token can never be
served back over HTTP — and, more importantly, never reaches the model.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

from ..domain import new_id
from ..errors import KaragError, NotFoundError, ValidationError
from .rest import RestConnector
from .sql import SqlConnector

# connector kinds understood by :func:`build_connector`
SQLITE = "sql_sqlite"
POSTGRES = "sql_postgres"
REST = "rest"
KINDS = (SQLITE, POSTGRES, REST)

# config keys whose values are secrets: redacted whenever a spec is serialised
_SECRET_KEYS = frozenset({"dsn", "path", "headers", "token", "password"})


class ConnectorNotFound(NotFoundError):
    pass


def resolve_secret(value: str) -> str:
    """Resolve an ``env:NAME`` indirection; plain values pass through.

    Lets an operator keep the real DSN/token in the environment (or a secrets
    manager that populates it) while the database only stores the *name*.
    """
    if isinstance(value, str) and value.startswith("env:"):
        name = value[4:]
        resolved = os.environ.get(name)
        if resolved is None:
            raise KaragError(f"connector references missing env var {name!r}")
        return resolved
    return value


@dataclass
class ConnectorSpec:
    """A registered, read-only data source belonging to one tenant."""

    id: str
    tenant_id: str
    name: str
    kind: str  # sql_sqlite | sql_postgres | rest
    config: dict = field(default_factory=dict)
    row_limit: int = 1000
    timeout_s: float = 5.0
    created_by: str = ""
    created_at: float = field(default_factory=time.time)

    def to_public_dict(self) -> dict:
        """Serialisation safe to send over HTTP: secrets replaced by a marker."""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "config": _redact(self.config),
            "row_limit": self.row_limit,
            "timeout_s": self.timeout_s,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


def _redact(config: dict) -> dict:
    """Replace secret-bearing values with a marker, keeping ``env:`` hints visible.

    An ``env:NAME`` value is not itself a secret (it's a pointer), so it stays —
    that's what an operator needs to see to debug a misconfigured connector.
    """
    out: dict = {}
    for key, value in config.items():
        if key in _SECRET_KEYS and not (isinstance(value, str) and value.startswith("env:")):
            out[key] = "••••••" if value else ""
        else:
            out[key] = value
    return out


def validate_spec(kind: str, config: dict) -> None:
    """Reject a connector definition that couldn't possibly be safe/valid."""
    if kind not in KINDS:
        raise ValidationError(f"unknown connector kind {kind!r}; expected one of {KINDS}")
    if kind in (SQLITE, POSTGRES):
        key = "path" if kind == SQLITE else "dsn"
        if not config.get(key):
            raise ValidationError(f"{kind} connector requires config.{key}")
    elif kind == REST:
        base = config.get("base_url", "")
        if not base:
            raise ValidationError("rest connector requires config.base_url")
        if not str(base).startswith(("http://", "https://")):
            raise ValidationError("base_url must be an http(s) URL")


def build_connector(spec: ConnectorSpec) -> SqlConnector | RestConnector:
    """Materialise a live, guard-railed connector from its stored definition.

    Every SQL connector is created through :class:`SqlConnector`, which enforces
    read-only single statements, a row limit and a statement timeout — the
    guardrails §6 requires. A REST connector can only issue GETs.
    """
    if spec.kind == SQLITE:
        return SqlConnector(
            sqlite_path=resolve_secret(spec.config["path"]),
            default_row_limit=spec.row_limit,
            timeout_s=spec.timeout_s,
        )
    if spec.kind == POSTGRES:
        return SqlConnector(
            pg_dsn=resolve_secret(spec.config["dsn"]),
            default_row_limit=spec.row_limit,
            timeout_s=spec.timeout_s,
        )
    if spec.kind == REST:
        raw_headers = spec.config.get("headers") or {}
        headers = {k: resolve_secret(v) for k, v in raw_headers.items()}
        return RestConnector(
            resolve_secret(spec.config["base_url"]),
            headers=headers,
            timeout_s=spec.timeout_s,
        )
    raise ValidationError(f"unknown connector kind {spec.kind!r}")


class ConnectorStore(Protocol):
    def create(self, spec: ConnectorSpec) -> ConnectorSpec: ...
    def get(self, tenant_id: str, connector_id: str) -> ConnectorSpec | None: ...
    def list(self, tenant_id: str) -> list[ConnectorSpec]: ...
    def delete(self, tenant_id: str, connector_id: str) -> bool: ...


class InMemoryConnectorStore:
    def __init__(self) -> None:
        self._by_id: dict[str, ConnectorSpec] = {}

    def create(self, spec: ConnectorSpec) -> ConnectorSpec:
        self._by_id[spec.id] = spec
        return spec

    def get(self, tenant_id: str, connector_id: str) -> ConnectorSpec | None:
        spec = self._by_id.get(connector_id)
        # tenant check is the isolation boundary: never hand back another
        # company's data source, not even to say it exists.
        return spec if spec is not None and spec.tenant_id == tenant_id else None

    def list(self, tenant_id: str) -> list[ConnectorSpec]:
        return sorted(
            (s for s in self._by_id.values() if s.tenant_id == tenant_id),
            key=lambda s: s.created_at,
        )

    def delete(self, tenant_id: str, connector_id: str) -> bool:
        if self.get(tenant_id, connector_id) is None:
            return False
        del self._by_id[connector_id]
        return True


_SCHEMA = """
CREATE TABLE IF NOT EXISTS connectors (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    config     TEXT NOT NULL,
    row_limit  INTEGER NOT NULL,
    timeout_s  REAL NOT NULL,
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS connectors_tenant ON connectors (tenant_id, created_at);
"""


class SqliteConnectorStore:
    """Durable connector definitions — they survive a restart, unlike code."""

    def __init__(self, path: str = "karag_app.db") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def create(self, spec: ConnectorSpec) -> ConnectorSpec:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO connectors (id, tenant_id, name, kind, config, row_limit,"
                " timeout_s, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    spec.id, spec.tenant_id, spec.name, spec.kind,
                    json.dumps(spec.config), spec.row_limit, spec.timeout_s,
                    spec.created_by, spec.created_at,
                ),
            )
        return spec

    def get(self, tenant_id: str, connector_id: str) -> ConnectorSpec | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM connectors WHERE id=? AND tenant_id=?",
                (connector_id, tenant_id),
            ).fetchone()
        return _row_to_spec(row) if row else None

    def list(self, tenant_id: str) -> list[ConnectorSpec]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM connectors WHERE tenant_id=? ORDER BY created_at",
                (tenant_id,),
            ).fetchall()
        return [_row_to_spec(r) for r in rows]

    def list_all(self) -> list[ConnectorSpec]:
        """Every tenant's connectors — for boot-time materialisation only."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM connectors ORDER BY created_at"
            ).fetchall()
        return [_row_to_spec(r) for r in rows]

    def delete(self, tenant_id: str, connector_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM connectors WHERE id=? AND tenant_id=?",
                (connector_id, tenant_id),
            )
        return cur.rowcount > 0


def _row_to_spec(row: sqlite3.Row) -> ConnectorSpec:
    return ConnectorSpec(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        kind=row["kind"],
        config=json.loads(row["config"]),
        row_limit=row["row_limit"],
        timeout_s=row["timeout_s"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def new_connector(
    tenant_id: str,
    *,
    name: str,
    kind: str,
    config: dict,
    row_limit: int = 1000,
    timeout_s: float = 5.0,
    created_by: str = "",
) -> ConnectorSpec:
    """Validate and build a spec (not yet stored)."""
    validate_spec(kind, config)
    return ConnectorSpec(
        id=new_id("conn"),
        tenant_id=tenant_id,
        name=name,
        kind=kind,
        config=config,
        row_limit=row_limit,
        timeout_s=timeout_s,
        created_by=created_by,
    )
