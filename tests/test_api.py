"""HTTP layer: auth, RBAC, ingest (text + file), ask, assistants, audit, usage."""

import base64

import pytest
from fastapi.testclient import TestClient

from karag.api.app import create_app
from karag.api.security import InMemoryResolver
from karag.config import Settings
from karag.domain import Principal
from karag.factory import build_platform
from karag.office.xlsx import build_xlsx
from karag.skills.registry import SkillRegistry
from karag.skills.samples import sales_by_store_skill


@pytest.fixture
def client():
    reg = SkillRegistry(); reg.register(sales_by_store_skill(tenant_id="koinoti"))
    plat = build_platform(
        Settings(generator="fake", embedder="fake", store="memory"), registry=reg)
    resolver = InMemoryResolver({
        "t_admin": Principal("koinoti", "admin", ("admin",)),
        "t_emp": Principal("koinoti", "emp", ("employee",)),
        "t_fin": Principal("koinoti", "fin", ("finance",)),
    })
    return TestClient(create_app(plat, resolver))


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_ui_served(client):
    for path in ("/", "/ui"):
        r = client.get(path)
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "KARAG" in r.text and "no-code" not in r.text.lower() or "Assistant" in r.text


def test_skills_endpoint_reflects_rbac(client):
    # finance can see the finance skill; employee cannot
    fin = client.get("/v1/skills", headers=_auth("t_fin")).json()["skills"]
    assert any(s["name"] == "sales_by_store" for s in fin)
    emp = client.get("/v1/skills", headers=_auth("t_emp")).json()["skills"]
    assert all(s["name"] != "sales_by_store" for s in emp)


def test_ask_requires_token(client):
    assert client.post("/v1/ask", json={"query": "hi"}).status_code == 401
    assert client.post("/v1/ask", json={"query": "hi"},
                       headers=_auth("bogus")).status_code == 401


def test_ingest_rbac(client):
    # employee cannot ingest
    r = client.post("/v1/ingest", json={"title": "P", "text": "x", "data_class": "public"},
                    headers=_auth("t_emp"))
    assert r.status_code == 403
    # admin can
    r = client.post("/v1/ingest",
                    json={"title": "Returns", "text": "Return within 14 days.", "data_class": "public"},
                    headers=_auth("t_admin"))
    assert r.status_code == 200 and r.json()["document_id"].startswith("doc_")


