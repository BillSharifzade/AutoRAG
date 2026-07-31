"""Shared fixtures: principals, a wired offline platform, and seeded data."""

from __future__ import annotations

import pytest

from karag.config import Settings
from karag.domain import DataClass, Principal
from karag.factory import build_platform
from karag.skills.registry import SkillRegistry
from karag.skills.samples import expiring_batches_skill, sales_by_store_skill


# ---- principals ----------------------------------------------------------
@pytest.fixture
def ceo() -> Principal:
    return Principal(tenant_id="koinoti", user_id="ceo1", roles=("ceo",))


@pytest.fixture
def hr() -> Principal:
    return Principal(tenant_id="koinoti", user_id="hr1", roles=("hr",))


@pytest.fixture
def finance() -> Principal:
    return Principal(tenant_id="koinoti", user_id="fin1", roles=("finance",))


@pytest.fixture
def employee() -> Principal:
    return Principal(tenant_id="koinoti", user_id="emp1", roles=("employee",))


@pytest.fixture
def admin() -> Principal:
    return Principal(tenant_id="koinoti", user_id="adm1", roles=("admin",))


@pytest.fixture
def other_tenant_ceo() -> Principal:
    return Principal(tenant_id="evar", user_id="ceo2", roles=("ceo",))


@pytest.fixture
def nobody() -> Principal:
    return Principal(tenant_id="koinoti", user_id="ghost", roles=())


# ---- platform ------------------------------------------------------------
@pytest.fixture
def platform():
    settings = Settings(generator="fake", embedder="fake", store="memory", embed_dim=256)
    registry = SkillRegistry()
    # Finance skill for koinoti only; regulated skill for dusti only.
    registry.register(sales_by_store_skill(tenant_id="koinoti"))
    registry.register(expiring_batches_skill(tenant_id="dusti"))
    return build_platform(settings, registry=registry)


@pytest.fixture
async def seeded(platform, admin):
    """Ingest a small corpus spanning several data classes into koinoti."""
    ing = platform.ingestion
    await ing.ingest_document(
        admin,
        title="Returns Policy",
        text="Customers may return unopened goods within 14 days for a refund.",
        data_class=DataClass.PUBLIC,
        source_uri="policy/returns",
    )
    await ing.ingest_document(
        admin,
        title="Warehouse SOP",
        text="Operational procedure for stock transfers between warehouses and stores.",
        data_class=DataClass.OPERATIONAL,
        source_uri="sop/transfers",
    )
    await ing.ingest_document(
        admin,
        title="Q2 Financial Summary",
        text="Confidential financial results: revenue and net profit for the quarter.",
        data_class=DataClass.FINANCIAL,
        source_uri="fin/q2",
    )
    await ing.ingest_document(
        admin,
        title="Compensation Bands",
        text="Confidential HR salary bands and compensation ranges for staff.",
        data_class=DataClass.HR,
        source_uri="hr/comp",
    )
    return platform
