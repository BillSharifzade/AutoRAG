"""Production vector store on PostgreSQL + pgvector.

Not exercised by the offline test suite (needs a live database), but written to
the same contract as the in-memory store and with the same security invariants
baked into the SQL: every query is parameterized, scoped by ``tenant_id``, and
filtered by ``data_class = ANY(:allowed)`` *inside* the WHERE clause. An empty
allowed set short-circuits to no rows (fail-closed) before touching the DB.

Requires ``psycopg[binary]`` and the ``pgvector`` extension. See
``sql/schema.sql`` for the table + index DDL.
"""

from __future__ import annotations

from ..domain import Chunk, DataClass, DocumentSummary, RetrievedChunk, Vector
from ..errors import ConfigError


def _psycopg():
    try:
        import psycopg  # noqa: PLC0415
        from psycopg.rows import dict_row  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise ConfigError(
            "pgvector store requires psycopg: pip install 'psycopg[binary]' pgvector"
        ) from exc
    return psycopg, dict_row


def _vec_literal(v: Vector) -> str:
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


class PgVectorStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    async def upsert(self, chunks: list[Chunk]) -> None:
        psycopg, _ = _psycopg()
        async with await psycopg.AsyncConnection.connect(self.dsn) as conn:
            async with conn.cursor() as cur:
                for c in chunks:
                    if c.embedding is None:
                        raise ValueError(f"chunk {c.id} has no embedding")
                    await cur.execute(
                        """
                        INSERT INTO karag_chunks
                          (id, document_id, tenant_id, data_class, ordinal,
                           title, source_uri, text, embedding)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (id) DO UPDATE SET
                          text = EXCLUDED.text,
                          embedding = EXCLUDED.embedding
                        """,
                        (
                            c.id,
                            c.document_id,
                            c.tenant_id,
                            c.data_class.value,
                            c.ordinal,
                            c.title,
                            c.source_uri,
                            c.text,
                            _vec_literal(c.embedding),
                        ),
                    )
            await conn.commit()

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
        psycopg, dict_row = _psycopg()
        allowed = [dc.value for dc in allowed_classes]
        async with await psycopg.AsyncConnection.connect(self.dsn) as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT id, document_id, tenant_id, data_class, ordinal,
                           title, source_uri, text,
                           1 - (embedding <=> %s::vector) AS score
                    FROM karag_chunks
                    WHERE tenant_id = %s
                      AND data_class = ANY(%s)
                    ORDER BY embedding <=> %s::vector ASC
                    LIMIT %s
                    """,
                    (
                        _vec_literal(query_embedding),
                        tenant_id,
                        allowed,
                        _vec_literal(query_embedding),
                        top_k,
                    ),
                )
                rows = await cur.fetchall()
        out: list[RetrievedChunk] = []
        for r in rows:
            out.append(
                RetrievedChunk(
                    chunk=Chunk(
                        id=r["id"],
                        document_id=r["document_id"],
                        tenant_id=r["tenant_id"],
                        data_class=DataClass(r["data_class"]),
                        ordinal=r["ordinal"],
                        text=r["text"],
                        title=r["title"],
                        source_uri=r["source_uri"],
                    ),
                    score=float(r["score"]),
                )
            )
        return out

    async def list_documents(
        self, *, tenant_id: str, allowed_classes: frozenset[DataClass]
    ) -> list[DocumentSummary]:
        if not allowed_classes:
            return []
        psycopg, dict_row = _psycopg()
        allowed = [dc.value for dc in allowed_classes]
        async with await psycopg.AsyncConnection.connect(self.dsn) as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT document_id, data_class, MIN(title) AS title,
                           MIN(source_uri) AS source_uri, COUNT(*) AS chunks
                    FROM karag_chunks
                    WHERE tenant_id = %s AND data_class = ANY(%s)
                    GROUP BY document_id, data_class
                    ORDER BY title
                    """,
                    (tenant_id, allowed),
                )
                rows = await cur.fetchall()
        return [
            DocumentSummary(
                document_id=r["document_id"],
                data_class=DataClass(r["data_class"]),
                title=r["title"],
                source_uri=r["source_uri"],
                chunks=int(r["chunks"]),
            )
            for r in rows
        ]

    async def delete_document(self, *, tenant_id: str, document_id: str) -> int:
        psycopg, _ = _psycopg()
        async with await psycopg.AsyncConnection.connect(self.dsn) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM karag_chunks WHERE tenant_id=%s AND document_id=%s",
                    (tenant_id, document_id),
                )
                n = cur.rowcount
            await conn.commit()
        return n

    async def count(self, *, tenant_id: str) -> int:
        psycopg, _ = _psycopg()
        async with await psycopg.AsyncConnection.connect(self.dsn) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT count(*) FROM karag_chunks WHERE tenant_id=%s",
                    (tenant_id,),
                )
                row = await cur.fetchone()
        return int(row[0]) if row else 0
