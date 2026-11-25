"""Inbound messenger webhooks — senders are authenticated by the bot, not a token."""

from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from ...messengers.inbound import parse_telegram_update, parse_whatsapp_update
from ..common import (
    ApiContext,
)


def mount(app: FastAPI, ctx: ApiContext) -> None:
    bot_svc = ctx.bot_svc

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
