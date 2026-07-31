"""Messengers: outbound notifiers + inbound bot parsing/handling (offline)."""

from karag.alerts import TelegramNotifier, WhatsAppNotifier
from karag.config import Settings
from karag.domain import Principal
from karag.factory import build_platform
from karag.messengers import (
    BotService,
    InboundMessage,
    InMemorySenderResolver,
    SenderBinding,
    parse_telegram_update,
    parse_whatsapp_update,
)


def test_telegram_url_and_payload():
    n = TelegramNotifier(bot_token="123:ABC", chat_id="42")
    assert n._url() == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert n._payload("batch expiring") == {"chat_id": "42", "text": "batch expiring"}


def test_whatsapp_url_headers_payload():
    n = WhatsAppNotifier(phone_number_id="999", to="+15550001111", access_token="tok")
    assert n._url() == "https://graph.facebook.com/v20.0/999/messages"
    assert n._headers() == {"Authorization": "Bearer tok"}
    p = n._payload("anomaly detected")
    assert p == {
        "messaging_product": "whatsapp",
        "to": "+15550001111",
        "type": "text",
        "text": {"body": "anomaly detected"},
    }


# --- inbound parsing --------------------------------------------------------

def test_parse_telegram_text_message():
    msg = parse_telegram_update({
        "update_id": 1,
        "message": {"message_id": 7, "text": "  what is the policy?  ",
                    "chat": {"id": 555}, "from": {"id": 999}},
    })
    assert msg == InboundMessage("telegram", "999", "555", "what is the policy?", msg.raw)


def test_parse_telegram_ignores_non_text():
    assert parse_telegram_update({"update_id": 2, "message": {"chat": {"id": 1},
                                  "from": {"id": 2}, "sticker": {}}}) is None
    assert parse_telegram_update({"my_chat_member": {}}) is None


def test_parse_whatsapp_batches_and_skips_status():
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"type": "text", "from": "15551112222", "text": {"body": "hi there"}},
        {"type": "image", "from": "15551112222"},
    ]}}]}]}
    msgs = parse_whatsapp_update(payload)
    assert len(msgs) == 1
    assert msgs[0].platform == "whatsapp" and msgs[0].sender_id == "15551112222"
    assert msgs[0].text == "hi there"
    # a status callback (no messages) yields nothing
    assert parse_whatsapp_update({"entry": [{"changes": [{"value": {"statuses": [{}]}}]}]}) == []


# --- sender resolution + bot handling --------------------------------------

def test_sender_resolver_from_env(monkeypatch):
    monkeypatch.setenv(
        "KARAG_MESSENGER_SENDERS",
        "telegram:999:koinoti:ceo1:ceo|admin, whatsapp:15551112222:koinoti:hr1:hr:asst_x",
    )
    r = InMemorySenderResolver.from_env()
    b = r.resolve("telegram", "999")
    assert b.principal.tenant_id == "koinoti" and "ceo" in b.principal.roles
    assert b.assistant_id is None
    b2 = r.resolve("whatsapp", "15551112222")
    assert b2.assistant_id == "asst_x"
    assert r.resolve("telegram", "000") is None


def _bot(resolver):
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    return BotService(plat.orchestrator, plat.assistant_service, resolver)


async def test_bot_fails_closed_for_unknown_sender():
    bot = _bot(InMemorySenderResolver())
    reply = await bot.handle(InboundMessage("telegram", "nope", "nope", "hello"))
    assert "isn't linked" in reply


async def test_bot_answers_registered_sender():
    resolver = InMemorySenderResolver()
    resolver.add("telegram", "999",
                 SenderBinding(Principal("koinoti", "ceo1", ("ceo",))))
    bot = _bot(resolver)
    reply = await bot.handle(InboundMessage("telegram", "999", "555", "hello"))
    assert reply and "isn't linked" not in reply
