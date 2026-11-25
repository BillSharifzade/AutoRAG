"""Ingestion: classify, chunk, embed, and store a document.

Every chunk inherits the document's ``tenant_id`` and ``data_class`` so the
store can filter on them at query time. Classification is fail-closed: if no
class is supplied it defaults to the most restrictive one.
"""

from __future__ import annotations

import os
from typing import Awaitable, Callable

from ..audit import AuditEvent, AuditLog, NullAuditLog
from ..domain import Chunk, DataClass, Document, Principal, new_id
from ..errors import AccessDenied, ValidationError
from ..ingestion import extract_text
from ..llm.base import Embedder
from ..rbac import can_ingest, visible_classes
from ..vectorstore.base import VectorStore
from .chunking import HEADING_SEP, Piece, chunk_document, chunk_text

# Reads a scanned PDF's pages and returns their text (see karag.llm.ocr).
PdfOcr = Callable[[bytes], Awaitable[str]]

# Below this many characters per page a PDF is treated as a scan: a real text
# layer has hundreds; a scan has none, or a stray page number.
_SCAN_CHARS_PER_PAGE = 40


def _same_title(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def _section(heading: str, title: str) -> str:
    """The heading path without a first level that only repeats the title."""
    parts = [p for p in heading.split(HEADING_SEP) if p]
    if parts and _same_title(parts[0], title):
        parts = parts[1:]
    return HEADING_SEP.join(parts)


def embedding_text(title: str, heading: str, text: str) -> str:
    """What a passage is embedded as: the passage *with* its context.

    "Оклад — 4 200 сомони" alone says little; under "Положение об оплате
    труда › Должностные оклады" it says exactly what it is. The context is
    added only to the embedding input — the stored and displayed text is the
    passage itself.
    """
    head = f"{title} — {heading}" if heading else title
    return f"{head}\n\n{text}"


class IngestionService:
    def __init__(
        self,
        store: VectorStore,
        embedder: Embedder,
        *,
        max_chars: int = 800,
        overlap: int = 120,
        audit: AuditLog | None = None,
        structured: bool = True,
        ocr: PdfOcr | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._max_chars = max_chars
        self._overlap = overlap
        self._audit = audit or NullAuditLog()
        # section-aware chunks embedded together with their title + heading
        self._structured = structured
        self._ocr = ocr

    async def ingest_file(
        self,
        principal: Principal,
        *,
        filename: str,
        data: bytes,
        data_class: DataClass | None = None,
        source_uri: str | None = None,
        metadata: dict | None = None,
    ) -> Document:
        """Extract text from a real document (.docx/.xlsx/.pptx/.pdf/.csv/.txt/.md)
        and ingest it into the knowledge plane.

        A PDF without a text layer (a scan, a photo of a page) is read by the
        configured OCR model; with none configured it is refused with a reason
        rather than stored as an empty document nobody can find.
        """
        text = extract_text(filename, data)
        meta = {"filename": filename, **(metadata or {})}
        if os.path.splitext(filename)[1].lower() == ".pdf":
            from ..ingestion.readers import pdf_page_count  # noqa: PLC0415

            pages = max(1, pdf_page_count(data))
            if len(text.strip()) < _SCAN_CHARS_PER_PAGE * pages:
                if self._ocr is None:
                    raise ValidationError(
                        "this PDF has no text layer (it looks scanned) and page "
                        "reading is switched off (KARAG_PDF_OCR)"
                    )
                text = (await self._ocr(data)).strip()
                meta["ocr"] = True
        if not text.strip():
            raise ValidationError(f"no text could be read from {filename}")
        title = (metadata or {}).get("title") or filename
        return await self.ingest_document(
            principal,
            title=title,
            text=text,
            data_class=data_class,
            source_uri=source_uri or filename,
            metadata=meta,
        )

    async def ingest_document(
        self,
        principal: Principal,
        *,
        title: str,
        text: str,
        data_class: DataClass | None = None,
        source_uri: str | None = None,
        metadata: dict | None = None,
        replace_existing: bool = True,
    ) -> Document:
        """Chunk, embed and store a document.

        Adding a document whose title already exists in the tenant *replaces*
        the earlier copy (``replace_existing``): people re-upload the corrected
        price list under the same name and expect one price list, not two —
        and duplicates would fill every retrieval slot with the same passage.
        The replaced document id is recorded in ``metadata["replaced"]``.
        """
        # Fail closed on missing classification.
        klass = data_class or DataClass.most_restrictive()

        if not can_ingest(principal, klass):
            self._audit.record(AuditEvent(
                action="ingest", tenant_id=principal.tenant_id, user_id=principal.user_id,
                decision="deny", resource=title, detail={"data_class": klass.value},
            ))
            raise AccessDenied(
                f"{principal.user_id} may not ingest {klass.value} data"
            )

        replaced: list[str] = []
        if replace_existing:
            # Only what the uploader can see is a candidate: a title they are
            # not cleared for must not become an oracle for its existence.
            existing = await self._store.list_documents(
                tenant_id=principal.tenant_id,
                allowed_classes=visible_classes(principal),
            )
            for old in existing:
                if _same_title(old.title, title):
                    await self._store.delete_document(
                        tenant_id=principal.tenant_id, document_id=old.document_id
                    )
                    replaced.append(old.document_id)
        meta = dict(metadata or {})
        if replaced:
            meta["replaced"] = replaced

        doc = Document(
            id=new_id("doc"),
            tenant_id=principal.tenant_id,
            title=title,
            data_class=klass,
            source_uri=source_uri,
            metadata=meta,
        )

        if self._structured:
            pieces = [
                Piece(p.text, _section(p.heading, title))
                for p in chunk_document(text, max_chars=self._max_chars, overlap=self._overlap)
            ]
        else:
            pieces = [
                Piece(t) for t in chunk_text(text, max_chars=self._max_chars, overlap=self._overlap)
            ]
        detail = {"title": title, "data_class": klass.value, "chunks": len(pieces)}
        if replaced:
            detail["replaced"] = replaced
        self._audit.record(AuditEvent(
            action="ingest", tenant_id=principal.tenant_id, user_id=principal.user_id,
            decision="allow", resource=doc.id, detail=detail,
        ))
        if not pieces:
            return doc

        inputs = [
            embedding_text(title, p.heading, p.text) if self._structured else p.text
            for p in pieces
        ]
        embeddings = await self._embedder.embed(inputs)
        chunks = [
            Chunk(
                id=new_id("chunk"),
                document_id=doc.id,
                tenant_id=doc.tenant_id,
                data_class=doc.data_class,
                ordinal=i,
                text=piece.text,
                title=doc.title,
                source_uri=doc.source_uri,
                embedding=emb,
                heading=piece.heading,
            )
            for i, (piece, emb) in enumerate(zip(pieces, embeddings))
        ]
        await self._store.upsert(chunks)
        return doc
