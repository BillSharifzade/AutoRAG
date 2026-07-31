"""RBAC-filtered retrieval — the knowledge-plane guard.

The principal's clearance is resolved to a set of data classes and passed *into*
the store's search, so filtering happens before scoring. A final defensive
assertion re-checks every returned chunk against the clearance and tenant, so a
buggy or malicious store implementation still cannot leak.
"""

from __future__ import annotations

from ..audit import AuditEvent, AuditLog, NullAuditLog
from ..domain import Principal, RetrievedChunk
from ..errors import TenantIsolationError
from ..llm.base import Embedder
from ..rbac import visible_classes
from ..vectorstore.base import VectorStore


class RetrievalService:
    def __init__(
        self, store: VectorStore, embedder: Embedder, audit: AuditLog | None = None
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._audit = audit or NullAuditLog()

    async def retrieve(
        self, principal: Principal, query: str, *, top_k: int = 5
    ) -> list[RetrievedChunk]:
        allowed = visible_classes(principal)
        if not allowed:
            self._audit.record(AuditEvent(
                action="retrieve", tenant_id=principal.tenant_id, user_id=principal.user_id,
                decision="deny", resource="knowledge", detail={"reason": "no_clearance"},
            ))
            return []  # no clearance -> nothing, without touching the store

        embedding = (await self._embedder.embed([query]))[0]
        results = await self._store.search(
            tenant_id=principal.tenant_id,
            query_embedding=embedding,
            allowed_classes=allowed,
            top_k=top_k,
        )

        # Defense in depth: never trust the store to have filtered correctly.
        for r in results:
            if r.chunk.tenant_id != principal.tenant_id:
                raise TenantIsolationError(
                    f"store returned tenant {r.chunk.tenant_id} for {principal.tenant_id}"
                )
            if r.chunk.data_class not in allowed:
                raise TenantIsolationError(
                    f"store returned forbidden class {r.chunk.data_class.value}"
                )
        self._audit.record(AuditEvent(
            action="retrieve", tenant_id=principal.tenant_id, user_id=principal.user_id,
            decision="allow", resource="knowledge",
            detail={"results": len(results), "allowed_classes": sorted(c.value for c in allowed)},
        ))
        return results
