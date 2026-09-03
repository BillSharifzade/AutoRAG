"""Guided integrations: API sources (probe → describe → save → sync) and
databases (login details / uploaded file / SQL dump → schema → query skill)."""

from __future__ import annotations

import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from karag.api.app import create_app
from karag.api.security import InMemoryResolver
from karag.config import Settings
from karag.connectors.registry import MYSQL, POSTGRES, build_dsn
from karag.connectors.sql import SqlConnector, parse_mysql_dsn, to_pyformat
from karag.domain import DataClass, Principal
from karag.factory import build_platform
from karag.integrations.analysis import analyze_payload, slug
from karag.integrations.dbsetup import import_sql_dump, schema_summary
from karag.integrations.payload import Payload, parse_payload, profile_payload, render_as_text
from karag.integrations.sources import DataSourceService, InMemoryDataSourceStore
from karag.web.guard import WebPolicy

ADMIN = Principal("koinoti", "admin1", ("admin",))
FIN = Principal("koinoti", "fin1", ("finance",))
EMP = Principal("koinoti", "emp1", ("employee",))
OTHER = Principal("evar", "ceo2", ("ceo",))


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ------------------------------------------------------------- payloads


def test_profile_finds_the_record_list_inside_an_envelope():
    body = {"status": "ok", "data": {"items": [{"sku": "A", "qty": 3}, {"sku": "B", "qty": None}]}}
    p = parse_payload("http://x/api", "application/json", json.dumps(body).encode())
    prof = profile_payload(p)
    assert prof.kind == "records" and prof.record_count == 2 and prof.records_path == "data.items"
    by_name = {f.name: f for f in prof.fields}
    assert by_name["sku"].types == ["string"] and by_name["qty"].filled == 1


def test_csv_and_text_payloads_are_recognised():
    csv = parse_payload("http://x/f", "text/plain", b"sku,qty\nA,1\nB,2\n")
    assert csv.kind == "csv" and profile_payload(csv).record_count == 2
    txt = parse_payload("http://x/f", "text/plain", b"hello there\nnothing tabular")
    assert txt.kind == "text" and profile_payload(txt).kind == "text"


def test_render_as_text_writes_one_record_per_line():
    p = parse_payload("http://x/api", "application/json",
                      json.dumps([{"store": 7, "sales": 9120}, {"store": 8, "sales": 15}]).encode())
    text = render_as_text(p, profile_payload(p), title="Sales feed", url="http://x/api")
    assert "store: 7; sales: 9120" in text and "Records: 2" in text


async def test_analysis_falls_back_to_a_heuristic_report():
    p = parse_payload("http://shop.example/api/v1/stock", "application/json",
                      json.dumps([{"sku": "A", "qty": 3}]).encode())
    report = await analyze_payload(None, profile_payload(p), url=p.url, language="en")
    assert report["source"] == "heuristic" and "sku" in report["summary"]
    assert report["suggested_name"]
    # and with the fake generator (no tool call) it still returns a usable report
    from karag.llm.fake import FakeGenerator

    report2 = await analyze_payload(FakeGenerator(), profile_payload(p), url=p.url, language="ru")
    assert report2["fields"][0]["name"] == "sku"


def test_slug_transliterates_cyrillic():
    assert slug("Продажи магазина") == "prodazhi_magazina"
    assert slug("Store Sales 2026!") == "store_sales_2026"


# ------------------------------------------------------------- sources


def _fake_fetcher(bodies: list[bytes]):
    calls = {"n": 0}

    async def fetch(url: str, policy: WebPolicy) -> Payload:
        body = bodies[min(calls["n"], len(bodies) - 1)]
        calls["n"] += 1
        return parse_payload(url, "application/json", body)

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def _sources(plat, bodies):
    return DataSourceService(
        InMemoryDataSourceStore(), plat.registry, plat.ingestion, plat.store,
        policy=WebPolicy(allow_private_addresses=True), fetch=_fake_fetcher(bodies), audit=plat.audit,
    )


@pytest.fixture
def plat():
    return build_platform(Settings(generator="fake", embedder="fake", store="memory"))


