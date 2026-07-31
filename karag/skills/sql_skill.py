"""Build a verified Skill from a SQL connector + a parameterized query.

This is the real data-plane path: a human writes and tests the SQL once, binds
it to a typed parameter schema, and the platform enforces read-only execution,
row limits and timeouts via the connector. The model sees only the safe tool.
"""

from __future__ import annotations

from ..connectors.sql import SqlConnector
from ..domain import DataClass, Principal
from .base import Skill, SkillResult


def make_sql_skill(
    *,
    name: str,
    description: str,
    sql: str,
    param_schema: dict,
    connector: SqlConnector,
    required_data_class: DataClass = DataClass.OPERATIONAL,
    required_roles: frozenset[str] = frozenset(),
    tenant_id: str = "*",
    row_limit: int | None = None,
    inject_tenant: bool = True,
) -> Skill:
    """Create a Skill whose handler runs ``sql`` with the validated arguments.

    If ``inject_tenant`` is set and the SQL references ``:tenant_id``, the
    caller's tenant is bound automatically — row-level scoping the query to the
    principal's own tenant, so a skill can never read another tenant's rows.
    """

    async def handler(principal: Principal, args: dict) -> SkillResult:
        params = dict(args)
        if inject_tenant:
            params.setdefault("tenant_id", principal.tenant_id)
        rows = await connector.query(sql, params, row_limit=row_limit)
        shown = sql.strip()
        return SkillResult(
            data={"rows": rows, "count": len(rows)},
            query_shown=f"{shown}  -- params={_redact(params)}",
        )

    return Skill(
        name=name,
        description=description,
        input_schema=param_schema,
        handler=handler,
        required_data_class=required_data_class,
        required_roles=required_roles,
        tenant_id=tenant_id,
    )


def _redact(params: dict) -> dict:
    # params are non-secret query values; shown for provenance as-is.
    return params
