"""Retrieval RBAC filtering + ingestion access control."""

import pytest

from karag.domain import DataClass as DC
from karag.errors import AccessDenied



async def test_hr_cannot_retrieve_financial(seeded, hr):
    res = await seeded.retrieval.retrieve(hr, "financial revenue profit results", top_k=10)
    classes = {r.chunk.data_class for r in res}
    assert DC.FINANCIAL not in classes
    assert all(c in {DC.PUBLIC, DC.OPERATIONAL, DC.HR} for c in classes)


async def test_finance_cannot_retrieve_hr(seeded, finance):
    res = await seeded.retrieval.retrieve(finance, "salary compensation bands staff", top_k=10)
    assert DC.HR not in {r.chunk.data_class for r in res}


async def test_ceo_can_retrieve_financial(seeded, ceo):
    res = await seeded.retrieval.retrieve(ceo, "financial revenue profit results", top_k=10)
    assert DC.FINANCIAL in {r.chunk.data_class for r in res}


async def test_no_clearance_retrieves_nothing(seeded, nobody):
    res = await seeded.retrieval.retrieve(nobody, "anything", top_k=10)
    assert res == []


async def test_cross_tenant_retrieval_empty(seeded, other_tenant_ceo):
    # A CEO of a *different* tenant sees none of koinoti's documents.
    res = await seeded.retrieval.retrieve(other_tenant_ceo, "returns policy refund", top_k=10)
    assert res == []


async def test_employee_cannot_ingest(platform, employee):
    with pytest.raises(AccessDenied):
        await platform.ingestion.ingest_document(
            employee, title="x", text="y", data_class=DC.PUBLIC
        )


async def test_admin_ingest_creates_chunks(platform, admin):
    doc = await platform.ingestion.ingest_document(
        admin, title="Doc", text="Sentence one. Sentence two. Sentence three.",
        data_class=DC.OPERATIONAL,
    )
    assert doc.tenant_id == "koinoti"
    assert await platform.store.count(tenant_id="koinoti") >= 1


async def test_missing_class_defaults_to_most_restrictive(platform, admin):
    doc = await platform.ingestion.ingest_document(admin, title="D", text="hello world")
    assert doc.data_class == DC.REGULATED  # fail-closed
