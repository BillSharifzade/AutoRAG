"""Per-table access on databases the assistant queries freely.

A connection has one audience; a table inside it can be narrowed further (or
hidden). The skill is offered by the connection's audience, and every query is
checked against the tables it names before it runs.
"""

from __future__ import annotations

import sqlite3

import pytest

from karag.config import Settings
from karag.domain import DataClass, Principal
from karag.errors import AccessDenied, KaragError, ValidationError
from karag.factory import build_platform
from karag.integrations.dbsetup import check_query, filter_summary, sql_identifiers

ADMIN = Principal("koinoti", "adm", ("admin",))
CEO = Principal("koinoti", "ceo", ("ceo",))
FIN = Principal("koinoti", "fin", ("finance",))
HR = Principal("koinoti", "hr", ("hr",))


def _db(tmp_path) -> bytes:
    path = tmp_path / "shop.db"
    c = sqlite3.connect(path)
    c.execute("create table sales(store_id int, amount real)")
    c.execute("create table employees(full_name text, monthly_salary real)")
    c.execute("create table audit_log(note text)")
    c.executemany("insert into sales values (?, ?)", [(1, 100.0), (2, 50.0)])
    c.executemany("insert into employees values (?, ?)", [("Азиза", 6800.0)])
    c.execute("insert into audit_log values ('internal')")
    c.commit()
    c.close()
    return path.read_bytes()


@pytest.fixture
async def setup(tmp_path):
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory",
                                   self_knowledge=False, engineer_enabled=False))
    plat.databases._upload_dir = tmp_path / "uploads"
    result = await plat.databases.upload(
        ADMIN, name="Shop", filename="shop.db", data=_db(tmp_path),
        data_class=DataClass.FINANCIAL, free_query=True, knowledge=True, language="en",
    )
    cid = result["connector"]["id"]
    await plat.databases.set_options(
        ADMIN, cid, table_classes={"employees": "hr"}, hidden_tables=["audit_log"],
    )
    return plat, cid


def test_identifiers_ignore_literals_and_comments_and_see_quoted_names():
    sql = """select 'employees' as label, x."Employees".a -- employees
             from [sales] /* employees */ join `audit_log` on 1=1"""
    idents = sql_identifiers(sql)
    assert "employees" in idents  # the quoted "Employees" identifier
    assert idents.count("employees") == 1  # not the string or the comments
    assert "sales" in idents and "audit_log" in idents


def test_functions_that_run_sql_from_a_string_are_refused():
    with pytest.raises(AccessDenied, match="query_to_xml"):
        check_query("select query_to_xml('select * from emp' || 'loyees', true, false, '')", set())
    with pytest.raises(AccessDenied, match="dblink"):
        check_query("select * from dblink('dbname=x', 'select 1') as t(a int)", set())


def test_schema_listing_drops_the_tables_a_caller_cannot_use():
    summary = "sales(store_id INT) ~2 rows\nemployees(full_name TEXT) ~1 rows\naudit_log(note TEXT)"
    assert filter_summary(summary, {"employees", "audit_log"}) == "sales(store_id INT) ~2 rows"


async def test_finance_queries_sales_but_not_salaries(setup):
    plat, _ = setup
    ok = await plat.executor.execute(FIN, "query_shop", {"sql": "select sum(amount) as t from sales"})
    assert ok.data["rows"] == [{"t": 150.0}]
    with pytest.raises(KaragError, match="employees is not available"):
        await plat.executor.execute(FIN, "query_shop", {"sql": "select * from employees"})
    with pytest.raises(KaragError, match="not available"):
        await plat.executor.execute(FIN, "query_shop", {"sql": 'select * from "Employees"'})


async def test_ceo_reaches_narrowed_tables_but_nobody_reaches_hidden_ones(setup):
    plat, _ = setup
    res = await plat.executor.execute(CEO, "query_shop", {"sql": "select monthly_salary from employees"})
    assert res.data["rows"] == [{"monthly_salary": 6800.0}]
    with pytest.raises(KaragError, match="audit_log"):
        await plat.executor.execute(CEO, "query_shop", {"sql": "select * from audit_log"})


async def test_schema_is_fetched_on_demand_and_filtered_for_the_caller(setup):
    plat, _ = setup
    skill = plat.registry.get("koinoti", "query_shop")
    assert "WITHOUT `sql`" in skill.description and "employees" not in skill.description
    fin = await plat.executor.execute(FIN, "query_shop", {})
    assert "sales(" in fin.data["schema"] and "employees" not in fin.data["schema"]
    ceo = await plat.executor.execute(CEO, "query_shop", {})
    assert "employees(" in ceo.data["schema"] and "audit_log" not in ceo.data["schema"]


async def test_hr_alone_is_not_offered_a_financial_connection(setup):
    """Per-table audiences only narrow: the connection's audience still gates
    the skill, so HR (no financial clearance) does not see it at all."""
    plat, _ = setup
    assert plat.registry.resolve(HR, "query_shop") is None


async def test_description_document_leaves_narrowed_tables_out(setup):
    plat, _ = setup
    docs = await plat.store.list_documents(tenant_id="koinoti", allowed_classes=frozenset(DataClass))
    doc = next(d for d in docs if d.title == "Shop — database")
    text = " ".join(c.text for c in plat.store._chunks.values() if c.document_id == doc.document_id)
    assert "sales" in text and "employees" not in text and "audit_log" not in text
    assert "6800" not in text


async def test_narrowing_requires_clearance_and_a_known_audience(setup):
    plat, cid = setup
    author = Principal("koinoti", "author", ("skill_author",))
    with pytest.raises(AccessDenied):
        await plat.databases.set_options(author, cid, table_classes={"sales": "hr"})
    with pytest.raises(ValidationError):
        await plat.databases.set_options(ADMIN, cid, table_classes={"sales": "top-secret"})
