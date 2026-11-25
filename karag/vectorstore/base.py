"""Vector store contract.

The signature is the security contract: ``search`` *requires* both a
``tenant_id`` and the set of ``allowed_classes``. There is no way to query
across tenants and no way to retrieve a class the caller wasn't cleared for —
the filter is applied inside the store, before scoring, so forbidden content
never enters a result set (and therefore never reaches the model's context).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain import Chunk, DataClass, DocumentSummary, RetrievedChunk, Vector


@runtime_checkable
class VectorStore(Protocol):
    async def upsert(self, chunks: list[Chunk]) -> None: ...

    async def search(
        self,
        *,
        tenant_id: str,
        query_embedding: Vector,
        allowed_classes: frozenset[DataClass],
        top_k: int = 5,
    ) -> list[RetrievedChunk]: ...

    async def keyword_search(
        self,
        *,
        tenant_id: str,
        terms: list[str],
        allowed_classes: frozenset[DataClass],
        top_k: int = 5,
        query_embedding: Vector | None = None,
    ) -> list[RetrievedChunk]:
        """Passages matching the question's words (BM25-style ranking).

        The same contract as ``search``: tenant-scoped and class-filtered
        inside the store. ``terms`` come from ``karag.knowledge.lexical`` so
        the store and the indexer agree on what a word is. When
        ``query_embedding`` is given, each hit also carries its cosine
        similarity (``dense_score``) so the caller can judge relevance on one
        scale whichever search found it.
        """
        ...

    async def list_documents(
        self, *, tenant_id: str, allowed_classes: frozenset[DataClass]
    ) -> list[DocumentSummary]:
        """The catalogue of documents this caller may see.

        Carries the same contract as ``search``: tenant-scoped, class-filtered
        inside the store. Listing a title is itself a disclosure — "Q3 layoffs
        plan" leaks even without the body — so the filter is not optional.
        """
        ...

    async def delete_document(self, *, tenant_id: str, document_id: str) -> int: ...

    async def count(self, *, tenant_id: str) -> int: ...
