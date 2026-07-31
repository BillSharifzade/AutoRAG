"""Stored code-change proposals — the review queue.

A proposal is the durable record of "the AI wrote this, here is the diff, here
is what the tests said, nobody has applied it yet". It outlives the chat turn
that produced it so a human can come back and decide.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

from ..domain import new_id
from ..errors import NotFoundError

PENDING = "pending"
APPLIED = "applied"
DISCARDED = "discarded"


class ProposalNotFound(NotFoundError):
    pass


@dataclass
class Proposal:
    id: str
    tenant_id: str
    author: str
    summary: str
    branch: str
    diff: str
    files_changed: list[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    tests_passed: bool = False
    tests_summary: str = ""
    status: str = PENDING
    model: str = ""
    created_at: float = field(default_factory=time.time)
    resolved_at: float = 0.0
    resolved_by: str = ""

    def to_dict(self, *, include_diff: bool = True) -> dict:
        payload = {
            "id": self.id,
            "author": self.author,
            "summary": self.summary,
            "branch": self.branch,
            "files_changed": self.files_changed,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "tests_passed": self.tests_passed,
            "tests_summary": self.tests_summary,
            "status": self.status,
            "model": self.model,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
        }
        if include_diff:
            payload["diff"] = self.diff
        return payload


class ProposalStore(Protocol):
    def create(self, proposal: Proposal) -> Proposal: ...
    def get(self, proposal_id: str) -> Proposal | None: ...
    def list(self, *, status: str | None = None) -> list[Proposal]: ...
    def update(self, proposal: Proposal) -> Proposal: ...


class InMemoryProposalStore:
    def __init__(self) -> None:
        self._by_id: dict[str, Proposal] = {}

    def create(self, proposal: Proposal) -> Proposal:
        self._by_id[proposal.id] = proposal
        return proposal

    def get(self, proposal_id: str) -> Proposal | None:
        return self._by_id.get(proposal_id)

    def list(self, *, status: str | None = None) -> list[Proposal]:
        items = [p for p in self._by_id.values() if status is None or p.status == status]
        return sorted(items, key=lambda p: p.created_at, reverse=True)

    def update(self, proposal: Proposal) -> Proposal:
        self._by_id[proposal.id] = proposal
        return proposal


_SCHEMA = """
CREATE TABLE IF NOT EXISTS code_proposals (
    id            TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    author        TEXT NOT NULL,
    summary       TEXT NOT NULL,
    branch        TEXT NOT NULL,
    diff          TEXT NOT NULL,
    files_changed TEXT NOT NULL DEFAULT '[]',
    insertions    INTEGER NOT NULL DEFAULT 0,
    deletions     INTEGER NOT NULL DEFAULT 0,
    tests_passed  INTEGER NOT NULL DEFAULT 0,
    tests_summary TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending',
    model         TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    resolved_at   REAL NOT NULL DEFAULT 0,
    resolved_by   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS code_proposals_status
    ON code_proposals (status, created_at DESC);
"""


class SqliteProposalStore:
    def __init__(self, path: str = "karag_app.db") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def create(self, p: Proposal) -> Proposal:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO code_proposals (id, tenant_id, author, summary, branch,"
                " diff, files_changed, insertions, deletions, tests_passed,"
                " tests_summary, status, model, created_at, resolved_at, resolved_by)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    p.id, p.tenant_id, p.author, p.summary, p.branch, p.diff,
                    json.dumps(p.files_changed), p.insertions, p.deletions,
                    int(p.tests_passed), p.tests_summary, p.status, p.model,
                    p.created_at, p.resolved_at, p.resolved_by,
                ),
            )
        return p

    def get(self, proposal_id: str) -> Proposal | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM code_proposals WHERE id=?", (proposal_id,)
            ).fetchone()
        return _row_to_proposal(row) if row else None

    def list(self, *, status: str | None = None) -> list[Proposal]:
        sql = "SELECT * FROM code_proposals"
        params: tuple = ()
        if status:
            sql += " WHERE status=?"
            params = (status,)
        sql += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_proposal(r) for r in rows]

    def update(self, p: Proposal) -> Proposal:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE code_proposals SET status=?, resolved_at=?, resolved_by=?"
                " WHERE id=?",
                (p.status, p.resolved_at, p.resolved_by, p.id),
            )
        return p


def _row_to_proposal(row: sqlite3.Row) -> Proposal:
    return Proposal(
        id=row["id"],
        tenant_id=row["tenant_id"],
        author=row["author"],
        summary=row["summary"],
        branch=row["branch"],
        diff=row["diff"],
        files_changed=json.loads(row["files_changed"]),
        insertions=row["insertions"],
        deletions=row["deletions"],
        tests_passed=bool(row["tests_passed"]),
        tests_summary=row["tests_summary"],
        status=row["status"],
        model=row["model"],
        created_at=row["created_at"],
        resolved_at=row["resolved_at"],
        resolved_by=row["resolved_by"],
    )


def new_proposal_id() -> str:
    return new_id("prop")
