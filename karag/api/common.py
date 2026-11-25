"""Shared pieces of the HTTP layer: request models, attachment handling,
chat-history helpers and the per-app context the route modules receive."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

import base64
import logging
from dataclasses import asdict

import os

from fastapi import (
    HTTPException,
    Request,
)
from pydantic import BaseModel

log = logging.getLogger("karag.api")

from ..assistants import can_manage
from ..conversations import Conversation, StoredMessage
from ..scheduler import AlertScheduler
from ..domain import Answer, DataClass, Principal
from ..errors import (
    AccessDenied,
    BudgetExceeded,
    RateLimited,
    GenerationError,
    KaragError,
    NotFoundError,
    ValidationError,
)
from ..llm.base import ChatMessage, MsgRole
from ..factory import Platform
from ..ingestion.readers import UnsupportedFormat, extract_text
from ..llm.base import ImagePart
from ..llm.transcribe import OpenAITranscriber, sniff_audio_name
from ..messengers.bots import BotService
from ..pricing import PriceList
from ..skills.agent_skill import SkillResource


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
    # either or both; an explicit null budget removes the cap
    active: bool | None = None
    monthly_budget_usd: float | None = None


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
    if isinstance(exc, (RateLimited, BudgetExceeded)):
        return 429
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


@dataclass
class ApiContext:
    """What every route module needs from :func:`karag.api.app.create_app`."""

    plat: Platform
    principal_from: Callable[..., Awaitable[Principal]]
    language_for: Callable[..., str]
    prices: PriceList
    scheduler: AlertScheduler
    bot_svc: BotService
