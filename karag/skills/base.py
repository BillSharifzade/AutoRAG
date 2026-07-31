"""Skills — the data plane's unit of trust.

A *skill* is a prepared, parameterized, read-only query written and verified by
a human once, then reused. It is the "universal adapter" from the concept doc:
inside, it is a SQL view query or an API call; outside, the model sees only a
safe, typed tool. The model never touches a raw database.

Each skill carries its own RBAC requirements (roles + data class) and returns a
``SkillResult`` that includes ``query_shown`` — the exact query executed — so the
answer's provenance can be surfaced to the user for verification.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ..domain import Artifact, DataClass, Principal
from ..llm.base import ToolSpec

# A handler runs a *verified, read-only* query. It receives the calling
# principal (for row-level scoping) and validated arguments.
SkillHandler = Callable[[Principal, dict], Awaitable["SkillResult"]]


@dataclass
class SkillResult:
    data: object  # rows | dict | scalar | str — JSON-serialisable
    query_shown: str  # the executed query/endpoint, shown to the user
    # optional generated file (Office output skills). Carried out-of-band so its
    # bytes never enter the model's context.
    artifact: Artifact | None = None


@dataclass
class Skill:
    name: str
    description: str
    input_schema: dict
    handler: SkillHandler
    required_data_class: DataClass = DataClass.OPERATIONAL
    required_roles: frozenset[str] = field(default_factory=frozenset)
    # tenant that owns this skill; "*" means available to every tenant.
    tenant_id: str = "*"

    def to_tool_spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )

    def visible_to(self, principal: Principal) -> bool:
        """Whether this skill should even be *offered* to the principal.

        Combines tenant ownership, role requirement, and data-class clearance.
        Used both to build the tool catalogue and (defensively) at execution.
        """
        from ..rbac import can_access  # local import avoids a cycle

        if self.tenant_id not in ("*", principal.tenant_id):
            return False
        if not principal.has_any_role(self.required_roles):
            return False
        return can_access(principal, self.required_data_class)
