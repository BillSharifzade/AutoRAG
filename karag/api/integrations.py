"""HTTP surface of the guided integrations (API sources and databases).

Mounted onto the main app so it shares the auth dependency and the platform;
kept in its own module so ``app.py`` stays the map of the core API.
"""

from __future__ import annotations

import json
import logging

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..connectors.sql import ReadOnlyViolation
from ..domain import DataClass, Principal
from ..errors import KaragError
from ..integrations.analysis import analyze_payload
from ..integrations.payload import EndpointError, profile_payload
from ..web.guard import WebAccessDenied

log = logging.getLogger("karag.api.integrations")


class ProbeRequest(BaseModel):
    url: str
    language: str = "ru"
    comment: str = ""
    previous: dict | None = None


class SourceRequest(BaseModel):
    name: str
    url: str
    description: str = ""
    field_notes: dict = {}
    data_class: DataClass = DataClass.OPERATIONAL
    required_roles: list[str] = []
    skill_enabled: bool = True
    sync_enabled: bool = False
    sync_interval_s: float = 3600.0


class SourceUpdateRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    description: str | None = None
    field_notes: dict | None = None
    data_class: DataClass | None = None
    required_roles: list[str] | None = None
    skill_enabled: bool | None = None
    sync_enabled: bool | None = None
    sync_interval_s: float | None = None


class DbTestRequest(BaseModel):
    kind: str  # sql_postgres | sql_mysql
    host: str
    port: int | None = None
    database: str
    username: str = ""
    password: str = ""
    ssl: bool = False


class DbConnectRequest(DbTestRequest):
    name: str
    # None: start at the narrowest audience the caller is cleared for, until
    # the review step says who it is for
    data_class: DataClass | None = None
    required_roles: list[str] = []
    free_query: bool = True
    knowledge: bool = True
    language: str = "ru"
    comment: str = ""


class DbDescribeRequest(BaseModel):
    comment: str = ""
    language: str | None = None


class DbOptionsRequest(BaseModel):
    name: str | None = None
    free_query: bool | None = None
    knowledge: bool | None = None
    data_class: DataClass | None = None
    required_roles: list[str] | None = None
    description: str | None = None
    # per-table audience: {"employees": "hr"}; null/"" puts a table back on
    # the connection's own audience. Only ever narrows.
    table_classes: dict[str, str | None] | None = None
    # tables the assistant may never query or see
    hidden_tables: list[str] | None = None


# Driver messages → one plain sentence. Found on the deployed server: the
# Data page showed psycopg's raw "connection to server at … failed: …" text to
# pharmacists. The technical text stays, in brackets, for whoever debugs it.
_GATEWAY_REASONS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("password authentication failed", "access denied for user", "authentication failed",
      "no password supplied", "role \"", "login failed"),
     "The database refused the login — check the user name and password."),
    (("unknown database",) , "There is no database with that name on this server."),
    (("could not translate host name", "name or service not known", "nodename nor servname",
      "getaddrinfo", "unknown mysql server host", "temporary failure in name resolution"),
     "The server name could not be found — check the address."),
    (("connection refused", "can't connect", "timed out", "timeout", "no route to host",
      "network is unreachable", "connection reset"),
     "The server did not answer on that address and port."),
    (("ssl", "tls", "certificate"),
     "The secure connection (SSL) failed — try switching SSL on or off."),
    (("file is not a database", "not a database", "malformed"),
     "This file is not a database that can be read."),
    (("permission denied for", "insufficient privilege", "command denied"),
     "The database login works but may not read these tables."),
)


def _gateway_error(exc: Exception) -> HTTPException:
    """A database or endpoint that could not be reached is a 502 with the
    reason in plain words first, then the technical text."""
    technical = f"{type(exc).__name__}: {exc}"
    low = technical.lower()
    if "does not exist" in low and "database" in low:
        plain = "There is no database with that name on this server."
    else:
        plain = next(
            (msg for needles, msg in _GATEWAY_REASONS if any(n in low for n in needles)),
            "The data source could not be reached.",
        )
    return HTTPException(status_code=502, detail=f"{plain} [{technical[:300]}]")


