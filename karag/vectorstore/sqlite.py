"""Persistent vector store on SQLite — stdlib only, fully testable offline.

A production-capable middle ground between the in-memory store (tests) and
pgvector (large scale): durable to disk, zero external dependencies.

* **Security first.** Tenant and data-class filtering happen before scoring,
  exactly as in the other stores: an empty ``allowed_classes`` returns
  nothing, and another tenant's rows are never candidates.
* **Vector search** scores a per-tenant matrix of embeddings held in memory
  and rebuilt only after that tenant's documents change. Scoring runs in a
  worker thread, so a large tenant never stalls other users' requests, and
  uses numpy when it is installed (pure Python otherwise). Embeddings are
  stored as float32 blobs — a quarter of the JSON size and no parsing; rows
  written as JSON by earlier versions are converted on start-up.
* **Keyword search** is SQLite's own FTS5 full-text index over stemmed terms
  (see ``karag.knowledge.lexical``), ranked by BM25. It is backfilled on
  start-up for databases written before it existed.

Switch to pgvector when a tenant's corpus reaches the hundreds of thousands of
passages; until then this is fast enough and needs no server.
"""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3
from array import array

from ..domain import Chunk, DataClass, DocumentSummary, RetrievedChunk, Vector
from ..knowledge.lexical import terms as index_terms

try:  # optional fast path
    import numpy as _np  # type: ignore
except ImportError:  # pragma: no cover - env-dependent
    _np = None

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

# Our terms are already lower-cased and stemmed; keep - / . inside a token so
# a code like "амк-875" stays one term.
_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS karag_chunks_fts USING fts5(
    terms, chunk_id UNINDEXED,
    tokenize = "unicode61 remove_diacritics 0 tokenchars '-/.'"
);
"""

_COLS = "id, document_id, tenant_id, data_class, ordinal, title, source_uri, text, heading"


def _pack(vec: Vector) -> bytes:
    return array("f", vec).tobytes()


def _unpack(raw) -> list[float]:
    if isinstance(raw, (bytes, bytearray, memoryview)):
        a = array("f")
        a.frombytes(bytes(raw))
        return a.tolist()
    return json.loads(raw)


def _cosine(a: Vector, b: Vector) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0.0 or nb == 0.0 else dot / (na * nb)


def _fts_query(terms: list[str]) -> str:
    quoted = ['"' + t.replace('"', '""') + '"' for t in terms if t]
    return " OR ".join(quoted)


def _chunk_terms(title: str, heading: str, text: str) -> str:
    return " ".join(index_terms(f"{title}\n{heading}\n{text}"))


class _TenantMatrix:
    """One tenant's embeddings, ready to score."""

    def __init__(self, ids: list[str], classes: list[str], vectors: list[list[float]]):
        self.ids = ids
        self.classes = classes
        if _np is not None and vectors:
            m = _np.asarray(vectors, dtype=_np.float32)
            norms = _np.linalg.norm(m, axis=1)
            norms[norms == 0] = 1.0
            self.matrix = m / norms[:, None]
            self.vectors = None
        else:
            self.matrix = None
            self.vectors = vectors

    def scores(self, query: Vector, allowed: set[str]) -> list[tuple[float, int]]:
        keep = [i for i, c in enumerate(self.classes) if c in allowed]
        if not keep:
            return []
        if self.matrix is not None:
            q = _np.asarray(query, dtype=_np.float32)
            n = float(_np.linalg.norm(q)) or 1.0
            sims = self.matrix[keep] @ (q / n)
            return [(float(s), i) for s, i in zip(sims.tolist(), keep)]
        return [(_cosine(query, self.vectors[i]), i) for i in keep]


