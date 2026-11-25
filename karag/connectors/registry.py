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
from pathlib import Path
from typing import Protocol

from urllib.parse import quote

from ..domain import new_id
from ..errors import AccessDenied, KaragError, NotFoundError, ValidationError
from ..secrets import seal, unseal
from .rest import RestConnector
from .sql import SqlConnector

# connector kinds understood by :func:`build_connector`
SQLITE = "sql_sqlite"
POSTGRES = "sql_postgres"
MYSQL = "sql_mysql"
REST = "rest"
KINDS = (SQLITE, POSTGRES, MYSQL, REST)
SQL_KINDS = (SQLITE, POSTGRES, MYSQL)

# config keys whose values are secrets: redacted whenever a spec is serialised
# and sealed (encrypted) at rest when KARAG_SECRET_KEY is configured
_SECRET_KEYS = frozenset({"dsn", "path", "headers", "token", "password"})


def build_dsn(kind: str, *, host: str, port: int | None, database: str,
              username: str, password: str, ssl: bool = False) -> str:
    """A DSN from the pieces a person can type: no engineer needed for the URL."""
    if kind not in (POSTGRES, MYSQL):
        raise ValidationError("a DSN can be built for postgres or mysql only")
    if not host.strip() or not database.strip():
        raise ValidationError("host and database name are required")
    scheme = "postgresql" if kind == POSTGRES else "mysql"
    default_port = 5432 if kind == POSTGRES else 3306
    auth = quote(username, safe="")
    if password:
        auth += ":" + quote(password, safe="")
    dsn = f"{scheme}://{auth}@{host.strip()}:{int(port or default_port)}/{database.strip()}"
    if ssl:
        dsn += "?sslmode=require" if kind == POSTGRES else "?ssl=1"
    return dsn


class ConnectorNotFound(NotFoundError):
    pass


def resolve_secret(value: str) -> str:
    """Resolve an ``env:NAME`` indirection; plain values pass through.

    Lets an operator keep the real DSN/token in the environment (or a secrets
    manager that populates it) while the database only stores the *name*.
    """
    value = unseal(value) if isinstance(value, str) else value
    if isinstance(value, str) and value.startswith("env:"):
        name = value[4:]
        resolved = os.environ.get(name)
        if resolved is None:
            raise KaragError(f"connector references missing env var {name!r}")
        return resolved
    return value


def seal_config(config: dict) -> dict:
    """Seal every secret-bearing value before the spec is stored."""
    out = dict(config)
    for key in _SECRET_KEYS:
        value = out.get(key)
        if isinstance(value, str):
            out[key] = seal(value)
    return out


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
    # What the guided onboarding learned and decided: a plain-language
    # description, the compact schema the query skill is described with, the
    # audience, whether the assistant may write its own read-only queries, the
    # knowledge document that describes the database, an upload's import report.
    metadata: dict = field(default_factory=dict)

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
            "metadata": self.metadata,
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


def is_sql_kind(kind: str) -> bool:
    return kind in SQL_KINDS


def validate_spec(kind: str, config: dict) -> None:
    """Reject a connector definition that couldn't possibly be safe/valid."""
    if kind not in KINDS:
        raise ValidationError(f"unknown connector kind {kind!r}; expected one of {KINDS}")
    if kind in SQL_KINDS:
        key = "path" if kind == SQLITE else "dsn"
        if not config.get(key):
            raise ValidationError(f"{kind} connector requires config.{key}")
    elif kind == REST:
        base = config.get("base_url", "")
        if not base:
            raise ValidationError("rest connector requires config.base_url")
        if not str(base).startswith(("http://", "https://")):
            raise ValidationError("base_url must be an http(s) URL")


@dataclass(frozen=True)
class SqlitePolicy:
    """Which SQLite files a tenant's connection may open.

    A SQLite "connection" is a path on the platform's own disk, so without a
    rule an author could point one at the platform's databases — every
    tenant's accounts, chats, audit trail and documents — or at another
    tenant's upload. The rule: a tenant may open files under its own upload
    folder (``<upload_dir>/<tenant>/``, where the Data page saves them) and
    under directories an operator cleared explicitly, and never one of the
    platform's own database files. Checked on the *resolved* path (symlinks
    and ``env:`` indirection included) every time a connector is built.
    """

    upload_dir: str | None = None
    extra_dirs: tuple[str, ...] = ()
    deny_files: tuple[str, ...] = ()

    def check(self, tenant_id: str, path: str) -> Path:
        if not path or path.strip() == ":memory:":
            raise AccessDenied("a SQLite connection needs a database file")
        target = Path(path).expanduser().resolve()
        denied = {Path(f).expanduser().resolve() for f in self.deny_files if f and f != ":memory:"}
        if target in denied:
            raise AccessDenied("that file belongs to the platform itself and cannot be a data source")
        roots = [Path(d).expanduser().resolve() for d in self.extra_dirs if d]
        if self.upload_dir:
            roots.append((Path(self.upload_dir).expanduser() / tenant_id).resolve())
        if not any(target == r or r in target.parents for r in roots):
            raise AccessDenied(
                "a SQLite file can only be one uploaded on the Data page "
                "(or kept in a directory the operator cleared)"
            )
        return target


