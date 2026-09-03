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

import asyncio
import base64
import json
import logging
from dataclasses import asdict

import os

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

log = logging.getLogger("karag.api")

from ..alerts import ConsoleNotifier
from ..assistants import AssistantNotFound, can_manage
from ..audit import AuditEvent
from ..engineer.guard import ENGINEER_ROLE
from ..conversations import Conversation, StoredMessage
from ..scheduler import AlertScheduler
from ..selfknowledge.handbook import guides_for, onboarding_prompt
from ..knowledge.classify import suggest_data_class
from ..rbac import INGEST_ROLES, visible_classes
from ..domain import Answer, DataClass, Principal
from ..errors import (
    AccessDenied,
    GenerationError,
    KaragError,
    NotFoundError,
    ValidationError,
)
from ..llm.base import ChatMessage, MsgRole
from ..factory import Platform, build_platform
from ..ingestion.readers import UnsupportedFormat, extract_text
from ..llm.base import ImagePart
from ..llm.transcribe import OpenAITranscriber, sniff_audio_name
from ..messengers.bots import BotService, InMemorySenderResolver
from ..messengers.inbound import parse_telegram_update, parse_whatsapp_update
from ..pricing import PriceList
from ..skills.agent_skill import SkillResource, parse_skill_md, render_skill_md
from ..skills.catalog import can_author
from ..tenants import LANGUAGES, validate_language
from ..request_context import set_request_context
from .security import InMemoryResolver, PrincipalResolver


