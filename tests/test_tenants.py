"""Tenants, accounts and token-based identity — §12's "accounts, tenants".

Also covers §14's rollout mechanics: onboarding Koinoti → Evar → Dusti Pharma
as real tenants, and suspending one without touching the others.
"""

import os
import tempfile

import pytest

from karag.domain import Principal
from karag.errors import AccessDenied, ValidationError
from karag.tenants import (
    AccountNotFound,
    ChainResolver,
    DirectoryResolver,
    DirectoryService,
    InMemoryDirectory,
    SqliteDirectory,
    hash_token,
)

OPERATOR = Principal("kit", "ops1", ("platform_admin",))
KOINOTI_ADMIN = Principal("koinoti", "admin1", ("admin",))
EVAR_ADMIN = Principal("evar", "admin2", ("admin",))
EMPLOYEE = Principal("koinoti", "emp1", ("employee",))


@pytest.fixture
def directory():
    return InMemoryDirectory()


@pytest.fixture
def service(directory):
    return DirectoryService(directory)


def test_rollout_sequence_onboards_three_tenants(service):
    """§14: Koinoti, then Evar, then Dusti Pharma — each its own tenant."""
    for slug, name in (
        ("koinoti", "Koinoti"),
        ("evar", "Evar"),
        ("dusti", "Dusti Pharma"),
    ):
        service.create_tenant(OPERATOR, tenant_id=slug, name=name)
    assert [t.id for t in service.list_tenants(OPERATOR)] == ["koinoti", "evar", "dusti"]


def test_only_platform_admin_may_create_a_tenant(service):
    with pytest.raises(AccessDenied):
        service.create_tenant(KOINOTI_ADMIN, tenant_id="rogue", name="Rogue")


def test_reserved_tenant_id_is_rejected(service):
    with pytest.raises(ValidationError):
        service.create_tenant(OPERATOR, tenant_id="*", name="Everything")


def test_duplicate_tenant_is_rejected(service):
    service.create_tenant(OPERATOR, tenant_id="koinoti", name="Koinoti")
    with pytest.raises(ValidationError):
        service.create_tenant(OPERATOR, tenant_id="koinoti", name="Again")


# ---------- accounts and tokens ----------


def test_token_is_returned_once_and_only_its_hash_is_stored(service, directory):
    account, token = service.create_account(KOINOTI_ADMIN, user_id="ceo1", roles=("ceo",))
    stored = directory.get_account("koinoti", "ceo1")
    assert stored.token_hash == hash_token(token)
    assert token not in str(stored.to_public_dict())
    assert stored.to_public_dict()["has_token"] is True


def test_resolver_maps_a_token_to_its_principal(service, directory):
    _, token = service.create_account(KOINOTI_ADMIN, user_id="ceo1", roles=("ceo",))
    principal = DirectoryResolver(directory).resolve(token)
    assert principal == Principal("koinoti", "ceo1", ("ceo",))


def test_unknown_token_is_refused(directory):
    with pytest.raises(AccessDenied):
        DirectoryResolver(directory).resolve("kg_not_a_real_token")


def test_suspended_account_stops_resolving(service, directory):
    _, token = service.create_account(KOINOTI_ADMIN, user_id="ceo1", roles=("ceo",))
    service.set_account_active(KOINOTI_ADMIN, "ceo1", False)
    with pytest.raises(AccessDenied):
        DirectoryResolver(directory).resolve(token)


def test_suspending_a_tenant_locks_out_all_of_its_accounts(service, directory):
    service.create_tenant(OPERATOR, tenant_id="koinoti", name="Koinoti")
    _, token = service.create_account(KOINOTI_ADMIN, user_id="ceo1", roles=("ceo",))
    resolver = DirectoryResolver(directory)
    assert resolver.resolve(token).user_id == "ceo1"

    service.set_tenant_active(OPERATOR, "koinoti", False)
    with pytest.raises(AccessDenied):
        resolver.resolve(token)


def test_rotating_a_token_invalidates_the_old_one(service, directory):
    _, old = service.create_account(KOINOTI_ADMIN, user_id="ceo1", roles=("ceo",))
    new = service.rotate_token(KOINOTI_ADMIN, "ceo1")
    resolver = DirectoryResolver(directory)
    assert resolver.resolve(new).user_id == "ceo1"
    with pytest.raises(AccessDenied):
        resolver.resolve(old)


