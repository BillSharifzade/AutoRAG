"""Authentication: resolve a bearer token to a Principal.

Pluggable by design. The in-memory resolver here is for local development and
tests; production swaps in an SSO/JWT-backed resolver behind the same
``PrincipalResolver`` protocol. Tokens are loaded from the environment, never
hard-coded.

Token env format (``KARAG_TOKENS``): comma-separated
``token:tenant:user:role1|role2`` entries, e.g.

    KARAG_TOKENS="tkn_ceo:koinoti:ceo1:ceo, tkn_hr:koinoti:hr1:hr"
"""

from __future__ import annotations

import os
from typing import Protocol

from ..domain import Principal
from ..errors import AccessDenied


class PrincipalResolver(Protocol):
    def resolve(self, token: str) -> Principal: ...


class InMemoryResolver:
    def __init__(self, tokens: dict[str, Principal] | None = None) -> None:
        self._tokens = tokens or {}

    def add(self, token: str, principal: Principal) -> None:
        self._tokens[token] = principal

    def resolve(self, token: str) -> Principal:
        principal = self._tokens.get(token)
        if principal is None:
            raise AccessDenied("invalid token")
        return principal

    def config_principals(self) -> list[Principal]:
        """The people these static tokens stand for — never the tokens."""
        return list(self._tokens.values())

    @classmethod
    def from_env(cls, var: str = "KARAG_TOKENS") -> "InMemoryResolver":
        raw = os.environ.get(var, "")
        tokens: dict[str, Principal] = {}
        for entry in raw.split(","):
            entry = entry.strip()
            if not entry:
                continue
            token, tenant, user, roles = entry.split(":", 3)
            tokens[token] = Principal(
                tenant_id=tenant,
                user_id=user,
                roles=tuple(r for r in roles.split("|") if r),
            )
        return cls(tokens)
