"""API data sources: an endpoint the platform fetches on demand or on a timer.

A :class:`DataSource` is what the guided flow saves once the person has read
the model's description and confirmed it. It can be used two ways, together
or alone:

* **as a skill** — a tool named ``fetch_<name>`` that GETs the endpoint live
  when the assistant needs today's figures;
* **as knowledge** — the payload is written into the knowledge plane as a
  document (one record per line, cited like any other) and refreshed on a
  cadence; when the endpoint's bytes have not changed nothing is rewritten.

The sync runs inside the scheduler process, under a synthetic principal that
belongs to the source's tenant — never across tenants.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol
from urllib.parse import urlsplit

from ..audit import AuditEvent, AuditLog, NullAuditLog
from ..domain import DataClass, Principal, new_id
from ..errors import AccessDenied, NotFoundError, ValidationError
from ..knowledge.ingest import IngestionService
from ..rbac import can_access
from ..skills.base import Skill, SkillResult
from ..skills.catalog import can_author
from ..skills.registry import SkillRegistry
from ..vectorstore.base import VectorStore
from ..web.guard import WebPolicy, check_url
from .analysis import slug
from .payload import Payload, fetch_payload, find_records, profile_payload, render_as_text

Fetcher = Callable[[str, WebPolicy], Awaitable[Payload]]

MIN_INTERVAL_S = 300.0
DEFAULT_INTERVAL_S = 3600.0
# what a live skill hands the model: enough rows to answer, never a dump
SKILL_MAX_RECORDS = 200
SKILL_MAX_CHARS = 60_000


class DataSourceNotFound(NotFoundError):
    pass


@dataclass
class DataSource:
    id: str
    tenant_id: str
    name: str
    url: str
    description: str = ""
    # field name -> meaning, as confirmed by the person
    field_notes: dict = field(default_factory=dict)
    data_class: DataClass = DataClass.OPERATIONAL
    required_roles: tuple[str, ...] = ()
    skill_enabled: bool = True
    sync_enabled: bool = False
    sync_interval_s: float = DEFAULT_INTERVAL_S
    created_by: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_synced_at: float = 0.0
    last_checked_at: float = 0.0
    last_hash: str = ""
    last_status: str = ""  # "" | ok | unchanged | error
    last_error: str = ""
    last_records: int = 0
    document_id: str = ""

    @property
    def skill_name(self) -> str:
        return "fetch_" + slug(self.name)

    def due(self, now: float | None = None) -> bool:
        now = now or time.time()
        return self.sync_enabled and now >= self.last_checked_at + self.sync_interval_s

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "url": self.url,
            "description": self.description,
            "field_notes": self.field_notes,
            "data_class": self.data_class.value,
            "required_roles": list(self.required_roles),
            "skill_enabled": self.skill_enabled,
            "skill_name": self.skill_name,
            "sync_enabled": self.sync_enabled,
            "sync_interval_s": self.sync_interval_s,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_synced_at": self.last_synced_at,
            "last_checked_at": self.last_checked_at,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_records": self.last_records,
            "document_id": self.document_id,
        }


# ------------------------------------------------------------------ stores


class DataSourceStore(Protocol):
    def create(self, s: DataSource) -> DataSource: ...
    def update(self, s: DataSource) -> DataSource: ...
    def get(self, tenant_id: str, source_id: str) -> DataSource | None: ...
    def list(self, tenant_id: str) -> list[DataSource]: ...
    def list_all(self) -> list[DataSource]: ...
    def delete(self, tenant_id: str, source_id: str) -> bool: ...


class InMemoryDataSourceStore:
    def __init__(self) -> None:
        self._by_id: dict[str, DataSource] = {}

    def create(self, s: DataSource) -> DataSource:
        self._by_id[s.id] = s
        return s

    def update(self, s: DataSource) -> DataSource:
        s.updated_at = time.time()
        self._by_id[s.id] = s
        return s

    def get(self, tenant_id: str, source_id: str) -> DataSource | None:
        s = self._by_id.get(source_id)
        return s if s is not None and s.tenant_id == tenant_id else None

    def list(self, tenant_id: str) -> list[DataSource]:
        return sorted((s for s in self._by_id.values() if s.tenant_id == tenant_id), key=lambda s: s.created_at)

    def list_all(self) -> list[DataSource]:
        return sorted(self._by_id.values(), key=lambda s: s.created_at)

    def delete(self, tenant_id: str, source_id: str) -> bool:
        if self.get(tenant_id, source_id) is None:
            return False
        del self._by_id[source_id]
        return True


_SCHEMA = """
CREATE TABLE IF NOT EXISTS data_sources (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    field_notes     TEXT NOT NULL DEFAULT '{}',
    data_class      TEXT NOT NULL,
    required_roles  TEXT NOT NULL DEFAULT '[]',
    skill_enabled   INTEGER NOT NULL DEFAULT 1,
    sync_enabled    INTEGER NOT NULL DEFAULT 0,
    sync_interval_s REAL NOT NULL DEFAULT 3600,
    created_by      TEXT NOT NULL DEFAULT '',
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    last_synced_at  REAL NOT NULL DEFAULT 0,
    last_checked_at REAL NOT NULL DEFAULT 0,
    last_hash       TEXT NOT NULL DEFAULT '',
    last_status     TEXT NOT NULL DEFAULT '',
    last_error      TEXT NOT NULL DEFAULT '',
    last_records    INTEGER NOT NULL DEFAULT 0,
    document_id     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS data_sources_tenant ON data_sources (tenant_id, created_at);
"""

_COLS = (
    "id, tenant_id, name, url, description, field_notes, data_class, required_roles,"
    " skill_enabled, sync_enabled, sync_interval_s, created_by, created_at, updated_at,"
    " last_synced_at, last_checked_at, last_hash, last_status, last_error, last_records,"
    " document_id"
)


def _params(s: DataSource) -> tuple:
    return (
        s.id, s.tenant_id, s.name, s.url, s.description, json.dumps(s.field_notes),
        s.data_class.value, json.dumps(list(s.required_roles)), int(s.skill_enabled),
        int(s.sync_enabled), s.sync_interval_s, s.created_by, s.created_at, s.updated_at,
        s.last_synced_at, s.last_checked_at, s.last_hash, s.last_status, s.last_error,
        s.last_records, s.document_id,
    )


def _row(r: sqlite3.Row) -> DataSource:
    return DataSource(
        id=r["id"], tenant_id=r["tenant_id"], name=r["name"], url=r["url"],
        description=r["description"], field_notes=json.loads(r["field_notes"] or "{}"),
        data_class=DataClass(r["data_class"]),
        required_roles=tuple(json.loads(r["required_roles"] or "[]")),
        skill_enabled=bool(r["skill_enabled"]), sync_enabled=bool(r["sync_enabled"]),
        sync_interval_s=float(r["sync_interval_s"]), created_by=r["created_by"],
        created_at=r["created_at"], updated_at=r["updated_at"],
        last_synced_at=r["last_synced_at"], last_checked_at=r["last_checked_at"],
        last_hash=r["last_hash"], last_status=r["last_status"], last_error=r["last_error"],
        last_records=r["last_records"], document_id=r["document_id"],
    )


class SqliteDataSourceStore:
    def __init__(self, path: str = "karag_app.db") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def create(self, s: DataSource) -> DataSource:
        with self._lock, self._conn:
            self._conn.execute(
                f"INSERT INTO data_sources ({_COLS}) VALUES ({','.join('?' * 21)})", _params(s)
            )
        return s

    def update(self, s: DataSource) -> DataSource:
        s.updated_at = time.time()
        sets = ", ".join(f"{c.strip()}=?" for c in _COLS.split(",")[2:])
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE data_sources SET {sets} WHERE id=? AND tenant_id=?",
                (*_params(s)[2:], s.id, s.tenant_id),
            )
        return s

    def get(self, tenant_id: str, source_id: str) -> DataSource | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM data_sources WHERE id=? AND tenant_id=?", (source_id, tenant_id)
            ).fetchone()
        return _row(row) if row else None

    def list(self, tenant_id: str) -> list[DataSource]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM data_sources WHERE tenant_id=? ORDER BY created_at", (tenant_id,)
            ).fetchall()
        return [_row(r) for r in rows]

    def list_all(self) -> list[DataSource]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM data_sources ORDER BY created_at").fetchall()
        return [_row(r) for r in rows]

    def delete(self, tenant_id: str, source_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM data_sources WHERE id=? AND tenant_id=?", (source_id, tenant_id)
            )
        return cur.rowcount > 0


# ----------------------------------------------------------------- service


@dataclass
class SyncOutcome:
    source_id: str
    status: str  # ok | unchanged | error | skipped
    records: int = 0
    error: str = ""


def _sync_principal(source: DataSource) -> Principal:
    """The sync writes as the platform, inside the source's own tenant."""
    return Principal(source.tenant_id, "system:sync", ("admin",))


class DataSourceService:
    def __init__(
        self,
        store: DataSourceStore,
        registry: SkillRegistry,
        ingestion: IngestionService,
        vectors: VectorStore,
        *,
        policy: WebPolicy | None = None,
        fetch: Fetcher | None = None,
        audit: AuditLog | None = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._ingestion = ingestion
        self._vectors = vectors
        self._policy = policy or WebPolicy()
        self._fetch: Fetcher = fetch or fetch_payload
        self._audit = audit or NullAuditLog()

    # ---- reading ------------------------------------------------------------

    async def probe(self, principal: Principal, url: str) -> Payload:
        """Fetch the endpoint once for the guided flow (nothing is stored)."""
        self._require_author(principal)
        check_url(url, self._policy)
        return await self._fetch(url, self._policy)

    def list(self, principal: Principal) -> list[DataSource]:
        self._require_author(principal)
        return self._store.list(principal.tenant_id)

    def get(self, principal: Principal, source_id: str) -> DataSource:
        self._require_author(principal)
        s = self._store.get(principal.tenant_id, source_id)
        if s is None:
            raise DataSourceNotFound(source_id)
        return s

    # ---- writing ------------------------------------------------------------

    async def create(
        self,
        principal: Principal,
        *,
        name: str,
        url: str,
        description: str = "",
        field_notes: dict | None = None,
        data_class: DataClass = DataClass.OPERATIONAL,
        required_roles: tuple[str, ...] = (),
        skill_enabled: bool = True,
        sync_enabled: bool = False,
        sync_interval_s: float = DEFAULT_INTERVAL_S,
    ) -> DataSource:
        self._require_author(principal)
        if not can_access(principal, data_class):
            raise AccessDenied("you are not cleared for that data class and may not publish it")
        if not name.strip():
            raise ValidationError("a data source needs a name")
        check_url(url, self._policy)
        if any(s.name.strip().casefold() == name.strip().casefold() for s in self._store.list(principal.tenant_id)):
            raise ValidationError(f"a source named {name!r} already exists")
        source = DataSource(
            id=new_id("src"), tenant_id=principal.tenant_id, name=name.strip(), url=url.strip(),
            description=description.strip(), field_notes=dict(field_notes or {}),
            data_class=data_class, required_roles=tuple(required_roles),
            skill_enabled=skill_enabled, sync_enabled=sync_enabled,
            sync_interval_s=max(MIN_INTERVAL_S, float(sync_interval_s or DEFAULT_INTERVAL_S)),
            created_by=principal.user_id,
        )
        self._store.create(source)
        self._log(principal, "source_create", source.id, {"name": source.name, "url": source.url})
        self._materialize(source)
        if sync_enabled:
            await self.sync(source, force=True)
        return source

    async def update(self, principal: Principal, source_id: str, **changes) -> DataSource:
        source = self.get(principal, source_id)
        was_sync = source.sync_enabled
        for key, value in changes.items():
            if value is None or not hasattr(source, key):
                continue
            if key == "data_class":
                value = DataClass(value) if not isinstance(value, DataClass) else value
                if not can_access(principal, value):
                    raise AccessDenied("you are not cleared for that data class")
            if key == "required_roles":
                value = tuple(value)
            if key == "sync_interval_s":
                value = max(MIN_INTERVAL_S, float(value))
            if key == "url":
                check_url(value, self._policy)
            if key == "name" and not str(value).strip():
                raise ValidationError("a data source needs a name")
            setattr(source, key, value)
        self._store.update(source)
        self._registry.unregister(source.tenant_id, source.skill_name)
        self._materialize(source)
        self._log(principal, "source_update", source.id, {k: str(v)[:80] for k, v in changes.items() if v is not None})
        if source.sync_enabled and (not was_sync or "url" in changes):
            await self.sync(source, force=True)
        if not source.sync_enabled and was_sync and source.document_id:
            await self._drop_document(source)
        return source

    async def delete(self, principal: Principal, source_id: str) -> bool:
        source = self.get(principal, source_id)
        self._registry.unregister(source.tenant_id, source.skill_name)
        if source.document_id:
            await self._drop_document(source)
        self._store.delete(source.tenant_id, source.id)
        self._log(principal, "source_delete", source.id, {"name": source.name})
        return True

    # ---- sync ---------------------------------------------------------------

    async def sync(self, source: DataSource, *, force: bool = False) -> SyncOutcome:
        """Fetch, compare, and rewrite the knowledge document if anything changed."""
        if not source.sync_enabled and not force:
            return SyncOutcome(source.id, "skipped")
        source.last_checked_at = time.time()
        try:
            payload = await self._fetch(source.url, self._policy)
            if not force and payload.digest == source.last_hash:
                source.last_status = "unchanged"
                source.last_error = ""
                self._store.update(source)
                return SyncOutcome(source.id, "unchanged", source.last_records)
            profile = profile_payload(payload)
            text = render_as_text(payload, profile, title=source.name, url=source.url)
            doc = await self._ingestion.ingest_document(
                _sync_principal(source), title=source.name, text=text,
                data_class=source.data_class, source_uri=source.url,
                metadata={"data_source": source.id, "fetched_at": payload.fetched_at},
            )
            source.document_id = doc.id
            source.last_hash = payload.digest
            source.last_synced_at = time.time()
            source.last_records = profile.record_count
            source.last_status = "ok"
            source.last_error = ""
            self._store.update(source)
            self._audit.record(AuditEvent(
                action="source_sync", tenant_id=source.tenant_id, user_id="system:sync",
                decision="allow", resource=source.id,
                detail={"records": profile.record_count, "document_id": doc.id},
            ))
            return SyncOutcome(source.id, "ok", profile.record_count)
        except Exception as exc:  # noqa: BLE001 — recorded, never raised into the loop
            source.last_status = "error"
            source.last_error = f"{type(exc).__name__}: {exc}"[:400]
            self._store.update(source)
            self._audit.record(AuditEvent(
                action="source_sync", tenant_id=source.tenant_id, user_id="system:sync",
                decision="deny", resource=source.id, detail={"error": source.last_error},
            ))
            return SyncOutcome(source.id, "error", error=source.last_error)

    async def sync_now(self, principal: Principal, source_id: str) -> SyncOutcome:
        source = self.get(principal, source_id)
        return await self.sync(source, force=True)

    async def run_due(self, now: float | None = None) -> list[SyncOutcome]:
        """One pass for the scheduler: every source whose interval has elapsed."""
        out = []
        for source in self._store.list_all():
            if source.due(now):
                out.append(await self.sync(source))
        return out

    # ---- skills -------------------------------------------------------------

    def load_all(self) -> int:
        n = 0
        for source in self._store.list_all():
            if source.skill_enabled:
                self._materialize(source)
                n += 1
        return n

    def _materialize(self, source: DataSource) -> None:
        if not source.skill_enabled:
            return
        self._registry.register(self._make_skill(source))

    def _make_skill(self, source: DataSource) -> Skill:
        fetch, policy = self._fetch, self._policy
        host = urlsplit(source.url).hostname or source.url
        notes = "; ".join(f"{k}: {v}" for k, v in list(source.field_notes.items())[:30])
        description = (
            f"{source.description or source.name}. Live data fetched now from {host}. "
            f"Returns matching records with their fields{(' — ' + notes) if notes else ''}. "
            "Large feeds are cut to `limit` records, so pass `filter` (a word or value "
            "that must appear in a record, e.g. a country, a store, a code) to get the "
            "rows you need."
        )[:1500]

        async def handler(principal: Principal, args: dict) -> SkillResult:
            payload = await fetch(source.url, policy)
            profile = profile_payload(payload)
            limit = max(1, min(int(args.get("limit") or SKILL_MAX_RECORDS), 500))
            needle = str(args.get("filter") or "").strip().casefold()
            shown = f"GET {source.url}" + (f"  filter={needle!r}" if needle else "")
            data: object
            if profile.kind == "records":
                records = find_records(payload)
                total = len(records)
                if needle:
                    records = [r for r in records if _matches(r, needle)]
                data = {
                    "record_count": total,
                    "matched": len(records) if needle else total,
                    "returned": min(len(records), limit),
                    "records": records[:limit],
                }
            elif profile.kind == "text":
                data = {"text": str(payload.data)[:SKILL_MAX_CHARS]}
            else:
                data = payload.data
            text = json.dumps(data, ensure_ascii=False, default=str)
            if len(text) > SKILL_MAX_CHARS:
                data = {"truncated": True, "preview": text[:SKILL_MAX_CHARS]}
            return SkillResult(data=data, query_shown=shown)

        return Skill(
            name=source.skill_name,
            description=description,
            input_schema={
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "description": "Keep only records containing this text in any field (case-insensitive).",
                    },
                    "limit": {"type": "integer", "description": "At most this many records (default 200, max 500)."},
                },
                "required": [],
                "additionalProperties": False,
            },
            handler=handler,
            required_data_class=source.data_class,
            required_roles=frozenset(source.required_roles),
            tenant_id=source.tenant_id,
            label=source.name,
        )

    # ---- helpers ------------------------------------------------------------

    async def _drop_document(self, source: DataSource) -> None:
        await self._vectors.delete_document(tenant_id=source.tenant_id, document_id=source.document_id)
        source.document_id = ""
        source.last_hash = ""
        self._store.update(source)

    def _require_author(self, principal: Principal) -> None:
        if not can_author(principal):
            raise AccessDenied("connecting a data source requires an admin/skill_author role")

    def _log(self, principal: Principal, action: str, resource: str, detail: dict) -> None:
        self._audit.record(AuditEvent(
            action=action, tenant_id=principal.tenant_id, user_id=principal.user_id,
            decision="allow", resource=resource, detail=detail,
        ))


__all__ = [
    "DataSource", "DataSourceNotFound", "DataSourceService", "DataSourceStore",
    "InMemoryDataSourceStore", "SqliteDataSourceStore", "SyncOutcome",
]



def _matches(record: object, needle: str) -> bool:
    if isinstance(record, dict):
        return any(needle in str(v).casefold() for v in record.values())
    return needle in str(record).casefold()