def test_admin_of_one_tenant_cannot_touch_another(service):
    service.create_account(KOINOTI_ADMIN, user_id="ceo1", roles=("ceo",))
    # evar's admin operates in its own tenant namespace, so koinoti's ceo1
    # simply does not exist for it
    with pytest.raises(AccountNotFound):
        service.rotate_token(EVAR_ADMIN, "ceo1")


def test_ordinary_employee_cannot_manage_accounts(service):
    with pytest.raises(AccessDenied):
        service.create_account(EMPLOYEE, user_id="sneaky", roles=("ceo",))


def test_ceo_manages_their_own_tenants_people(service):
    """§7: the CEO is a superuser of their own tenant — including its people."""
    ceo = Principal("koinoti", "ceo1", ("ceo",))
    account, token = service.create_account(ceo, user_id="emp2", roles=("employee",))
    assert account.tenant_id == "koinoti" and token
    assert [a.id for a in service.list_accounts(ceo)] == ["emp2"]


def test_ceo_is_still_confined_to_their_own_tenant(service):
    """Superuser of *their own* tenant — never of the platform."""
    ceo = Principal("koinoti", "ceo1", ("ceo",))
    with pytest.raises(AccessDenied):
        service.list_tenants(ceo)
    with pytest.raises(AccessDenied):
        service.create_account(ceo, user_id="x", roles=("platform_admin",))


def test_tenant_admin_cannot_mint_a_platform_admin(service):
    """Otherwise "admin of Evar" could read every other company's tenant list."""
    with pytest.raises(AccessDenied):
        service.create_account(
            KOINOTI_ADMIN, user_id="escalated", roles=("platform_admin",)
        )


def test_tenant_admin_cannot_escalate_an_existing_account(service):
    service.create_account(KOINOTI_ADMIN, user_id="u1", roles=("employee",))
    with pytest.raises(AccessDenied):
        service.set_account_roles(KOINOTI_ADMIN, "u1", ("platform_admin",))


def test_user_sets_their_own_language_without_admin(service):
    service.create_account(KOINOTI_ADMIN, user_id="emp1", roles=("employee",))
    account = service.set_language(EMPLOYEE, "tg")
    assert account.language == "tg"


def test_invalid_language_is_rejected(service):
    service.create_account(KOINOTI_ADMIN, user_id="emp1", roles=("employee",))
    with pytest.raises(ValidationError):
        service.set_language(EMPLOYEE, "fr")


def test_language_falls_back_to_the_tenant_default(service, directory):
    service.create_tenant(OPERATOR, tenant_id="koinoti", name="Koinoti", default_language="ru")
    service.create_account(KOINOTI_ADMIN, user_id="emp1", roles=("employee",))
    resolver = DirectoryResolver(directory)
    assert resolver.language_for(EMPLOYEE) == "ru"  # account is "auto"

    service.set_language(EMPLOYEE, "tg")
    assert resolver.language_for(EMPLOYEE) == "tg"  # personal choice wins


# ---------- chaining with the env-var resolver ----------


def test_chain_resolver_falls_through_to_the_next_resolver(service, directory):
    from karag.api.security import InMemoryResolver

    _, db_token = service.create_account(KOINOTI_ADMIN, user_id="ceo1", roles=("ceo",))
    env = InMemoryResolver({"tkn_bot": Principal("koinoti", "bot", ("employee",))})
    chain = ChainResolver(DirectoryResolver(directory), env)

    assert chain.resolve(db_token).user_id == "ceo1"
    assert chain.resolve("tkn_bot").user_id == "bot"
    with pytest.raises(AccessDenied):
        chain.resolve("nonsense")


# ---------- durability ----------


def test_accounts_survive_a_restart():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        first = SqliteDirectory(path)
        DirectoryService(first).create_tenant(
            OPERATOR, tenant_id="koinoti", name="Koinoti"
        )
        _, token = DirectoryService(first).create_account(
            KOINOTI_ADMIN, user_id="ceo1", roles=("ceo",)
        )

        second = SqliteDirectory(path)  # a fresh process
        assert DirectoryResolver(second).resolve(token).user_id == "ceo1"
        assert [t.id for t in second.list_tenants()] == ["koinoti"]
    finally:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(path + suffix):
                os.remove(path + suffix)