async def test_source_becomes_a_skill_and_a_synced_document(plat):
    svc = _sources(plat, [
        json.dumps([{"sku": "AMOX", "qty": 12}]).encode(),
        json.dumps([{"sku": "AMOX", "qty": 12}]).encode(),
        json.dumps([{"sku": "AMOX", "qty": 9}]).encode(),
    ])
    src = await svc.create(ADMIN, name="Stock levels", url="https://erp.example/stock",
                           description="current stock per sku", data_class=DataClass.OPERATIONAL,
                           sync_enabled=True)
    assert src.skill_name == "fetch_stock_levels"
    assert src.last_status == "ok" and src.last_records == 1 and src.document_id
    # the document is retrievable in the tenant
    docs = await plat.store.list_documents(tenant_id="koinoti", allowed_classes=frozenset(DataClass))
    assert [d.title for d in docs] == ["Stock levels"]
    # the skill is offered to the tenant's people and hidden from another tenant
    assert any(s.name == "fetch_stock_levels" for s in plat.registry.visible_for(EMP))
    assert not any(s.name == "fetch_stock_levels" for s in plat.registry.visible_for(OTHER))
    # a second sync with identical bytes touches nothing
    out = await svc.sync(src)
    assert out.status == "unchanged"
    # changed bytes replace the document (still one document)
    out = await svc.sync(src)
    assert out.status == "ok"
    docs = await plat.store.list_documents(tenant_id="koinoti", allowed_classes=frozenset(DataClass))
    assert len(docs) == 1 and docs[0].document_id == src.document_id


async def test_source_sync_is_only_due_after_its_interval(plat):
    svc = _sources(plat, [b"[{\"a\": 1}]"])
    src = await svc.create(ADMIN, name="Feed", url="https://erp.example/feed", sync_enabled=True,
                           sync_interval_s=3600)
    assert await svc.run_due() == []  # just synced
    src.last_checked_at = time.time() - 4000
    svc._store.update(src)
    assert [o.status for o in await svc.run_due()] == ["unchanged"]


async def test_source_errors_are_recorded_not_raised(plat):
    async def broken(url, policy):
        raise RuntimeError("connection refused")

    svc = DataSourceService(InMemoryDataSourceStore(), plat.registry, plat.ingestion, plat.store,
                            policy=WebPolicy(allow_private_addresses=True), fetch=broken)
    src = await svc.create(ADMIN, name="Flaky", url="https://erp.example/x", sync_enabled=True)
    assert src.last_status == "error" and "connection refused" in src.last_error


async def test_source_requires_an_author_and_class_clearance(plat):
    svc = _sources(plat, [b"[]"])
    from karag.errors import AccessDenied

    with pytest.raises(AccessDenied):
        await svc.create(EMP, name="x", url="https://erp.example/x")
    with pytest.raises(AccessDenied):
        await svc.create(Principal("koinoti", "sa", ("skill_author",)), name="x",
                         url="https://erp.example/x", data_class=DataClass.FINANCIAL)


async def test_the_fetch_skill_returns_records_with_provenance(plat):
    svc = _sources(plat, [json.dumps({"rows": [{"store": 7, "total": 9120}]}).encode()])
    await svc.create(ADMIN, name="Sales", url="https://erp.example/sales")
    result = await plat.executor.execute(FIN, "fetch_sales", {})
    assert result.data["records"] == [{"store": 7, "total": 9120}]
    assert result.query_shown == "GET https://erp.example/sales"


# --------------------------------------------------------------- sources over HTTP


@pytest.fixture
def client(plat, monkeypatch):
    # the probe and the skill fetch the same in-memory endpoint
    plat.sources._fetch = _fake_fetcher([json.dumps([{"sku": "A", "qty": 1}]).encode()])
    plat.sources._policy = WebPolicy(allow_private_addresses=True)
    resolver = InMemoryResolver({"t_admin": ADMIN, "t_emp": EMP})
    return TestClient(create_app(plat, resolver))


