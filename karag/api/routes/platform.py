"""Health, the caller's profile, onboarding, code proposals, audit and usage."""

from __future__ import annotations

from dataclasses import asdict
from fastapi import Depends, FastAPI, HTTPException

from ...domain import Principal
from ...engineer.guard import ENGINEER_ROLE
from ...errors import NotFoundError
from ...selfknowledge.handbook import guides_for, onboarding_prompt
from ...skills.catalog import can_author
from ...tenants import LANGUAGES, validate_language
from ..common import (
    ApiContext,
    LanguageRequest,
)


def mount(app: FastAPI, ctx: ApiContext) -> None:
    plat = ctx.plat
    principal_from = ctx.principal_from
    language_for = ctx.language_for
    prices = ctx.prices

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "model": plat.gateway.model,
            "languages": list(LANGUAGES),
            # a definition that failed to materialise is visible, not silent
            "skill_load_errors": plat.skill_load_errors,
        }

    @app.get("/v1/me")
    async def me(principal: Principal = Depends(principal_from)) -> dict:
        return {
            "tenant_id": principal.tenant_id,
            "user_id": principal.user_id,
            "roles": list(principal.roles),
            "language": language_for(principal, None),
            "can_author_skills": can_author(principal),
            "can_edit_code": (
                plat.settings.engineer_enabled and ENGINEER_ROLE in principal.roles
            ),
        }

    @app.post("/v1/me/language")
    async def set_my_language(
        req: LanguageRequest, principal: Principal = Depends(principal_from)
    ) -> dict:
        validate_language(req.language)
        try:
            plat.directory_service.set_language(principal, req.language)
        except NotFoundError:
            # env-token users have no account row; the choice is then per-request
            raise HTTPException(
                status_code=404,
                detail="no stored account for this token; pass language per request",
            )
        return {"language": req.language}

    @app.get("/")
    async def root() -> dict:
        # The console is the Next.js app (web/); the API itself has no pages.
        return {"service": "karag", "console": "web/ on :3000", "health": "/health"}


    # --- Platform self-knowledge (onboarding tour) -------------------------

    @app.get("/v1/onboarding")
    async def onboarding(principal: Principal = Depends(principal_from)) -> dict:
        """What the first-visit tip offers, and the prompt it sends if accepted."""
        return {
            "roles": list(principal.roles),
            "guides": [
                {"role": role, "guide": text} for role, text in guides_for(principal)
            ],
            "prompt": onboarding_prompt(principal),
        }

    # --- Code changes (karag_engineer only) --------------------------------
    # An AI turn can only ever *propose*; applying is this explicit human step.

    @app.get("/v1/code/proposals")
    async def list_proposals(
        status: str | None = None, principal: Principal = Depends(principal_from)
    ) -> dict:
        return {
            "proposals": [
                p.to_dict(include_diff=False)
                for p in plat.code_changes.list(principal, status=status)
            ]
        }

    @app.get("/v1/code/proposals/{proposal_id}")
    async def get_proposal(
        proposal_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        return plat.code_changes.get(principal, proposal_id).to_dict()

    @app.post("/v1/code/proposals/{proposal_id}/apply")
    async def apply_proposal(
        proposal_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        return plat.code_changes.apply(principal, proposal_id).to_dict(include_diff=False)

    @app.post("/v1/code/proposals/{proposal_id}/discard")
    async def discard_proposal(
        proposal_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        return plat.code_changes.discard(principal, proposal_id).to_dict(include_diff=False)


    @app.get("/v1/audit")
    async def audit(principal: Principal = Depends(principal_from)) -> dict:
        if not principal.has_any_role(frozenset({"admin", "ceo"})):
            raise HTTPException(status_code=403, detail="admin role required")
        # Both the in-memory and the durable sink expose for_tenant(); a
        # write-only sink (JSONL, null) has no query path and says so.
        reader = getattr(plat.audit, "for_tenant", None)
        if reader is None:
            raise HTTPException(
                status_code=501, detail="this audit sink is write-only; query it at the source"
            )
        return {"events": [asdict(e) for e in reader(principal.tenant_id)]}

    @app.get("/v1/usage")
    async def usage(principal: Principal = Depends(principal_from)) -> dict:
        t = plat.usage.tenant_totals(principal.tenant_id)
        # §15's dashboard is "usage *and cost*": price the per-model token
        # totals at read time so a corrected price list reprices history.
        by_model = plat.usage.tenant_by_model(principal.tenant_id)
        breakdown, total_usd, unpriced = [], 0.0, []
        for model, totals in sorted(by_model.items()):
            cost = prices.cost(model, totals.input_tokens, totals.output_tokens)
            total_usd += cost.total_usd
            if not cost.priced and totals.total_tokens:
                unpriced.append(model)
            breakdown.append({
                "model": model or "unknown",
                "requests": totals.requests,
                "input_tokens": totals.input_tokens,
                "output_tokens": totals.output_tokens,
                "total_tokens": totals.total_tokens,
                "cost": cost.to_dict(),
            })
        return {"tenant_id": principal.tenant_id, "requests": t.requests,
                "input_tokens": t.input_tokens, "output_tokens": t.output_tokens,
                "total_tokens": t.total_tokens,
                "cost_usd": round(total_usd, 6),
                "unpriced_models": unpriced,
                "by_model": breakdown,
                "budget": plat.guard.status(principal.tenant_id) if plat.guard else None,
                "events": plat.usage.tenant_events(principal.tenant_id)}
