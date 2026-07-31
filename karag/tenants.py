"""Tenants and accounts — the platform's own registry of *who* it serves.

§12's stack table gives the app database four jobs: accounts, tenants, skills,
audit. This module covers the first two, and with them §14's rollout plan
becomes something you can actually execute: onboard Koinoti, then Evar, then
Dusti Pharma as real tenant rows rather than strings hard-coded in an env var.

Security notes:

* A tenant is the isolation boundary already enforced everywhere else
  (retrieval, skills, assistants, chats). Registering one here does not create
  the boundary — it names it, so it can be listed, suspended and audited.
* Account tokens are stored **hashed** (SHA-256), never in the clear, and
  compared in constant time. A leaked database therefore does not hand an
  attacker working credentials.
* Suspending a tenant or an account takes effect on the next request: the
  resolver refuses to mint a Principal for it, so every downstream check that
  depends on a Principal fails closed automatically.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

from .domain import Principal
from .errors import AccessDenied, NotFoundError, ValidationError

# Supported answer/UI languages (§2's moat, §15's multilingual line).
LANGUAGES = ("auto", "ru", "tg", "en")


class TenantNotFound(NotFoundError):
    pass


class AccountNotFound(NotFoundError):
    pass


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token(prefix: str = "kg") -> str:
    """A fresh, high-entropy bearer token. Shown to the operator exactly once."""
    return f"{prefix}_{secrets.token_urlsafe(32)}"


@dataclass
class Tenant:
    id: str  # short slug used as tenant_id everywhere else, e.g. "koinoti"
    name: str
    active: bool = True
    default_language: str = "auto"
    created_at: float = field(default_factory=time.time)
    settings: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "active": self.active,
            "default_language": self.default_language,
            "created_at": self.created_at,
            "settings": self.settings,
        }


@dataclass
class Account:
    id: str  # user_id within the tenant
    tenant_id: str
    display_name: str
    roles: tuple[str, ...]
    token_hash: str = ""
    language: str = "auto"
    active: bool = True
    created_at: float = field(default_factory=time.time)

    def to_public_dict(self) -> dict:
        """No token material — not even the hash — ever leaves the server."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "display_name": self.display_name,
            "roles": list(self.roles),
            "language": self.language,
            "active": self.active,
            "created_at": self.created_at,
            "has_token": bool(self.token_hash),
        }

    def to_principal(self) -> Principal:
        return Principal(
            tenant_id=self.tenant_id, user_id=self.id, roles=tuple(self.roles)
        )


def validate_tenant_id(tenant_id: str) -> None:
    if not tenant_id or not tenant_id.replace("-", "").replace("_", "").isalnum():
        raise ValidationError(
            "tenant id must be a short alphanumeric slug (dashes/underscores ok)"
        )
    if tenant_id == "*":
        raise ValidationError("'*' is reserved for library-wide skills")


def validate_language(language: str) -> None:
    if language not in LANGUAGES:
        raise ValidationError(f"language must be one of {LANGUAGES}")


class DirectoryStore(Protocol):
    """Tenants + accounts, together — they are always read as a pair."""

    def create_tenant(self, tenant: Tenant) -> Tenant: ...
    def get_tenant(self, tenant_id: str) -> Tenant | None: ...
    def list_tenants(self) -> list[Tenant]: ...
    def set_tenant_active(self, tenant_id: str, active: bool) -> bool: ...
    def create_account(self, account: Account) -> Account: ...
    def get_account(self, tenant_id: str, user_id: str) -> Account | None: ...
    def list_accounts(self, tenant_id: str) -> list[Account]: ...
    def account_by_token(self, token_hash: str) -> Account | None: ...
    def update_account(self, account: Account) -> Account: ...
    def delete_account(self, tenant_id: str, user_id: str) -> bool: ...


