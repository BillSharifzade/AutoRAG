"""Tenants (platform operators), accounts (tenant admins) and alert rules."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException

from ...domain import Principal
from ..common import (
    AccountRequest,
    AccountUpdateRequest,
    AlertEnabledRequest,
    AlertRequest,
    ApiContext,
    TenantActiveRequest,
    TenantRequest,
)


def mount(app: FastAPI, ctx: ApiContext) -> None:
    plat = ctx.plat
    principal_from = ctx.principal_from
    scheduler = ctx.scheduler

    # --- Proactive alerts (§15) --------------------------------------------

    @app.get("/v1/alerts")
    async def list_alerts(principal: Principal = Depends(principal_from)) -> dict:
        return {"alerts": [r.to_dict() for r in plat.alert_service.list(principal)]}

    @app.post("/v1/alerts")
    async def create_alert(
        req: AlertRequest, principal: Principal = Depends(principal_from)
    ) -> dict:
        rule = plat.alert_service.create(
            principal, name=req.name, skill_name=req.skill_name,
            arguments=req.arguments, interval_s=req.interval_s,
            condition=req.condition, condition_config=req.condition_config,
            message_template=req.message_template, channel=req.channel,
            run_as_roles=tuple(req.run_as_roles) if req.run_as_roles is not None else None,
        )
        return rule.to_dict()

    @app.patch("/v1/alerts/{rule_id}")
    async def set_alert_enabled(
        rule_id: str,
        req: AlertEnabledRequest,
        principal: Principal = Depends(principal_from),
    ) -> dict:
        return plat.alert_service.set_enabled(principal, rule_id, req.enabled).to_dict()

    @app.delete("/v1/alerts/{rule_id}")
    async def delete_alert(
        rule_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        if not plat.alert_service.delete(principal, rule_id):
            raise HTTPException(status_code=404, detail="alert not found")
        return {"deleted": rule_id}

    @app.post("/v1/alerts/{rule_id}/run")
    async def run_alert_now(
        rule_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        """Fire a rule on demand — the "does my alert work?" button."""
        rule = plat.alert_service.get(principal, rule_id)
        outcome = await scheduler.run_rule(rule, force=True)
        return {
            "ran": outcome.ran, "fired": outcome.fired,
            "error": outcome.error, "message": outcome.message,
        }

    # --- Tenants + accounts (§12 "accounts, tenants"; §14 rollout) ----------

    @app.post("/v1/tenants")
    async def create_tenant(
        req: TenantRequest, principal: Principal = Depends(principal_from)
    ) -> dict:
        t = plat.directory_service.create_tenant(
            principal, tenant_id=req.id, name=req.name,
            default_language=req.default_language,
        )
        return t.to_dict()

    @app.get("/v1/tenants")
    async def list_tenants(principal: Principal = Depends(principal_from)) -> dict:
        tenants = []
        for t in plat.directory_service.list_tenants(principal):
            row = t.to_dict()
            if plat.guard is not None:
                row["budget"] = plat.guard.status(t.id)
            tenants.append(row)
        return {"tenants": tenants}

    @app.patch("/v1/tenants/{tenant_id}")
    async def set_tenant_active(
        tenant_id: str,
        req: TenantActiveRequest,
        principal: Principal = Depends(principal_from),
    ) -> dict:
        fields = req.model_fields_set
        if not fields & {"active", "monthly_budget_usd"}:
            raise HTTPException(status_code=400, detail="nothing to update")
        if "active" in fields and req.active is not None:
            if not plat.directory_service.set_tenant_active(principal, tenant_id, req.active):
                raise HTTPException(status_code=404, detail="tenant not found")
        if "monthly_budget_usd" in fields:
            if not plat.directory_service.set_tenant_budget(
                principal, tenant_id, req.monthly_budget_usd
            ):
                raise HTTPException(status_code=404, detail="tenant not found")
            if plat.guard is not None:
                plat.guard.forget_spend(tenant_id)
        tenant = plat.directory.get_tenant(tenant_id)
        out = {"id": tenant_id, "active": tenant.active if tenant else req.active}
        if plat.guard is not None:
            out["budget"] = plat.guard.status(tenant_id)
        return out

    @app.post("/v1/accounts")
    async def create_account(
        req: AccountRequest, principal: Principal = Depends(principal_from)
    ) -> dict:
        account, token = plat.directory_service.create_account(
            principal, user_id=req.user_id, display_name=req.display_name,
            roles=tuple(req.roles), language=req.language,
        )
        # The token is shown exactly once — only its hash is stored.
        return {"account": account.to_public_dict(), "token": token}

    @app.get("/v1/accounts")
    async def list_accounts(principal: Principal = Depends(principal_from)) -> dict:
        accounts = [
            {**a.to_public_dict(), "source": "directory"}
            for a in plat.directory_service.list_accounts(principal)
        ]
        # People who sign in with a token from the server's configuration
        # (KARAG_TOKENS) are listed too, read-only: they are managed in the
        # config, not here — but an admin should still see who has access.
        known = {a["id"] for a in accounts}
        for p in ctx.config_principals():
            if p.tenant_id == principal.tenant_id and p.user_id not in known:
                known.add(p.user_id)
                accounts.append({
                    "id": p.user_id, "tenant_id": p.tenant_id, "display_name": p.user_id,
                    "roles": list(p.roles), "language": "auto", "active": True,
                    "created_at": 0, "has_token": True, "source": "config",
                })
        return {"accounts": accounts}

    @app.patch("/v1/accounts/{user_id}")
    async def update_account(
        user_id: str,
        req: AccountUpdateRequest,
        principal: Principal = Depends(principal_from),
    ) -> dict:
        account = None
        if req.roles is not None:
            account = plat.directory_service.set_account_roles(
                principal, user_id, tuple(req.roles)
            )
        if req.active is not None:
            account = plat.directory_service.set_account_active(
                principal, user_id, req.active
            )
        if account is None:
            raise HTTPException(status_code=400, detail="nothing to update")
        return account.to_public_dict()

    @app.post("/v1/accounts/{user_id}/rotate")
    async def rotate_token(
        user_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        return {"user_id": user_id, "token": plat.directory_service.rotate_token(principal, user_id)}

    @app.delete("/v1/accounts/{user_id}")
    async def delete_account(
        user_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        if not plat.directory_service.delete_account(principal, user_id):
            raise HTTPException(status_code=404, detail="account not found")
        return {"deleted": user_id}