def _client_ip(request: Request) -> str:
    """Best-effort client IP: first hop of X-Forwarded-For, else the socket peer.

    Behind a reverse proxy the real client is the left-most XFF entry; directly
    connected, it's request.client.host (127.0.0.1 in local dev — reported
    honestly rather than faked)."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    real = request.headers.get("x-real-ip", "")
    if real:
        return real.strip()
    return request.client.host if request.client else ""


class IngestRequest(BaseModel):
    title: str
    text: str
    data_class: DataClass = DataClass.OPERATIONAL
    source_uri: str | None = None


class AskAttachment(BaseModel):
    kind: str  # image | file | audio
    filename: str = ""
    media_type: str = ""
    data_b64: str


class AskRequest(BaseModel):
    query: str = ""
    attachments: list[AskAttachment] = []
    # auto | ru | tg | en — overrides the caller's stored preference for one turn
    language: str | None = None


_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_MAX_ATTACHMENTS = 8
_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
_MAX_FILE_TEXT_CHARS = 20_000


async def _resolve_attachments(req: AskRequest) -> tuple[str, list[ImagePart]]:
    """Turn attachments into model inputs: images pass through as vision blocks,
    files contribute extracted text, voice notes are transcribed. Returns the
    final query text and the image parts."""
    if len(req.attachments) > _MAX_ATTACHMENTS:
        raise HTTPException(status_code=413, detail="too many attachments")

    query = req.query.strip()
    images: list[ImagePart] = []
    extras: list[str] = []

    for att in req.attachments:
        try:
            raw = base64.b64decode(att.data_b64)
        except Exception:
            raise HTTPException(status_code=400, detail=f"bad base64 in {att.filename!r}")
        if len(raw) > _MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413, detail=f"{att.filename!r} is too large")

        if att.kind == "image":
            if att.media_type not in _IMAGE_TYPES:
                raise HTTPException(
                    status_code=415, detail=f"unsupported image type {att.media_type!r}"
                )
            images.append(ImagePart(media_type=att.media_type, data_b64=att.data_b64))
        elif att.kind == "file":
            try:
                text = extract_text(att.filename, raw)
            except UnsupportedFormat as exc:
                raise HTTPException(status_code=415, detail=str(exc))
            if len(text) > _MAX_FILE_TEXT_CHARS:
                text = text[:_MAX_FILE_TEXT_CHARS] + "\n… (truncated)"
            extras.append(f"Attached file {att.filename!r}:\n{text}")
        elif att.kind == "audio":
            transcriber = OpenAITranscriber(
                api_key=os.environ.get("OPENAI_API_KEY"),
                model=os.environ.get("KARAG_OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"),
            )
            try:
                transcript = await transcriber.transcribe(
                    raw, sniff_audio_name(raw, att.filename or "voice-note.webm")
                )
            except KaragError as exc:
                raise HTTPException(status_code=502, detail=str(exc))
            if transcript:
                query = f"{query}\n\n{transcript}".strip() if query else transcript
            elif not query and len(req.attachments) == 1:
                raise HTTPException(
                    status_code=422,
                    detail="The voice note didn't contain any recognizable speech.",
                )
        else:
            raise HTTPException(status_code=400, detail=f"unknown attachment kind {att.kind!r}")

    if extras:
        query = "\n\n".join([query, *extras]).strip() if query else "\n\n".join(extras)
    if not query and images:
        query = "Describe the attached image(s)."
    if not query:
        raise HTTPException(status_code=400, detail="empty query")
    return query, images


class AssistantRequest(BaseModel):
    name: str
    instruction: str = ""
    # null = every skill the person may already use; [] = documents only;
    # a list = exactly those (still intersected with what the person may use)
    allowed_skill_names: list[str] | None = None
    # accepted for compatibility — answers always follow the question's language
    language: str = "auto"


class AssistantUpdateRequest(BaseModel):
    """Every field optional: what is omitted stays as it was."""

    name: str | None = None
    instruction: str | None = None
    allowed_skill_names: list[str] | None = None
    language: str | None = None


class ConnectorRequest(BaseModel):
    name: str
    kind: str  # sql_sqlite | sql_postgres | rest
    config: dict = {}
    row_limit: int = 1000
    timeout_s: float = 5.0


class SkillResourceRequest(BaseModel):
    path: str
    content: str = ""


class SkillDefinitionRequest(BaseModel):
    name: str
    description: str
    kind: str = "sql"  # sql | rest | agent
    # An agent skill reaches no data source, so it names no connector.
    connector_id: str = ""
    param_schema: dict | None = None
    sql: str = ""
    path: str = ""
    instructions: str = ""
    resources: list[SkillResourceRequest] = []
    required_data_class: DataClass = DataClass.OPERATIONAL
    required_roles: list[str] = []
    row_limit: int | None = None
    inject_tenant: bool = True
    shared: bool = False
    # None on update = leave as is; a disabled skill stays stored but is not
    # offered to the model
    enabled: bool | None = None

    def resource_tuple(self) -> tuple[SkillResource, ...]:
        return tuple(SkillResource(path=r.path, content=r.content) for r in self.resources)


class SkillTestRequest(BaseModel):
    arguments: dict = {}


class SkillMarkdownRequest(BaseModel):
    """A pasted SKILL.md, to be split into its fields before authoring."""

    text: str


class LibraryImportRequest(BaseModel):
    connector_id: str = ""
    name: str | None = None


class AlertRequest(BaseModel):
    name: str
    skill_name: str
    arguments: dict = {}
    interval_s: float = 3600.0
    condition: str = "rows_returned"
    condition_config: dict = {}
    message_template: str = ""
    channel: str = "default"
    run_as_roles: list[str] | None = None


class AlertEnabledRequest(BaseModel):
    enabled: bool


class TenantRequest(BaseModel):
    id: str
    name: str
    default_language: str = "auto"


class TenantActiveRequest(BaseModel):
    active: bool


class AccountRequest(BaseModel):
    user_id: str
    display_name: str = ""
    roles: list[str] = ["employee"]
    language: str = "auto"


class AccountUpdateRequest(BaseModel):
    roles: list[str] | None = None
    active: bool | None = None


class LanguageRequest(BaseModel):
    language: str


class ChatCreateRequest(BaseModel):
    title: str = ""
    assistant_id: str | None = None


class ChatRenameRequest(BaseModel):
    title: str


# How many prior messages of a thread to replay as model context, and how much
# text at most — a message cap alone lets twelve long answers fill the prompt.
_HISTORY_LIMIT = 24
_HISTORY_CHARS = 40_000
# Stored turns that are not part of the conversation's substance.
_NON_CONTENT_PLANES = ("error", "stopped")


def _history_messages(conv: Conversation) -> list[ChatMessage]:
    """Prior turns as neutral chat messages for conversational memory.

    Newest first until the character budget is spent, so what the model
    forgets is always the oldest part of a long thread. Failed and stopped
    turns are not replayed: an error message is not something to build on.
    """
    picked: list[StoredMessage] = []
    total = 0
    for m in reversed(conv.messages[-_HISTORY_LIMIT:]):
        if not m.text.strip():
            continue
        if m.answer and m.answer.get("plane") in _NON_CONTENT_PLANES:
            continue
        total += len(m.text)
        if total > _HISTORY_CHARS and picked:
            break
        picked.append(m)
    picked.reverse()
    # The replay must start with the user, or the provider rejects the turn order.
    while picked and picked[0].role != "user":
        picked.pop(0)
    return [
        ChatMessage(
            role=MsgRole.USER if m.role == "user" else MsgRole.ASSISTANT,
            content=m.text,
        )
        for m in picked
    ]


def _failure_text(exc: BaseException) -> str:
    """What a failed turn leaves in the thread — a reason, not a stack trace."""
    if isinstance(exc, GenerationError):
        return "The model could not be reached for this message. Please try again."
    if isinstance(exc, AccessDenied):
        return "This request touched something outside your access."
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return "The answer could not be produced. Please try again."


def _status_for(exc: BaseException) -> int:
    if isinstance(exc, HTTPException):
        return exc.status_code
    if isinstance(exc, AccessDenied):
        return 403
    if isinstance(exc, ValidationError):
        return 400
    if isinstance(exc, NotFoundError):
        return 404
    if isinstance(exc, GenerationError):
        return 502
    return 500


def _stored_answer(answer: Answer) -> dict:
    """Answer provenance for persistence — artifact summaries, never bytes."""
    return {
        "text": answer.text,
        "citations": [
            {
                "marker": c.marker,
                "document_id": c.document_id,
                "chunk_id": c.chunk_id,
                "title": c.title,
                "source_uri": c.source_uri,
                "snippet": c.snippet,
            }
            for c in answer.citations
        ],
        "plane": answer.plane,
        "skills_used": list(answer.skills_used),
        "queries_shown": list(answer.queries_shown),
        "artifacts": [a.to_summary() for a in answer.artifacts],
        "diagnostics": answer.diagnostics,
    }


def _assistant_payload(a, principal: Principal | None = None) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "instruction": a.instruction,
        "allowed_skill_names": (
            sorted(a.allowed_skill_names) if a.allowed_skill_names is not None else None
        ),
        "language": a.language,
        "created_by": a.created_by,
        "can_edit": can_manage(principal, a) if principal is not None else False,
    }


def _answer_payload(answer: Answer) -> dict:
    payload = asdict(answer)
    payload["artifacts"] = [
        {
            "filename": a.filename,
            "mime": a.mime,
            "size_bytes": len(a.content),
            "content_base64": base64.b64encode(a.content).decode("ascii"),
        }
        for a in answer.artifacts
    ]
    return payload


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
        return {
            "tenants": [t.to_dict() for t in plat.directory_service.list_tenants(principal)]
        }

    @app.patch("/v1/tenants/{tenant_id}")
    async def set_tenant_active(
        tenant_id: str,
        req: TenantActiveRequest,
        principal: Principal = Depends(principal_from),
    ) -> dict:
        if not plat.directory_service.set_tenant_active(principal, tenant_id, req.active):
            raise HTTPException(status_code=404, detail="tenant not found")
        return {"id": tenant_id, "active": req.active}

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
        return {
            "accounts": [
                a.to_public_dict() for a in plat.directory_service.list_accounts(principal)
            ]
        }

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

    @app.post("/v1/ingest")
    async def ingest(req: IngestRequest, principal: Principal = Depends(principal_from)) -> dict:
        try:
            doc = await plat.ingestion.ingest_document(
                principal, title=req.title, text=req.text,
                data_class=req.data_class, source_uri=req.source_uri,
            )
        except AccessDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {
            "document_id": doc.id, "data_class": doc.data_class.value,
            "replaced": doc.metadata.get("replaced", []),
        }

    @app.post("/v1/ingest/file")
    async def ingest_file(
        file: UploadFile = File(...),
        data_class: DataClass = Form(DataClass.OPERATIONAL),
        principal: Principal = Depends(principal_from),
    ) -> dict:
        data = await file.read()
        try:
            doc = await plat.ingestion.ingest_file(
                principal, filename=file.filename or "upload", data=data,
                data_class=data_class,
            )
        except AccessDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except UnsupportedFormat as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        return {
            "document_id": doc.id, "data_class": doc.data_class.value,
            "replaced": doc.metadata.get("replaced", []),
        }

    @app.get("/v1/documents")
    async def list_documents(principal: Principal = Depends(principal_from)) -> dict:
        """The knowledge catalogue, filtered exactly like retrieval is.

        A title is a disclosure in itself, so an HR user listing documents does
        not see that a financial one exists.
        """
        docs = await plat.store.list_documents(
            tenant_id=principal.tenant_id, allowed_classes=visible_classes(principal)
        )
        return {"documents": [d.to_dict() for d in docs]}

    @app.delete("/v1/documents/{document_id}")
    async def delete_document(
        document_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        if not principal.has_any_role(INGEST_ROLES):
            raise HTTPException(status_code=403, detail="ingest role required")
        # Only documents the caller can actually see are deletable — otherwise
        # deletion becomes an oracle for what exists in a class you can't read.
        visible = {
            d.document_id
            for d in await plat.store.list_documents(
                tenant_id=principal.tenant_id, allowed_classes=visible_classes(principal)
            )
        }
        if document_id not in visible:
            raise HTTPException(status_code=404, detail="document not found")
        removed = await plat.store.delete_document(
            tenant_id=principal.tenant_id, document_id=document_id
        )
        plat.audit.record(AuditEvent(
            action="document_delete", tenant_id=principal.tenant_id,
            user_id=principal.user_id, decision="allow", resource=document_id,
            detail={"chunks": removed},
        ))
        return {"deleted": document_id, "chunks": removed}

    @app.post("/v1/documents/classify")
    async def classify_document(
        file: UploadFile = File(...),
        principal: Principal = Depends(principal_from),
    ) -> dict:
        """Propose a data class for an upload — advisory only (§7).

        Nothing is stored and nothing is ingested by this call. The uploader
        sees the suggestion and the terms behind it, then chooses.
        """
        data = await file.read()
        name = file.filename or "upload"
        try:
            text = extract_text(name, data)
        except UnsupportedFormat as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        return suggest_data_class(title=name, text=text, filename=name).to_dict()

    @app.post("/v1/ask")
    async def ask(req: AskRequest, principal: Principal = Depends(principal_from)) -> dict:
        query, images = await _resolve_attachments(req)
        answer = await plat.orchestrator.ask(
            principal, query, images=images or None,
            language=language_for(principal, req.language),
        )
        return _answer_payload(answer)

    @app.post("/v1/assistants")
    async def create_assistant(
        req: AssistantRequest, principal: Principal = Depends(principal_from)
    ) -> dict:
        if not req.name.strip():
            raise HTTPException(status_code=400, detail="an assistant needs a name")
        allowed = frozenset(req.allowed_skill_names) if req.allowed_skill_names is not None else None
        a = plat.assistants.create(
            principal, name=req.name.strip(), instruction=req.instruction,
            allowed_skill_names=allowed, language=req.language,
        )
        return _assistant_payload(a, principal)

    @app.get("/v1/assistants")
    async def list_assistants(principal: Principal = Depends(principal_from)) -> dict:
        return {"assistants": [
            _assistant_payload(a, principal) for a in plat.assistants.list_for(principal)
        ]}

    @app.get("/v1/assistants/{assistant_id}")
    async def get_assistant(
        assistant_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        return _assistant_payload(plat.assistants.get(principal, assistant_id), principal)

    @app.put("/v1/assistants/{assistant_id}")
    async def update_assistant(
        assistant_id: str,
        req: AssistantUpdateRequest,
        principal: Principal = Depends(principal_from),
    ) -> dict:
        """Partial update. ``allowed_skill_names`` keeps the create semantics:
        omitted = unchanged, null = every skill the person may use, [] =
        documents only, a list = exactly those."""
        current = plat.assistants.get(principal, assistant_id)  # 404 across tenants
        if not can_manage(principal, current):
            raise AccessDenied("only the person who made this assistant, or an administrator, can change it")
        sent = req.model_fields_set
        clear = "allowed_skill_names" in sent and req.allowed_skill_names is None
        allowed = (
            frozenset(req.allowed_skill_names)
            if "allowed_skill_names" in sent and req.allowed_skill_names is not None
            else None
        )
        if req.name is not None and not req.name.strip():
            raise HTTPException(status_code=400, detail="an assistant needs a name")
        a = plat.assistants.update(
            principal, assistant_id,
            name=req.name.strip() if req.name is not None else None,
            instruction=req.instruction,
            allowed_skill_names=allowed, clear_allowed=clear,
            language=req.language,
        )
        return _assistant_payload(a, principal)

    @app.delete("/v1/assistants/{assistant_id}")
    async def delete_assistant(
        assistant_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        current = plat.assistants.get(principal, assistant_id)  # 404s across tenants
        if not can_manage(principal, current):
            raise AccessDenied("only the person who made this assistant, or an administrator, can delete it")
        plat.assistants.delete(principal, assistant_id)
        return {"deleted": assistant_id}

    @app.post("/v1/assistants/{assistant_id}/ask")
    async def ask_assistant(
        assistant_id: str, req: AskRequest, principal: Principal = Depends(principal_from)
    ) -> dict:
        query, images = await _resolve_attachments(req)
        answer = await plat.assistant_service.ask(
            principal, assistant_id, query, images=images or None,
            language=language_for(principal, req.language),
        )
        return _answer_payload(answer)

    # --- Chat history (saved conversations, per principal) ----------------

    @app.get("/v1/chats")
    async def list_chats(principal: Principal = Depends(principal_from)) -> dict:
        owner = (principal.tenant_id, principal.user_id)
        return {"chats": [s.to_dict() for s in plat.conversations.list(owner)]}

    @app.post("/v1/chats")
    async def create_chat(
        req: ChatCreateRequest, principal: Principal = Depends(principal_from)
    ) -> dict:
        owner = (principal.tenant_id, principal.user_id)
        conv = plat.conversations.create(
            owner, title=req.title, assistant_id=req.assistant_id
        )
        return conv.to_dict()

    @app.get("/v1/chats/{chat_id}")
    async def get_chat(
        chat_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        owner = (principal.tenant_id, principal.user_id)
        conv = plat.conversations.get(owner, chat_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="chat not found")
        return conv.to_dict()

    @app.patch("/v1/chats/{chat_id}")
    async def rename_chat(
        chat_id: str,
        req: ChatRenameRequest,
        principal: Principal = Depends(principal_from),
    ) -> dict:
        owner = (principal.tenant_id, principal.user_id)
        if not plat.conversations.rename(owner, chat_id, req.title):
            raise HTTPException(status_code=404, detail="chat not found")
        conv = plat.conversations.get(owner, chat_id)
        return conv.to_dict() if conv else {"id": chat_id, "title": req.title}

    @app.delete("/v1/chats/{chat_id}")
    async def delete_chat(
        chat_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        owner = (principal.tenant_id, principal.user_id)
        if not plat.conversations.delete(owner, chat_id):
            raise HTTPException(status_code=404, detail="chat not found")
        return {"deleted": chat_id}

    async def _chat_turn(
        principal: Principal,
        conv: Conversation,
        req: AskRequest,
        query: str,
        images: list[ImagePart],
        on_event=None,
    ) -> dict:
        """One turn of a saved conversation, shared by the JSON and the
        streaming endpoint.

        The persona is never quietly dropped: a failure inside the assistant
        path is reported as a failure. The one exception is an assistant that
        has since been deleted — the thread then continues with the default
        persona and says so in the response (``assistant_missing``).

        Whatever happens after the user's message is stored, the thread ends
        up consistent: a failed or stopped turn leaves a short assistant note
        rather than an orphaned question.
        """
        owner = (principal.tenant_id, principal.user_id)
        history = _history_messages(conv)
        language = language_for(principal, req.language)

        display = req.query.strip() or query
        plat.conversations.append(
            owner,
            conv.id,
            StoredMessage(
                role="user",
                text=display,
                attachments=[
                    {"kind": a.kind, "filename": a.filename} for a in req.attachments
                ],
            ),
        )

        assistant_missing = False
        try:
            if conv.assistant_id:
                try:
                    answer = await plat.assistant_service.ask(
                        principal, conv.assistant_id, query,
                        images=images or None, history=history, language=language,
                        on_event=on_event,
                    )
                except AssistantNotFound:
                    assistant_missing = True
                    answer = await plat.orchestrator.ask(
                        principal, query, images=images or None, history=history,
                        language=language, on_event=on_event,
                    )
            else:
                answer = await plat.orchestrator.ask(
                    principal, query, images=images or None, history=history,
                    language=language, on_event=on_event,
                )
        except asyncio.CancelledError:
            plat.conversations.append(
                owner, conv.id,
                StoredMessage(
                    role="assistant", text="(stopped before an answer arrived)",
                    answer={"plane": "stopped"},
                ),
            )
            raise
        except Exception as exc:
            plat.conversations.append(
                owner, conv.id,
                StoredMessage(
                    role="assistant", text=_failure_text(exc),
                    answer={"plane": "error", "error": str(exc)[:500]},
                ),
            )
            raise

        plat.conversations.append(
            owner,
            conv.id,
            StoredMessage(
                role="assistant", text=answer.text, answer=_stored_answer(answer)
            ),
        )

        refreshed = plat.conversations.get(owner, conv.id)
        return {
            "answer": _answer_payload(answer),
            "title": refreshed.title if refreshed else conv.title,
            "updated_at": refreshed.updated_at if refreshed else None,
            "assistant_missing": assistant_missing,
        }

    @app.post("/v1/chats/{chat_id}/ask")
    async def chat_ask(
        chat_id: str, req: AskRequest, principal: Principal = Depends(principal_from)
    ) -> dict:
        owner = (principal.tenant_id, principal.user_id)
        conv = plat.conversations.get(owner, chat_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="chat not found")
        query, images = await _resolve_attachments(req)
        return await _chat_turn(principal, conv, req, query, images)

    @app.post("/v1/chats/{chat_id}/stream")
    async def chat_stream(
        chat_id: str, req: AskRequest, principal: Principal = Depends(principal_from)
    ):
        """The same turn as ``/ask``, delivered as Server-Sent Events.

        Events (one JSON object per ``data:`` line):
          status  {stage: retrieving|thinking}
          tool    {name, status: start|done|error}
          delta   {text}            — answer text as the model writes it
          done    {answer, title, updated_at, assistant_missing}
          error   {status, detail}

        Closing the connection cancels the turn server-side: nothing keeps
        running — or being billed — for a reader who has gone.
        """
        owner = (principal.tenant_id, principal.user_id)
        conv = plat.conversations.get(owner, chat_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="chat not found")
        query, images = await _resolve_attachments(req)

        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(event: dict) -> None:
            await queue.put(event)

        async def run() -> None:
            try:
                result = await _chat_turn(principal, conv, req, query, images, on_event)
                await queue.put({"type": "done", **result})
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — reported to the client
                if _status_for(exc) >= 500:
                    log.exception("chat turn failed")
                await queue.put({
                    "type": "error",
                    "status": _status_for(exc),
                    "detail": _failure_text(exc),
                })
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())

        async def events():
            try:
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

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
                "events": plat.usage.tenant_events(principal.tenant_id)}

    # --- Inbound messenger webhooks ---------------------------------------
    # Senders are authenticated by the bot's SenderResolver, not by a bearer
    # token; an unregistered sender is answered with a refusal and nothing runs.

    @app.post("/v1/webhooks/telegram")
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str = Header(default=""),
    ) -> dict:
        secret = os.environ.get("KARAG_TELEGRAM_WEBHOOK_SECRET")
        if secret and x_telegram_bot_api_secret_token != secret:
            raise HTTPException(status_code=403, detail="bad webhook secret")
        update = await request.json()
        msg = parse_telegram_update(update)
        if msg is None:
            return {"ok": True}
        reply = await bot_svc.handle(msg)
        # Telegram sends the reply if the webhook responds with a method call.
        return {"method": "sendMessage", "chat_id": msg.chat_id, "text": reply}

    @app.get("/v1/webhooks/whatsapp", response_class=PlainTextResponse)
    async def whatsapp_verify(
        mode: str = Query("", alias="hub.mode"),
        token: str = Query("", alias="hub.verify_token"),
        challenge: str = Query("", alias="hub.challenge"),
    ) -> str:
        expected = os.environ.get("KARAG_WHATSAPP_VERIFY_TOKEN")
        if mode == "subscribe" and expected and token == expected:
            return challenge
        raise HTTPException(status_code=403, detail="verification failed")

    @app.post("/v1/webhooks/whatsapp")
    async def whatsapp_webhook(request: Request) -> dict:
        payload = await request.json()
        replies = []
        for msg in parse_whatsapp_update(payload):
            reply = await bot_svc.handle(msg)
            replies.append({"to": msg.chat_id, "text": reply})
        return {"replies": replies}

    # --- guided integrations: API sources and databases ---------------------
    from .integrations import mount_integrations  # noqa: PLC0415

    mount_integrations(app, plat, principal_from)

    return app


# Default app for `uvicorn karag.api.app:app`
app = create_app()
