"""Inbound messenger integration: Telegram / WhatsApp bots over KARAG."""

from __future__ import annotations

from .bots import (
    BotService,
    InMemorySenderResolver,
    SenderBinding,
    SenderResolver,
    format_reply,
)
from .inbound import InboundMessage, parse_telegram_update, parse_whatsapp_update

__all__ = [
    "BotService",
    "InMemorySenderResolver",
    "SenderBinding",
    "SenderResolver",
    "format_reply",
    "InboundMessage",
    "parse_telegram_update",
    "parse_whatsapp_update",
]
