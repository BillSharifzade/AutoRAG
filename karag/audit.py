"""Audit trail — who did what, to which resource, and whether it was allowed.

Required by the concept for cross-tenant/compliance assurance. Every
security-relevant action (ingest, retrieval, skill execution, answer) records an
immutable event. Sinks are pluggable: in-memory (tests), JSONL file (durable),
or a null sink (disabled).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class AuditEvent:
    action: str  # ingest | retrieve | skill_execute | ask
    tenant_id: str
    user_id: str
    decision: str  # allow | deny
    resource: str = ""
    detail: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    # device / identity context, filled by the API layer at record time
    ip: str = ""
    user_agent: str = ""
    roles: tuple[str, ...] = ()


@runtime_checkable
class AuditLog(Protocol):
    def record(self, event: AuditEvent) -> None: ...


class NullAuditLog:
    def record(self, event: AuditEvent) -> None:  # noqa: D401
        return None


class InMemoryAuditLog:
    """Bounded in-memory sink. Keeps the most recent ``maxlen`` events so a
    long-running process can't grow without limit; older events age out."""

    def __init__(self, maxlen: int = 10_000) -> None:
        self.events: deque[AuditEvent] = deque(maxlen=maxlen)

    def record(self, event: AuditEvent) -> None:
        self.events.append(_enrich(event))

    def for_tenant(self, tenant_id: str) -> list[AuditEvent]:
        return [e for e in self.events if e.tenant_id == tenant_id]


class JsonlAuditLog:
    """Append-only JSON-lines sink. One event per line, flushed immediately."""

    def __init__(self, path: str) -> None:
        self.path = path

    def record(self, event: AuditEvent) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(_enrich(event)), ensure_ascii=False) + "\n")


_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    action     TEXT NOT NULL,
    tenant_id  TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    decision   TEXT NOT NULL,
    resource   TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT '{}',
    ip         TEXT NOT NULL DEFAULT '',
    user_agent TEXT NOT NULL DEFAULT '',
    roles      TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS audit_events_tenant ON audit_events (tenant_id, ts DESC);
"""


class SqliteAuditLog:
    """Durable, queryable audit trail — the §12 "app database" role.

    The in-memory sink loses every event on restart, which is the one thing an
    audit trail may not do: §13 lists cross-tenant leakage as the top risk and
    names *audit* as its control, and a control that forgets is not a control.
    Rows are append-only (no update/delete path exists on this class).
    """

    def __init__(self, path: str = "karag_app.db", *, retention_days: float | None = None) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._retention_days = retention_days
        with self._conn:
            self._conn.executescript(_AUDIT_SCHEMA)

    def record(self, event: AuditEvent) -> None:
        e = _enrich(event)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO audit_events (ts, action, tenant_id, user_id, decision,"
                " resource, detail, ip, user_agent, roles) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    e.ts, e.action, e.tenant_id, e.user_id, e.decision, e.resource,
                    json.dumps(e.detail, default=str), e.ip, e.user_agent,
                    json.dumps(list(e.roles)),
                ),
            )

    def for_tenant(self, tenant_id: str, *, limit: int = 1000) -> list[AuditEvent]:
        """Most recent events for one tenant, oldest-first within the window."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM (SELECT * FROM audit_events WHERE tenant_id=?"
                " ORDER BY ts DESC LIMIT ?) ORDER BY ts ASC",
                (tenant_id, limit),
            ).fetchall()
        return [_row_to_event(r) for r in rows]

    def purge_expired(self) -> int:
        """Drop events older than the retention window (no-op if unset)."""
        if not self._retention_days:
            return 0
        cutoff = time.time() - self._retention_days * 86400
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM audit_events WHERE ts < ?", (cutoff,))
        return cur.rowcount


def _row_to_event(row) -> AuditEvent:
    return AuditEvent(
        action=row["action"],
        tenant_id=row["tenant_id"],
        user_id=row["user_id"],
        decision=row["decision"],
        resource=row["resource"],
        detail=json.loads(row["detail"]),
        ts=row["ts"],
        ip=row["ip"],
        user_agent=row["user_agent"],
        roles=tuple(json.loads(row["roles"])),
    )


def _enrich(event: AuditEvent) -> AuditEvent:
    """Attach the active request's device/role context, if any."""
    from .request_context import enrich_event

    return enrich_event(event)
