"""Runtime skill authoring: connectors, definitions, testing, library reuse.

Covers the concept doc's §5 promise — a technical specialist builds and tests a
skill once, without editing Python — and the guardrails that keep that from
becoming a privilege-escalation path.
"""

import os
import sqlite3
import tempfile

import pytest

from karag.config import Settings
from karag.connectors.registry import (
    ConnectorNotFound,
    build_connector,
    new_connector,
    resolve_secret,
)
from karag.domain import DataClass, Principal
from karag.errors import AccessDenied, ValidationError
from karag.factory import build_platform
from karag.skills.definitions import (
    SkillDefinitionNotFound,
    sql_bindings,
    validate_param_schema,
)

CEO = Principal("koinoti", "ceo1", ("ceo",))
AUTHOR = Principal("koinoti", "dev1", ("skill_author",))
FINANCE = Principal("koinoti", "fin1", ("finance",))
HR = Principal("koinoti", "hr1", ("hr",))
EMPLOYEE = Principal("koinoti", "emp1", ("employee",))
OTHER_TENANT = Principal("evar", "dev2", ("admin",))

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
        "INSERT INTO sales VALUES (?,?,?)",
        [("koinoti", 5, 18450), ("evar", 5, 9300)],
    )
    conn.commit()
    conn.close()
    yield path
    os.remove(path)


@pytest.fixture
def platform():
    return build_platform(Settings(generator="fake", embedder="fake", store="memory"))


def _connector(platform, sales_db, principal=CEO):
    return platform.catalog.create_connector(
        principal, name="sales replica", kind="sql_sqlite", config={"path": sales_db}
    )


def _skill(platform, conn_id, principal=CEO, **kw):
    params = dict(
        name="sales_by_store_live",
        description="Total sales for a store, from the read replica.",
        kind="sql",
        connector_id=conn_id,
        param_schema=SCHEMA,
        sql=SQL,
        required_data_class=DataClass.FINANCIAL,
        required_roles=("finance", "ceo"),
    )
    params.update(kw)
    return platform.catalog.create_skill(principal, **params)


# ---------- authoring end-to-end ----------


async def test_authored_skill_becomes_a_live_tool(platform, sales_db):
    """A skill created through the catalogue is immediately callable by the model."""
    conn = _connector(platform, sales_db)
    _skill(platform, conn.id)

    answer = await platform.orchestrator.ask(FINANCE, "sales store_id=5")
    assert "sales_by_store_live" in answer.skills_used
    assert "18450" in answer.text
    assert answer.queries_shown  # provenance is shown, per §5


async def test_test_run_shows_query_and_rows_before_publishing(platform, sales_db):
    conn = _connector(platform, sales_db)
    defn = _skill(platform, conn.id)

    run = await platform.catalog.test_skill(CEO, defn.id, {"store_id": 5})
    assert run.ok
    assert run.row_count == 1
    assert "sales" in run.query_shown
    assert run.data["rows"][0]["amount"] == 18450


async def test_test_run_reports_bad_arguments_instead_of_raising(platform, sales_db):
    conn = _connector(platform, sales_db)
    defn = _skill(platform, conn.id)
    run = await platform.catalog.test_skill(CEO, defn.id, {"store_id": "five"})
    assert not run.ok
    assert "store_id" in run.error


async def test_skill_rows_are_scoped_to_the_callers_tenant(platform, sales_db):
    """:tenant_id is bound by the platform, so evar can never see koinoti's row."""
    conn = _connector(platform, sales_db)
    defn = _skill(platform, conn.id)
    run = await platform.catalog.test_skill(CEO, defn.id, {"store_id": 5})
    assert all(r["amount"] != 9300 for r in run.data["rows"])


def test_update_renames_the_live_tool(platform, sales_db):
    conn = _connector(platform, sales_db)
    defn = _skill(platform, conn.id)
    platform.catalog.update_skill(CEO, defn.id, name="sales_v2")

    names = {s.name for s in platform.registry.visible_for(CEO)}
    assert "sales_v2" in names
    assert "sales_by_store_live" not in names  # stale tool name is dropped