def mount_integrations(app: FastAPI, plat, principal_from) -> None:
    @app.exception_handler(WebAccessDenied)
    async def _web_denied(_request, exc: WebAccessDenied):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ReadOnlyViolation)
    async def _read_only(_request, exc: ReadOnlyViolation):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(EndpointError)
    async def _upstream(_request, exc: EndpointError):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    # ------------------------------------------------------------ sources

    @app.post("/v1/sources/probe")
    async def probe_source(req: ProbeRequest, principal: Principal = Depends(principal_from)) -> dict:
        """Fetch the endpoint once and explain what came back. Stores nothing."""
        try:
            payload = await plat.sources.probe(principal, req.url)
        except KaragError:
            raise
        except Exception as exc:  # noqa: BLE001 — network / TLS / DNS
            raise _gateway_error(exc) from exc
        profile = profile_payload(payload)
        analysis = await analyze_payload(
            plat.gateway.generator, profile, url=payload.url, language=req.language,
            comment=req.comment, previous=req.previous,
        )
        return {
            "url": payload.url,
            "content_type": payload.content_type,
            "kind": payload.kind,
            "bytes": len(payload.raw),
            "truncated": payload.truncated,
            "profile": profile.to_dict(),
            "analysis": analysis,
        }

    @app.get("/v1/sources")
    async def list_sources(principal: Principal = Depends(principal_from)) -> dict:
        return {"sources": [s.to_dict() for s in plat.sources.list(principal)]}

    @app.post("/v1/sources")
    async def create_source(req: SourceRequest, principal: Principal = Depends(principal_from)) -> dict:
        source = await plat.sources.create(
            principal, name=req.name, url=req.url, description=req.description,
            field_notes=req.field_notes, data_class=req.data_class,
            required_roles=tuple(req.required_roles), skill_enabled=req.skill_enabled,
            sync_enabled=req.sync_enabled, sync_interval_s=req.sync_interval_s,
        )
        return source.to_dict()

    @app.get("/v1/sources/{source_id}")
    async def get_source(source_id: str, principal: Principal = Depends(principal_from)) -> dict:
        return plat.sources.get(principal, source_id).to_dict()

    @app.put("/v1/sources/{source_id}")
    async def update_source(
        source_id: str, req: SourceUpdateRequest, principal: Principal = Depends(principal_from)
    ) -> dict:
        changes = {k: v for k, v in req.model_dump().items() if k in req.model_fields_set}
        source = await plat.sources.update(principal, source_id, **changes)
        return source.to_dict()

    @app.delete("/v1/sources/{source_id}")
    async def delete_source(source_id: str, principal: Principal = Depends(principal_from)) -> dict:
        await plat.sources.delete(principal, source_id)
        return {"deleted": source_id}

    @app.post("/v1/sources/{source_id}/sync")
    async def sync_source(source_id: str, principal: Principal = Depends(principal_from)) -> dict:
        outcome = await plat.sources.sync_now(principal, source_id)
        return {
            "status": outcome.status, "records": outcome.records, "error": outcome.error,
            "source": plat.sources.get(principal, source_id).to_dict(),
        }

    # ---------------------------------------------------------- databases

    @app.post("/v1/databases/test")
    async def test_database(req: DbTestRequest, principal: Principal = Depends(principal_from)) -> dict:
        try:
            return await plat.databases.test_connection(
                principal, kind=req.kind, host=req.host, port=req.port, database=req.database,
                username=req.username, password=req.password, ssl=req.ssl,
            )
        except KaragError:
            raise
        except Exception as exc:  # noqa: BLE001 — driver errors
            raise _gateway_error(exc) from exc

    @app.post("/v1/databases/connect")
    async def connect_database(
        req: DbConnectRequest, principal: Principal = Depends(principal_from)
    ) -> dict:
        try:
            return await plat.databases.connect(
                principal, name=req.name, kind=req.kind, host=req.host, port=req.port,
                database=req.database, username=req.username, password=req.password, ssl=req.ssl,
                data_class=req.data_class, required_roles=tuple(req.required_roles),
                free_query=req.free_query, knowledge=req.knowledge, language=req.language,
                comment=req.comment,
            )
        except KaragError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _gateway_error(exc) from exc

    @app.post("/v1/databases/upload")
    async def upload_database(
        file: UploadFile = File(...),
        name: str = Form(""),
        data_class: DataClass | None = Form(None),
        required_roles: str = Form(""),
        free_query: bool = Form(True),
        knowledge: bool = Form(True),
        language: str = Form("ru"),
        comment: str = Form(""),
        principal: Principal = Depends(principal_from),
    ) -> dict:
        data = await file.read()
        filename = file.filename or "upload.db"
        roles = tuple(r.strip() for r in required_roles.split(",") if r.strip())
        try:
            return await plat.databases.upload(
                principal, name=name or filename.rsplit(".", 1)[0], filename=filename, data=data,
                data_class=data_class, required_roles=roles, free_query=free_query,
                knowledge=knowledge, language=language, comment=comment,
            )
        except KaragError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _gateway_error(exc) from exc

    @app.get("/v1/databases/{connector_id}/schema")
    async def database_schema(connector_id: str, principal: Principal = Depends(principal_from)) -> dict:
        try:
            return await plat.databases.schema(principal, connector_id)
        except KaragError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _gateway_error(exc) from exc

    @app.post("/v1/databases/{connector_id}/describe")
    async def describe_database(
        connector_id: str, req: DbDescribeRequest, principal: Principal = Depends(principal_from)
    ) -> dict:
        try:
            return await plat.databases.describe(
                principal, connector_id, comment=req.comment, language=req.language
            )
        except KaragError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _gateway_error(exc) from exc

    @app.patch("/v1/databases/{connector_id}")
    async def update_database(
        connector_id: str, req: DbOptionsRequest, principal: Principal = Depends(principal_from)
    ) -> dict:
        spec = await plat.databases.set_options(
            principal, connector_id, name=req.name, free_query=req.free_query,
            knowledge=req.knowledge, data_class=req.data_class,
            required_roles=tuple(req.required_roles) if req.required_roles is not None else None,
            description=req.description,
            table_classes=req.table_classes, hidden_tables=req.hidden_tables,
        )
        return spec.to_public_dict()

    @app.delete("/v1/databases/{connector_id}")
    async def delete_database(connector_id: str, principal: Principal = Depends(principal_from)) -> dict:
        if not await plat.databases.delete(principal, connector_id):
            raise HTTPException(status_code=404, detail="connection not found")
        return {"deleted": connector_id}

    # keep json referenced for tools that serialise sample rows
    _ = json
