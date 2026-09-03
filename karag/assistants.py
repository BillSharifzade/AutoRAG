"""Assistants — the no-code builder's backend.

A non-technical user creates an *assistant* by naming it, writing a short
instruction, and choosing which skills it may use — no programming. An assistant
is a stored, tenant-scoped configuration; asking "through" it runs the
orchestrator with that persona and a restricted skill set. A thin web form is
all the UI needs on top of this.

Security: an assistant is bound to a tenant, and it can only ever narrow what its
caller is already allowed to do (its skill allow-list intersects the principal's
RBAC-visible skills). It cannot widen access.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field

from .domain import Answer, Principal, new_id
from .errors import AccessDenied, NotFoundError
from .llm.base import ChatMessage, ImagePart
from .orchestrator import Orchestrator


class AssistantNotFound(NotFoundError):
    pass


# Anyone in the tenant may *use* an assistant; changing or deleting one is for
# whoever made it and for the roles that shape the company's tooling.
MANAGE_ROLES: frozenset[str] = frozenset({"admin", "skill_author", "ceo"})


def can_manage(principal: Principal, assistant: "Assistant") -> bool:
    return (
        assistant.created_by == principal.user_id
        or principal.has_any_role(MANAGE_ROLES)
    )


@dataclass
class Assistant:
    id: str
    tenant_id: str
    name: str
    instruction: str = ""
    # None = every skill the caller may see; otherwise restrict to these names.
    allowed_skill_names: frozenset[str] | None = None
    # answer language: "auto" mirrors the user's language; ru/tg/en pin it.
    language: str = "auto"
    created_by: str = ""
    metadata: dict = field(default_factory=dict)


class AssistantRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, Assistant] = {}

    def create(
        self,
        principal: Principal,
        *,
        name: str,
        instruction: str = "",
        allowed_skill_names: frozenset[str] | None = None,
        language: str = "auto",
    ) -> Assistant:
        assistant = Assistant(
            id=new_id("asst"),
            tenant_id=principal.tenant_id,
            name=name,
            instruction=instruction,
            allowed_skill_names=allowed_skill_names,
            language=language,
            created_by=principal.user_id,
        )
        self._by_id[assistant.id] = assistant
        return assistant

    def get(self, principal: Principal, assistant_id: str) -> Assistant:
        a = self._by_id.get(assistant_id)
        if a is None or a.tenant_id != principal.tenant_id:
            # don't disclose existence across tenants
            raise AssistantNotFound(assistant_id)
        return a

    def update(
        self,
        principal: Principal,
        assistant_id: str,
        *,
        name: str | None = None,
        instruction: str | None = None,
        allowed_skill_names: frozenset[str] | None = None,
        clear_allowed: bool = False,
        language: str | None = None,
    ) -> Assistant:
        """Edit an existing assistant (tenant-checked).

        ``allowed_skill_names=None`` leaves the allow-list unchanged; pass
        ``clear_allowed=True`` to reset it to "every skill the caller may see".
        """
        a = self.get(principal, assistant_id)  # raises across tenants
        if name is not None:
            a.name = name
        if instruction is not None:
            a.instruction = instruction
        if language is not None:
            a.language = language
        if clear_allowed:
            a.allowed_skill_names = None
        elif allowed_skill_names is not None:
            a.allowed_skill_names = allowed_skill_names
        return a

    def list_for(self, principal: Principal) -> list[Assistant]:
        return [a for a in self._by_id.values() if a.tenant_id == principal.tenant_id]

    def delete(self, principal: Principal, assistant_id: str) -> bool:
        a = self.get(principal, assistant_id)  # raises across tenants
        del self._by_id[a.id]
        return True


_SCHEMA = """
CREATE TABLE IF NOT EXISTS assistants (
    id             TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL,
    name           TEXT NOT NULL,
    instruction    TEXT NOT NULL DEFAULT '',
    allowed_skills TEXT,               -- JSON array, or NULL = "all you can see"
    language       TEXT NOT NULL DEFAULT 'auto',
    created_by     TEXT NOT NULL DEFAULT '',
    metadata       TEXT NOT NULL DEFAULT '{}',
    created_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS assistants_tenant ON assistants (tenant_id, created_at);
"""


class SqliteAssistantRegistry:
    """Durable assistants — same interface as :class:`AssistantRegistry`.

    Without this, every assistant a non-technical user builds disappears on the
    next restart, which makes the §12 "no-code builder" unusable as a product.
    Tenant scoping is enforced in SQL on every read, so the isolation guarantee
    is identical to the in-memory registry's.
    """

    def __init__(self, path: str = "karag_app.db") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def create(
        self,
        principal: Principal,
        *,
        name: str,
        instruction: str = "",
        allowed_skill_names: frozenset[str] | None = None,
        language: str = "auto",
    ) -> Assistant:
        a = Assistant(
            id=new_id("asst"),
            tenant_id=principal.tenant_id,
            name=name,
            instruction=instruction,
            allowed_skill_names=allowed_skill_names,
            language=language,
            created_by=principal.user_id,
        )
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO assistants (id, tenant_id, name, instruction,"
                " allowed_skills, language, created_by, metadata, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    a.id, a.tenant_id, a.name, a.instruction,
                    None if a.allowed_skill_names is None
                    else json.dumps(sorted(a.allowed_skill_names)),
                    a.language, a.created_by, json.dumps(a.metadata), time.time(),
                ),
            )
        return a

    def get(self, principal: Principal, assistant_id: str) -> Assistant:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM assistants WHERE id=? AND tenant_id=?",
                (assistant_id, principal.tenant_id),
            ).fetchone()
        if row is None:
            raise AssistantNotFound(assistant_id)
        return _row_to_assistant(row)

    def update(
        self,
        principal: Principal,
        assistant_id: str,
        *,
        name: str | None = None,
        instruction: str | None = None,
        allowed_skill_names: frozenset[str] | None = None,
        clear_allowed: bool = False,
        language: str | None = None,
    ) -> Assistant:
        a = self.get(principal, assistant_id)  # raises across tenants
        if name is not None:
            a.name = name
        if instruction is not None:
            a.instruction = instruction
        if language is not None:
            a.language = language
        if clear_allowed:
            a.allowed_skill_names = None
        elif allowed_skill_names is not None:
            a.allowed_skill_names = allowed_skill_names
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE assistants SET name=?, instruction=?, allowed_skills=?,"
                " language=? WHERE id=? AND tenant_id=?",
                (
                    a.name, a.instruction,
                    None if a.allowed_skill_names is None
                    else json.dumps(sorted(a.allowed_skill_names)),
                    a.language, a.id, a.tenant_id,
                ),
            )
        return a

    def list_for(self, principal: Principal) -> list[Assistant]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM assistants WHERE tenant_id=? ORDER BY created_at",
                (principal.tenant_id,),
            ).fetchall()
        return [_row_to_assistant(r) for r in rows]

    def delete(self, principal: Principal, assistant_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM assistants WHERE id=? AND tenant_id=?",
                (assistant_id, principal.tenant_id),
            )
        if cur.rowcount == 0:
            raise AssistantNotFound(assistant_id)
        return True


def _row_to_assistant(row: sqlite3.Row) -> Assistant:
    raw = row["allowed_skills"]
    return Assistant(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        instruction=row["instruction"],
        allowed_skill_names=None if raw is None else frozenset(json.loads(raw)),
        language=row["language"],
        created_by=row["created_by"],
        metadata=json.loads(row["metadata"]),
    )


class AssistantService:
    def __init__(self, registry: AssistantRegistry, orchestrator: Orchestrator) -> None:
        self._registry = registry
        self._orchestrator = orchestrator

    async def ask(
        self,
        principal: Principal,
        assistant_id: str,
        query: str,
        *,
        images: list["ImagePart"] | None = None,
        history: list["ChatMessage"] | None = None,
        language: str | None = None,
        on_event=None,
    ) -> Answer:
        assistant = self._registry.get(principal, assistant_id)  # tenant-checked
        if assistant.tenant_id != principal.tenant_id:  # defense in depth
            raise AccessDenied("assistant belongs to another tenant")
        # The answer follows the question's language; the stored ``language``
        # is kept for compatibility and no longer pins anything.
        return await self._orchestrator.ask(
            principal,
            query,
            system_extra=assistant.instruction or None,
            allowed_skill_names=assistant.allowed_skill_names,
            images=images,
            history=history,
            language=language,
            on_event=on_event,
        )
