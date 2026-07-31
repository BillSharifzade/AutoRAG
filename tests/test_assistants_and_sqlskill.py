"""No-code assistants + real SQL-backed skills end-to-end."""

import os
import sqlite3
import tempfile

import pytest

from karag.connectors.sql import SqlConnector
from karag.config import Settings
from karag.domain import DataClass, Principal
from karag.factory import build_platform
from karag.skills.registry import SkillRegistry
from karag.skills.samples import sales_by_store_skill
from karag.skills.sql_skill import make_sql_skill


# ---------- SQL-backed skill with tenant row-scoping ----------
@pytest.fixture
def sales_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sales (tenant TEXT, store_id INT, amount INT)")
    conn.executemany("INSERT INTO sales VALUES (?,?,?)",
                     [("koinoti", 5, 18450), ("evar", 5, 9300)])
    conn.commit(); conn.close()
    yield path
    os.remove(path)


def _sql_platform(sales_db):
    connector = SqlConnector(sqlite_path=sales_db)
    skill = make_sql_skill(
        name="sales_sql",
        description="Total sales for a store.",
        sql="SELECT amount FROM sales WHERE tenant = :tenant_id AND store_id = :store_id",
        param_schema={
            "type": "object",
            "properties": {"store_id": {"type": "integer"}},
            "required": ["store_id"],
            "additionalProperties": False,
        },
        connector=connector,
        required_data_class=DataClass.FINANCIAL,
        required_roles=frozenset({"finance", "ceo"}),
        tenant_id="*",  # global skill, but rows scoped by injected tenant_id
    )
    reg = SkillRegistry(); reg.register(skill)
    return build_platform(Settings(generator="fake", embedder="fake", store="memory"), registry=reg)


async def test_sql_skill_returns_real_rows_scoped_to_tenant(sales_db):
    plat = _sql_platform(sales_db)
    koinoti_fin = Principal("koinoti", "f1", ("finance",))
    evar_fin = Principal("evar", "f2", ("finance",))

    a1 = await plat.orchestrator.ask(koinoti_fin, "sales store_id=5")
    assert "sales_sql" in a1.skills_used
    assert "18450" in a1.text  # koinoti's row
    assert "9300" not in a1.text

    a2 = await plat.orchestrator.ask(evar_fin, "sales store_id=5")
    assert "9300" in a2.text  # evar sees only its own row
    assert "18450" not in a2.text


# ---------- no-code assistants ----------
def _assistant_platform():
    reg = SkillRegistry(); reg.register(sales_by_store_skill(tenant_id="koinoti"))
    return build_platform(Settings(generator="fake", embedder="fake", store="memory"), registry=reg)


async def test_assistant_create_and_ask():
    plat = _assistant_platform()
    admin = Principal("koinoti", "admin", ("admin",))
    finance = Principal("koinoti", "fin", ("finance",))
    await plat.ingestion.ingest_document(
        admin, title="Policy", text="Return within 14 days.", data_class=DataClass.PUBLIC)

    asst = plat.assistants.create(finance, name="Helpdesk", instruction="Be concise.")
    ans = await plat.assistant_service.ask(finance, asst.id, "What is the policy?")
    assert ans.citations


async def test_assistant_skill_allowlist_narrows_not_widens():
    plat = _assistant_platform()
    finance = Principal("koinoti", "fin", ("finance",))
    # allowlist excludes the finance skill -> it cannot be used through this assistant
    asst = plat.assistants.create(
        finance, name="KnowledgeOnly", allowed_skill_names=frozenset()
    )
    ans = await plat.assistant_service.ask(finance, asst.id, "sales store_id=5 date=2026-07-20")
    assert ans.skills_used == []  # narrowed away


async def test_assistant_cross_tenant_hidden():
    plat = _assistant_platform()
    finance = Principal("koinoti", "fin", ("finance",))
    other = Principal("evar", "x", ("finance",))
    asst = plat.assistants.create(finance, name="A")
    from karag.assistants import AssistantNotFound
    with pytest.raises(AssistantNotFound):
        await plat.assistant_service.ask(other, asst.id, "hi")