class SqliteVectorStore:
    def __init__(self, path: str = ":memory:") -> None:
        # check_same_thread=False so asyncio.to_thread workers can reuse it;
        # a lock serialises access.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()
        self._lock = asyncio.Lock()
        self._matrices: dict[str, _TenantMatrix] = {}
        # Bumped by SQLite when *another* connection commits (the scheduler
        # process syncing a source, a second API worker); our own writes clear
        # the cache directly.
        self._data_version = self._version()

    def _version(self) -> int:
        return int(self._conn.execute("PRAGMA data_version").fetchone()[0])

    # ----------------------------------------------------------- migrations

    def _migrate(self) -> None:
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(karag_chunks)")}
        if "heading" not in cols:
            self._conn.execute(
                "ALTER TABLE karag_chunks ADD COLUMN heading TEXT NOT NULL DEFAULT ''"
            )
        # JSON-encoded embeddings from earlier versions -> float32 blobs.
        rows = self._conn.execute(
            "SELECT id, embedding FROM karag_chunks WHERE typeof(embedding) = 'text'"
        ).fetchall()
        for cid, raw in rows:
            self._conn.execute(
                "UPDATE karag_chunks SET embedding = ? WHERE id = ?",
                (_pack(json.loads(raw)), cid),
            )
        # The keyword index, backfilled when it is missing or out of step.
        self._conn.executescript(_FTS)
        indexed = self._conn.execute("SELECT count(*) FROM karag_chunks_fts").fetchone()[0]
        total = self._conn.execute("SELECT count(*) FROM karag_chunks").fetchone()[0]
        if indexed != total:
            self._conn.execute("DELETE FROM karag_chunks_fts")
            for cid, title, heading, text in self._conn.execute(
                "SELECT id, title, heading, text FROM karag_chunks"
            ).fetchall():
                self._conn.execute(
                    "INSERT INTO karag_chunks_fts (terms, chunk_id) VALUES (?, ?)",
                    (_chunk_terms(title, heading, text), cid),
                )

    # ---------------------------------------------------------------- write

    async def upsert(self, chunks: list[Chunk]) -> None:
        for c in chunks:
            if c.embedding is None:
                raise ValueError(f"chunk {c.id} has no embedding")
        rows = [
            (
                c.id, c.document_id, c.tenant_id, c.data_class.value, c.ordinal,
                c.title, c.source_uri, c.text, _pack(c.embedding), c.heading,
            )
            for c in chunks
        ]
        fts = [(_chunk_terms(c.title, c.heading, c.text), c.id) for c in chunks]

        def _write():
            self._conn.executemany(
                """
                INSERT INTO karag_chunks
                  (id, document_id, tenant_id, data_class, ordinal,
                   title, source_uri, text, embedding, heading)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                  text=excluded.text, embedding=excluded.embedding,
                  heading=excluded.heading, title=excluded.title
                """,
                rows,
            )
            self._conn.executemany(
                "DELETE FROM karag_chunks_fts WHERE chunk_id = ?", [(cid,) for _, cid in fts]
            )
            self._conn.executemany(
                "INSERT INTO karag_chunks_fts (terms, chunk_id) VALUES (?, ?)", fts
            )
            self._conn.commit()

        async with self._lock:
            await asyncio.to_thread(_write)
            for tenant in {c.tenant_id for c in chunks}:
                self._matrices.pop(tenant, None)

    # --------------------------------------------------------------- search

    async def _matrix(self, tenant_id: str) -> _TenantMatrix:
        version = await asyncio.to_thread(self._version)
        if version != self._data_version:
            self._matrices.clear()
            self._data_version = version
        m = self._matrices.get(tenant_id)
        if m is not None:
            return m

        def _load():
            rows = self._conn.execute(
                "SELECT id, data_class, embedding FROM karag_chunks WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchall()
            return _TenantMatrix(
                [r[0] for r in rows], [r[1] for r in rows], [_unpack(r[2]) for r in rows]
            )

        m = await asyncio.to_thread(_load)
        self._matrices[tenant_id] = m
        return m

    def _rows_by_id(self, ids: list[str]) -> dict[str, tuple]:
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT {_COLS} FROM karag_chunks WHERE id IN ({marks})", ids
        ).fetchall()
        return {r[0]: r for r in rows}

    @staticmethod
    def _chunk(r: tuple) -> Chunk:
        return Chunk(
            id=r[0], document_id=r[1], tenant_id=r[2], data_class=DataClass(r[3]),
            ordinal=r[4], title=r[5], source_uri=r[6], text=r[7], heading=r[8] or "",
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
        allowed = {dc.value for dc in allowed_classes}
        async with self._lock:
            matrix = await self._matrix(tenant_id)
            scored = await asyncio.to_thread(matrix.scores, query_embedding, allowed)
            scored.sort(reverse=True)
            top = scored[:top_k]
            ids = [matrix.ids[i] for _, i in top]
            rows = await asyncio.to_thread(self._rows_by_id, ids)
        out = []
        for sim, i in top:
            r = rows.get(matrix.ids[i])
            # A row deleted between loading and reading simply drops out; the
            # filter is re-applied on the row itself, not on the cache.
            if r is None or r[2] != tenant_id or r[3] not in allowed:
                continue
            out.append(RetrievedChunk(chunk=self._chunk(r), score=sim, dense_score=sim))
        return out

    async def keyword_search(
        self,
        *,
        tenant_id: str,
        terms: list[str],
        allowed_classes: frozenset[DataClass],
        top_k: int = 5,
        query_embedding: Vector | None = None,
    ) -> list[RetrievedChunk]:
        query = _fts_query(terms)
        if not allowed_classes or not query:
            return []
        allowed = [dc.value for dc in allowed_classes]
        marks = ",".join("?" for _ in allowed)

        def _read():
            return self._conn.execute(
                f"""
                SELECT c.id, c.document_id, c.tenant_id, c.data_class, c.ordinal,
                       c.title, c.source_uri, c.text, c.heading, c.embedding,
                       bm25(karag_chunks_fts) AS rank
                FROM karag_chunks_fts
                JOIN karag_chunks c ON c.id = karag_chunks_fts.chunk_id
                WHERE karag_chunks_fts MATCH ?
                  AND c.tenant_id = ? AND c.data_class IN ({marks})
                ORDER BY rank
                LIMIT ?
                """,
                (query, tenant_id, *allowed, top_k),
            ).fetchall()

        async with self._lock:
            try:
                rows = await asyncio.to_thread(_read)
            except sqlite3.OperationalError:
                return []  # a term FTS5 cannot parse is not worth failing a turn
        out = []
        for r in rows:
            sim = _cosine(query_embedding, _unpack(r[9])) if query_embedding else None
            lex = -float(r[10])  # FTS5 bm25: lower is better
            out.append(RetrievedChunk(
                chunk=self._chunk(r[:9]), score=lex, lexical_score=lex, dense_score=sim,
            ))
        return out

    # -------------------------------------------------------------- catalog

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
            ids = [r[0] for r in self._conn.execute(
                "SELECT id FROM karag_chunks WHERE tenant_id=? AND document_id=?",
                (tenant_id, document_id),
            )]
            self._conn.executemany(
                "DELETE FROM karag_chunks_fts WHERE chunk_id = ?", [(i,) for i in ids]
            )
            cur = self._conn.execute(
                "DELETE FROM karag_chunks WHERE tenant_id=? AND document_id=?",
                (tenant_id, document_id),
            )
            self._conn.commit()
            return cur.rowcount

        async with self._lock:
            n = await asyncio.to_thread(_del)
            self._matrices.pop(tenant_id, None)
            return n

    async def count(self, *, tenant_id: str) -> int:
        def _count():
            cur = self._conn.execute(
                "SELECT count(*) FROM karag_chunks WHERE tenant_id=?", (tenant_id,)
            )
            return int(cur.fetchone()[0])

        async with self._lock:
            return await asyncio.to_thread(_count)
