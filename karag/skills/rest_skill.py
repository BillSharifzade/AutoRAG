"""Build a verified Skill from a REST connector + a fixed endpoint.

The concept doc's §6 calls the API path *stronger*, not weaker, than DB views:
the company exposes a limited read-only endpoint returning ready business
objects, so the platform never touches their database and their security team
only has to approve "call our own API".

The endpoint path is fixed at definition time — the model supplies query
parameters, never the path — so a skill can't be steered at a different route.
"""

from __future__ import annotations

from ..connectors.rest import RestConnector
from ..domain import DataClass, Principal
from .base import Skill, SkillResult


def make_rest_skill(
    *,
    name: str,
    description: str,
    path: str,
    param_schema: dict,
    connector: RestConnector,
    required_data_class: DataClass = DataClass.OPERATIONAL,
    required_roles: frozenset[str] = frozenset(),
    tenant_id: str = "*",
    inject_tenant: bool = True,
) -> Skill:
    """Create a Skill that GETs ``path`` on the connector with validated args.

    If ``inject_tenant`` is set, the caller's tenant is added as a query
    parameter, so an endpoint that honours it is row-scoped the same way a SQL
    skill is.
    """

    async def handler(principal: Principal, args: dict) -> SkillResult:
        params = dict(args)
        if inject_tenant:
            params.setdefault("tenant_id", principal.tenant_id)
        data = await connector.get(path, params)
        shown = f"GET {connector.base_url}/{path.lstrip('/')} params={params}"
        return SkillResult(data=data, query_shown=shown)

    return Skill(
        name=name,
        description=description,
        input_schema=param_schema,
        handler=handler,
        required_data_class=required_data_class,
        required_roles=required_roles,
        tenant_id=tenant_id,
    )