def build_connector(
    spec: ConnectorSpec, policy: SqlitePolicy | None = None
) -> SqlConnector | RestConnector:
    """Materialise a live, guard-railed connector from its stored definition.

    Every SQL connector is created through :class:`SqlConnector`, which enforces
    read-only single statements, a row limit and a statement timeout — the
    guardrails §6 requires. A REST connector can only issue GETs. A SQLite
    path is checked against the deployment's :class:`SqlitePolicy` here, so a
    stored definition that breaks the rule never opens anything.
    """
    if spec.kind == SQLITE:
        path = resolve_secret(spec.config["path"])
        if policy is not None:
            policy.check(spec.tenant_id, path)
        return SqlConnector(
            sqlite_path=path,
            default_row_limit=spec.row_limit,
            timeout_s=spec.timeout_s,
        )
    if spec.kind == POSTGRES:
        return SqlConnector(
            pg_dsn=resolve_secret(spec.config["dsn"]),
            default_row_limit=spec.row_limit,
            timeout_s=spec.timeout_s,
        )
    if spec.kind == MYSQL:
        return SqlConnector(
            mysql_dsn=resolve_secret(spec.config["dsn"]),
            default_row_limit=spec.row_limit,
            timeout_s=spec.timeout_s,
        )
    if spec.kind == REST:
        raw_headers = spec.config.get("headers") or {}
        headers = {k: resolve_secret(v) for k, v in raw_headers.items()}
        allow_private = str(spec.config.get("allow_private", "")).lower() in ("1", "true", "yes")
        return RestConnector(
            resolve_secret(spec.config["base_url"]),
            headers=headers,
            allow_private=allow_private,
            timeout_s=spec.timeout_s,
        )
    raise ValidationError(f"unknown connector kind {spec.kind!r}")


class ConnectorStore(Protocol):
    def create(self, spec: ConnectorSpec) -> ConnectorSpec: ...
    def update(self, spec: ConnectorSpec) -> ConnectorSpec: ...
    def get(self, tenant_id: str, connector_id: str) -> ConnectorSpec | None: ...
    def list(self, tenant_id: str) -> list[ConnectorSpec]: ...
    def list_all(self) -> list[ConnectorSpec]: ...
    def delete(self, tenant_id: str, connector_id: str) -> bool: ...


class InMemoryConnectorStore:
    def __init__(self) -> None:
        self._by_id: dict[str, ConnectorSpec] = {}

    def create(self, spec: ConnectorSpec) -> ConnectorSpec:
        self._by_id[spec.id] = spec
        return spec

    def update(self, spec: ConnectorSpec) -> ConnectorSpec:
        self._by_id[spec.id] = spec
        return spec

    def list_all(self) -> list[ConnectorSpec]:
        return sorted(self._by_id.values(), key=lambda s: s.created_at)

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
    created_at REAL NOT NULL,
    metadata   TEXT NOT NULL DEFAULT '{}'
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
            # a database created before metadata existed gets the column added
            have = {r["name"] for r in self._conn.execute("PRAGMA table_info(connectors)")}
            if "metadata" not in have:
                self._conn.execute(
                    "ALTER TABLE connectors ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'"
                )

    def create(self, spec: ConnectorSpec) -> ConnectorSpec:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO connectors (id, tenant_id, name, kind, config, row_limit,"
                " timeout_s, created_by, created_at, metadata) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    spec.id, spec.tenant_id, spec.name, spec.kind,
                    json.dumps(spec.config), spec.row_limit, spec.timeout_s,
                    spec.created_by, spec.created_at, json.dumps(spec.metadata),
                ),
            )
        return spec

    def update(self, spec: ConnectorSpec) -> ConnectorSpec:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE connectors SET name=?, config=?, row_limit=?, timeout_s=?,"
                " metadata=? WHERE id=? AND tenant_id=?",
                (
                    spec.name, json.dumps(spec.config), spec.row_limit, spec.timeout_s,
                    json.dumps(spec.metadata), spec.id, spec.tenant_id,
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
        metadata=json.loads(row["metadata"] or "{}") if "metadata" in row.keys() else {},
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
    metadata: dict | None = None,
) -> ConnectorSpec:
    """Validate and build a spec (not yet stored). Secrets are sealed here."""
    validate_spec(kind, config)
    return ConnectorSpec(
        id=new_id("conn"),
        tenant_id=tenant_id,
        name=name,
        kind=kind,
        config=seal_config(config),
        row_limit=row_limit,
        timeout_s=timeout_s,
        created_by=created_by,
        metadata=dict(metadata or {}),
    )