def test_delete_removes_it_from_the_catalogue(platform, sales_db):
    conn = _connector(platform, sales_db)
    defn = _skill(platform, conn.id)
    assert platform.catalog.delete_skill(CEO, defn.id)
    assert not [s for s in platform.registry.visible_for(CEO) if s.name == defn.name]


# ---------- authorisation ----------


def test_non_author_cannot_create_a_skill(platform, sales_db):
    conn = _connector(platform, sales_db)
    with pytest.raises(AccessDenied):
        _skill(platform, conn.id, principal=EMPLOYEE)


def test_author_cannot_expose_a_class_they_may_not_read(platform, sales_db):
    """The §7 trap one level up: HR must not be able to mint a financial skill."""
    conn = _connector(platform, sales_db, principal=CEO)
    with pytest.raises(AccessDenied):
        platform.catalog.create_skill(
            HR,
            name="payroll_totals",
            description="Financial totals.",
            kind="sql",
            connector_id=conn.id,
            param_schema=SCHEMA,
            sql=SQL,
            required_data_class=DataClass.FINANCIAL,
        )


def test_skill_cannot_bind_another_tenants_connector(platform, sales_db):
    conn = _connector(platform, sales_db, principal=CEO)  # koinoti's connector
    with pytest.raises(ConnectorNotFound):
        platform.catalog.create_skill(
            OTHER_TENANT,
            name="borrowed",
            description="Someone else's data source.",
            kind="sql",
            connector_id=conn.id,
            param_schema=SCHEMA,
            sql=SQL,
            required_data_class=DataClass.OPERATIONAL,
        )


def test_other_tenant_cannot_read_or_delete_a_definition(platform, sales_db):
    conn = _connector(platform, sales_db)
    defn = _skill(platform, conn.id)
    with pytest.raises(SkillDefinitionNotFound):
        platform.catalog.get_skill(OTHER_TENANT, defn.id)
    assert platform.catalog.delete_skill(OTHER_TENANT, defn.id) is False


def test_uncleared_user_never_sees_the_skill(platform, sales_db):
    conn = _connector(platform, sales_db)
    _skill(platform, conn.id)
    # HR still sees the public platform skills (handbook, source lookup) — what
    # they must never see is the financial one they hold no clearance for.
    assert "sales_by_store_live" not in {
        s.name for s in platform.registry.visible_for(HR)
    }


# ---------- definition validation ----------


def test_write_statements_are_rejected_at_authoring_time(platform, sales_db):
    conn = _connector(platform, sales_db)
    with pytest.raises(ValidationError, match="read-only"):
        _skill(platform, conn.id, sql="DELETE FROM sales WHERE store_id = :store_id")


def test_stacked_statements_are_rejected(platform, sales_db):
    conn = _connector(platform, sales_db)
    with pytest.raises(ValidationError):
        _skill(
            platform,
            conn.id,
            sql="SELECT amount FROM sales WHERE store_id = :store_id; DROP TABLE sales",
        )


def test_undeclared_binding_is_rejected(platform, sales_db):
    conn = _connector(platform, sales_db)
    with pytest.raises(ValidationError, match="undeclared"):
        _skill(platform, conn.id, sql="SELECT amount FROM sales WHERE day = :day")


def test_unused_declared_parameter_is_rejected(platform, sales_db):
    conn = _connector(platform, sales_db)
    with pytest.raises(ValidationError, match="never used"):
        _skill(platform, conn.id, sql="SELECT amount FROM sales")


def test_open_param_schema_is_rejected():
    with pytest.raises(ValidationError, match="additionalProperties"):
        validate_param_schema({"type": "object", "properties": {}, "additionalProperties": True})


def test_tenant_id_cannot_be_declared_as_a_model_parameter():
    with pytest.raises(ValidationError, match="bound by the platform"):
        validate_param_schema({
            "type": "object",
            "properties": {"tenant_id": {"type": "string"}},
            "additionalProperties": False,
        })


def test_bad_skill_names_are_rejected(platform, sales_db):
    conn = _connector(platform, sales_db)
    with pytest.raises(ValidationError):
        _skill(platform, conn.id, name="Sales By Store")


