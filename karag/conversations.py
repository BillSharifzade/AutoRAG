"""Chat persistence — saved conversations and history, per principal.

Every saved chat belongs to exactly one ``(tenant_id, user_id)`` owner; the
store never returns a conversation to anyone but its owner, so history can't
leak across users or tenants. Two interchangeable backends implement the same
:class:`ConversationStore` protocol:

* :class:`InMemoryConversationStore` — fast, used by tests and ephemeral runs.
* :class:`SqliteConversationStore` — durable across restarts (one small DB).

Assistant turns keep a trimmed provenance payload (plane, citations, skills,
artifact *summaries*) so a reloaded thread renders exactly like a live one —
but generated file bytes are never stored here.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

from .domain import new_id

Owner = tuple[str, str]  # (tenant_id, user_id)


@dataclass
class StoredMessage:
    role: str  # "user" | "assistant"
    text: str
    ts: float = field(default_factory=time.time)
    # provenance for assistant turns (answer payload minus artifact bytes)
    answer: dict | None = None
    # lightweight attachment descriptors for user turns ({kind, filename})
    attachments: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "text": self.text,
            "ts": self.ts,
            "answer": self.answer,
            "attachments": self.attachments,
        }


@dataclass
class Conversation:
    id: str
    tenant_id: str
    user_id: str
    title: str
    assistant_id: str | None
    created_at: float
    updated_at: float
    messages: list[StoredMessage] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "assistant_id": self.assistant_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [m.to_dict() for m in self.messages],
        }


@dataclass
class ConversationSummary:
    id: str
    title: str
    assistant_id: str | None
    created_at: float
    updated_at: float
    message_count: int
    preview: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "assistant_id": self.assistant_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": self.message_count,
            "preview": self.preview,
        }


def default_title(text: str) -> str:
    """A short, human title from the first user message."""
    t = " ".join((text or "").split())
    if not t:
        return "New chat"
    return t[:48] + ("…" if len(t) > 48 else "")


def _preview(messages: list[StoredMessage]) -> str:
    for m in messages:
        if m.role == "user" and m.text.strip():
            return default_title(m.text)
    for m in messages:
        if m.text.strip():
            return default_title(m.text)
    return "Empty chat"


class ConversationStore(Protocol):
    def create(
        self, owner: Owner, *, title: str = "", assistant_id: str | None = None
    ) -> Conversation: ...
    def get(self, owner: Owner, cid: str) -> Conversation | None: ...
    def list(self, owner: Owner) -> list[ConversationSummary]: ...
    def append(self, owner: Owner, cid: str, message: StoredMessage) -> bool: ...
    def rename(self, owner: Owner, cid: str, title: str) -> bool: ...
    def delete(self, owner: Owner, cid: str) -> bool: ...


# --------------------------------------------------------------------------- #
# In-memory                                                                    #
# --------------------------------------------------------------------------- #


class InMemoryConversationStore:
    def __init__(self) -> None:
        self._by_id: dict[str, Conversation] = {}
        self._lock = threading.Lock()

    def create(
        self, owner: Owner, *, title: str = "", assistant_id: str | None = None
    ) -> Conversation:
        now = time.time()
        conv = Conversation(
            id=new_id("chat"),
            tenant_id=owner[0],
            user_id=owner[1],
            title=title or "New chat",
            assistant_id=assistant_id,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._by_id[conv.id] = conv
        return conv

    def _owned(self, owner: Owner, cid: str) -> Conversation | None:
        conv = self._by_id.get(cid)
        if conv is None or (conv.tenant_id, conv.user_id) != owner:
            return None
        return conv

    def get(self, owner: Owner, cid: str) -> Conversation | None:
        with self._lock:
            return self._owned(owner, cid)

    def list(self, owner: Owner) -> list[ConversationSummary]:
        with self._lock:
            convs = [
                c
                for c in self._by_id.values()
                if (c.tenant_id, c.user_id) == owner
            ]
        convs.sort(key=lambda c: c.updated_at, reverse=True)
        return [
            ConversationSummary(
                id=c.id,
                title=c.title,
                assistant_id=c.assistant_id,
                created_at=c.created_at,
                updated_at=c.updated_at,
                message_count=len(c.messages),
                preview=_preview(c.messages),
            )
            for c in convs
        ]

    def append(self, owner: Owner, cid: str, message: StoredMessage) -> bool:
        with self._lock:
            conv = self._owned(owner, cid)
            if conv is None:
                return False
            conv.messages.append(message)
            conv.updated_at = message.ts
            if conv.title == "New chat" and message.role == "user" and message.text.strip():
                conv.title = default_title(message.text)
            return True

    def rename(self, owner: Owner, cid: str, title: str) -> bool:
        with self._lock:
            conv = self._owned(owner, cid)
            if conv is None:
                return False
            conv.title = title.strip() or conv.title
            conv.updated_at = time.time()
            return True

    def delete(self, owner: Owner, cid: str) -> bool:
        with self._lock:
            conv = self._owned(owner, cid)
            if conv is None:
                return False
            del self._by_id[cid]
            return True


# --------------------------------------------------------------------------- #
# SQLite (durable)                                                             #
# --------------------------------------------------------------------------- #


class SqliteConversationStore:
    """Durable store. Two tables; messages carry a JSON provenance blob."""

    def __init__(self, path: str = "karag_chats.db") -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    assistant_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    conversation_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    ts REAL NOT NULL,
                    answer TEXT,
                    attachments TEXT,
                    PRIMARY KEY (conversation_id, seq)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conv_owner "
                "ON conversations (tenant_id, user_id, updated_at DESC)"
            )

    def create(
        self, owner: Owner, *, title: str = "", assistant_id: str | None = None
    ) -> Conversation:
        now = time.time()
        conv = Conversation(
            id=new_id("chat"),
            tenant_id=owner[0],
            user_id=owner[1],
            title=title or "New chat",
            assistant_id=assistant_id,
            created_at=now,
            updated_at=now,
        )
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO conversations VALUES (?,?,?,?,?,?,?)",
                (
                    conv.id,
                    conv.tenant_id,
                    conv.user_id,
                    conv.title,
                    conv.assistant_id,
                    conv.created_at,
                    conv.updated_at,
                ),
            )
        return conv

    def _row(self, owner: Owner, cid: str) -> sqlite3.Row | None:
        cur = self._conn.execute(
            "SELECT * FROM conversations WHERE id=? AND tenant_id=? AND user_id=?",
            (cid, owner[0], owner[1]),
        )
        return cur.fetchone()

    def get(self, owner: Owner, cid: str) -> Conversation | None:
        with self._lock:
            row = self._row(owner, cid)
            if row is None:
                return None
            msgs = self._conn.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY seq",
                (cid,),
            ).fetchall()
        return Conversation(
            id=row["id"],
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
            title=row["title"],
            assistant_id=row["assistant_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            messages=[
                StoredMessage(
                    role=m["role"],
                    text=m["text"],
                    ts=m["ts"],
                    answer=json.loads(m["answer"]) if m["answer"] else None,
                    attachments=json.loads(m["attachments"]) if m["attachments"] else [],
                )
                for m in msgs
            ],
        )

    def list(self, owner: Owner) -> list[ConversationSummary]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT c.*,
                  (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS n,
                  (SELECT text FROM messages m WHERE m.conversation_id=c.id
                     AND m.role='user' ORDER BY seq LIMIT 1) AS first_user
                FROM conversations c
                WHERE c.tenant_id=? AND c.user_id=?
                ORDER BY c.updated_at DESC
                """,
                (owner[0], owner[1]),
            ).fetchall()
        return [
            ConversationSummary(
                id=r["id"],
                title=r["title"],
                assistant_id=r["assistant_id"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                message_count=r["n"],
                preview=default_title(r["first_user"] or r["title"]),
            )
            for r in rows
        ]

    def append(self, owner: Owner, cid: str, message: StoredMessage) -> bool:
        with self._lock, self._conn:
            row = self._row(owner, cid)
            if row is None:
                return False
            seq = self._conn.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 AS s FROM messages "
                "WHERE conversation_id=?",
                (cid,),
            ).fetchone()["s"]
            self._conn.execute(
                "INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
                (
                    cid,
                    seq,
                    message.role,
                    message.text,
                    message.ts,
                    json.dumps(message.answer) if message.answer else None,
                    json.dumps(message.attachments) if message.attachments else None,
                ),
            )
            title = row["title"]
            if title == "New chat" and message.role == "user" and message.text.strip():
                title = default_title(message.text)
            self._conn.execute(
                "UPDATE conversations SET updated_at=?, title=? WHERE id=?",
                (message.ts, title, cid),
            )
        return True

    def rename(self, owner: Owner, cid: str, title: str) -> bool:
        clean = title.strip()
        with self._lock, self._conn:
            row = self._row(owner, cid)
            if row is None:
                return False
            self._conn.execute(
                "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                (clean or row["title"], time.time(), cid),
            )
        return True

    def delete(self, owner: Owner, cid: str) -> bool:
        with self._lock, self._conn:
            row = self._row(owner, cid)
            if row is None:
                return False
            self._conn.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
            self._conn.execute("DELETE FROM conversations WHERE id=?", (cid,))
        return True
