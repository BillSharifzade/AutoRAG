"""RBAC-filtered retrieval — the knowledge-plane guard.

The principal's clearance is resolved to a set of data classes and passed *into*
the store's search, so filtering happens before scoring. A final defensive
assertion re-checks every returned chunk against the clearance and tenant, so a
buggy or malicious store implementation still cannot leak.

Retrieval is *hybrid* by default: a vector search (meaning) and a keyword
search (exact words, codes, names — see ``lexical``) run side by side and their
rankings are fused with reciprocal-rank fusion. RRF needs no score calibration
between the two very different scales, and a passage that both searches rank
highly rises to the top. Every passage keeps its cosine similarity
(``dense_score``) so the caller can still judge relevance on one scale.
"""

from __future__ import annotations

from ..audit import AuditEvent, AuditLog, NullAuditLog
from ..domain import Principal, RetrievedChunk
from ..errors import TenantIsolationError
from ..llm.base import Embedder
from ..rbac import visible_classes
from ..vectorstore.base import VectorStore
from .lexical import query_terms

# Reciprocal-rank-fusion constant: the usual 60 keeps a single list's top hit
# from dominating, so agreement between the two searches is what wins.
RRF_K = 60


class RetrievalService:
    def __init__(
        self,
        store: VectorStore,
        embedder: Embedder,
        audit: AuditLog | None = None,
        *,
        mode: str = "hybrid",
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._audit = audit or NullAuditLog()
        self.mode = mode

    async def has_documents(self, principal: Principal) -> bool:
        """Whether this caller could find anything at all — offering a search
        tool over an empty (or wholly forbidden) knowledge base wastes a turn."""
        if not visible_classes(principal):
            return False
        return await self._store.count(tenant_id=principal.tenant_id) > 0

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
        # Each search looks deeper than top_k so fusion has something to fuse.
        depth = max(top_k * 3, 20) if self.mode == "hybrid" else top_k
        dense = await self._store.search(
            tenant_id=principal.tenant_id,
            query_embedding=embedding,
            allowed_classes=allowed,
            top_k=depth,
        )
        lexical: list[RetrievedChunk] = []
        terms = query_terms(query) if self.mode == "hybrid" else []
        if terms:
            lexical = await self._store.keyword_search(
                tenant_id=principal.tenant_id,
                terms=terms,
                allowed_classes=allowed,
                top_k=depth,
                query_embedding=embedding,
            )

        # Defense in depth: never trust the store to have filtered correctly.
        for r in [*dense, *lexical]:
            if r.chunk.tenant_id != principal.tenant_id:
                raise TenantIsolationError(
                    f"store returned tenant {r.chunk.tenant_id} for {principal.tenant_id}"
                )
            if r.chunk.data_class not in allowed:
                raise TenantIsolationError(
                    f"store returned forbidden class {r.chunk.data_class.value}"
                )
        results = _fuse(dense, lexical)[:top_k] if lexical else dense[:top_k]
        self._audit.record(AuditEvent(
            action="retrieve", tenant_id=principal.tenant_id, user_id=principal.user_id,
            decision="allow", resource="knowledge",
            detail={"results": len(results), "allowed_classes": sorted(c.value for c in allowed)},
        ))
        return results


def _fuse(dense: list[RetrievedChunk], lexical: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Reciprocal-rank fusion of the vector and keyword rankings."""
    fused: dict[str, RetrievedChunk] = {}
    scores: dict[str, float] = {}
    for ranking in (dense, lexical):
        for rank, r in enumerate(ranking):
            cid = r.chunk.id
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
            prev = fused.get(cid)
            if prev is None:
                fused[cid] = RetrievedChunk(
                    chunk=r.chunk, score=0.0,
                    dense_score=r.dense_score, lexical_score=r.lexical_score,
                )
            else:
                if prev.dense_score is None:
                    prev.dense_score = r.dense_score
                if prev.lexical_score is None:
                    prev.lexical_score = r.lexical_score
    out = list(fused.values())
    for r in out:
        r.score = scores[r.chunk.id]
    out.sort(key=lambda r: r.score, reverse=True)
    return out
