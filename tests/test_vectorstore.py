"""Vector store: tenant isolation, class filtering, fail-closed, CRUD."""

import pytest

from karag.domain import Chunk, DataClass as DC
from karag.vectorstore.memory import InMemoryVectorStore



def _chunk(cid, tenant, klass, vec):
    return Chunk(
        id=cid, document_id="d", tenant_id=tenant, data_class=klass,
        ordinal=0, text=cid, title="t", embedding=vec,
    )


async def test_tenant_isolation():
    store = InMemoryVectorStore()
    await store.upsert([
        _chunk("a", "koinoti", DC.PUBLIC, [1.0, 0.0]),
        _chunk("b", "evar", DC.PUBLIC, [1.0, 0.0]),  # identical vector, other tenant
    ])
    res = await store.search(
        tenant_id="koinoti", query_embedding=[1.0, 0.0],
        allowed_classes=frozenset({DC.PUBLIC}), top_k=10,
    )
    ids = {r.chunk.id for r in res}
    assert ids == {"a"}  # evar's identical chunk is invisible


async def test_class_filter_before_scoring():
    store = InMemoryVectorStore()
    # Financial chunk is the *best* match, but caller isn't cleared for it.
    await store.upsert([
        _chunk("fin", "koinoti", DC.FINANCIAL, [1.0, 0.0]),
        _chunk("pub", "koinoti", DC.PUBLIC, [0.9, 0.1]),
    ])
    res = await store.search(
        tenant_id="koinoti", query_embedding=[1.0, 0.0],
        allowed_classes=frozenset({DC.PUBLIC}), top_k=10,
    )
    ids = {r.chunk.id for r in res}
    assert ids == {"pub"}  # financial never appears despite higher similarity


async def test_empty_clearance_returns_nothing():
    store = InMemoryVectorStore()
    await store.upsert([_chunk("a", "koinoti", DC.PUBLIC, [1.0, 0.0])])
    res = await store.search(
        tenant_id="koinoti", query_embedding=[1.0, 0.0],
        allowed_classes=frozenset(), top_k=10,
    )
    assert res == []


async def test_top_k_and_ordering():
    store = InMemoryVectorStore()
    await store.upsert([
        _chunk("near", "t", DC.PUBLIC, [1.0, 0.0]),
        _chunk("mid", "t", DC.PUBLIC, [0.7, 0.7]),
        _chunk("far", "t", DC.PUBLIC, [0.0, 1.0]),
    ])
    res = await store.search(
        tenant_id="t", query_embedding=[1.0, 0.0],
        allowed_classes=frozenset({DC.PUBLIC}), top_k=2,
    )
    assert [r.chunk.id for r in res] == ["near", "mid"]


async def test_delete_and_count():
    store = InMemoryVectorStore()
    await store.upsert([
        _chunk("a", "t", DC.PUBLIC, [1.0, 0.0]),
        _chunk("b", "t", DC.PUBLIC, [1.0, 0.0]),
    ])
    for c in ("a", "b"):
        store._chunks[c].document_id = "doc1"
    assert await store.count(tenant_id="t") == 2
    n = await store.delete_document(tenant_id="t", document_id="doc1")
    assert n == 2
    assert await store.count(tenant_id="t") == 0