def test_ingest_file_and_ask(client):
    data = build_xlsx({"S": [["metric", "value"], ["policy", "Return within 14 days"]]})
    r = client.post(
        "/v1/ingest/file",
        files={"file": ("book.xlsx", data,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"data_class": "operational"},
        headers=_auth("t_admin"),
    )
    assert r.status_code == 200
    r = client.post("/v1/ask", json={"query": "what is the policy"}, headers=_auth("t_emp"))
    assert r.status_code == 200
    assert "citations" in r.json()


def test_unsupported_file_type(client):
    r = client.post("/v1/ingest/file",
                    files={"file": ("x.heic", b"...", "image/heic")},
                    data={"data_class": "public"}, headers=_auth("t_admin"))
    assert r.status_code == 415


def test_assistants_flow(client):
    r = client.post("/v1/assistants", json={"name": "Help", "instruction": "Be brief."},
                    headers=_auth("t_fin"))
    assert r.status_code == 200
    aid = r.json()["id"]
    assert any(a["id"] == aid for a in client.get("/v1/assistants", headers=_auth("t_fin")).json()["assistants"])
    # other tenant / same-tenant ask
    r = client.post(f"/v1/assistants/{aid}/ask", json={"query": "hello"}, headers=_auth("t_fin"))
    assert r.status_code == 200


def test_builder_served(client):
    r = client.get("/builder")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Assistant Builder" in r.text


def test_assistant_get_and_update(client):
    r = client.post("/v1/assistants",
                    json={"name": "Help", "instruction": "Be brief.",
                          "allowed_skill_names": ["sales_by_store"]},
                    headers=_auth("t_fin"))
    aid = r.json()["id"]
    # full config comes back on POST and GET
    assert r.json()["allowed_skill_names"] == ["sales_by_store"]
    got = client.get(f"/v1/assistants/{aid}", headers=_auth("t_fin")).json()
    assert got["instruction"] == "Be brief."
    # update: rename + widen back to "all" via empty list
    up = client.put(f"/v1/assistants/{aid}",
                    json={"name": "Helpdesk", "instruction": "Cite sources.",
                          "allowed_skill_names": []},
                    headers=_auth("t_fin")).json()
    assert up["name"] == "Helpdesk" and up["allowed_skill_names"] is None
    # updating an unknown id is a 404, not a disclosure
    assert client.put("/v1/assistants/asst_missing", json={"name": "x"},
                      headers=_auth("t_fin")).status_code == 404


def test_telegram_webhook_registered_and_unknown(monkeypatch):
    from karag.domain import Principal as P
    from karag.messengers.bots import BotService, InMemorySenderResolver, SenderBinding
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    resolver = InMemorySenderResolver()
    resolver.add("telegram", "999", SenderBinding(P("koinoti", "ceo1", ("ceo",))))
    bot = BotService(plat.orchestrator, plat.assistant_service, resolver)
    c = TestClient(create_app(plat, InMemoryResolver({}), bot))

    r = c.post("/v1/webhooks/telegram", json={
        "message": {"text": "hello", "chat": {"id": 555}, "from": {"id": 999}}})
    body = r.json()
    assert r.status_code == 200 and body["method"] == "sendMessage"
    assert body["chat_id"] == "555" and "isn't linked" not in body["text"]

    # unknown sender is answered with the fail-closed refusal
    r = c.post("/v1/webhooks/telegram", json={
        "message": {"text": "hello", "chat": {"id": 1}, "from": {"id": 1}}})
    assert "isn't linked" in r.json()["text"]

    # non-message updates are acknowledged, not processed
    assert c.post("/v1/webhooks/telegram", json={"update_id": 5}).json() == {"ok": True}


def test_telegram_webhook_secret_enforced(monkeypatch):
    monkeypatch.setenv("KARAG_TELEGRAM_WEBHOOK_SECRET", "s3cret")
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    c = TestClient(create_app(plat, InMemoryResolver({})))
    upd = {"message": {"text": "hi", "chat": {"id": 1}, "from": {"id": 1}}}
    assert c.post("/v1/webhooks/telegram", json=upd).status_code == 403
    assert c.post("/v1/webhooks/telegram", json=upd,
                  headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"}).status_code == 200


def test_whatsapp_verify_handshake(monkeypatch):
    monkeypatch.setenv("KARAG_WHATSAPP_VERIFY_TOKEN", "vtok")
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    c = TestClient(create_app(plat, InMemoryResolver({})))
    r = c.get("/v1/webhooks/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "vtok", "hub.challenge": "42"})
    assert r.status_code == 200 and r.text == "42"
    assert c.get("/v1/webhooks/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42"}
    ).status_code == 403


def test_whatsapp_webhook_message():
    from karag.domain import Principal as P
    from karag.messengers.bots import BotService, InMemorySenderResolver, SenderBinding
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    resolver = InMemorySenderResolver()
    resolver.add("whatsapp", "15551112222", SenderBinding(P("koinoti", "hr1", ("hr",))))
    bot = BotService(plat.orchestrator, plat.assistant_service, resolver)
    c = TestClient(create_app(plat, InMemoryResolver({}), bot))
    r = c.post("/v1/webhooks/whatsapp", json={"entry": [{"changes": [{"value": {
        "messages": [{"type": "text", "from": "15551112222",
                      "text": {"body": "hello"}}]}}]}]})
    replies = r.json()["replies"]
    assert len(replies) == 1 and replies[0]["to"] == "15551112222"


def test_audit_admin_only(client):
    client.post("/v1/ask", json={"query": "hi"}, headers=_auth("t_emp"))
    assert client.get("/v1/audit", headers=_auth("t_emp")).status_code == 403
    events = client.get("/v1/audit", headers=_auth("t_admin")).json()["events"]
    assert any(e["action"] == "ask" for e in events)


def test_usage_endpoint(client):
    for _ in range(2):
        client.post("/v1/ask", json={"query": "hi"}, headers=_auth("t_emp"))
    u = client.get("/v1/usage", headers=_auth("t_emp")).json()
    assert u["requests"] >= 2


def test_office_artifact_returned_base64(client):
    from karag.skills.samples import sales_report_skill
    # register an output skill and exercise it via the API
    reg = SkillRegistry(); reg.register(sales_report_skill(tenant_id="koinoti"))
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"), registry=reg)
    resolver = InMemoryResolver({"t_fin": Principal("koinoti", "fin", ("finance",))})
    c = TestClient(create_app(plat, resolver))
    r = c.post("/v1/ask", json={"query": "generate report store_id=5 format=xlsx"},
               headers=_auth("t_fin"))
    arts = r.json()["artifacts"]
    assert len(arts) == 1
    assert base64.b64decode(arts[0]["content_base64"])[:2] == b"PK"


def test_ask_with_file_attachment(client):
    import base64 as _b64
    payload = {
        "query": "Summarize the attached file",
        "attachments": [{
            "kind": "file", "filename": "notes.txt", "media_type": "text/plain",
            "data_b64": _b64.b64encode(b"The warehouse opens at 8am.").decode(),
        }],
    }
    r = client.post("/v1/ask", json=payload, headers=_auth("t_emp"))
    assert r.status_code == 200


def test_ask_with_image_attachment(client):
    # 1x1 transparent PNG
    png_b64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNg"
               "YAAAAAMAASsJTYQAAAAASUVORK5CYII=")
    payload = {
        "query": "What is in this image?",
        "attachments": [{
            "kind": "image", "filename": "px.png", "media_type": "image/png",
            "data_b64": png_b64,
        }],
    }
    r = client.post("/v1/ask", json=payload, headers=_auth("t_emp"))
    assert r.status_code == 200


def test_ask_rejects_empty_query_without_attachments(client):
    r = client.post("/v1/ask", json={"query": "  "}, headers=_auth("t_emp"))
    assert r.status_code == 400


def test_ask_rejects_unknown_attachment_kind(client):
    r = client.post("/v1/ask", json={
        "query": "hi",
        "attachments": [{"kind": "exe", "filename": "x", "data_b64": "QUJD"}],
    }, headers=_auth("t_emp"))
    assert r.status_code == 400
