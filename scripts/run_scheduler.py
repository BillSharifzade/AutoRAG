"""Run the proactive-alert scheduler as a long-lived process.

This is the process §15 assumes exists: "the system writes to the manager"
without anyone asking. It evaluates every stored alert rule on its own cadence
and delivers through whichever notifier the rule names.

    set -a; source .env; set +a
    PYTHONPATH=. .venv/bin/python scripts/run_scheduler.py

Channels are configured from the environment; a rule's ``channel`` picks one:
    KARAG_ALERT_TELEGRAM_TOKEN / KARAG_ALERT_TELEGRAM_CHAT  -> "telegram"
    KARAG_ALERT_WEBHOOK_URL                                 -> "webhook"
Console output is always available as "default".
"""

from __future__ import annotations

import asyncio
import os
import signal

from karag.alerts import ConsoleNotifier, TelegramNotifier, WebhookNotifier
from karag.config import Settings
from karag.factory import build_platform
from karag.scheduler import AlertScheduler
from karag.skills.authoring import authoring_skills
from karag.skills.registry import SkillRegistry
from karag.skills.samples import sales_by_store_skill, sales_report_skill


def build_notifiers() -> dict:
    notifiers = {"default": ConsoleNotifier(), "console": ConsoleNotifier()}
    token = os.environ.get("KARAG_ALERT_TELEGRAM_TOKEN")
    chat = os.environ.get("KARAG_ALERT_TELEGRAM_CHAT")
    if token and chat:
        notifiers["telegram"] = TelegramNotifier(token, chat)
    url = os.environ.get("KARAG_ALERT_WEBHOOK_URL")
    if url:
        notifiers["webhook"] = WebhookNotifier(url)
    return notifiers


async def main() -> None:
    registry = SkillRegistry()
    registry.register(sales_by_store_skill(tenant_id="koinoti"))
    registry.register(sales_report_skill(tenant_id="koinoti"))
    for skill in authoring_skills():
        registry.register(skill)

    platform = build_platform(Settings.from_env(), registry=registry)
    if platform.skill_load_errors:
        for err in platform.skill_load_errors:
            print(f"[karag-scheduler] skill failed to load: {err}", flush=True)

    tick = float(os.environ.get("KARAG_SCHEDULER_TICK_S", "30"))
    scheduler = AlertScheduler(
        platform.alerts, platform.executor, build_notifiers(),
        audit=platform.audit, tick_s=tick,
    )

    stopping = asyncio.Event()

    def stop() -> None:
        scheduler.stop()
        stopping.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop)

    rules = platform.alerts.list_all()
    print(
        f"[karag-scheduler] {len(rules)} rule(s), tick {tick}s, "
        f"channels: {', '.join(sorted(build_notifiers()))}",
        flush=True,
    )

    async def sync_sources() -> None:
        """Refresh API data sources whose interval has elapsed (hourly by default)."""
        while not stopping.is_set():
            try:
                for outcome in await platform.sources.run_due():
                    print(
                        f"[karag-scheduler] source {outcome.source_id}: {outcome.status}"
                        + (f" ({outcome.error})" if outcome.error else ""),
                        flush=True,
                    )
            except Exception as exc:  # noqa: BLE001 — one bad pass must not end the loop
                print(f"[karag-scheduler] source sync pass failed: {exc}", flush=True)
            try:
                await asyncio.wait_for(stopping.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass

    await asyncio.gather(scheduler.run_forever(), sync_sources())
    print("[karag-scheduler] stopped", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
