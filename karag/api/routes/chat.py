"""Asking: one-shot questions, no-code assistants and durable chats (incl. SSE streaming)."""

from __future__ import annotations

import asyncio
import urllib.parse
import json

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse

from ...assistants import AssistantNotFound, can_manage
from ...conversations import Conversation, StoredMessage
from ...domain import new_id, Principal
from ...errors import AccessDenied
from ...llm.base import ImagePart
from ..common import (
    ApiContext,
    AskRequest,
    AssistantRequest,
    AssistantUpdateRequest,
    ChatCreateRequest,
    ChatRenameRequest,
    log,
    _answer_payload,
    _assistant_payload,
    _failure_text,
    _history_messages,
    _resolve_attachments,
    _status_for,
    _stored_answer,
)


# Files larger than this are handed over once and not kept with the chat.
_MAX_KEPT_FILE_BYTES = 25 * 1024 * 1024


def mount(app: FastAPI, ctx: ApiContext) -> None:
    plat = ctx.plat
    principal_from = ctx.principal_from
    language_for = ctx.language_for

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

    @app.get("/v1/chats/{chat_id}/files/{file_id}")
    async def chat_file(
        chat_id: str, file_id: str, principal: Principal = Depends(principal_from)
    ) -> Response:
        """A file an answer in this chat generated — only for the chat's owner."""
        found = plat.conversations.get_file(
            (principal.tenant_id, principal.user_id), chat_id, file_id
        )
        if found is None:
            raise HTTPException(status_code=404, detail="file not found")
        filename, mime, data = found
        quoted = urllib.parse.quote(filename)
        return Response(
            content=data,
            media_type=mime or "application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
                "Cache-Control": "private, no-store",
            },
        )

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

        stored = _stored_answer(answer)
        # Generated files are kept with the chat (up to a size cap), so the
        # history can hand them over again after a reload.
        for summary, artifact in zip(stored.get("artifacts", []), answer.artifacts):
            if len(artifact.content) <= _MAX_KEPT_FILE_BYTES:
                file_id = new_id("file")
                if plat.conversations.put_file(owner, conv.id, file_id, artifact.filename,
                                               artifact.mime, artifact.content):
                    summary["file_id"] = file_id
        plat.conversations.append(
            owner,
            conv.id,
            StoredMessage(role="assistant", text=answer.text, answer=stored),
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
