"""Production vector store on PostgreSQL + pgvector.

Written to the same contract as the in-memory store and with the same security
invariants baked into the SQL: every query is parameterized, scoped by
``tenant_id``, and filtered by ``data_class = ANY(:allowed)`` *inside* the
WHERE clause. An empty allowed set short-circuits to no rows (fail-closed)
before touching the DB.

* **Connections are pooled** (``psycopg_pool``, installed with the ``pgvector``
  extra) instead of opened per query — a TLS handshake per search was most of
  the latency. Without the pool package it falls back to one connection per
  call, as before.
* **Keyword search** runs on Postgres full-text search over the same stemmed
  terms the other stores index (``simple`` configuration: the stemming already
  happened in ``karag.knowledge.lexical``), behind a GIN index.
* **The schema upgrades itself** the first time the store is used: the
  ``heading`` and ``terms`` columns and the GIN index are added if missing and
  ``terms`` is backfilled, so an existing deployment needs no manual
  migration. ``sql/schema.sql`` creates the full schema, HNSW index included,
  for a new one.

Requires ``psycopg[binary]`` and the ``pgvector`` extension.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from ..domain import Chunk, DataClass, DocumentSummary, RetrievedChunk, Vector
from ..errors import ConfigError
from ..knowledge.lexical import terms as index_terms

log = logging.getLogger("karag.vectorstore.pgvector")

_COLS = "id, document_id, tenant_id, data_class, ordinal, title, source_uri, text, heading"


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


def _chunk_terms(title: str, heading: str, text: str) -> str:
    return " ".join(index_terms(f"{title}\n{heading}\n{text}"))


_UPGRADE = (
    "ALTER TABLE karag_chunks ADD COLUMN IF NOT EXISTS heading text NOT NULL DEFAULT ''",
    "ALTER TABLE karag_chunks ADD COLUMN IF NOT EXISTS terms text",
    "CREATE INDEX IF NOT EXISTS karag_chunks_terms_idx ON karag_chunks "
    "USING gin (to_tsvector('simple', coalesce(terms, '')))",
)


class PgVectorStore:
    def __init__(self, dsn: str, *, pool_max: int = 10) -> None:
        self.dsn = dsn
        self._pool_max = pool_max
        self._pools: dict[int, object] = {}
        self._schema_ready = False
        self._schema_lock: asyncio.Lock | None = None

    # ---------------------------------------------------------- connections

    @contextlib.asynccontextmanager
    async def _conn(self):
        psycopg, _ = _psycopg()
        pool = await self._pool()
        if pool is None:
            async with await psycopg.AsyncConnection.connect(self.dsn) as conn:
                yield conn
            return
        async with pool.connection() as conn:  # type: ignore[attr-defined]
            yield conn

    async def _pool(self):
        try:
            from psycopg_pool import AsyncConnectionPool  # noqa: PLC0415
        except ImportError:
            return None
        loop_id = id(asyncio.get_running_loop())
        pool = self._pools.get(loop_id)
        if pool is None:
            pool = AsyncConnectionPool(
                self.dsn, min_size=1, max_size=self._pool_max, open=False
            )
            await pool.open()
            self._pools = {loop_id: pool}
        return pool

    async def _ready(self) -> None:
        """Bring an existing table up to the current schema, once."""
        if self._schema_ready:
            return
        if self._schema_lock is None:
            self._schema_lock = asyncio.Lock()
        async with self._schema_lock:
            if self._schema_ready:
                return
            async with self._conn() as conn:
                async with conn.cursor() as cur:
                    for stmt in _UPGRADE:
                        await cur.execute(stmt)
                    await cur.execute(
                        "SELECT id, title, heading, text FROM karag_chunks WHERE terms IS NULL"
                    )
                    missing = await cur.fetchall()
                    if missing:
                        log.info("backfilling keyword terms for %d chunks", len(missing))
                        await cur.executemany(
                            "UPDATE karag_chunks SET terms = %s WHERE id = %s",
                            [(_chunk_terms(t, h or "", x), i) for i, t, h, x in missing],
                        )
                await conn.commit()
            self._schema_ready = True

    # ---------------------------------------------------------------- write

    async def upsert(self, chunks: list[Chunk]) -> None:
        await self._ready()
        rows = []
        for c in chunks:
            if c.embedding is None:
                raise ValueError(f"chunk {c.id} has no embedding")
            rows.append((
                c.id, c.document_id, c.tenant_id, c.data_class.value, c.ordinal,
                c.title, c.source_uri, c.text, _vec_literal(c.embedding), c.heading,
                _chunk_terms(c.title, c.heading, c.text),
            ))
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(
                    """
                    INSERT INTO karag_chunks
                      (id, document_id, tenant_id, data_class, ordinal,
                       title, source_uri, text, embedding, heading, terms)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET
                      text = EXCLUDED.text,
                      embedding = EXCLUDED.embedding,
                      heading = EXCLUDED.heading,
                      terms = EXCLUDED.terms,
                      title = EXCLUDED.title
                    """,
                    rows,
                )
            await conn.commit()

    # --------------------------------------------------------------- search

    @staticmethod
    def _chunk(r: dict) -> Chunk:
        return Chunk(
            id=r["id"], document_id=r["document_id"], tenant_id=r["tenant_id"],
            data_class=DataClass(r["data_class"]), ordinal=r["ordinal"],
            text=r["text"], title=r["title"], source_uri=r["source_uri"],
            heading=r.get("heading") or "",
        )

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
        await self._ready()
        _, dict_row = _psycopg()
        allowed = [dc.value for dc in allowed_classes]
        vec = _vec_literal(query_embedding)
        async with self._conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    f"""
                    SELECT {_COLS}, 1 - (embedding <=> %s::vector) AS score
                    FROM karag_chunks
                    WHERE tenant_id = %s
                      AND data_class = ANY(%s)
                    ORDER BY embedding <=> %s::vector ASC
                    LIMIT %s
                    """,
                    (vec, tenant_id, allowed, vec, top_k),
                )
                rows = await cur.fetchall()
        return [
            RetrievedChunk(
                chunk=self._chunk(r), score=float(r["score"]), dense_score=float(r["score"])
            )
            for r in rows
        ]

    async def keyword_search(
        self,
        *,
        tenant_id: str,
        terms: list[str],
        allowed_classes: frozenset[DataClass],
        top_k: int = 5,
        query_embedding: Vector | None = None,
    ) -> list[RetrievedChunk]:
        words = [t for t in terms if t and not t.startswith("-")]
        if not allowed_classes or not words:
            return []
        await self._ready()
        _, dict_row = _psycopg()
        allowed = [dc.value for dc in allowed_classes]
        sim_sql = "1 - (embedding <=> %s::vector)" if query_embedding else "NULL"
        params: list = []
        if query_embedding:
            params.append(_vec_literal(query_embedding))
        params += [" or ".join(words), tenant_id, allowed, top_k]
        async with self._conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    f"""
                    SELECT {_COLS},
                           ts_rank_cd(to_tsvector('simple', coalesce(terms, '')), q) AS rank,
                           {sim_sql} AS sim
                    FROM karag_chunks, websearch_to_tsquery('simple', %s) AS q
                    WHERE tenant_id = %s
                      AND data_class = ANY(%s)
                      AND to_tsvector('simple', coalesce(terms, '')) @@ q
                    ORDER BY rank DESC
                    LIMIT %s
                    """,
                    # the embedding parameter, when present, comes first
                    params,
                )
                rows = await cur.fetchall()
        return [
            RetrievedChunk(
                chunk=self._chunk(r),
                score=float(r["rank"]),
                lexical_score=float(r["rank"]),
                dense_score=None if r["sim"] is None else float(r["sim"]),
            )
            for r in rows
        ]

    # -------------------------------------------------------------- catalog

    async def list_documents(
        self, *, tenant_id: str, allowed_classes: frozenset[DataClass]
    ) -> list[DocumentSummary]:
        if not allowed_classes:
            return []
        _, dict_row = _psycopg()
        allowed = [dc.value for dc in allowed_classes]
        async with self._conn() as conn:
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
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM karag_chunks WHERE tenant_id=%s AND document_id=%s",
                    (tenant_id, document_id),
                )
                n = cur.rowcount
            await conn.commit()
        return n

    async def count(self, *, tenant_id: str) -> int:
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT count(*) FROM karag_chunks WHERE tenant_id=%s",
                    (tenant_id,),
                )
                row = await cur.fetchone()
        return int(row[0]) if row else 0
