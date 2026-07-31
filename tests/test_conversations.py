"""Chat persistence — store units + the /v1/chats HTTP surface."""

import pytest
from fastapi.testclient import TestClient

from karag.api.app import create_app
from karag.api.security import InMemoryResolver
from karag.config import Settings
from karag.conversations import (
    InMemoryConversationStore,
    SqliteConversationStore,
    StoredMessage,
)
from karag.domain import Principal
from karag.factory import build_platform

OWNER = ("koinoti", "u1")
OTHER = ("koinoti", "u2")


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryConversationStore()
    return SqliteConversationStore(str(tmp_path / "chats.db"))


def test_create_append_and_get(store):
    conv = store.create(OWNER)
    assert conv.title == "New chat"
    store.append(OWNER, conv.id, StoredMessage(role="user", text="What is the policy?"))
    store.append(OWNER, conv.id, StoredMessage(role="assistant", text="14 days."))
    got = store.get(OWNER, conv.id)
    assert [m.text for m in got.messages] == ["What is the policy?", "14 days."]
    # first user message auto-titles the chat
    assert got.title == "What is the policy?"


def test_owner_isolation(store):
    conv = store.create(OWNER)
    assert store.get(OTHER, conv.id) is None
    assert store.append(OTHER, conv.id, StoredMessage(role="user", text="x")) is False
    assert store.delete(OTHER, conv.id) is False
    assert store.list(OTHER) == []


def test_list_orders_newest_first_with_preview(store):
    a = store.create(OWNER)
    b = store.create(OWNER)
    store.append(OWNER, a.id, StoredMessage(role="user", text="older"))
    store.append(OWNER, b.id, StoredMessage(role="user", text="newer"))
    summaries = store.list(OWNER)
    assert summaries[0].id == b.id
    assert summaries[0].preview == "newer"
    assert summaries[0].message_count == 1


def test_rename_and_delete(store):
    conv = store.create(OWNER)
    assert store.rename(OWNER, conv.id, "Renamed") is True
    assert store.get(OWNER, conv.id).title == "Renamed"
    assert store.delete(OWNER, conv.id) is True
    assert store.get(OWNER, conv.id) is None


# --- HTTP surface ---------------------------------------------------------- #


@pytest.fixture
def client():
    plat = build_platform(
        Settings(generator="fake", embedder="fake", store="memory", chat_store="memory")
    )
    resolver = InMemoryResolver({
        "t_a": Principal("koinoti", "alice", ("employee",)),
        "t_b": Principal("koinoti", "bob", ("employee",)),
    })
    return TestClient(create_app(plat, resolver))


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_chat_flow_persists_and_answers(client):
    created = client.post("/v1/chats", json={}, headers=_auth("t_a"))
    assert created.status_code == 200
    cid = created.json()["id"]

    r = client.post(f"/v1/chats/{cid}/ask", json={"query": "hello"}, headers=_auth("t_a"))
    assert r.status_code == 200
    assert "answer" in r.json()

    full = client.get(f"/v1/chats/{cid}", headers=_auth("t_a")).json()
    roles = [m["role"] for m in full["messages"]]
    assert roles == ["user", "assistant"]
    assert full["title"] != "New chat"  # auto-titled from first message

    listed = client.get("/v1/chats", headers=_auth("t_a")).json()["chats"]
    assert any(c["id"] == cid for c in listed)


def test_chat_history_is_private_to_owner(client):
    cid = client.post("/v1/chats", json={}, headers=_auth("t_a")).json()["id"]
    # bob cannot see, load, or post to alice's chat
    assert client.get("/v1/chats", headers=_auth("t_b")).json()["chats"] == []
    assert client.get(f"/v1/chats/{cid}", headers=_auth("t_b")).status_code == 404
    assert client.post(
        f"/v1/chats/{cid}/ask", json={"query": "peek"}, headers=_auth("t_b")
    ).status_code == 404


def test_rename_and_delete_endpoints(client):
    cid = client.post("/v1/chats", json={}, headers=_auth("t_a")).json()["id"]
    assert client.patch(
        f"/v1/chats/{cid}", json={"title": "My chat"}, headers=_auth("t_a")
    ).json()["title"] == "My chat"
    assert client.delete(f"/v1/chats/{cid}", headers=_auth("t_a")).status_code == 200
    assert client.get(f"/v1/chats/{cid}", headers=_auth("t_a")).status_code == 404
