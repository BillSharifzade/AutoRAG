"""Generated files stay downloadable from the chat history.

Found on the deployed server: an answer's .xlsx downloaded fine right away,
but the stored history kept only its name, so after a reload the report was
gone. Files are now kept with the chat (owner-scoped) and served on demand.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from karag.api.app import create_app
from karag.api.security import InMemoryResolver
from karag.config import Settings
from karag.conversations import InMemoryConversationStore, SqliteConversationStore
from karag.domain import Answer, Artifact, Principal
from karag.factory import build_platform

EMP = Principal("koinoti", "emp", ("employee",))
FIN = Principal("koinoti", "fin", ("finance",))


def _client():
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))

    async def ask(principal, query, **kw):
        return Answer(text="Готово: report.xlsx", plane="knowledge",
                      artifacts=[Artifact(filename="Отчёт.xlsx", mime="application/x-test",
                                          content=b"PK\x03\x04 spreadsheet bytes")])

    plat.orchestrator.ask = ask
    client = TestClient(create_app(plat, InMemoryResolver({"t_emp": EMP, "t_fin": FIN})))
    return plat, client


def test_a_generated_file_survives_a_reload_and_only_its_owner_gets_it():
    plat, client = _client()
    auth = {"Authorization": "Bearer t_emp"}
    cid = client.post("/v1/chats", json={"title": "x"}, headers=auth).json()["id"]
    client.post(f"/v1/chats/{cid}/ask", json={"query": "сделай отчёт"}, headers=auth)

    history = client.get(f"/v1/chats/{cid}", headers=auth).json()["messages"]
    summary = history[-1]["answer"]["artifacts"][0]
    assert summary["filename"] == "Отчёт.xlsx" and summary["file_id"]

    r = client.get(f"/v1/chats/{cid}/files/{summary['file_id']}", headers=auth)
    assert r.status_code == 200 and r.content == b"PK\x03\x04 spreadsheet bytes"
    assert "filename*=UTF-8''%D0%9E%D1%82%D1%87%D1%91%D1%82.xlsx" in r.headers["content-disposition"]

    other = {"Authorization": "Bearer t_fin"}
    assert client.get(f"/v1/chats/{cid}/files/{summary['file_id']}", headers=other).status_code == 404
    assert client.get(f"/v1/chats/{cid}/files/nope", headers=auth).status_code == 404

    client.delete(f"/v1/chats/{cid}", headers=auth)
    assert plat.conversations.get_file(("koinoti", "emp"), cid, summary["file_id"]) is None


def test_both_stores_keep_files_owner_scoped(tmp_path):
    for store in (InMemoryConversationStore(), SqliteConversationStore(str(tmp_path / "c.db"))):
        conv = store.create(("t", "a"), title="x")
        assert store.put_file(("t", "a"), conv.id, "f1", "a.pdf", "application/pdf", b"%PDF")
        assert store.get_file(("t", "a"), conv.id, "f1") == ("a.pdf", "application/pdf", b"%PDF")
        assert store.get_file(("t", "b"), conv.id, "f1") is None
        assert not store.put_file(("t", "b"), conv.id, "f2", "x", "y", b"z")
        store.delete(("t", "a"), conv.id)
        assert store.get_file(("t", "a"), conv.id, "f1") is None
