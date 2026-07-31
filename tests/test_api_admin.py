"""HTTP layer for the admin surfaces: connectors, skill authoring, tenants, accounts."""

import os
import sqlite3
import tempfile

import pytest
from fastapi.testclient import TestClient

from karag.api.app import create_app
from karag.api.security import InMemoryResolver
from karag.config import Settings
from karag.domain import Principal
from karag.factory import build_platform

SCHEMA = {
    "type": "object",
    "properties": {"store_id": {"type": "integer"}},
    "required": ["store_id"],
    "additionalProperties": False,
}
SQL = "SELECT amount FROM sales WHERE tenant = :tenant_id AND store_id = :store_id"


@pytest.fixture
def sales_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sales (tenant TEXT, store_id INT, amount INT)")
    conn.executemany(
        "INSERT INTO sales VALUES (?,?,?)", [("koinoti", 5, 18450), ("evar", 5, 9300)]
    )
    conn.commit()
    conn.close()
    yield path
    os.remove(path)


@pytest.fixture
def client():
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    resolver = InMemoryResolver({
        "t_ops": Principal("kit", "ops", ("platform_admin",)),
        "t_admin": Principal("koinoti", "admin", ("admin",)),
        "t_dev": Principal("koinoti", "dev", ("skill_author",)),
        "t_fin": Principal("koinoti", "fin", ("finance",)),
        "t_emp": Principal("koinoti", "emp", ("employee",)),
        "t_evar": Principal("evar", "admin2", ("admin",)),
    })
    return TestClient(create_app(plat, resolver))


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _make_connector(client, sales_db, tok="t_admin"):
    r = client.post(
        "/v1/connectors",
        json={"name": "replica", "kind": "sql_sqlite", "config": {"path": sales_db}},
        headers=_auth(tok),
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _make_skill(client, conn_id, tok="t_admin", **over):
    body = {
        "name": "sales_live",
        "description": "Sales for a store from the replica.",
        "kind": "sql",
        "connector_id": conn_id,
        "param_schema": SCHEMA,
        "sql": SQL,
        "required_data_class": "financial",
        "required_roles": ["finance", "ceo"],
    }
    body.update(over)
    return client.post("/v1/skills/definitions", json=body, headers=_auth(tok))


# ---------- connectors ----------


def test_connector_response_never_leaks_the_dsn(client, sales_db):
    r = client.post(
        "/v1/connectors",
        json={"name": "replica", "kind": "sql_sqlite", "config": {"path": sales_db}},
        headers=_auth("t_admin"),
    )
    assert r.status_code == 200
    assert sales_db not in r.text
    assert r.json()["config"]["path"] == "••••••"


def test_employee_cannot_create_a_connector(client, sales_db):
    r = client.post(
        "/v1/connectors",
        json={"name": "x", "kind": "sql_sqlite", "config": {"path": sales_db}},
        headers=_auth("t_emp"),
    )
    assert r.status_code == 403


def test_connectors_are_not_listed_across_tenants(client, sales_db):
    _make_connector(client, sales_db, tok="t_admin")
    assert client.get("/v1/connectors", headers=_auth("t_evar")).json()["connectors"] == []


def test_bad_connector_kind_is_a_400(client):
    r = client.post(
        "/v1/connectors",
        json={"name": "x", "kind": "mongo", "config": {}},
        headers=_auth("t_admin"),
    )
    assert r.status_code == 400


# ---------- skill authoring ----------


def test_author_create_test_and_use_a_skill(client, sales_db):
    conn_id = _make_connector(client, sales_db)
    created = _make_skill(client, conn_id)
    assert created.status_code == 200, created.text
    skill_id = created.json()["id"]

    # the specialist tries it before anyone relies on it (§5)
    run = client.post(
        f"/v1/skills/definitions/{skill_id}/test",
        json={"arguments": {"store_id": 5}},
        headers=_auth("t_admin"),
    ).json()
    assert run["ok"] and run["row_count"] == 1
    assert "sales" in run["query_shown"]

    # and it is immediately live for a cleared user
    names = [
        s["name"] for s in client.get("/v1/skills", headers=_auth("t_fin")).json()["skills"]
    ]
    assert "sales_live" in names


def test_authored_skill_stays_invisible_to_uncleared_users(client, sales_db):
    conn_id = _make_connector(client, sales_db)
    _make_skill(client, conn_id)
    names = [
        s["name"] for s in client.get("/v1/skills", headers=_auth("t_emp")).json()["skills"]
    ]
    assert "sales_live" not in names


def test_write_sql_is_rejected_with_400(client, sales_db):
    conn_id = _make_connector(client, sales_db)
    r = _make_skill(client, conn_id, sql="DROP TABLE sales")
    assert r.status_code == 400
    assert "read-only" in r.json()["detail"]


def test_skill_author_cannot_expose_financial_data(client, sales_db):
    """skill_author is cleared for operational only — financial is refused."""
    conn_id = _make_connector(client, sales_db, tok="t_admin")
    r = _make_skill(client, conn_id, tok="t_dev")
    assert r.status_code == 403


def test_skill_author_can_publish_an_operational_skill(client, sales_db):
    conn_id = _make_connector(client, sales_db, tok="t_admin")
    r = _make_skill(
        client, conn_id, tok="t_dev",
        required_data_class="operational", required_roles=[],
    )
    assert r.status_code == 200, r.text


def test_definitions_are_not_readable_across_tenants(client, sales_db):
    conn_id = _make_connector(client, sales_db)
    skill_id = _make_skill(client, conn_id).json()["id"]
    r = client.get(f"/v1/skills/definitions/{skill_id}", headers=_auth("t_evar"))
    assert r.status_code == 404


def test_delete_removes_the_live_tool(client, sales_db):
    conn_id = _make_connector(client, sales_db)
    skill_id = _make_skill(client, conn_id).json()["id"]
    assert client.delete(
        f"/v1/skills/definitions/{skill_id}", headers=_auth("t_admin")
    ).status_code == 200
    names = [
        s["name"] for s in client.get("/v1/skills", headers=_auth("t_fin")).json()["skills"]
    ]
    assert "sales_live" not in names


def test_library_import_binds_the_importers_own_connector(client, sales_db):
    conn_id = _make_connector(client, sales_db, tok="t_admin")
    source_id = _make_skill(client, conn_id, shared=True).json()["id"]

    evar_conn = _make_connector(client, sales_db, tok="t_evar")
    library = client.get("/v1/skills/library", headers=_auth("t_evar")).json()["skills"]
    assert [d["id"] for d in library] == [source_id]

    r = client.post(
        f"/v1/skills/library/{source_id}/import",
        json={"connector_id": evar_conn},
        headers=_auth("t_evar"),
    )
    assert r.status_code == 200
    assert r.json()["tenant_id"] == "evar"
    assert r.json()["connector_id"] == evar_conn


# ---------- tenants + accounts ----------


def test_operator_onboards_a_tenant_and_admin_issues_a_token(client):
    r = client.post(
        "/v1/tenants", json={"id": "dusti", "name": "Dusti Pharma"}, headers=_auth("t_ops")
    )
    assert r.status_code == 200

    created = client.post(
        "/v1/accounts",
        json={"user_id": "qa1", "roles": ["qa"], "display_name": "QA lead"},
        headers=_auth("t_admin"),
    )
    assert created.status_code == 200
    token = created.json()["token"]
    assert token.startswith("kg_")
    # the token is never echoed by a later read
    listing = client.get("/v1/accounts", headers=_auth("t_admin")).text
    assert token not in listing


def test_tenant_admin_cannot_create_a_tenant(client):
    r = client.post(
        "/v1/tenants", json={"id": "rogue", "name": "Rogue"}, headers=_auth("t_admin")
    )
    assert r.status_code == 403


def test_tenant_admin_cannot_mint_a_platform_admin(client):
    r = client.post(
        "/v1/accounts",
        json={"user_id": "escalate", "roles": ["platform_admin"]},
        headers=_auth("t_admin"),
    )
    assert r.status_code == 403


def test_accounts_are_scoped_to_the_callers_tenant(client):
    client.post(
        "/v1/accounts", json={"user_id": "qa1", "roles": ["qa"]}, headers=_auth("t_admin")
    )
    assert client.get("/v1/accounts", headers=_auth("t_evar")).json()["accounts"] == []


def test_rotate_issues_a_different_token(client):
    first = client.post(
        "/v1/accounts", json={"user_id": "qa1", "roles": ["qa"]}, headers=_auth("t_admin")
    ).json()["token"]
    second = client.post("/v1/accounts/qa1/rotate", headers=_auth("t_admin")).json()["token"]
    assert first != second


def test_issued_token_actually_authenticates(sales_db):
    """End-to-end: onboard through HTTP, then use the minted token to ask."""
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    from karag.tenants import ChainResolver, DirectoryResolver

    env = InMemoryResolver({"t_admin": Principal("koinoti", "admin", ("admin",))})
    resolver = ChainResolver(env, DirectoryResolver(plat.directory))
    client = TestClient(create_app(plat, resolver))

    token = client.post(
        "/v1/accounts",
        json={"user_id": "ceo1", "roles": ["ceo"]},
        headers=_auth("t_admin"),
    ).json()["token"]

    r = client.post("/v1/ask", json={"query": "hello"}, headers=_auth(token))
    assert r.status_code == 200
