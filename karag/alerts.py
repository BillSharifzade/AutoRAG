"""Proactive alerts — the system watches a skill and notifies when a rule fires.

An :class:`AlertRule` runs a verified skill under a system principal on a
schedule; if the result meets a condition ("a batch is expiring", "an anomaly"),
the engine sends a message through a pluggable :class:`Notifier` (console, a
webhook to Telegram/WhatsApp/Slack, or a capturing sink for tests). Scheduling
itself is left to cron / a task runner calling ``run_once`` on a cadence.

Alerts execute skills through the same RBAC-checked executor, so a rule can only
ever read what its system principal is authorized to read.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .domain import Principal
from .skills.executor import SkillExecutor


@runtime_checkable
class Notifier(Protocol):
    async def notify(self, message: str, context: dict) -> None: ...


class ConsoleNotifier:
    async def notify(self, message: str, context: dict) -> None:
        print(f"[ALERT] {message}  {context}")


class CapturingNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []

    async def notify(self, message: str, context: dict) -> None:
        self.messages.append((message, context))


class WebhookNotifier:
    """POST the alert to an HTTPS endpoint (e.g. a Telegram/Slack bridge)."""

    def __init__(self, url: str, *, timeout_s: float = 10.0) -> None:
        self.url = url
        self.timeout_s = timeout_s

    async def notify(self, message: str, context: dict) -> None:
        import httpx  # noqa: PLC0415

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(self.url, json={"message": message, "context": context})
            resp.raise_for_status()


class TelegramNotifier:
    """Send alerts to a Telegram chat via the Bot API.

    Request building is a pure method so it is unit-testable without a token or
    network; ``notify`` performs the POST (lazy ``httpx``).
    """

    def __init__(self, bot_token: str, chat_id: str, *, timeout_s: float = 10.0) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout_s = timeout_s

    def _url(self) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def _payload(self, message: str) -> dict:
        return {"chat_id": self.chat_id, "text": message}

    async def notify(self, message: str, context: dict) -> None:
        import httpx  # noqa: PLC0415

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(self._url(), json=self._payload(message))
            resp.raise_for_status()


class WhatsAppNotifier:
    """Send alerts via the WhatsApp Cloud API (Meta Graph)."""

    def __init__(
        self,
        phone_number_id: str,
        to: str,
        access_token: str,
        *,
        api_version: str = "v20.0",
        timeout_s: float = 10.0,
    ) -> None:
        self.phone_number_id = phone_number_id
        self.to = to
        self.access_token = access_token
        self.api_version = api_version
        self.timeout_s = timeout_s

    def _url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _payload(self, message: str) -> dict:
        return {
            "messaging_product": "whatsapp",
            "to": self.to,
            "type": "text",
            "text": {"body": message},
        }

    async def notify(self, message: str, context: dict) -> None:
        import httpx  # noqa: PLC0415

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(
                self._url(), headers=self._headers(), json=self._payload(message)
            )
            resp.raise_for_status()


@dataclass
class AlertRule:
    name: str
    principal: Principal  # the system identity the rule runs as
    skill_name: str
    arguments: dict = field(default_factory=dict)
    # condition receives the skill's result.data and returns True to fire.
    condition: Callable[[object], bool] = lambda data: bool(data)
    # build the human message from the data; defaults to a generic line.
    message: Callable[[object], str] | None = None


class AlertEngine:
    def __init__(self, executor: SkillExecutor, notifier: Notifier) -> None:
        self._executor = executor
        self._notifier = notifier

    async def run_once(self, rule: AlertRule) -> bool:
        """Execute the rule's skill; notify if the condition fires. Returns fired."""
        result = await self._executor.execute(
            rule.principal, rule.skill_name, rule.arguments
        )
        if not rule.condition(result.data):
            return False
        msg = (
            rule.message(result.data)
            if rule.message
            else f"Alert '{rule.name}' fired for tenant {rule.principal.tenant_id}"
        )
        await self._notifier.notify(
            msg,
            {
                "rule": rule.name,
                "tenant_id": rule.principal.tenant_id,
                "skill": rule.skill_name,
                "query_shown": result.query_shown,
                "data": result.data,
            },
        )
        return True

    async def run_all(self, rules: list[AlertRule]) -> list[str]:
        """Run every rule once; return the names of those that fired."""
        fired: list[str] = []
        for rule in rules:
            if await self.run_once(rule):
                fired.append(rule.name)
        return fired