def test_probe_then_save_over_http(client):
    r = client.post("/v1/sources/probe", json={"url": "https://erp.example/stock", "language": "en"},
                    headers=_auth("t_admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile"]["record_count"] == 1 and body["analysis"]["fields"][0]["name"] == "sku"
    # a correction goes back in with the previous report
    r = client.post("/v1/sources/probe", json={
        "url": "https://erp.example/stock", "comment": "qty is units on hand", "previous": body["analysis"],
    }, headers=_auth("t_admin"))
    assert r.status_code == 200
    r = client.post("/v1/sources", json={
        "name": "Stock", "url": "https://erp.example/stock", "description": "stock per sku",
        "field_notes": {"qty": "units on hand"}, "sync_enabled": True, "sync_interval_s": 60,
    }, headers=_auth("t_admin"))
    assert r.status_code == 200, r.text
    src = r.json()
    assert src["last_status"] == "ok" and src["sync_interval_s"] == 300  # floor
    assert client.get("/v1/sources", headers=_auth("t_admin")).json()["sources"][0]["id"] == src["id"]
    assert client.post("/v1/sources/probe", json={"url": "https://x"}, headers=_auth("t_emp")).status_code == 403
    r = client.put(f"/v1/sources/{src['id']}", json={"sync_enabled": False}, headers=_auth("t_admin"))
    assert r.status_code == 200 and r.json()["document_id"] == ""
    assert client.delete(f"/v1/sources/{src['id']}", headers=_auth("t_admin")).status_code == 200
    assert client.get("/v1/sources", headers=_auth("t_admin")).json()["sources"] == []


def test_probe_refuses_private_addresses_by_policy(plat):
    plat.sources._policy = WebPolicy()
    resolver = InMemoryResolver({"t_admin": ADMIN})
    c = TestClient(create_app(plat, resolver))
    r = c.post("/v1/sources/probe", json={"url": "http://127.0.0.1:9/x"}, headers=_auth("t_admin"))
    assert r.status_code == 400


# ------------------------------------------------------------- databases


def test_dsn_builder_and_placeholder_conversion():
    dsn = build_dsn(MYSQL, host="db.local", port=None, database="shop", username="u", password="p@ss", ssl=True)
    assert dsn == "mysql://u:p%40ss@db.local:3306/shop?ssl=1"
    assert parse_mysql_dsn(dsn)["password"] == "p@ss"
    assert build_dsn(POSTGRES, host="pg", port=5433, database="erp", username="r", password="").startswith("postgresql://r@pg:5433/erp")
    assert to_pyformat("select * from t where a = :a and b::int = :b") == "select * from t where a = %(a)s and b::int = %(b)s"


def test_sql_dump_import_handles_mysql_and_postgres_syntax(tmp_path):
    mysql = """CREATE TABLE `sales` (
  `id` int(11) unsigned NOT NULL AUTO_INCREMENT,
  `store_id` int NOT NULL,
  `amount` decimal(10,2) NOT NULL DEFAULT '0.00' COMMENT 'money',
  PRIMARY KEY (`id`),
  KEY `idx_store` (`store_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
LOCK TABLES `sales` WRITE;
INSERT INTO `sales` VALUES (1,7,9120.00),(2,8,15.50);
UNLOCK TABLES;
"""
    rep = import_sql_dump(mysql, tmp_path / "m.db")
    assert rep.tables == ["sales"] and rep.rows == 2 and not rep.failed
    pg = """CREATE TABLE public.batches (sku character varying(20) NOT NULL, units integer);
COPY public.batches (sku, units) FROM stdin;
AMOX\t12
IBU\t\\N
\\.
"""
    rep = import_sql_dump(pg, tmp_path / "p.db")
    assert rep.tables == ["batches"] and rep.rows == 2
    rows = sqlite3.connect(tmp_path / "p.db").execute("select sku, units from batches order by sku").fetchall()
    assert rows == [("AMOX", 12), ("IBU", None)]


async def test_sqlite_introspection_reports_tables_columns_and_samples(tmp_path):
    db = tmp_path / "x.db"
    c = sqlite3.connect(db)
    c.execute("create table sales(store_id int, amount real)")
    c.execute("insert into sales values (7, 9120)")
    c.commit()
    schema = await SqlConnector(sqlite_path=str(db)).introspect()
    assert schema["backend"] == "sqlite" and schema["table_count"] == 1
    t = schema["tables"][0]
    assert t["name"] == "sales" and [col["name"] for col in t["columns"]] == ["store_id", "amount"]
    assert t["row_estimate"] == 1 and t["sample"] == [{"store_id": 7, "amount": 9120.0}]
    assert "sales(store_id int, amount real) ~1 rows" in schema_summary(schema)


@pytest.fixture
def db_client(plat, tmp_path):
    plat.databases._upload_dir = tmp_path / "uploads"
    resolver = InMemoryResolver({"t_admin": ADMIN, "t_fin": FIN, "t_emp": EMP})
    return TestClient(create_app(plat, resolver))


def _sqlite_bytes(tmp_path) -> bytes:
    db = tmp_path / "src.db"
    c = sqlite3.connect(db)
    c.execute("create table sales(store_id int, amount real)")
    c.executemany("insert into sales values (?, ?)", [(7, 9120), (8, 15)])
    c.commit()
    c.close()
    return db.read_bytes()


def test_upload_a_sqlite_file_and_query_it_through_the_assistant(db_client, plat, tmp_path):
    r = db_client.post(
        "/v1/databases/upload",
        files={"file": ("sales.sqlite", _sqlite_bytes(tmp_path), "application/octet-stream")},
        data={"name": "Sales db", "data_class": "financial", "free_query": "true", "language": "en"},
        headers=_auth("t_admin"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema"]["tables"][0]["name"] == "sales"
    assert body["connector"]["config"]["path"] == "••••••"  # never served back
    cid = body["connector"]["id"]
    # the knowledge document exists and is class-filtered like any other
    docs = db_client.get("/v1/documents", headers=_auth("t_fin")).json()["documents"]
    assert any(d["title"] == "Sales db — database" for d in docs)
    assert not any("Sales db" in d["title"] for d in db_client.get("/v1/documents", headers=_auth("t_emp")).json()["documents"])
    # the query skill is offered to finance, hidden from an employee, and read-only
    names = lambda tok: [s["name"] for s in db_client.get("/v1/skills", headers=_auth(tok)).json()["skills"]]  # noqa: E731
    assert "query_sales_db" in names("t_fin") and "query_sales_db" not in names("t_emp")
    import asyncio

    result = asyncio.run(plat.executor.execute(FIN, "query_sales_db", {"sql": "select sum(amount) as total from sales"}))
    assert result.data["rows"] == [{"total": 9135.0}] and result.query_shown.startswith("select")
    from karag.errors import KaragError

    with pytest.raises(KaragError):
        asyncio.run(plat.executor.execute(FIN, "query_sales_db", {"sql": "delete from sales"}))
    # switching free queries off removes the skill; the connection stays
    r = db_client.patch(f"/v1/databases/{cid}", json={"free_query": False}, headers=_auth("t_admin"))
    assert r.status_code == 200 and r.json()["metadata"]["free_query"] is False
    assert "query_sales_db" not in names("t_fin")
    # a correction re-describes and keeps working without a model
    r = db_client.post(f"/v1/databases/{cid}/describe", json={"comment": "amount is in somoni"}, headers=_auth("t_admin"))
    assert r.status_code == 200 and r.json()["connector"]["metadata"]["comment"] == "amount is in somoni"
    assert db_client.delete(f"/v1/databases/{cid}", headers=_auth("t_admin")).status_code == 200
    assert db_client.get("/v1/connectors", headers=_auth("t_admin")).json()["connectors"] == []


def test_upload_a_sql_dump(db_client):
    dump = b"CREATE TABLE t (a INT); INSERT INTO t VALUES (1), (2);"
    r = db_client.post(
        "/v1/databases/upload",
        files={"file": ("dump.sql", dump, "text/plain")},
        data={"name": "Dump", "language": "en"},
        headers=_auth("t_admin"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["connector"]["metadata"]["import"]["tables"] == ["t"]
    assert r.json()["schema"]["tables"][0]["row_estimate"] == 2


def test_uploads_are_validated(db_client):
    r = db_client.post("/v1/databases/upload", files={"file": ("x.db", b"not a database", "application/octet-stream")},
                       data={"name": "x"}, headers=_auth("t_admin"))
    assert r.status_code == 400
    r = db_client.post("/v1/databases/upload", files={"file": ("x.txt", b"hi", "text/plain")},
                       data={"name": "x"}, headers=_auth("t_admin"))
    assert r.status_code == 400
    r = db_client.post("/v1/databases/upload", files={"file": ("x.sql", b"nonsense;", "text/plain")},
                       data={"name": "x"}, headers=_auth("t_admin"))
    assert r.status_code == 400
    assert db_client.post("/v1/databases/test", json={"kind": "sql_postgres", "host": "h", "database": "d"},
                          headers=_auth("t_emp")).status_code == 403


def test_connecting_to_an_unreachable_server_is_a_502_with_the_reason(db_client):
    r = db_client.post("/v1/databases/test", json={
        "kind": "sql_postgres", "host": "127.0.0.1", "port": 1, "database": "d", "username": "u", "password": "p",
    }, headers=_auth("t_admin"))
    assert r.status_code == 502 and r.json()["detail"]


def test_secrets_are_sealed_when_a_key_is_configured(monkeypatch, tmp_path):
    from karag.connectors.registry import new_connector, resolve_secret

    monkeypatch.setenv("KARAG_SECRET_KEY", "test-key")
    spec = new_connector("koinoti", name="db", kind="sql_postgres", config={"dsn": "postgresql://u:p@h/d"})
    assert spec.config["dsn"].startswith("enc:") and "u:p" not in spec.config["dsn"]
    assert resolve_secret(spec.config["dsn"]) == "postgresql://u:p@h/d"
    assert spec.to_public_dict()["config"]["dsn"] == "••••••"


# ---------------------------------------------------- follow-ups from the live run


async def test_step_exhaustion_ends_with_an_answer_not_a_refusal(plat):
    """A model that keeps calling tools still gets asked for a final answer."""
    from karag.llm.base import LLMResponse, MsgRole, ToolCall
    from karag.llm.fake import FakeGenerator
    from karag.skills.base import Skill, SkillResult

    async def handler(principal, args):
        return SkillResult(data={"n": 1}, query_shown="select 1")

    plat.registry.register(Skill(
        name="peek", description="x", handler=handler,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        required_data_class=DataClass.PUBLIC, tenant_id="*",
    ))

    class Greedy(FakeGenerator):
        async def generate(self, *, system, messages, tools=None, **kw):
            if tools:  # keeps exploring as long as tools are offered
                return LLMResponse(tool_calls=[ToolCall("c", "peek", {})], stop_reason="tool_use")
            assert messages[-1].role == MsgRole.USER and "Do not call any tool" in messages[-1].content
            return LLMResponse(text="From what I gathered: n is 1.")

    plat.gateway.generator = Greedy()
    plat.orchestrator._max_iterations = 3
    ans = await plat.orchestrator.ask(EMP, "please peek at everything")
    assert ans.text == "From what I gathered: n is 1."
    assert ans.plane == "data" and ans.skills_used == ["peek"]
    assert ans.diagnostics["exhausted"] is True and ans.diagnostics["usage"]["calls"] == 4


async def test_fetch_skill_filters_and_limits_large_feeds(plat):
    rows = [{"country": "Tajikistan", "year": 2000, "value": 6.2}] + [
        {"country": f"Land {i}", "year": 2000, "value": i} for i in range(300)
    ]
    svc = _sources(plat, [json.dumps(rows).encode()])
    await svc.create(ADMIN, name="Population", url="https://data.example/pop")
    result = await plat.executor.execute(EMP, "fetch_population", {"filter": "tajik"})
    assert result.data["record_count"] == 301 and result.data["matched"] == 1
    assert result.data["records"][0]["country"] == "Tajikistan"
    assert "filter='tajik'" in result.query_shown
    capped = await plat.executor.execute(EMP, "fetch_population", {"limit": 5})
    assert capped.data["returned"] == 5 and len(capped.data["records"]) == 5


def test_an_endpoint_that_answers_404_is_a_502(plat):
    from karag.integrations.payload import EndpointError

    async def not_found(url, policy):
        raise EndpointError("the endpoint answered 404 Not Found")

    plat.sources._fetch = not_found
    plat.sources._policy = WebPolicy(allow_private_addresses=True)
    c = TestClient(create_app(plat, InMemoryResolver({"t_admin": ADMIN})))
    r = c.post("/v1/sources/probe", json={"url": "https://erp.example/x"}, headers=_auth("t_admin"))
    assert r.status_code == 502 and "404" in r.json()["detail"]


def test_pg_dump_17_meta_commands_and_alter_column_are_skipped(tmp_path):
    dump = """\\restrict abc123
CREATE TABLE public.t (id integer NOT NULL, name text);
ALTER TABLE ONLY public.t ALTER COLUMN id SET DEFAULT nextval('public.t_id_seq'::regclass);
COPY public.t (id, name) FROM stdin;
1\tАптека №1
\\.
\\unrestrict abc123
"""
    rep = import_sql_dump(dump, tmp_path / "d.db")
    assert rep.tables == ["t"] and rep.rows == 1 and rep.failed == []
    assert sqlite3.connect(tmp_path / "d.db").execute("select name from t").fetchone() == ("Аптека №1",)
