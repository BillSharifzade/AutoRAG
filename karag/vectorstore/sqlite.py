"""Persistent vector store on SQLite — stdlib only, fully testable offline.

A production-capable middle ground between the in-memory store (tests) and
pgvector (large scale): durable to disk, zero external dependencies. Tenant and
data-class filtering happen in SQL (before scoring); cosine similarity is
computed in Python over the filtered slice. Suitable for small/medium tenants;
switch to pgvector when a tenant's corpus outgrows a brute-force scan.

The same security contract holds: an empty ``allowed_classes`` returns nothing,
and cross-tenant rows are excluded by the WHERE clause.
"""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3

from ..domain import Chunk, DataClass, DocumentSummary, RetrievedChunk, Vector

_SCHEMA = """
CREATE TABLE IF NOT EXISTS karag_chunks (
    id          TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    data_class  TEXT NOT NULL,
    ordinal     INTEGER NOT NULL,
    title       TEXT NOT NULL,
    source_uri  TEXT,
    text        TEXT NOT NULL,
    embedding   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS karag_chunks_tenant_class
    ON karag_chunks (tenant_id, data_class);
CREATE INDEX IF NOT EXISTS karag_chunks_document
    ON karag_chunks (tenant_id, document_id);
"""


def _cosine(a: Vector, b: Vector) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0.0 or nb == 0.0 else dot / (na * nb)


class SqliteVectorStore:
    def __init__(self, path: str = ":memory:") -> None:
        # check_same_thread=False so asyncio.to_thread workers can reuse it;
        # a lock serialises access.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._lock = asyncio.Lock()

    async def upsert(self, chunks: list[Chunk]) -> None:
        for c in chunks:
            if c.embedding is None:
                raise ValueError(f"chunk {c.id} has no embedding")
        rows = [
            (
                c.id, c.document_id, c.tenant_id, c.data_class.value, c.ordinal,
                c.title, c.source_uri, c.text, json.dumps(c.embedding),
            )
            for c in chunks
        ]

        def _write():
            self._conn.executemany(
                """
                INSERT INTO karag_chunks
                  (id, document_id, tenant_id, data_class, ordinal,
                   title, source_uri, text, embedding)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                  text=excluded.text, embedding=excluded.embedding
                """,
                rows,
            )
            self._conn.commit()

        async with self._lock:
            await asyncio.to_thread(_write)

    async def search(
        self,
        *,
        tenant_id: str,
        query_embedding: Vector,
        allowed_classes: frozenset[DataClass],
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        if not allowed_classes:
            return []
        allowed = [dc.value for dc in allowed_classes]
        placeholders = ",".join("?" for _ in allowed)

        def _read():
            cur = self._conn.execute(
                f"""
                SELECT id, document_id, tenant_id, data_class, ordinal,
                       title, source_uri, text, embedding
                FROM karag_chunks
                WHERE tenant_id = ? AND data_class IN ({placeholders})
                """,
                (tenant_id, *allowed),
            )
            return cur.fetchall()

        async with self._lock:
            rows = await asyncio.to_thread(_read)

        scored: list[RetrievedChunk] = []
        for r in rows:
            emb = json.loads(r[8])
            scored.append(
                RetrievedChunk(
                    chunk=Chunk(
                        id=r[0], document_id=r[1], tenant_id=r[2],
                        data_class=DataClass(r[3]), ordinal=r[4],
                        title=r[5], source_uri=r[6], text=r[7],
                    ),
                    score=_cosine(query_embedding, emb),
                )
            )
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]

    async def list_documents(
        self, *, tenant_id: str, allowed_classes: frozenset[DataClass]
    ) -> list[DocumentSummary]:
        if not allowed_classes:
            return []
        allowed = [dc.value for dc in allowed_classes]
        placeholders = ",".join("?" for _ in allowed)

        def _read():
            return self._conn.execute(
                f"""
                SELECT document_id, data_class, MIN(title) AS title,
                       MIN(source_uri) AS source_uri, COUNT(*) AS chunks
                FROM karag_chunks
                WHERE tenant_id = ? AND data_class IN ({placeholders})
                GROUP BY document_id, data_class
                ORDER BY title
                """,
                (tenant_id, *allowed),
            ).fetchall()

        async with self._lock:
            rows = await asyncio.to_thread(_read)
        return [
            DocumentSummary(
                document_id=r[0], data_class=DataClass(r[1]), title=r[2],
                source_uri=r[3], chunks=r[4],
            )
            for r in rows
        ]

    async def delete_document(self, *, tenant_id: str, document_id: str) -> int:
        def _del():
            cur = self._conn.execute(
                "DELETE FROM karag_chunks WHERE tenant_id=? AND document_id=?",
                (tenant_id, document_id),
            )
            self._conn.commit()
            return cur.rowcount

        async with self._lock:
            return await asyncio.to_thread(_del)

    async def count(self, *, tenant_id: str) -> int:
        def _count():
            cur = self._conn.execute(
                "SELECT count(*) FROM karag_chunks WHERE tenant_id=?", (tenant_id,)
            )
            return int(cur.fetchone()[0])

        async with self._lock:
            return await asyncio.to_thread(_count)
