"""Parse inbound webhook payloads from messenger platforms into a common shape.

These are pure functions — no network, no tokens — so the (fiddly) payload
shapes can be unit-tested offline. Anything that isn't a plain text message from
a user (edited messages, delivery receipts, stickers, status callbacks) is
ignored: the parsers return ``None`` / an empty list rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class InboundMessage:
    """A normalized inbound chat message.

    ``sender_id`` identifies the person on the platform (Telegram user id /
    WhatsApp phone number); it is mapped to a KARAG :class:`Principal` by a
    :class:`~karag.messengers.bots.SenderResolver`. ``chat_id`` is where a reply
    should be delivered.
    """

    platform: str  # "telegram" | "whatsapp"
    sender_id: str
    chat_id: str
    text: str
    raw: dict = field(default_factory=dict)


def parse_telegram_update(update: dict) -> InboundMessage | None:
    """Extract a text message from a Telegram Bot API ``Update`` object.

    Returns ``None`` for non-message updates or messages without text.
    """
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    sender_id = sender.get("id", chat.get("id"))
    chat_id = chat.get("id")
    if sender_id is None or chat_id is None:
        return None
    return InboundMessage(
        platform="telegram",
        sender_id=str(sender_id),
        chat_id=str(chat_id),
        text=text.strip(),
        raw=update,
    )


def parse_whatsapp_update(payload: dict) -> list[InboundMessage]:
    """Extract text messages from a WhatsApp Cloud API webhook payload.

    A single callback can batch several messages across entries/changes; each
    text message becomes one :class:`InboundMessage`. Status callbacks (sent /
    delivered / read) carry no ``messages`` array and yield nothing.
    """
    out: list[InboundMessage] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            for msg in value.get("messages", []) or []:
                if msg.get("type") != "text":
                    continue
                body = (msg.get("text") or {}).get("body")
                sender = msg.get("from")
                if not isinstance(body, str) or not body.strip() or not sender:
                    continue
                out.append(
                    InboundMessage(
                        platform="whatsapp",
                        sender_id=str(sender),
                        chat_id=str(sender),
                        text=body.strip(),
                        raw=msg,
                    )
                )
    return out
