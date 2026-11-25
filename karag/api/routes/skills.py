"""The skill catalogue: connections, stored definitions, SKILL.md, the shared library."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from ...domain import Principal
from ...skills.agent_skill import parse_skill_md, render_skill_md
from ...skills.catalog import can_author
from ..common import (
    ApiContext,
    ConnectorRequest,
    LibraryImportRequest,
    SkillDefinitionRequest,
    SkillMarkdownRequest,
    SkillTestRequest,
)


def mount(app: FastAPI, ctx: ApiContext) -> None:
    plat = ctx.plat
    principal_from = ctx.principal_from

    @app.get("/v1/skills")
    async def list_skills(principal: Principal = Depends(principal_from)) -> dict:
        return {"skills": [
            {"name": s.name, "description": s.description}
            for s in plat.registry.visible_for(principal)
        ]}

    # --- Data connections + skill authoring (§5, §6, §11 "technical staff") ---
    # These are the registry endpoints that let a specialist build a verified
    # skill without editing Python. Every one is authorised inside SkillCatalog,
    # not here, so the bot/webhook paths inherit the same rules.

    @app.post("/v1/connectors")
    async def create_connector(
        req: ConnectorRequest, principal: Principal = Depends(principal_from)
    ) -> dict:
        spec = plat.catalog.create_connector(
            principal, name=req.name, kind=req.kind, config=req.config,
            row_limit=req.row_limit, timeout_s=req.timeout_s,
        )
        return spec.to_public_dict()

    @app.get("/v1/connectors")
    async def list_connectors(principal: Principal = Depends(principal_from)) -> dict:
        return {
            "connectors": [
                c.to_public_dict() for c in plat.catalog.list_connectors(principal)
            ]
        }

    @app.delete("/v1/connectors/{connector_id}")
    async def delete_connector(
        connector_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        if not plat.catalog.delete_connector(principal, connector_id):
            raise HTTPException(status_code=404, detail="connector not found")
        return {"deleted": connector_id}

    @app.get("/v1/skills/definitions")
    async def list_skill_definitions(
        principal: Principal = Depends(principal_from),
    ) -> dict:
        return {"skills": [d.to_dict() for d in plat.catalog.list_skills(principal)]}

    @app.post("/v1/skills/definitions")
    async def create_skill_definition(
        req: SkillDefinitionRequest, principal: Principal = Depends(principal_from)
    ) -> dict:
        defn = plat.catalog.create_skill(
            principal,
            name=req.name, description=req.description, kind=req.kind,
            connector_id=req.connector_id, param_schema=req.param_schema,
            sql=req.sql, path=req.path,
            instructions=req.instructions, resources=req.resource_tuple(),
            required_data_class=req.required_data_class,
            required_roles=tuple(req.required_roles), row_limit=req.row_limit,
            inject_tenant=req.inject_tenant, shared=req.shared,
        )
        return defn.to_dict()

    @app.get("/v1/skills/definitions/{skill_id}")
    async def get_skill_definition(
        skill_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        return plat.catalog.get_skill(principal, skill_id).to_dict()

    @app.put("/v1/skills/definitions/{skill_id}")
    async def update_skill_definition(
        skill_id: str,
        req: SkillDefinitionRequest,
        principal: Principal = Depends(principal_from),
    ) -> dict:
        defn = plat.catalog.update_skill(
            principal, skill_id,
            name=req.name, description=req.description, kind=req.kind,
            connector_id=req.connector_id, param_schema=req.param_schema,
            sql=req.sql, path=req.path,
            instructions=req.instructions, resources=req.resource_tuple(),
            required_data_class=req.required_data_class,
            required_roles=tuple(req.required_roles), row_limit=req.row_limit,
            inject_tenant=req.inject_tenant, shared=req.shared,
            enabled=req.enabled,
        )
        return defn.to_dict()

    @app.delete("/v1/skills/definitions/{skill_id}")
    async def delete_skill_definition(
        skill_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        if not plat.catalog.delete_skill(principal, skill_id):
            raise HTTPException(status_code=404, detail="skill not found")
        return {"deleted": skill_id}

    @app.post("/v1/skills/definitions/{skill_id}/test")
    async def test_skill_definition(
        skill_id: str,
        req: SkillTestRequest,
        principal: Principal = Depends(principal_from),
    ) -> dict:
        run = await plat.catalog.test_skill(principal, skill_id, req.arguments)
        return run.to_dict()

    @app.get("/v1/skills/definitions/{skill_id}/skill_md", response_class=PlainTextResponse)
    async def export_skill_md(
        skill_id: str, principal: Principal = Depends(principal_from)
    ) -> str:
        """An agent skill as a real ``SKILL.md``.

        A procedure written here is portable: the same bytes load in Claude Code
        or claude.ai, so the company's knowledge is not locked inside KARAG.
        """
        defn = plat.catalog.get_skill(principal, skill_id)
        if defn.kind != "agent":
            raise HTTPException(
                status_code=400, detail="only a procedure has a SKILL.md"
            )
        return render_skill_md(defn.name, defn.description, defn.instructions)

    @app.post("/v1/skills/parse_skill_md")
    async def read_skill_md(
        req: SkillMarkdownRequest, principal: Principal = Depends(principal_from)
    ) -> dict:
        """Split a pasted SKILL.md into fields, so an existing skill can be adopted.

        Author-gated like every other authoring route, and purely a parse: it
        stores nothing.
        """
        if not can_author(principal):
            raise HTTPException(status_code=403, detail="not a skill author")
        name, description, instructions = parse_skill_md(req.text)
        return {"name": name, "description": description, "instructions": instructions}

    @app.get("/v1/skills/library")
    async def list_skill_library(principal: Principal = Depends(principal_from)) -> dict:
        return {"skills": [d.to_dict() for d in plat.catalog.list_library(principal)]}

    @app.post("/v1/skills/library/{skill_id}/import")
    async def import_skill(
        skill_id: str,
        req: LibraryImportRequest,
        principal: Principal = Depends(principal_from),
    ) -> dict:
        defn = plat.catalog.import_from_library(
            principal, skill_id, connector_id=req.connector_id, name=req.name
        )
        return defn.to_dict()
