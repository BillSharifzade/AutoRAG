"""In-memory vector store — pure stdlib, used for tests and small demos.

Implements the same security-critical filtering as the production pgvector
store: tenant scoping and data-class filtering happen *before* similarity
scoring, and an empty ``allowed_classes`` set returns nothing (fail-closed).
"""

from __future__ import annotations

import asyncio
import math

from ..domain import Chunk, DataClass, DocumentSummary, RetrievedChunk, Vector


def cosine(a: Vector, b: Vector) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, chunks: list[Chunk]) -> None:
        async with self._lock:
            for c in chunks:
                if c.embedding is None:
                    raise ValueError(f"chunk {c.id} has no embedding")
                self._chunks[c.id] = c

    async def search(
        self,
        *,
        tenant_id: str,
        query_embedding: Vector,
        allowed_classes: frozenset[DataClass],
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        # Fail closed: no clearance -> no results, regardless of similarity.
        if not allowed_classes:
            return []
        scored: list[RetrievedChunk] = []
        for c in self._chunks.values():
            # Tenant isolation + RBAC filter applied BEFORE scoring.
            if c.tenant_id != tenant_id:
                continue
            if c.data_class not in allowed_classes:
                continue
            scored.append(RetrievedChunk(chunk=c, score=cosine(query_embedding, c.embedding)))
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    async def list_documents(
        self, *, tenant_id: str, allowed_classes: frozenset[DataClass]
    ) -> list[DocumentSummary]:
        if not allowed_classes:
            return []
        by_doc: dict[str, DocumentSummary] = {}
        for c in self._chunks.values():
            if c.tenant_id != tenant_id or c.data_class not in allowed_classes:
                continue
            existing = by_doc.get(c.document_id)
            if existing is None:
                by_doc[c.document_id] = DocumentSummary(
                    document_id=c.document_id, title=c.title,
                    data_class=c.data_class, source_uri=c.source_uri, chunks=1,
                )
            else:
                existing.chunks += 1
        return sorted(by_doc.values(), key=lambda d: d.title)

    async def delete_document(self, *, tenant_id: str, document_id: str) -> int:
        async with self._lock:
            to_del = [
                cid
                for cid, c in self._chunks.items()
                if c.tenant_id == tenant_id and c.document_id == document_id
            ]
            for cid in to_del:
                del self._chunks[cid]
            return len(to_del)

    async def count(self, *, tenant_id: str) -> int:
        return sum(1 for c in self._chunks.values() if c.tenant_id == tenant_id)
