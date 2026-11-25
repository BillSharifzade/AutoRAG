"""FastAPI application — the HTTP surface, built by an app factory for testing.

Endpoints (all /v1/* except the webhooks require a bearer token):
  GET  /health
  POST /v1/ingest             (ingest role) — add a text document
  POST /v1/ingest/file        (ingest role) — upload .docx/.xlsx/.pptx/.pdf/.csv/…
  POST /v1/ask                — knowledge + data answer
  POST /v1/assistants         — create a no-code assistant
  GET  /v1/assistants         — list this tenant's assistants (full config)
  GET  /v1/assistants/{id}    — one assistant's full config
  PUT  /v1/assistants/{id}    — edit an assistant
  POST /v1/assistants/{id}/ask
  GET  /v1/audit              (admin) — this tenant's audit events
  GET  /v1/usage              — this tenant's usage totals
  POST /v1/webhooks/telegram  — inbound Telegram bot (sender-authenticated)
  GET  /v1/webhooks/whatsapp  — WhatsApp verification handshake
  POST /v1/webhooks/whatsapp  — inbound WhatsApp bot (sender-authenticated)

Artifacts (generated Office files) are returned base64-encoded so a browser/UI
can offer them for download; their bytes never went through the model.
"""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from ..alerts import ConsoleNotifier
from ..domain import Principal
from ..errors import (
    AccessDenied,
    BudgetExceeded,
    GenerationError,
    KaragError,
    NotFoundError,
    RateLimited,
    ValidationError,
)
from ..factory import build_platform, Platform
from ..messengers.bots import BotService, InMemorySenderResolver
from ..pricing import PriceList
from ..request_context import set_request_context
from ..scheduler import AlertScheduler
from ..tenants import validate_language
from .security import InMemoryResolver, PrincipalResolver
from .common import (  # noqa: F401 — re-exported for tests
    ApiContext,
    log,
    _client_ip,
    _HISTORY_CHARS,
    _history_messages,
)
from ..tenants import ensure_config_tenants
from .routes import admin as admin_routes
from .routes import chat as chat_routes
from .routes import documents as documents_routes
from .routes import platform as platform_routes
from .routes import skills as skills_routes
from .routes import webhooks as webhook_routes


def create_app(
    platform: Platform | None = None,
    resolver: PrincipalResolver | None = None,
    bot: BotService | None = None,
) -> FastAPI:
    plat = platform or build_platform()
    res = resolver or InMemoryResolver.from_env()
    prices = PriceList.from_env()
    # Rules are evaluated by a scheduler process (scripts/run_scheduler.py);
    # this instance exists so an operator can also fire one on demand.
    scheduler = AlertScheduler(
        plat.alerts, plat.executor, ConsoleNotifier(), audit=plat.audit
    )
    bot_svc = bot or BotService(
        plat.orchestrator, plat.assistant_service, InMemorySenderResolver.from_env()
    )
    app = FastAPI(title="KARAG", version="0.1.0")

    # Typed domain errors map to HTTP once, here, instead of being re-wrapped in
    # every endpoint. AccessDenied deliberately answers 403 with the reason: the
    # authoring API is used by trusted staff who need to know *why* a grant was
    # refused. The model-facing paths still disclose nothing (SkillNotFound).
    @app.exception_handler(AccessDenied)
    async def _denied(_request: Request, exc: AccessDenied):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(ValidationError)
    async def _invalid(_request: Request, exc: ValidationError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(NotFoundError)
    async def _missing(_request: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(RateLimited)
    async def _rate_limited(_request: Request, exc: RateLimited):
        return JSONResponse(
            status_code=429,
            content={"detail": str(exc), "code": "rate_limited"},
            headers={"Retry-After": str(exc.retry_after)},
        )

    @app.exception_handler(BudgetExceeded)
    async def _over_budget(_request: Request, exc: BudgetExceeded):
        return JSONResponse(
            status_code=429, content={"detail": str(exc), "code": "budget_exceeded"}
        )

    @app.exception_handler(GenerationError)
    async def _provider_down(_request: Request, exc: GenerationError):
        log.warning("generation failed: %s", exc)
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(KaragError)
    async def _platform_error(_request: Request, exc: KaragError):
        # Anything typed but not mapped above is still a JSON error with a
        # reason, never a bare 500 page.
        log.exception("unhandled platform error")
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    # Async on purpose: a plain ``def`` dependency runs in a worker thread with
    # a *copy* of the request context, so the ContextVar set below would be
    # lost before the endpoint ran — every audit event then recorded an empty
    # address and role. That was a real bug.
    async def principal_from(
        request: Request, authorization: str = Header(default="")
    ) -> Principal:
        if not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        try:
            principal = res.resolve(token)
        except AccessDenied as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        # Stash device/identity context so audit events written downstream can
        # record where the request came from (IP, user-agent) and as whom.
        set_request_context(
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent", ""),
            roles=principal.roles,
        )
        return principal

    def language_for(principal: Principal, requested: str | None) -> str:
        """Answer language: explicit request → stored account/tenant → default.

        §2 sells RU/TJ as the differentiator, so this has to resolve on every
        path (chat, assistant, bot), not just where a UI happens to pass a flag.
        """
        if requested and requested != "auto":
            validate_language(requested)
            return requested
        account = plat.directory.get_account(principal.tenant_id, principal.user_id)
        if account is not None and account.language != "auto":
            return account.language
        tenant = plat.directory.get_tenant(principal.tenant_id)
        if tenant is not None and tenant.default_language != "auto":
            return tenant.default_language
        return plat.settings.default_language

    config_principals = getattr(res, "config_principals", lambda: [])
    # A company that signs in with config tokens is a real tenant too.
    ensure_config_tenants(plat.directory, config_principals())
    ctx = ApiContext(
        plat=plat, principal_from=principal_from, language_for=language_for,
        prices=prices, scheduler=scheduler, bot_svc=bot_svc,
        config_principals=config_principals,
    )
    for module in (platform_routes, skills_routes, admin_routes, documents_routes,
                   chat_routes, webhook_routes):
        module.mount(app, ctx)

    # Guided integrations (Data page): API sources + connected databases.
    from .integrations import mount_integrations

    mount_integrations(app, plat, principal_from)

    return app


# Default app for `uvicorn karag.api.app:app`
app = create_app()
