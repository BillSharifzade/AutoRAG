"""Per-request device/identity context for audit enrichment.

The audit trail is written deep in the stack (ingest, retrieve, skill, ask),
far from the HTTP layer that actually knows *where* a request came from. Rather
than thread request metadata through every call, the API layer stashes it in a
:class:`contextvars.ContextVar` for the duration of the request; the audit sink
reads it back when it records an event.

Only what HTTP actually exposes is captured: the client IP (honouring a proxy's
``X-Forwarded-For``), the User-Agent string, and the caller's roles. A client's
MAC address / hardware identity is deliberately absent — it never travels beyond
the local network segment and is not available to a remote web server.
"""

from __future__ import annotations

import contextvars
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .audit import AuditEvent

_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "karag_request_ctx", default={}
)


def set_request_context(
    *, ip: str = "", user_agent: str = "", roles: tuple[str, ...] = ()
) -> None:
    _ctx.set({"ip": ip, "user_agent": user_agent, "roles": tuple(roles)})


def clear_request_context() -> None:
    _ctx.set({})


def current_request_context() -> dict:
    return _ctx.get()


def mark_untrusted_content(source: str) -> None:
    """Record that this turn's context contains content KARAG did not author.

    Retrieved document passages, uploaded files and tool output are *data*, and
    the system prompt says so — but a source-code edit is too consequential to
    rest on the model having obeyed that instruction. The orchestrator marks the
    turn whenever such content is present, and the code-change guard refuses
    outright, so a sentence buried in an uploaded PDF cannot talk the platform
    into rewriting itself.
    """
    ctx = dict(_ctx.get())
    sources = set(ctx.get("untrusted_sources", ()))
    sources.add(source)
    ctx["untrusted_sources"] = tuple(sorted(sources))
    _ctx.set(ctx)


def untrusted_sources() -> tuple[str, ...]:
    """Which kinds of untrusted content this turn pulled in, if any."""
    return tuple(_ctx.get().get("untrusted_sources", ()))


def reset_source_markers() -> None:
    """Start a fresh citation numbering for this turn."""
    ctx = dict(_ctx.get())
    ctx["source_marker"] = 0
    _ctx.set(ctx)


def next_source_marker(prefix: str = "W") -> str:
    """The next citation marker for a source a *skill* brought in.

    Retrieved documents are numbered ``[1]``, ``[2]``… by the orchestrator
    before the model sees them. A skill that fetches its own sources cannot
    know how many of those there were, so it numbers into a separate series —
    ``[W1]``, ``[W2]`` — which can never collide and still reads as a citation.
    Per-request, because the counter lives in the same contextvar as the rest
    of the turn's state.
    """
    ctx = dict(_ctx.get())
    n = int(ctx.get("source_marker", 0)) + 1
    ctx["source_marker"] = n
    _ctx.set(ctx)
    return f"[{prefix}{n}]"


def enrich_event(event: "AuditEvent") -> "AuditEvent":
    """Fill an event's device/role fields from the active request, if unset."""
    ctx = _ctx.get()
    if not ctx:
        return event
    updates: dict = {}
    if not event.ip and ctx.get("ip"):
        updates["ip"] = ctx["ip"]
    if not event.user_agent and ctx.get("user_agent"):
        updates["user_agent"] = ctx["user_agent"]
    if not event.roles and ctx.get("roles"):
        updates["roles"] = ctx["roles"]
    return replace(event, **updates) if updates else event
