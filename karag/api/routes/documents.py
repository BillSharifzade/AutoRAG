"""The knowledge plane over HTTP: ingest text and files, list, delete, classify."""

from __future__ import annotations

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile

from ...audit import AuditEvent
from ...domain import DataClass, Principal
from ...errors import AccessDenied
from ...ingestion.readers import extract_text, UnsupportedFormat
from ...knowledge.classify import suggest_data_class
from ...rbac import INGEST_ROLES, visible_classes
from ..common import (
    ApiContext,
    IngestRequest,
)


def mount(app: FastAPI, ctx: ApiContext) -> None:
    plat = ctx.plat
    principal_from = ctx.principal_from

    @app.post("/v1/ingest")
    async def ingest(req: IngestRequest, principal: Principal = Depends(principal_from)) -> dict:
        try:
            doc = await plat.ingestion.ingest_document(
                principal, title=req.title, text=req.text,
                data_class=req.data_class, source_uri=req.source_uri,
            )
        except AccessDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {
            "document_id": doc.id, "data_class": doc.data_class.value,
            "replaced": doc.metadata.get("replaced", []),
        }

    @app.post("/v1/ingest/file")
    async def ingest_file(
        file: UploadFile = File(...),
        data_class: DataClass = Form(DataClass.OPERATIONAL),
        principal: Principal = Depends(principal_from),
    ) -> dict:
        data = await file.read()
        try:
            doc = await plat.ingestion.ingest_file(
                principal, filename=file.filename or "upload", data=data,
                data_class=data_class,
            )
        except AccessDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except UnsupportedFormat as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        return {
            "document_id": doc.id, "data_class": doc.data_class.value,
            "replaced": doc.metadata.get("replaced", []),
        }

    @app.get("/v1/documents")
    async def list_documents(principal: Principal = Depends(principal_from)) -> dict:
        """The knowledge catalogue, filtered exactly like retrieval is.

        A title is a disclosure in itself, so an HR user listing documents does
        not see that a financial one exists.
        """
        docs = await plat.store.list_documents(
            tenant_id=principal.tenant_id, allowed_classes=visible_classes(principal)
        )
        return {"documents": [d.to_dict() for d in docs]}

    @app.delete("/v1/documents/{document_id}")
    async def delete_document(
        document_id: str, principal: Principal = Depends(principal_from)
    ) -> dict:
        if not principal.has_any_role(INGEST_ROLES):
            raise HTTPException(status_code=403, detail="ingest role required")
        # Only documents the caller can actually see are deletable — otherwise
        # deletion becomes an oracle for what exists in a class you can't read.
        visible = {
            d.document_id
            for d in await plat.store.list_documents(
                tenant_id=principal.tenant_id, allowed_classes=visible_classes(principal)
            )
        }
        if document_id not in visible:
            raise HTTPException(status_code=404, detail="document not found")
        removed = await plat.store.delete_document(
            tenant_id=principal.tenant_id, document_id=document_id
        )
        plat.audit.record(AuditEvent(
            action="document_delete", tenant_id=principal.tenant_id,
            user_id=principal.user_id, decision="allow", resource=document_id,
            detail={"chunks": removed},
        ))
        return {"deleted": document_id, "chunks": removed}

    @app.post("/v1/documents/classify")
    async def classify_document(
        file: UploadFile = File(...),
        principal: Principal = Depends(principal_from),
    ) -> dict:
        """Propose a data class for an upload — advisory only (§7).

        Nothing is stored and nothing is ingested by this call. The uploader
        sees the suggestion and the terms behind it, then chooses.
        """
        data = await file.read()
        name = file.filename or "upload"
        try:
            text = extract_text(name, data)
        except UnsupportedFormat as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        return suggest_data_class(title=name, text=text, filename=name).to_dict()
