"""Real pgvector integration test — same security contract as the other stores.

Runs only when ``KARAG_TEST_PG_DSN`` points at a Postgres with the ``vector``
extension available (skipped otherwise, so the default offline suite is
unaffected). Example:

    KARAG_TEST_PG_DSN="host=127.0.0.1 port=54329 dbname=karag user=karag" \
        .venv/bin/python -m pytest tests/integration/test_pgvector.py
"""

from __future__ import annotations

import os

import pytest

from karag.domain import Chunk, DataClass as DC

DSN = os.environ.get("KARAG_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="KARAG_TEST_PG_DSN not set")

DIM = 4


def _reset_schema() -> None:
    import psycopg

    with psycopg.connect(DSN) as conn:  # type: ignore[arg-type]
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("DROP TABLE IF EXISTS karag_chunks")
            cur.execute(
                f"""
                CREATE TABLE karag_chunks (
                    id text PRIMARY KEY,
                    document_id text NOT NULL,
                    tenant_id text NOT NULL,
                    data_class text NOT NULL,
                    ordinal integer NOT NULL,
                    title text NOT NULL,
                    source_uri text,
                    text text NOT NULL,
                    embedding vector({DIM}) NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX ON karag_chunks (tenant_id, data_class)"
            )
        conn.commit()


def _chunk(cid, tenant, klass, vec, doc="d"):
    return Chunk(
        id=cid, document_id=doc, tenant_id=tenant, data_class=klass,
        ordinal=0, text=cid, title="t", embedding=vec,
    )


@pytest.fixture
def store():
    _reset_schema()
    from karag.vectorstore.pgvector import PgVectorStore

    return PgVectorStore(DSN)


async def test_tenant_isolation_and_class_filter(store):
    await store.upsert([
        _chunk("fin", "koinoti", DC.FINANCIAL, [1, 0, 0, 0]),
        _chunk("pub", "koinoti", DC.PUBLIC, [0.9, 0.1, 0, 0]),
        _chunk("other", "evar", DC.PUBLIC, [1, 0, 0, 0]),
    ])
    res = await store.search(
        tenant_id="koinoti", query_embedding=[1, 0, 0, 0],
        allowed_classes=frozenset({DC.PUBLIC}), top_k=10,
    )
    assert {r.chunk.id for r in res} == {"pub"}  # no financial, no cross-tenant


async def test_empty_clearance_returns_nothing(store):
    await store.upsert([_chunk("a", "t", DC.PUBLIC, [1, 0, 0, 0])])
    res = await store.search(
        tenant_id="t", query_embedding=[1, 0, 0, 0],
        allowed_classes=frozenset(), top_k=10,
    )
    assert res == []


async def test_ordering_and_top_k(store):
    await store.upsert([
        _chunk("near", "t", DC.PUBLIC, [1, 0, 0, 0]),
        _chunk("mid", "t", DC.PUBLIC, [0.7, 0.7, 0, 0]),
        _chunk("far", "t", DC.PUBLIC, [0, 1, 0, 0]),
    ])
    res = await store.search(
        tenant_id="t", query_embedding=[1, 0, 0, 0],
        allowed_classes=frozenset({DC.PUBLIC}), top_k=2,
    )
    assert [r.chunk.id for r in res] == ["near", "mid"]
    assert res[0].score > res[1].score  # cosine score, higher is closer


async def test_upsert_delete_count(store):
    await store.upsert([
        _chunk("a", "t", DC.PUBLIC, [1, 0, 0, 0], doc="d1"),
        _chunk("b", "t", DC.PUBLIC, [0, 1, 0, 0], doc="d1"),
    ])
    assert await store.count(tenant_id="t") == 2
    await store.upsert([_chunk("a", "t", DC.PUBLIC, [0, 0, 1, 0], doc="d1")])  # update
    assert await store.count(tenant_id="t") == 2
    n = await store.delete_document(tenant_id="t", document_id="d1")
    assert n == 2
    assert await store.count(tenant_id="t") == 0


def _doc_chunk(cid, tenant, klass, text, vec, doc="d"):
    return Chunk(
        id=cid, document_id=doc, tenant_id=tenant, data_class=klass,
        ordinal=0, text=text, title="Справочник", embedding=vec,
    )


async def test_keyword_search_filters_and_finds_codes(store):
    """The table starts in the old schema (no terms column): the store adds
    it on first use, then keyword search keeps the same security contract."""
    from karag.knowledge.lexical import query_terms

    await store.upsert([
        _doc_chunk("code", "t", DC.OPERATIONAL, "АМК-875 Амоксиклав 875/125 мг №14", [1, 0, 0, 0]),
        _doc_chunk("near", "t", DC.OPERATIONAL, "АМК-500 Амоксиклав 500/125 мг №20", [1, 0, 0, 0]),
        _doc_chunk("secret", "t", DC.FINANCIAL, "АМК-875 закупочная цена 41,20", [1, 0, 0, 0]),
        _doc_chunk("other", "evar", DC.OPERATIONAL, "АМК-875 у другого арендатора", [1, 0, 0, 0]),
    ])
    hits = await store.keyword_search(
        tenant_id="t", terms=query_terms("Что за товар АМК-875?"),
        allowed_classes=frozenset({DC.OPERATIONAL}), top_k=5,
        query_embedding=[1, 0, 0, 0],
    )
    ids = [h.chunk.id for h in hits]
    assert ids[0] == "code"  # the exact code outranks its look-alike
    assert "secret" not in ids and "other" not in ids
    assert hits[0].lexical_score > 0 and hits[0].dense_score is not None
    assert await store.keyword_search(
        tenant_id="t", terms=["амк-875"], allowed_classes=frozenset(), top_k=5
    ) == []


async def test_existing_rows_get_terms_backfilled():
    """Rows written before the keyword index existed become searchable."""
    import psycopg

    from karag.knowledge.lexical import query_terms
    from karag.vectorstore.pgvector import PgVectorStore

    _reset_schema()
    with psycopg.connect(DSN) as conn:  # type: ignore[arg-type]
        conn.execute(
            "INSERT INTO karag_chunks (id, document_id, tenant_id, data_class, ordinal,"
            " title, text, embedding) VALUES ('old', 'd', 't', 'public', 0, 'Правила',"
            " 'Возврат денег на карту в течение 5 рабочих дней', '[1,0,0,0]')"
        )
        conn.commit()
    store = PgVectorStore(DSN)
    hits = await store.keyword_search(
        tenant_id="t", terms=query_terms("возврат денег"),
        allowed_classes=frozenset({DC.PUBLIC}), top_k=3,
    )
    assert [h.chunk.id for h in hits] == ["old"]
