"""Run the KARAG Telegram bot via long polling (no public URL / domain needed).

For local testing before an HTTPS webhook endpoint exists: this calls Telegram's
getUpdates in a loop and answers each message through the same RBAC-governed
``BotService`` the webhook uses. Config comes from the environment (load .env
first: ``set -a; source .env; set +a``).

Requires KARAG_TELEGRAM_BOT_TOKEN and KARAG_MESSENGER_SENDERS. Seeds a small demo
corpus + the sample sales skill so there is something to ask about.
"""

from __future__ import annotations

import asyncio
import os

import httpx

from karag.config import Settings
from karag.domain import DataClass, Principal
from karag.factory import build_platform
from karag.messengers.bots import BotService, InMemorySenderResolver
from karag.messengers.inbound import parse_telegram_update
from karag.skills.registry import SkillRegistry
from karag.skills.authoring import authoring_skills
from karag.skills.samples import sales_by_store_skill, sales_report_skill

_SEED = Principal("koinoti", "seed_admin", ("admin",))


async def seed(platform) -> None:
    docs = [
        ("Returns Policy",
         "Customers may return unopened goods within 14 days for a full refund. "
         "Opened goods are non-refundable except for manufacturing defects.",
         DataClass.PUBLIC),
        ("Warehouse SOP",
         "Stock transfers between warehouses require a signed movement note and "
         "same-day system entry.",
         DataClass.OPERATIONAL),
        ("Q2 Financials",
         "Confidential: Q2 revenue was 4.2M and net profit was 610K somoni.",
         DataClass.FINANCIAL),
    ]
    for title, text, dc in docs:
        await platform.ingestion.ingest_document(
            _SEED, title=title, text=text, data_class=dc)


async def run() -> None:
    settings = Settings.from_env()
    token = os.environ.get("KARAG_TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("KARAG_TELEGRAM_BOT_TOKEN is not set (source your .env)")

    registry = SkillRegistry()
    registry.register(sales_by_store_skill(tenant_id="koinoti"))
    registry.register(sales_report_skill(tenant_id="koinoti"))
    for _skill in authoring_skills():
        registry.register(_skill)
    platform = build_platform(settings, registry=registry)
    await seed(platform)

    resolver = InMemorySenderResolver.from_env()
    bot = BotService(platform.orchestrator, platform.assistant_service, resolver)

    api = f"https://api.telegram.org/bot{token}"
    async with httpx.AsyncClient(timeout=40.0) as client:
        me = (await client.get(f"{api}/getMe")).json()
        uname = me.get("result", {}).get("username", "?")
        print(f"[karag-bot] up as @{uname} · model={settings.generator}:"
              f"{settings.openai_model} · store={settings.store}", flush=True)
        print(f"[karag-bot] registered senders: {list(resolver._bindings)}", flush=True)

        offset = None
        while True:
            try:
                params = {"timeout": 30}
                if offset is not None:
                    params["offset"] = offset
                resp = await client.get(f"{api}/getUpdates", params=params)
                updates = resp.json().get("result", [])
            except Exception as exc:  # network hiccup: back off and retry
                print(f"[karag-bot] poll error: {exc}", flush=True)
                await asyncio.sleep(3)
                continue

            for upd in updates:
                offset = upd["update_id"] + 1
                msg = parse_telegram_update(upd)
                if msg is None:
                    continue
                print(f"[karag-bot] <- {msg.sender_id}: {msg.text!r}", flush=True)
                try:
                    reply = await bot.handle(msg)
                except Exception as exc:
                    reply = f"Sorry — something went wrong ({type(exc).__name__})."
                    print(f"[karag-bot] handle error: {exc}", flush=True)
                await client.post(f"{api}/sendMessage",
                                  json={"chat_id": msg.chat_id, "text": reply})
                print(f"[karag-bot] -> {msg.chat_id}: {reply[:80]!r}", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