class InMemoryDirectory:
    def __init__(self) -> None:
        self._tenants: dict[str, Tenant] = {}
        self._accounts: dict[tuple[str, str], Account] = {}

    def create_tenant(self, tenant: Tenant) -> Tenant:
        if tenant.id in self._tenants:
            raise ValidationError(f"tenant {tenant.id!r} already exists")
        self._tenants[tenant.id] = tenant
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)

    def list_tenants(self) -> list[Tenant]:
        return sorted(self._tenants.values(), key=lambda t: t.created_at)

    def set_tenant_active(self, tenant_id: str, active: bool) -> bool:
        t = self._tenants.get(tenant_id)
        if t is None:
            return False
        t.active = active
        return True

    def create_account(self, account: Account) -> Account:
        key = (account.tenant_id, account.id)
        if key in self._accounts:
            raise ValidationError(
                f"account {account.id!r} already exists in {account.tenant_id!r}"
            )
        self._accounts[key] = account
        return account

    def get_account(self, tenant_id: str, user_id: str) -> Account | None:
        return self._accounts.get((tenant_id, user_id))

    def list_accounts(self, tenant_id: str) -> list[Account]:
        return sorted(
            (a for a in self._accounts.values() if a.tenant_id == tenant_id),
            key=lambda a: a.created_at,
        )

    def account_by_token(self, token_hash: str) -> Account | None:
        for a in self._accounts.values():
            if a.token_hash and hmac.compare_digest(a.token_hash, token_hash):
                return a
        return None

    def update_account(self, account: Account) -> Account:
        self._accounts[(account.tenant_id, account.id)] = account
        return account

    def delete_account(self, tenant_id: str, user_id: str) -> bool:
        return self._accounts.pop((tenant_id, user_id), None) is not None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    active           INTEGER NOT NULL DEFAULT 1,
    default_language TEXT NOT NULL DEFAULT 'auto',
    created_at       REAL NOT NULL,
    settings         TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS accounts (
    tenant_id    TEXT NOT NULL,
    id           TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    roles        TEXT NOT NULL DEFAULT '[]',
    token_hash   TEXT NOT NULL DEFAULT '',
    language     TEXT NOT NULL DEFAULT 'auto',
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   REAL NOT NULL,
    PRIMARY KEY (tenant_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS accounts_token
    ON accounts (token_hash) WHERE token_hash <> '';
"""


class SqliteDirectory:
    def __init__(self, path: str = "karag_app.db") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def create_tenant(self, tenant: Tenant) -> Tenant:
        with self._lock, self._conn:
            try:
                self._conn.execute(
                    "INSERT INTO tenants (id, name, active, default_language,"
                    " created_at, settings) VALUES (?,?,?,?,?,?)",
                    (
                        tenant.id, tenant.name, int(tenant.active),
                        tenant.default_language, tenant.created_at,
                        json.dumps(tenant.settings),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValidationError(f"tenant {tenant.id!r} already exists") from exc
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tenants WHERE id=?", (tenant_id,)
            ).fetchone()
        return _row_to_tenant(row) if row else None

    def list_tenants(self) -> list[Tenant]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tenants ORDER BY created_at"
            ).fetchall()
        return [_row_to_tenant(r) for r in rows]

    def set_tenant_active(self, tenant_id: str, active: bool) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE tenants SET active=? WHERE id=?", (int(active), tenant_id)
            )
        return cur.rowcount > 0

    def create_account(self, account: Account) -> Account:
        with self._lock, self._conn:
            try:
                self._conn.execute(
                    "INSERT INTO accounts (tenant_id, id, display_name, roles,"
                    " token_hash, language, active, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    _account_params(account),
                )
            except sqlite3.IntegrityError as exc:
                raise ValidationError(
                    f"account {account.id!r} already exists in {account.tenant_id!r}"
                ) from exc
        return account

    def get_account(self, tenant_id: str, user_id: str) -> Account | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM accounts WHERE tenant_id=? AND id=?",
                (tenant_id, user_id),
            ).fetchone()
        return _row_to_account(row) if row else None

    def list_accounts(self, tenant_id: str) -> list[Account]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM accounts WHERE tenant_id=? ORDER BY created_at",
                (tenant_id,),
            ).fetchall()
        return [_row_to_account(r) for r in rows]

    def account_by_token(self, token_hash: str) -> Account | None:
        if not token_hash:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM accounts WHERE token_hash=?", (token_hash,)
            ).fetchone()
        return _row_to_account(row) if row else None

    def update_account(self, account: Account) -> Account:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE accounts SET display_name=?, roles=?, token_hash=?,"
                " language=?, active=? WHERE tenant_id=? AND id=?",
                (
                    account.display_name, json.dumps(list(account.roles)),
                    account.token_hash, account.language, int(account.active),
                    account.tenant_id, account.id,
                ),
            )
        return account

    def delete_account(self, tenant_id: str, user_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM accounts WHERE tenant_id=? AND id=?", (tenant_id, user_id)
            )
        return cur.rowcount > 0


def _account_params(a: Account) -> tuple:
    return (
        a.tenant_id, a.id, a.display_name, json.dumps(list(a.roles)),
        a.token_hash, a.language, int(a.active), a.created_at,
    )


def _row_to_tenant(row: sqlite3.Row) -> Tenant:
    return Tenant(
        id=row["id"],
        name=row["name"],
        active=bool(row["active"]),
        default_language=row["default_language"],
        created_at=row["created_at"],
        settings=json.loads(row["settings"]),
    )


def _row_to_account(row: sqlite3.Row) -> Account:
    return Account(
        id=row["id"],
        tenant_id=row["tenant_id"],
        display_name=row["display_name"],
        roles=tuple(json.loads(row["roles"])),
        token_hash=row["token_hash"],
        language=row["language"],
        active=bool(row["active"]),
        created_at=row["created_at"],
    )


class DirectoryService:
    """Onboarding operations — creating tenants and issuing account tokens.

    Only a principal holding ``admin`` may manage accounts, and only within
    their own tenant. Creating a *tenant* is a platform-operator action (KIT),
    gated on the ``platform_admin`` role, because it is the one operation that
    is not scoped by an existing tenant boundary.
    """

    def __init__(self, store: DirectoryStore) -> None:
        self._store = store

    # ---- tenants (KIT operators) ----------------------------------------

    def create_tenant(
        self,
        principal: Principal,
        *,
        tenant_id: str,
        name: str,
        default_language: str = "auto",
    ) -> Tenant:
        if "platform_admin" not in principal.roles:
            raise AccessDenied("creating a tenant requires the platform_admin role")
        validate_tenant_id(tenant_id)
        validate_language(default_language)
        return self._store.create_tenant(
            Tenant(id=tenant_id, name=name, default_language=default_language)
        )

    def list_tenants(self, principal: Principal) -> list[Tenant]:
        if "platform_admin" not in principal.roles:
            raise AccessDenied("listing tenants requires the platform_admin role")
        return self._store.list_tenants()

    def set_tenant_active(
        self, principal: Principal, tenant_id: str, active: bool
    ) -> bool:
        if "platform_admin" not in principal.roles:
            raise AccessDenied("suspending a tenant requires the platform_admin role")
        return self._store.set_tenant_active(tenant_id, active)

    # ---- accounts (tenant admins) ---------------------------------------

    def create_account(
        self,
        principal: Principal,
        *,
        user_id: str,
        display_name: str = "",
        roles: tuple[str, ...] = ("employee",),
        language: str = "auto",
    ) -> tuple[Account, str]:
        """Create an account in the caller's tenant and mint its token.

        Returns ``(account, token)``. The token is returned **once** — only its
        hash is stored, so it cannot be recovered later, only rotated.
        """
        self._require_tenant_admin(principal)
        validate_language(language)
        self._reject_privilege_escalation(principal, roles)
        token = generate_token()
        account = Account(
            id=user_id,
            tenant_id=principal.tenant_id,
            display_name=display_name or user_id,
            roles=tuple(roles),
            token_hash=hash_token(token),
            language=language,
        )
        self._store.create_account(account)
        return account, token

    def list_accounts(self, principal: Principal) -> list[Account]:
        self._require_tenant_admin(principal)
        return self._store.list_accounts(principal.tenant_id)

    def rotate_token(self, principal: Principal, user_id: str) -> str:
        self._require_tenant_admin(principal)
        account = self._store.get_account(principal.tenant_id, user_id)
        if account is None:
            raise AccountNotFound(user_id)
        token = generate_token()
        account.token_hash = hash_token(token)
        self._store.update_account(account)
        return token

    def set_account_active(
        self, principal: Principal, user_id: str, active: bool
    ) -> Account:
        self._require_tenant_admin(principal)
        account = self._store.get_account(principal.tenant_id, user_id)
        if account is None:
            raise AccountNotFound(user_id)
        account.active = active
        return self._store.update_account(account)

    def set_account_roles(
        self, principal: Principal, user_id: str, roles: tuple[str, ...]
    ) -> Account:
        self._require_tenant_admin(principal)
        self._reject_privilege_escalation(principal, roles)
        account = self._store.get_account(principal.tenant_id, user_id)
        if account is None:
            raise AccountNotFound(user_id)
        account.roles = tuple(roles)
        return self._store.update_account(account)

    def set_language(self, principal: Principal, language: str) -> Account:
        """A user changes their own answer language — no admin role needed."""
        validate_language(language)
        account = self._store.get_account(principal.tenant_id, principal.user_id)
        if account is None:
            raise AccountNotFound(principal.user_id)
        account.language = language
        return self._store.update_account(account)

    def delete_account(self, principal: Principal, user_id: str) -> bool:
        self._require_tenant_admin(principal)
        return self._store.delete_account(principal.tenant_id, user_id)

    @staticmethod
    def _require_tenant_admin(principal: Principal) -> None:
        # §7: "the CEO is a superuser of their own tenant" — that has to include
        # managing its people, not just reading its data.
        if not ({"admin", "platform_admin", "ceo"} & set(principal.roles)):
            raise AccessDenied("managing accounts requires an admin or ceo role")

    @staticmethod
    def _reject_privilege_escalation(
        principal: Principal, roles: tuple[str, ...]
    ) -> None:
        """A tenant admin must not be able to mint platform operators.

        Without this, "admin of Evar" could create a ``platform_admin`` account
        and read every other company's tenant list — precisely the cross-tenant
        leak §13 ranks first.
        """
        if "platform_admin" in roles and "platform_admin" not in principal.roles:
            raise AccessDenied("only a platform_admin may grant the platform_admin role")


class DirectoryResolver:
    """Resolve a bearer token to a Principal against the accounts database.

    Drop-in replacement for
    :class:`~karag.api.security.InMemoryResolver` that reads real accounts
    instead of an env var, so users can be onboarded and revoked at runtime.
    A suspended account or a suspended tenant resolves to nothing — fail-closed.
    """

    def __init__(self, store: DirectoryStore) -> None:
        self._store = store

    def resolve(self, token: str) -> Principal:
        account = self._store.account_by_token(hash_token(token))
        if account is None or not account.active:
            raise AccessDenied("invalid token")
        tenant = self._store.get_tenant(account.tenant_id)
        if tenant is not None and not tenant.active:
            raise AccessDenied("tenant is suspended")
        return account.to_principal()

    def language_for(self, principal: Principal) -> str:
        """The principal's preferred answer language, falling back to the tenant's."""
        account = self._store.get_account(principal.tenant_id, principal.user_id)
        if account is not None and account.language != "auto":
            return account.language
        tenant = self._store.get_tenant(principal.tenant_id)
        return tenant.default_language if tenant else "auto"


class ChainResolver:
    """Try several resolvers in order; the first to succeed wins.

    Lets a deployment run env-var tokens (dev, bots) and database accounts
    (real users) side by side during migration without a flag day.
    """

    def __init__(self, *resolvers) -> None:
        self._resolvers = resolvers

    def resolve(self, token: str) -> Principal:
        for resolver in self._resolvers:
            try:
                return resolver.resolve(token)
            except AccessDenied:
                continue
        raise AccessDenied("invalid token")
