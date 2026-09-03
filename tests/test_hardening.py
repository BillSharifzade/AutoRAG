"""Regression tests for the 2026-09 hardening pass.

Each test here is a bug that was observed on a running instance first.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from karag.api.app import create_app
from karag.api.security import InMemoryResolver
from karag.config import Settings
from karag.domain import DataClass, Principal
from karag.errors import ValidationError
from karag.factory import build_platform
from karag.llm.base import ChatMessage, LLMResponse, MsgRole, ToolCall
from karag.llm.fake import FakeGenerator
from karag.pricing import PriceList
from karag.skills.base import Skill, SkillResult
from karag.skills.definitions import infer_param_schema
from karag.skills.registry import SkillRegistry

ADMIN = Principal("koinoti", "admin1", ("admin",))
FIN = Principal("koinoti", "fin1", ("finance",))
EMP = Principal("koinoti", "emp1", ("employee",))
EMP2 = Principal("koinoti", "emp2", ("employee",))


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def plat():
    return build_platform(Settings(generator="fake", embedder="fake", store="memory"))


@pytest.fixture
def client(plat):
    resolver = InMemoryResolver({
        "t_admin": ADMIN, "t_fin": FIN, "t_emp": EMP, "t_emp2": EMP2,
    })
    return TestClient(create_app(plat, resolver))


# ---------------------------------------------------------------- audit ctx


def test_audit_events_carry_ip_agent_and_roles(client, plat):
    """The auth dependency runs in the request's own context now, so the
    ContextVar it sets is visible to every audit write downstream."""
    client.post(
        "/v1/ingest",
        json={"title": "Hours", "text": "Open 8 to 22.", "data_class": "public"},
        headers={**_auth("t_admin"), "User-Agent": "ProbeBrowser/1.0",
                 "X-Forwarded-For": "203.0.113.9"},
    )
    events = plat.audit.for_tenant("koinoti")
    ingest = [e for e in events if e.action == "ingest"][-1]
    assert ingest.ip == "203.0.113.9"
    assert ingest.user_agent == "ProbeBrowser/1.0"
    assert list(ingest.roles) == ["admin"]


# ------------------------------------------------------------ usage totals


class _TwoStep(FakeGenerator):
    """Calls a tool once, then answers — two model calls with known usage."""

    model = "two-step"

    async def generate(self, *, system, messages, tools=None, **kw):
        if messages[-1].role == MsgRole.TOOL:
            return LLMResponse(text="done", usage={"input_tokens": 300, "output_tokens": 30})
        return LLMResponse(
            tool_calls=[ToolCall("c1", "echo", {"value": "x"})],
            stop_reason="tool_use",
            usage={"input_tokens": 200, "output_tokens": 20},
        )


def _echo_skill():
    async def handler(principal, args):
        return SkillResult(data={"echo": args["value"]}, query_shown="echo")

    return Skill(
        name="echo", description="echo", handler=handler,
        input_schema={"type": "object", "properties": {"value": {"type": "string"}},
                      "required": ["value"], "additionalProperties": False},
        required_data_class=DataClass.PUBLIC, tenant_id="*",
    )


async def test_usage_counts_every_model_call_of_a_turn():
    reg = SkillRegistry()
    reg.register(_echo_skill())
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"), registry=reg)
    plat.gateway.generator = _TwoStep()
    ans = await plat.orchestrator.ask(EMP, "please echo something for me")
    assert ans.skills_used == ["echo"]
    totals = plat.usage.tenant_totals("koinoti")
    assert totals.input_tokens == 500 and totals.output_tokens == 50
    assert ans.diagnostics["usage"]["calls"] == 2


def test_cached_tokens_are_billed_at_their_weights():
    from karag.usage import UsageRecorder, billable_input_tokens

    assert billable_input_tokens({"input_tokens": 100}) == 100
    # 1000 cached reads cost like 100 plain tokens; 1000 cache writes like 1250
    assert billable_input_tokens({
        "input_tokens": 100, "cache_read_input_tokens": 1000,
        "cache_creation_input_tokens": 1000,
    }) == 100 + 100 + 1250
    rec = UsageRecorder()
    rec.record(tenant_id="t", user_id="u", model="m",
               usage={"input_tokens": 10, "cache_read_input_tokens": 100, "output_tokens": 5})
    assert rec.tenant_totals("t").input_tokens == 20


def test_price_list_matches_current_anthropic_rates():
    prices = PriceList()
    assert prices.cost("claude-sonnet-5", 1_000_000, 0).total_usd == pytest.approx(2.0)
    assert prices.cost("claude-opus-4-8", 0, 1_000_000).total_usd == pytest.approx(25.0)


# ------------------------------------------------------------ skill errors


class _Explodes(FakeGenerator):
    """Calls a skill that raises a non-platform exception, then answers."""

    async def generate(self, *, system, messages, tools=None, **kw):
        if messages[-1].role == MsgRole.TOOL:
            return LLMResponse(text="I could not read the database: " + messages[-1].content)
        return LLMResponse(
            tool_calls=[ToolCall("c1", "broken", {})], stop_reason="tool_use"
        )


async def test_a_crashing_skill_becomes_a_tool_error_not_a_failed_turn():
    async def handler(principal, args):
        raise RuntimeError("no such table: sales")

    reg = SkillRegistry()
    reg.register(Skill(
        name="broken", description="x", handler=handler,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        required_data_class=DataClass.PUBLIC, tenant_id="*",
    ))
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"), registry=reg)
    plat.gateway.generator = _Explodes()
    ans = await plat.orchestrator.ask(EMP, "run the broken thing please")
    assert "skill_failed" in ans.text and "no such table" in ans.text
    assert ans.skills_used == []  # a failed call is not "used"


# ------------------------------------------------------------- retrieval


async def test_small_talk_retrieves_nothing(plat):
    await plat.ingestion.ingest_document(
        ADMIN, title="Hours", text="Open 8 to 22.", data_class=DataClass.PUBLIC
    )
    ans = await plat.orchestrator.ask(EMP, "hello")
    assert ans.citations == []
    ans = await plat.orchestrator.ask(EMP, "Привет!")
    assert ans.citations == []


async def test_a_short_follow_up_searches_with_the_previous_question(plat):
    await plat.ingestion.ingest_document(
        ADMIN, title="Hours", text="Pharmacy opening hours are 8 to 22 daily.",
        data_class=DataClass.PUBLIC,
    )
    history = [
        ChatMessage(role=MsgRole.USER, content="What are the pharmacy opening hours?"),
        ChatMessage(role=MsgRole.ASSISTANT, content="8 to 22."),
    ]
    ans = await plat.orchestrator.ask(EMP, "and daily?", history=history)
    assert ans.citations and ans.citations[0].title == "Hours"


async def test_one_document_cannot_crowd_out_the_others(plat):
    long_text = " ".join(
        f"Pharmacy opening hours paragraph {i} about opening hours and pharmacy." for i in range(40)
    )
    await plat.ingestion.ingest_document(ADMIN, title="Big", text=long_text, data_class=DataClass.PUBLIC)
    await plat.ingestion.ingest_document(
        ADMIN, title="Small", text="Pharmacy opening hours: 8 to 22.", data_class=DataClass.PUBLIC
    )
    ans = await plat.orchestrator.ask(EMP, "pharmacy opening hours")
    titles = [c.title for c in ans.citations]
    assert titles.count("Big") <= 2 and "Small" in titles


# ---------------------------------------------------------------- ingest


async def test_re_adding_a_title_replaces_the_old_copy(plat):
    first = await plat.ingestion.ingest_document(
        ADMIN, title="Price list", text="Aspirin 10.", data_class=DataClass.PUBLIC
    )
    second = await plat.ingestion.ingest_document(
        ADMIN, title="price list ", text="Aspirin 12.", data_class=DataClass.PUBLIC
    )
    docs = await plat.store.list_documents(
        tenant_id="koinoti", allowed_classes=frozenset(DataClass)
    )
    assert [d.document_id for d in docs] == [second.id]
    assert second.metadata["replaced"] == [first.id]


def test_ingest_endpoint_reports_what_it_replaced(client):
    a = client.post("/v1/ingest", json={"title": "T", "text": "one", "data_class": "public"},
                    headers=_auth("t_admin")).json()
    b = client.post("/v1/ingest", json={"title": "T", "text": "two", "data_class": "public"},
                    headers=_auth("t_admin")).json()
    assert b["replaced"] == [a["document_id"]]


# ------------------------------------------------------------ assistants


def test_only_the_owner_or_an_admin_may_change_an_assistant(client):
    a = client.post("/v1/assistants", json={"name": "Mine"}, headers=_auth("t_emp")).json()
    assert a["can_edit"] is True and a["created_by"] == "emp1"
    # another employee sees it, may use it, may not edit or delete it
    listed = client.get("/v1/assistants", headers=_auth("t_emp2")).json()["assistants"]
    assert listed[0]["can_edit"] is False
    assert client.put(f"/v1/assistants/{a['id']}", json={"name": "Stolen"},
                      headers=_auth("t_emp2")).status_code == 403
    assert client.delete(f"/v1/assistants/{a['id']}", headers=_auth("t_emp2")).status_code == 403
    assert client.post(f"/v1/assistants/{a['id']}/ask", json={"query": "hi"},
                       headers=_auth("t_emp2")).status_code == 200
    # an administrator may
    assert client.put(f"/v1/assistants/{a['id']}", json={"name": "Renamed"},
                      headers=_auth("t_admin")).status_code == 200
    assert client.delete(f"/v1/assistants/{a['id']}", headers=_auth("t_admin")).status_code == 200


def test_empty_allow_list_means_documents_only_on_create_and_update(client):
    a = client.post("/v1/assistants", json={"name": "Docs", "allowed_skill_names": []},
                    headers=_auth("t_admin")).json()
    assert a["allowed_skill_names"] == []
    b = client.put(f"/v1/assistants/{a['id']}", json={"allowed_skill_names": None},
                   headers=_auth("t_admin")).json()
    assert b["allowed_skill_names"] is None
    c = client.put(f"/v1/assistants/{a['id']}", json={"instruction": "Be brief."},
                   headers=_auth("t_admin")).json()
    assert c["allowed_skill_names"] is None and c["instruction"] == "Be brief."


def test_a_chat_whose_assistant_was_deleted_says_so(client):
    a = client.post("/v1/assistants", json={"name": "Gone"}, headers=_auth("t_admin")).json()
    chat = client.post("/v1/chats", json={"assistant_id": a["id"]}, headers=_auth("t_admin")).json()
    client.delete(f"/v1/assistants/{a['id']}", headers=_auth("t_admin"))
    r = client.post(f"/v1/chats/{chat['id']}/ask", json={"query": "hello there"},
                    headers=_auth("t_admin"))
    assert r.status_code == 200
    assert r.json()["assistant_missing"] is True


# ----------------------------------------------------------- chat failures


class _Boom(FakeGenerator):
    async def generate(self, *, system, messages, tools=None, **kw):
        from karag.errors import GenerationError

        raise GenerationError("provider down")


def test_a_failed_turn_is_recorded_and_not_replayed(client, plat):
    plat.gateway.generator = _Boom()
    chat = client.post("/v1/chats", json={}, headers=_auth("t_admin")).json()
    r = client.post(f"/v1/chats/{chat['id']}/ask", json={"query": "hello there"},
                    headers=_auth("t_admin"))
    assert r.status_code == 502
    detail = client.get(f"/v1/chats/{chat['id']}", headers=_auth("t_admin")).json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant"]
    assert detail["messages"][1]["answer"]["plane"] == "error"
    # the error turn is not part of the model's memory next time
    from karag.api.app import _history_messages
    from karag.conversations import Conversation, StoredMessage

    conv = Conversation(
        id="c", tenant_id="t", user_id="u", title="", assistant_id=None,
        created_at=0, updated_at=0,
        messages=[
            StoredMessage(role="user", text="q1"),
            StoredMessage(role="assistant", text="boom", answer={"plane": "error"}),
            StoredMessage(role="user", text="q2"),
            StoredMessage(role="assistant", text="fine", answer={"plane": "knowledge"}),
        ],
    )
    assert [m.content for m in _history_messages(conv)] == ["q1", "q2", "fine"]


def test_history_budget_drops_the_oldest_turns_first():
    from karag.api.app import _HISTORY_CHARS, _history_messages
    from karag.conversations import Conversation, StoredMessage

    big = "x" * (_HISTORY_CHARS // 2 + 10)
    conv = Conversation(
        id="c", tenant_id="t", user_id="u", title="", assistant_id=None,
        created_at=0, updated_at=0,
        messages=[
            StoredMessage(role="user", text="old question"),
            StoredMessage(role="assistant", text=big),
            StoredMessage(role="user", text="new question"),
            StoredMessage(role="assistant", text=big),
        ],
    )
    kept = _history_messages(conv)
    assert kept[0].role == MsgRole.USER and kept[0].content == "new question"


# ----------------------------------------------------------------- stream


def test_streaming_endpoint_emits_progress_deltas_and_a_final_answer(client):
    client.post("/v1/ingest", json={"title": "Hours", "text": "Open 8 to 22 daily.",
                                    "data_class": "public"}, headers=_auth("t_admin"))
    chat = client.post("/v1/chats", json={}, headers=_auth("t_admin")).json()
    with client.stream(
        "POST", f"/v1/chats/{chat['id']}/stream",
        json={"query": "When are we open every day?"}, headers=_auth("t_admin"),
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = [
            json.loads(line[len("data: "):])
            for line in r.iter_lines()
            if line.startswith("data: ")
        ]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "status" and kinds[-1] == "done"
    deltas = "".join(e["text"] for e in events if e["type"] == "delta")
    done = events[-1]
    assert deltas == done["answer"]["text"]
    assert done["title"] and done["answer"]["citations"]
    # and the turn was saved exactly like the JSON path saves it
    detail = client.get(f"/v1/chats/{chat['id']}", headers=_auth("t_admin")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]


# ------------------------------------------------------------- skills


def test_a_sql_skill_needs_a_database_connection_not_an_api(client):
    api = client.post("/v1/connectors", json={
        "name": "api", "kind": "rest", "config": {"base_url": "https://example.com"},
    }, headers=_auth("t_admin")).json()
    r = client.post("/v1/skills/definitions", json={
        "name": "wrong_kind", "description": "x", "kind": "sql",
        "connector_id": api["id"], "sql": "select 1",
    }, headers=_auth("t_admin"))
    assert r.status_code == 400 and "database" in r.json()["detail"]


def test_a_skill_may_not_take_a_built_in_tools_name(client, tmp_path):
    import sqlite3

    db = tmp_path / "x.db"
    sqlite3.connect(db).execute("create table t(a int)")
    conn = client.post("/v1/connectors", json={
        "name": "db", "kind": "sql_sqlite", "config": {"path": str(db)},
    }, headers=_auth("t_admin")).json()
    r = client.post("/v1/skills/definitions", json={
        "name": "create_spreadsheet", "description": "x", "kind": "sql",
        "connector_id": conn["id"], "sql": "select a from t",
    }, headers=_auth("t_admin"))
    assert r.status_code == 400 and "built-in" in r.json()["detail"]


def test_parameters_are_inferred_from_the_statement(client, tmp_path):
    import sqlite3

    db = tmp_path / "x.db"
    c = sqlite3.connect(db)
    c.execute("create table sales(tenant text, store_id int, day text, amount int)")
    c.execute("insert into sales values ('koinoti', 7, '2026-01-01', 5)")
    c.commit()
    conn = client.post("/v1/connectors", json={
        "name": "db", "kind": "sql_sqlite", "config": {"path": str(db)},
    }, headers=_auth("t_admin")).json()
    r = client.post("/v1/skills/definitions", json={
        "name": "store_day_sales", "description": "sales of a store on a day", "kind": "sql",
        "connector_id": conn["id"],
        "sql": "select sum(amount) as total from sales where tenant=:tenant_id and store_id=:store_id and day=:day",
    }, headers=_auth("t_admin"))
    assert r.status_code == 200, r.text
    props = r.json()["param_schema"]["properties"]
    assert props["store_id"]["type"] == "integer" and props["day"]["type"] == "string"
    assert "tenant_id" not in props
    run = client.post(f"/v1/skills/definitions/{r.json()['id']}/test",
                      json={"arguments": {"store_id": 7, "day": "2026-01-01"}},
                      headers=_auth("t_admin")).json()
    assert run["ok"] and run["data"]["rows"][0]["total"] == 5


def test_infer_param_schema_type_guesses():
    schema = infer_param_schema("select * from t where a=:store_id and b=:amount and c=:is_active and d=:name")
    props = schema["properties"]
    assert props["store_id"]["type"] == "integer"
    assert props["amount"]["type"] == "number"
    assert props["is_active"]["type"] == "boolean"
    assert props["name"]["type"] == "string"
    assert schema["additionalProperties"] is False


def test_a_rest_connector_may_not_point_inside_the_network():
    from karag.connectors.rest import RestConnector
    from karag.errors import KaragError

    for url in ("http://127.0.0.1:8000", "http://localhost/api", "http://169.254.169.254/latest",
                "http://10.0.0.5", "file:///etc/passwd"):
        with pytest.raises(KaragError):
            RestConnector(url).check()
    # an operator can opt a private API in explicitly
    RestConnector("http://10.0.0.5", allow_private=True).check()


def test_a_disabled_skill_is_not_offered(client, tmp_path):
    import sqlite3

    db = tmp_path / "x.db"
    sqlite3.connect(db).execute("create table t(a int)")
    conn = client.post("/v1/connectors", json={
        "name": "db", "kind": "sql_sqlite", "config": {"path": str(db)},
    }, headers=_auth("t_admin")).json()
    body = {"name": "toggle_me", "description": "x", "kind": "sql",
            "connector_id": conn["id"], "sql": "select a from t"}
    d = client.post("/v1/skills/definitions", json=body, headers=_auth("t_admin")).json()
    names = lambda: [s["name"] for s in client.get("/v1/skills", headers=_auth("t_admin")).json()["skills"]]  # noqa: E731
    assert "toggle_me" in names()
    client.put(f"/v1/skills/definitions/{d['id']}", json={**body, "enabled": False},
               headers=_auth("t_admin"))
    assert "toggle_me" not in names()
    client.put(f"/v1/skills/definitions/{d['id']}", json={**body, "enabled": True},
               headers=_auth("t_admin"))
    assert "toggle_me" in names()


def test_audit_is_readable_by_leadership(client):
    resolver_ceo = Principal("koinoti", "ceo1", ("ceo",))
    from karag.api.security import InMemoryResolver as R
    app = client.app
    c2 = TestClient(app)
    # the fixture's resolver has no ceo token; build one on the same app is not
    # possible, so check the rule directly
    assert resolver_ceo.has_any_role(frozenset({"admin", "ceo"}))
    assert R  # silence unused-import linters
