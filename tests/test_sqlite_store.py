"""SQLite vector store: same security contract as memory + persistence."""

import os
import tempfile

import pytest

from karag.domain import Chunk, DataClass as DC
from karag.vectorstore.sqlite import SqliteVectorStore


def _chunk(cid, tenant, klass, vec, doc="d"):
    return Chunk(
        id=cid, document_id=doc, tenant_id=tenant, data_class=klass,
        ordinal=0, text=cid, title="t", embedding=vec,
    )


async def test_tenant_isolation_and_class_filter():
    store = SqliteVectorStore(":memory:")
    await store.upsert([
        _chunk("fin", "koinoti", DC.FINANCIAL, [1.0, 0.0]),
        _chunk("pub", "koinoti", DC.PUBLIC, [0.9, 0.1]),
        _chunk("other", "evar", DC.PUBLIC, [1.0, 0.0]),
    ])
    res = await store.search(
        tenant_id="koinoti", query_embedding=[1.0, 0.0],
        allowed_classes=frozenset({DC.PUBLIC}), top_k=10,
    )
    assert {r.chunk.id for r in res} == {"pub"}  # no financial, no cross-tenant


async def test_empty_clearance_returns_nothing():
    store = SqliteVectorStore(":memory:")
    await store.upsert([_chunk("a", "t", DC.PUBLIC, [1.0, 0.0])])
    res = await store.search(
        tenant_id="t", query_embedding=[1.0, 0.0],
        allowed_classes=frozenset(), top_k=10,
    )
    assert res == []


async def test_persistence_across_instances():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        s1 = SqliteVectorStore(path)
        await s1.upsert([_chunk("a", "t", DC.PUBLIC, [1.0, 0.0], doc="doc1")])
        assert await s1.count(tenant_id="t") == 1

        # A fresh instance on the same file sees the data.
        s2 = SqliteVectorStore(path)
        assert await s2.count(tenant_id="t") == 1
        n = await s2.delete_document(tenant_id="t", document_id="doc1")
        assert n == 1
        assert await s2.count(tenant_id="t") == 0
    finally:
        os.remove(path)


async def test_upsert_updates_existing():
    store = SqliteVectorStore(":memory:")
    await store.upsert([_chunk("a", "t", DC.PUBLIC, [1.0, 0.0])])
    await store.upsert([_chunk("a", "t", DC.PUBLIC, [0.0, 1.0])])  # same id
    assert await store.count(tenant_id="t") == 1
