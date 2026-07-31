"""Answer language: RU / TJ / EN (§2's moat, §15's multilingual line).

The system prompt is where the language is pinned, so these tests capture the
prompt the generator actually received rather than asserting on model output.
"""

import pytest
from fastapi.testclient import TestClient

from karag.api.app import create_app
from karag.api.security import InMemoryResolver
from karag.config import Settings
from karag.domain import Principal
from karag.factory import build_platform
from karag.llm.fake import FakeGenerator
from karag.messengers.bots import BotService, InMemorySenderResolver, SenderBinding
from karag.messengers.inbound import InboundMessage
from karag.orchestrator import language_instruction

CEO = Principal("koinoti", "ceo1", ("ceo",))


class RecordingGenerator(FakeGenerator):
    """A FakeGenerator that remembers the system prompt of each call."""

    def __init__(self) -> None:
        super().__init__()
        self.systems: list[str] = []

    async def generate(self, *, system, messages, tools=None, **kw):
        self.systems.append(system)
        return await super().generate(system=system, messages=messages, tools=tools, **kw)


def _platform(language="auto"):
    plat = build_platform(
        Settings(generator="fake", embedder="fake", store="memory", default_language=language)
    )
    recorder = RecordingGenerator()
    plat.gateway.generator = recorder
    return plat, recorder


# ---------- the instruction itself ----------


def test_auto_adds_no_instruction():
    assert language_instruction("auto") is None
    assert language_instruction(None) is None
    assert language_instruction("") is None


@pytest.mark.parametrize(
    "code,marker", [("ru", "Russian"), ("tg", "Tajik"), ("en", "English")]
)
def test_each_supported_language_has_an_instruction(code, marker):
    assert marker in language_instruction(code)


def test_an_unknown_language_adds_nothing_rather_than_guessing():
    assert language_instruction("fr") is None


def test_instructions_forbid_altering_numbers():
    """Translating a figure's label is fine; translating the figure is not."""
    for code in ("ru", "tg", "en"):
        assert "never alter the numbers" in language_instruction(code)


# ---------- orchestrator ----------


async def test_request_language_reaches_the_system_prompt():
    plat, recorder = _platform()
    await plat.orchestrator.ask(CEO, "hello", language="tg")
    assert "Tajik" in recorder.systems[-1]


async def test_deployment_default_applies_when_nothing_is_requested():
    plat, recorder = _platform(language="ru")
    await plat.orchestrator.ask(CEO, "hello")
    assert "Russian" in recorder.systems[-1]


async def test_per_request_language_overrides_the_deployment_default():
    plat, recorder = _platform(language="ru")
    await plat.orchestrator.ask(CEO, "hello", language="en")
    system = recorder.systems[-1]
    # Assert on the directive itself: the platform handbook also mentions the
    # supported languages by name, so a bare "Russian" substring proves nothing.
    assert "Always answer in English" in system
    assert "Always answer in Russian" not in system


async def test_language_clause_comes_after_the_assistant_instruction():
    """An assistant persona written in English must not undo a Tajik pin."""
    plat, recorder = _platform()
    asst = plat.assistants.create(
        CEO, name="Helpdesk", instruction="Be extremely concise.", language="tg"
    )
    await plat.assistant_service.ask(CEO, asst.id, "hello")
    system = recorder.systems[-1]
    assert system.index("Be extremely concise.") < system.index("Always answer in Tajik")


async def test_assistant_language_wins_over_the_callers_preference():
    plat, recorder = _platform()
    asst = plat.assistants.create(CEO, name="Tajik desk", language="tg")
    await plat.assistant_service.ask(CEO, asst.id, "hello", language="ru")
    assert "Tajik" in recorder.systems[-1]


async def test_an_auto_assistant_defers_to_the_caller():
    plat, recorder = _platform()
    asst = plat.assistants.create(CEO, name="Neutral", language="auto")
    await plat.assistant_service.ask(CEO, asst.id, "hello", language="ru")
    assert "Russian" in recorder.systems[-1]


# ---------- messenger bots ----------


async def test_a_messenger_binding_can_pin_a_language():
    plat, recorder = _platform()
    resolver = InMemorySenderResolver({
        ("telegram", "42"): SenderBinding(principal=CEO, language="tg")
    })
    bot = BotService(plat.orchestrator, plat.assistant_service, resolver)
    await bot.handle(
        InboundMessage(platform="telegram", sender_id="42", chat_id="42", text="salom")
    )
    assert "Tajik" in recorder.systems[-1]


def test_binding_language_parses_from_the_env_format(monkeypatch):
    monkeypatch.setenv(
        "KARAG_MESSENGER_SENDERS", "telegram:42:koinoti:ceo1:ceo:asst_x:tg"
    )
    binding = InMemorySenderResolver.from_env().resolve("telegram", "42")
    assert binding.language == "tg"
    assert binding.assistant_id == "asst_x"


def test_binding_without_a_language_still_parses(monkeypatch):
    monkeypatch.setenv("KARAG_MESSENGER_SENDERS", "telegram:42:koinoti:ceo1:ceo")
    binding = InMemorySenderResolver.from_env().resolve("telegram", "42")
    assert binding.language is None and binding.assistant_id is None


# ---------- HTTP ----------


@pytest.fixture
def client():
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    resolver = InMemoryResolver({
        "t_admin": Principal("koinoti", "admin", ("admin",)),
    })
    return TestClient(create_app(plat, resolver)), plat


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_health_advertises_the_supported_languages(client):
    c, _ = client
    body = c.get("/health").json()
    assert set(body["languages"]) == {"auto", "ru", "tg", "en"}


def test_me_reports_the_effective_language(client):
    c, _ = client
    body = c.get("/v1/me", headers=_auth("t_admin")).json()
    assert body["language"] == "auto"
    assert body["can_author_skills"] is True


def test_stored_account_preference_drives_the_answer_language(client):
    c, plat = client
    # onboard an account and set its language, then use its own token
    token = c.post(
        "/v1/accounts",
        json={"user_id": "u1", "roles": ["employee"], "language": "tg"},
        headers=_auth("t_admin"),
    ).json()["token"]

    from karag.tenants import ChainResolver, DirectoryResolver

    resolver = ChainResolver(
        InMemoryResolver({"t_admin": Principal("koinoti", "admin", ("admin",))}),
        DirectoryResolver(plat.directory),
    )
    c2 = TestClient(create_app(plat, resolver))
    assert c2.get("/v1/me", headers=_auth(token)).json()["language"] == "tg"


def test_a_user_can_change_their_own_language(client):
    c, plat = client
    token = c.post(
        "/v1/accounts", json={"user_id": "u1", "roles": ["employee"]},
        headers=_auth("t_admin"),
    ).json()["token"]

    from karag.tenants import ChainResolver, DirectoryResolver

    resolver = ChainResolver(
        InMemoryResolver({"t_admin": Principal("koinoti", "admin", ("admin",))}),
        DirectoryResolver(plat.directory),
    )
    c2 = TestClient(create_app(plat, resolver))
    assert c2.post(
        "/v1/me/language", json={"language": "ru"}, headers=_auth(token)
    ).status_code == 200
    assert c2.get("/v1/me", headers=_auth(token)).json()["language"] == "ru"


def test_an_unsupported_language_is_rejected(client):
    c, _ = client
    r = c.post("/v1/ask", json={"query": "hi", "language": "fr"}, headers=_auth("t_admin"))
    assert r.status_code == 400