def test_sql_bindings_reads_both_placeholder_styles():
    assert sql_bindings("SELECT 1 WHERE a = :a AND b = %(b)s") == {"a", "b"}


# ---------- connectors ----------


def test_connector_secrets_are_redacted_on_read(platform, sales_db):
    conn = _connector(platform, sales_db)
    public = conn.to_public_dict()
    assert public["config"]["path"] == "••••••"
    assert sales_db not in str(public)


def test_env_indirection_keeps_secrets_out_of_the_database(monkeypatch):
    monkeypatch.setenv("MY_DSN", "postgresql://real/dsn")
    spec = new_connector("koinoti", name="pg", kind="sql_postgres", config={"dsn": "env:MY_DSN"})
    # the pointer is stored and shown; the value only resolves at connect time
    assert spec.to_public_dict()["config"]["dsn"] == "env:MY_DSN"
    assert resolve_secret(spec.config["dsn"]) == "postgresql://real/dsn"
    assert build_connector(spec).pg_dsn == "postgresql://real/dsn"


def test_rest_connector_requires_an_http_url():
    with pytest.raises(ValidationError, match="http"):
        new_connector("koinoti", name="api", kind="rest", config={"base_url": "ftp://x"})


def test_connector_in_use_cannot_be_deleted(platform, sales_db):
    conn = _connector(platform, sales_db)
    _skill(platform, conn.id)
    with pytest.raises(ValidationError, match="used by"):
        platform.catalog.delete_connector(CEO, conn.id)


# ---------- the skill library (§15) ----------


def test_shared_definition_is_importable_against_the_importers_own_connector(sales_db):
    platform = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    conn = _connector(platform, sales_db)
    source = _skill(platform, conn.id, shared=True)

    # Evar sees the template but not koinoti's connector...
    evar_ceo = Principal("evar", "ceo2", ("ceo",))
    library = platform.catalog.list_library(evar_ceo)
    assert [d.id for d in library] == [source.id]

    # ...so it must bind its own before the skill exists for it.
    evar_conn = platform.catalog.create_connector(
        evar_ceo, name="evar replica", kind="sql_sqlite", config={"path": sales_db}
    )
    copy = platform.catalog.import_from_library(
        evar_ceo, source.id, connector_id=evar_conn.id
    )
    assert copy.tenant_id == "evar"
    assert copy.connector_id == evar_conn.id
    assert copy.id != source.id


def test_library_excludes_your_own_and_unshared_definitions(platform, sales_db):
    conn = _connector(platform, sales_db)
    _skill(platform, conn.id, shared=True)  # own tenant's — not "library" for us
    assert platform.catalog.list_library(CEO) == []


# ---------- durability ----------


def test_definitions_survive_a_restart(sales_db):
    fd, app_db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        settings = Settings(
            generator="fake", embedder="fake", store="memory",
            app_store="sqlite", app_db_path=app_db,
        )
        first = build_platform(settings)
        conn = _connector(first, sales_db)
        _skill(first, conn.id)

        # a fresh process reading the same app database
        second = build_platform(settings)
        assert not second.skill_load_errors
        assert "sales_by_store_live" in {
            s.name for s in second.registry.visible_for(FINANCE)
        }
    finally:
        for suffix in ("", "-wal", "-shm"):
            path = app_db + suffix
            if os.path.exists(path):
                os.remove(path)


def test_a_broken_definition_does_not_stop_startup(sales_db, monkeypatch):
    fd, app_db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        settings = Settings(
            generator="fake", embedder="fake", store="memory",
            app_store="sqlite", app_db_path=app_db,
        )
        first = build_platform(settings)
        monkeypatch.setenv("SALES_DSN", "postgresql://x/y")
        conn = first.catalog.create_connector(
            CEO, name="pg", kind="sql_postgres", config={"dsn": "env:SALES_DSN"}
        )
        _skill(first, conn.id)

        monkeypatch.delenv("SALES_DSN")  # the env var goes missing
        second = build_platform(settings)
        assert second.skill_load_errors  # reported, not raised
        assert "SALES_DSN" in second.skill_load_errors[0]
    finally:
        for suffix in ("", "-wal", "-shm"):
            path = app_db + suffix
            if os.path.exists(path):
                os.remove(path)
