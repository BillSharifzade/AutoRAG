"""Which SQLite files a tenant's connection may open.

Found by testing the deployed server: a tenant admin could register a
"SQLite connection" pointing at the platform's own app database and read every
tenant's accounts, chats and audit trail through a skill. These tests use the
real policy (the conftest fixture only widens it for other test modules).
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from karag.config import Settings
from karag.connectors.registry import ConnectorSpec, SqlitePolicy, build_connector
from karag.domain import Principal
from karag.errors import AccessDenied
from karag.factory import build_platform

ADMIN = Principal("koinoti", "adm", ("admin",))


def _db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.execute("create table t(x int)")
    c.commit()
    c.close()
    return path


@pytest.fixture
def layout(tmp_path):
    uploads = tmp_path / "uploads"
    app_db = _db(tmp_path / "karag_app.db")
    own = _db(uploads / "koinoti" / "sales.db")
    other = _db(uploads / "evar" / "secret.db")
    stray = _db(tmp_path / "elsewhere" / "x.db")
    policy = SqlitePolicy(upload_dir=str(uploads), deny_files=(str(app_db),))
    return policy, app_db, own, other, stray


def test_a_tenant_opens_only_its_own_uploads(layout):
    policy, app_db, own, other, stray = layout
    assert policy.check("koinoti", str(own)) == own.resolve()
    for path in (other, stray, app_db):
        with pytest.raises(AccessDenied):
            policy.check("koinoti", str(path))
    with pytest.raises(AccessDenied):
        policy.check("koinoti", ":memory:")


def test_the_platforms_own_files_stay_denied_even_in_a_cleared_directory(layout, tmp_path):
    policy, app_db, *_ = layout
    wide = SqlitePolicy(upload_dir=policy.upload_dir, extra_dirs=(str(tmp_path),),
                        deny_files=policy.deny_files)
    with pytest.raises(AccessDenied, match="belongs to the platform"):
        wide.check("koinoti", str(app_db))


def test_a_symlink_or_dotdot_cannot_escape(layout, tmp_path):
    policy, app_db, own, *_ = layout
    link = own.parent / "innocent.db"
    os.symlink(app_db, link)
    with pytest.raises(AccessDenied):
        policy.check("koinoti", str(link))
    with pytest.raises(AccessDenied):
        policy.check("koinoti", str(own.parent / ".." / ".." / "karag_app.db"))


def test_env_indirection_is_checked_after_resolution(layout, monkeypatch):
    policy, app_db, *_ = layout
    monkeypatch.setenv("QA_POINTS_AT_APP_DB", str(app_db))
    spec = ConnectorSpec(id="c", tenant_id="koinoti", name="x", kind="sql_sqlite",
                         config={"path": "env:QA_POINTS_AT_APP_DB"})
    with pytest.raises(AccessDenied):
        build_connector(spec, policy)


def test_the_platform_refuses_to_store_such_a_connection(tmp_path):
    settings = Settings(generator="fake", embedder="fake", store="memory",
                        upload_dir=str(tmp_path / "uploads"),
                        app_db_path=str(tmp_path / "karag_app.db"))
    from karag.factory import build_sqlite_policy as real  # noqa: F401 (patched in conftest)

    plat = build_platform(settings)
    plat.catalog.sqlite_policy = SqlitePolicy(
        upload_dir=settings.upload_dir, deny_files=(settings.app_db_path,)
    )
    _db(tmp_path / "karag_app.db")
    with pytest.raises(AccessDenied):
        plat.catalog.create_connector(ADMIN, name="app", kind="sql_sqlite",
                                      config={"path": str(tmp_path / "karag_app.db")})
    events = [e for e in plat.audit.for_tenant("koinoti") if e.action == "connector_create"]
    assert events and events[-1].decision == "deny"
    # an upload of the tenant's own still works
    own = _db(tmp_path / "uploads" / "koinoti" / "ok.db")
    spec = plat.catalog.create_connector(ADMIN, name="ok", kind="sql_sqlite", config={"path": str(own)})
    assert spec.kind == "sql_sqlite"


def test_default_policy_denies_every_platform_database():
    from karag.factory import build_sqlite_policy

    s = Settings(app_db_path="/data/a.db", chat_db_path="/data/c.db",
                 usage_db_path="/data/u.db", sqlite_path="/data/k.db", upload_dir="/data/uploads")
    # the conftest fixture wraps the function; the deny list is untouched by it
    policy = build_sqlite_policy(s)
    assert set(policy.deny_files) >= {"/data/a.db", "/data/c.db", "/data/u.db", "/data/k.db"}
    assert policy.upload_dir == "/data/uploads"
