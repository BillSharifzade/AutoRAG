"""Core domain types shared across the knowledge and data planes.

Pure stdlib on purpose: the domain has no third-party dependency so it can be
imported by tests, adapters, and the API layer without pulling in a web
framework or an LLM SDK.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

Vector = list[float]


def new_id(prefix: str) -> str:
    """Short, prefixed, collision-resistant identifier (e.g. ``doc_1a2b...``)."""
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


class DataClass(str, Enum):
    """Sensitivity classes attached to every document, chunk and skill.

    These are *not* a linear hierarchy (HR is not "less than" financial); which
    roles may see which classes is defined explicitly in :mod:`karag.rbac`.
    Anything unclassified is treated as the most restrictive (fail-closed).
    """

    PUBLIC = "public"
    OPERATIONAL = "operational"
    HR = "hr"
    FINANCIAL = "financial"
    REGULATED = "regulated"

    @classmethod
    def most_restrictive(cls) -> "DataClass":
        return cls.REGULATED


@dataclass(frozen=True)
class Principal:
    """An authenticated actor: who they are, and which tenant they belong to.

    Roles are role *names* (strings) resolved against the RBAC matrix. A
    principal only ever operates within a single tenant; cross-tenant access is
    impossible by construction.
    """

    tenant_id: str
    user_id: str
    roles: tuple[str, ...]

    def has_any_role(self, roles: frozenset[str]) -> bool:
        if not roles:
            return True  # empty requirement == any authenticated principal
        return bool(set(self.roles) & roles)


@dataclass
class Document:
    id: str
    tenant_id: str
    title: str
    data_class: DataClass
    source_uri: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Chunk:
    """A retrievable unit of a document, carrying its own tenant + class tags.

    The tags are duplicated onto every chunk (rather than looked up via the
    parent document) so the vector store can filter *at query time* in a single
    pass, without a join and without the possibility of a stale tag.
    """

    id: str
    document_id: str
    tenant_id: str
    data_class: DataClass
    ordinal: int
    text: str
    title: str
    source_uri: str | None = None
    embedding: Vector | None = None


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float


@dataclass
class DocumentSummary:
    """A document as it appears in the knowledge-plane catalogue.

    Derived from the stored chunks rather than kept in a separate table, so the
    catalogue can never disagree with what is actually retrievable — and so the
    same ``allowed_classes`` filter that governs retrieval governs the listing.
    """

    document_id: str
    title: str
    data_class: DataClass
    source_uri: str | None
    chunks: int

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "data_class": self.data_class.value,
            "source_uri": self.source_uri,
            "chunks": self.chunks,
        }


@dataclass
class Citation:
    marker: str
    document_id: str
    chunk_id: str
    title: str
    source_uri: str | None
    snippet: str


@dataclass
class Artifact:
    """A generated business document (Office file) produced by an output skill.

    The bytes are carried out-of-band from the model's context — the model only
    ever sees a short confirmation, never the file payload.
    """

    filename: str
    mime: str
    content: bytes

    def to_summary(self) -> dict:
        return {"filename": self.filename, "mime": self.mime, "size_bytes": len(self.content)}


@dataclass
class Answer:
    """The unit returned to callers, carrying provenance for verification."""

    text: str
    citations: list[Citation] = field(default_factory=list)
    plane: str = "knowledge"  # knowledge | data | mixed | refusal
    skills_used: list[str] = field(default_factory=list)
    queries_shown: list[str] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
