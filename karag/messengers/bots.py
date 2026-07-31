"""Inbound messenger bots: map a chat sender to a Principal and answer them.

This is the *inbound* counterpart to the outbound notifiers in
:mod:`karag.alerts`. A registered employee can DM the company's Telegram /
WhatsApp bot and get the same RBAC-governed answer the web console would give —
every query still runs through the orchestrator under *their* Principal, so the
messenger surface can never read past what that person is allowed to see.

Fail-closed: an unrecognized sender is never processed. There is no anonymous
access to the knowledge or data planes over chat.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from ..assistants import AssistantService
from ..domain import Answer, Principal
from ..errors import KaragError
from ..orchestrator import Orchestrator
from .inbound import InboundMessage

_UNREGISTERED = (
    "This number/account isn't linked to a KARAG identity. "
    "Ask your administrator to register you."
)


@dataclass(frozen=True)
class SenderBinding:
    """What a chat sender maps to: who they are, and an optional bound assistant."""

    principal: Principal
    assistant_id: str | None = None
    # auto | ru | tg | en — a messenger user rarely gets to pick in a UI, so the
    # binding carries it (§2: the platform answers in Russian and Tajik).
    language: str | None = None


class SenderResolver(Protocol):
    def resolve(self, platform: str, sender_id: str) -> SenderBinding | None: ...


class InMemorySenderResolver:
    """Map ``(platform, sender_id)`` to a binding; loadable from the environment.

    ``KARAG_MESSENGER_SENDERS`` is a comma-separated list of
    ``platform:sender_id:tenant:user:role1|role2[:assistant_id[:language]]``
    entries, e.g.

        KARAG_MESSENGER_SENDERS="telegram:12345:koinoti:ceo1:ceo,
                                 whatsapp:15550001111:koinoti:hr1:hr:asst_help:tg"
    """

    def __init__(self, bindings: dict[tuple[str, str], SenderBinding] | None = None) -> None:
        self._bindings = bindings or {}

    def add(self, platform: str, sender_id: str, binding: SenderBinding) -> None:
        self._bindings[(platform, sender_id)] = binding

    def resolve(self, platform: str, sender_id: str) -> SenderBinding | None:
        return self._bindings.get((platform, sender_id))

    @classmethod
    def from_env(cls, var: str = "KARAG_MESSENGER_SENDERS") -> "InMemorySenderResolver":
        bindings: dict[tuple[str, str], SenderBinding] = {}
        for entry in os.environ.get(var, "").split(","):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split(":")
            if len(parts) < 5:
                continue
            platform, sender_id, tenant, user, roles = parts[:5]
            assistant_id = parts[5] if len(parts) > 5 and parts[5] else None
            language = parts[6].strip() if len(parts) > 6 and parts[6].strip() else None
            principal = Principal(
                tenant_id=tenant,
                user_id=user,
                roles=tuple(r for r in roles.split("|") if r),
            )
            bindings[(platform.strip(), sender_id.strip())] = SenderBinding(
                principal=principal, assistant_id=assistant_id, language=language
            )
        return cls(bindings)


def format_reply(answer: Answer) -> str:
    """Render an :class:`Answer` as a plain-text chat reply (no file bytes).

    Citations are named so the reader can trust the source; generated Office
    files are mentioned by name but not attached here.
    """
    lines = [answer.text or "(no answer)"]
    if answer.citations:
        titles = ", ".join(dict.fromkeys(c.title for c in answer.citations))
        lines.append(f"Sources: {titles}")
    if answer.artifacts:
        names = ", ".join(a.filename for a in answer.artifacts)
        lines.append(f"Attached (available in the console): {names}")
    return "\n\n".join(lines)


class BotService:
    """Turn an :class:`InboundMessage` into a reply, under the sender's authority."""

    def __init__(
        self,
        orchestrator: Orchestrator,
        assistant_service: AssistantService,
        resolver: SenderResolver,
        *,
        unregistered_message: str = _UNREGISTERED,
    ) -> None:
        self._orchestrator = orchestrator
        self._assistants = assistant_service
        self._resolver = resolver
        self._unregistered = unregistered_message

    async def handle(self, message: InboundMessage) -> str:
        binding = self._resolver.resolve(message.platform, message.sender_id)
        if binding is None:  # fail closed: unknown sender is never processed
            return self._unregistered
        if binding.assistant_id:
            try:
                answer = await self._assistants.ask(
                    binding.principal, binding.assistant_id, message.text,
                    language=binding.language,
                )
            except KaragError:
                answer = await self._orchestrator.ask(
                    binding.principal, message.text, language=binding.language
                )
        else:
            answer = await self._orchestrator.ask(
                binding.principal, message.text, language=binding.language
            )
        return format_reply(answer)
