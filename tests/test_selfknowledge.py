"""KARAG explaining and operating itself.

Two capabilities: reading its own source to answer implementation questions,
and taking real actions under the asking user's own permissions.
"""

import pytest
from fastapi.testclient import TestClient

from karag.api.app import create_app
from karag.api.security import InMemoryResolver
from karag.config import Settings
from karag.domain import Principal
from karag.errors import AccessDenied
from karag.factory import build_platform
from karag.selfknowledge import CodebaseIndex, PathNotAllowed, guides_for, system_context

CEO = Principal("koinoti", "ceo1", ("ceo",))
ADMIN = Principal("koinoti", "admin1", ("admin",))
EMPLOYEE = Principal("koinoti", "emp1", ("employee",))
ENGINEER = Principal("kit", "eng1", ("karag_engineer",))

REPO = "."


@pytest.fixture
def platform():
    return build_platform(Settings(generator="fake", embedder="fake", store="memory"))


@pytest.fixture
def index():
    return CodebaseIndex(REPO)


# ---------- the codebase window is guarded ----------


def test_reads_a_real_source_file(index):
    body = index.read("karag/rbac.py")
    assert "ROLE_DATA_CLASSES" in body


def test_line_numbers_are_available_for_citation(index):
    assert index.read_numbered("karag/rbac.py").lstrip().startswith("1\t")


def test_env_file_is_never_readable(index):
    with pytest.raises(PathNotAllowed):
        index.read(".env")


def test_databases_are_never_readable(index):
    with pytest.raises(PathNotAllowed):
        index.read("karag.db")


def test_path_traversal_is_refused(index):
    for attempt in ("../../etc/passwd", "/etc/passwd", "karag/../../etc/hosts"):
        with pytest.raises(PathNotAllowed):
            index.read(attempt)


def test_git_internals_are_not_listed(index):
    files = index.files()
    assert not any(f.startswith(".git/") for f in files)
    assert not any("node_modules" in f for f in files)
    assert not any(f.endswith(".db") for f in files)


def test_search_finds_a_known_symbol(index):
    hits = index.search("def visible_classes", subdir="karag")
    assert hits and hits[0].path == "karag/rbac.py"


def test_search_survives_a_malformed_regex(index):
    # A model may search for "def foo(" — an invalid pattern must not raise.
    assert isinstance(index.search("def foo("), list)


# ---------- the handbook ----------


def test_system_prompt_carries_the_handbook_and_the_role_guide(platform):
    ctx = system_context(CEO)
    assert "Knowledge plane" in ctx and "Data plane" in ctx
    assert "superuser of your own tenant" in ctx
    assert "ceo1" in ctx and "koinoti" in ctx


def test_each_role_gets_its_own_guide():
    assert "cannot" in dict(guides_for(EMPLOYEE))["employee"]
    assert "no business data" in dict(guides_for(Principal("kit", "o", ("platform_admin",))))[
        "platform_admin"
    ]


def test_engineer_guide_states_the_human_gate():
    guide = dict(guides_for(ENGINEER))["karag_engineer"]
    assert "Nothing goes live until a human applies it" in guide


def test_an_unknown_role_is_not_told_it_can_do_things():
    guides = guides_for(Principal("koinoti", "x", ("nonsense_role",)))
    assert [r for r, _ in guides] == ["employee"]


# ---------- introspection skills are available to everyone ----------


async def test_any_user_can_consult_the_platform_skills(platform):
    names = {s.name for s in platform.registry.visible_for(EMPLOYEE)}
    assert {"search_codebase", "read_source_file", "platform_handbook"} <= names


async def test_read_source_refusal_is_data_not_a_crash(platform):
    result = await platform.executor.execute(EMPLOYEE, "read_source_file", {"path": ".env"})
    assert "error" in result.data
    assert "not readable" in result.data["error"]


# ---------- operational skills run under the caller's own RBAC ----------


async def test_admin_can_create_accounts_in_bulk(platform):
    result = await platform.executor.execute(
        ADMIN, "create_accounts",
        {"count": 5, "roles": ["skill_author"], "user_id_prefix": "dev"},
    )
    created = result.data["created"]
    assert len(created) == 5
    assert created[0]["user_id"] == "dev001"
    assert all(c["token"].startswith("kg_") for c in created)


async def test_employee_cannot_create_accounts(platform):
    from karag.errors import SkillNotFound

    # Not merely refused — an employee is never even offered the tool.
    with pytest.raises(SkillNotFound):
        await platform.executor.execute(
            EMPLOYEE, "create_accounts", {"count": 1, "roles": ["employee"]}
        )


async def test_bulk_creation_is_capped(platform):
    from karag.errors import KaragError

    with pytest.raises(KaragError, match="between 1 and"):
        await platform.executor.execute(
            ADMIN, "create_accounts", {"count": 5000, "roles": ["employee"]}
        )


async def test_agent_cannot_grant_platform_roles(platform):
    with pytest.raises(AccessDenied):
        await platform.executor.execute(
            ADMIN, "create_accounts", {"count": 1, "roles": ["platform_admin"]}
        )


async def test_agent_cannot_grant_the_engineer_role(platform):
    """Otherwise "make me an engineer" would be a chat away from editing source."""
    with pytest.raises(AccessDenied):
        await platform.executor.execute(
            ADMIN, "create_accounts", {"count": 1, "roles": ["karag_engineer"]}
        )


async def test_destructive_action_needs_an_explicit_confirm(platform):
    await platform.executor.execute(
        ADMIN, "create_accounts", {"count": 1, "roles": ["employee"], "user_id_prefix": "victim"}
    )
    first = await platform.executor.execute(
        ADMIN, "deactivate_account", {"user_id": "victim"}
    )
    assert first.data["status"] == "confirmation_required"

    second = await platform.executor.execute(
        ADMIN, "deactivate_account", {"user_id": "victim", "confirm": True}
    )
    assert second.data["active"] is False


async def test_usage_stats_are_scoped_to_the_callers_tenant(platform):
    platform.usage.record(tenant_id="koinoti", user_id="u", usage={"input_tokens": 10,
                          "output_tokens": 5}, model="fake")
    platform.usage.record(tenant_id="evar", user_id="u", usage={"input_tokens": 999,
                          "output_tokens": 999}, model="fake")
    result = await platform.executor.execute(CEO, "usage_stats", {})
    assert result.data["total_tokens"] == 15


async def test_audit_summary_is_admin_only_and_undisclosed(platform):
    """Mirrors GET /v1/audit, which is admin-only. A non-admin isn't refused —
    the tool is never offered at all, so its existence isn't disclosed."""
    from karag.errors import SkillNotFound

    assert "audit_summary" not in {s.name for s in platform.registry.visible_for(CEO)}
    with pytest.raises(SkillNotFound):
        await platform.executor.execute(CEO, "audit_summary", {})

    result = await platform.executor.execute(ADMIN, "audit_summary", {"limit": 5})
    assert "events" in result.data


async def test_bulk_creation_is_audited(platform):
    await platform.executor.execute(
        ADMIN, "create_accounts", {"count": 3, "roles": ["employee"], "user_id_prefix": "z"}
    )
    actions = [e.action for e in platform.audit.for_tenant("koinoti")]
    assert "agent_create_accounts" in actions


# ---------- HTTP ----------


@pytest.fixture
def client():
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    resolver = InMemoryResolver({
        "t_admin": ADMIN, "t_emp": EMPLOYEE, "t_eng": ENGINEER, "t_ceo": CEO,
    })
    return TestClient(create_app(plat, resolver))


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_onboarding_endpoint_returns_a_role_guide(client):
    body = client.get("/v1/onboarding", headers=_auth("t_emp")).json()
    assert body["roles"] == ["employee"]
    assert body["guides"][0]["role"] == "employee"
    assert "tour" in body["prompt"].lower()


def test_me_reports_code_capability_only_for_engineers(client):
    assert client.get("/v1/me", headers=_auth("t_eng")).json()["can_edit_code"] is True
    assert client.get("/v1/me", headers=_auth("t_admin")).json()["can_edit_code"] is False
