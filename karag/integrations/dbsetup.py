"""Connecting a database without an engineer.

Three ways in, one result:

* **login details** for PostgreSQL or MySQL — the DSN is built here, the
  connection tested, the schema read;
* **a SQLite file** — stored under the upload directory and opened read-only;
* **a SQL dump** (``mysqldump`` / ``pg_dump`` / plain SQL) — imported into a
  fresh SQLite file, best effort, with a report of every statement that could
  not be taken.

Whatever the way in, the schema is described by the model, the description is
written into the knowledge plane so the assistant knows what the database
holds, and — if the person allows it — a guarded *query skill* lets the
assistant write its own read-only SELECT at chat time. Every query still goes
through the connector's read-only transaction, row limit and timeout, and is
shown to the reader with the answer.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from ..audit import AuditEvent, AuditLog, NullAuditLog
from ..connectors.registry import (
    MYSQL,
    POSTGRES,
    SQLITE,
    ConnectorNotFound,
    ConnectorSpec,
    ConnectorStore,
    build_connector,
    build_dsn,
    is_sql_kind,
)
from ..connectors.sql import SqlConnector
from ..domain import DataClass, Principal, new_id
from ..errors import AccessDenied, ValidationError
from ..knowledge.ingest import IngestionService
from ..llm.base import Generator
from ..rbac import can_access
from ..skills.base import Skill, SkillResult
from ..skills.catalog import SkillCatalog, can_author
from ..skills.registry import SkillRegistry
from ..vectorstore.base import VectorStore
from .analysis import describe_schema, slug

QUERY_ROW_LIMIT = 200
SUMMARY_MAX_CHARS = 7000
ALLOWED_UPLOADS = (".db", ".sqlite", ".sqlite3", ".sql")
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
_SQLITE_MAGIC = b"SQLite format 3\x00"


# ------------------------------------------------------------- SQL dumps


@dataclass
class ImportReport:
    statements: int = 0
    executed: int = 0
    failed: list[dict] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    rows: int = 0

    def to_dict(self) -> dict:
        return {
            "statements": self.statements, "executed": self.executed,
            "failed": self.failed[:50], "failed_count": len(self.failed),
            "tables": self.tables, "rows": self.rows,
        }


_LINE_SKIP = re.compile(
    r"^\s*(SET\s|LOCK\s+TABLES|UNLOCK\s+TABLES|USE\s|DELIMITER\s|START\s+TRANSACTION|COMMIT\b|"
    r"BEGIN\b|SELECT\s+pg_catalog\.|ALTER\s+TABLE\s+\S+\s+OWNER\s+TO|CREATE\s+SEQUENCE|"
    r"ALTER\s+SEQUENCE|CREATE\s+EXTENSION|COMMENT\s+ON|GRANT\s|REVOKE\s|CREATE\s+SCHEMA|"
    r"ALTER\s+TABLE\s+(ONLY\s+)?\S+\s+ADD\s+CONSTRAINT|ALTER\s+TABLE\s+(ONLY\s+)?\S+\s+ALTER\s+COLUMN|"
    r"COPY\s+\S+.*FROM\s+stdin|CREATE\s+INDEX|"
    r"CREATE\s+UNIQUE\s+INDEX|CREATE\s+TRIGGER|CREATE\s+FUNCTION|CREATE\s+OR\s+REPLACE|"
    r"DROP\s+(TABLE|INDEX|SEQUENCE|VIEW|TRIGGER|FUNCTION)|CREATE\s+DATABASE|DROP\s+DATABASE)",
    re.IGNORECASE,
)
_MYSQL_TABLE_OPTS = re.compile(
    r"\)\s*(ENGINE|DEFAULT\s+CHARSET|CHARSET|COLLATE|AUTO_INCREMENT|COMMENT|ROW_FORMAT)[^;]*$",
    re.IGNORECASE | re.S,
)
_COL_NOISE = [
    (re.compile(r"\bUNSIGNED\b", re.I), ""),
    (re.compile(r"\bZEROFILL\b", re.I), ""),
    (re.compile(r"\bAUTO_INCREMENT\b", re.I), ""),
    (re.compile(r"\bCHARACTER\s+SET\s+\w+", re.I), ""),
    (re.compile(r"\bCOLLATE\s+[\w.]+", re.I), ""),
    (re.compile(r"\bCOMMENT\s+'(?:[^']|'')*'", re.I), ""),
    (re.compile(r"\bON\s+UPDATE\s+CURRENT_TIMESTAMP(?:\(\d*\))?", re.I), ""),
    (re.compile(r"\bDEFAULT\s+CURRENT_TIMESTAMP\(\d+\)", re.I), "DEFAULT CURRENT_TIMESTAMP"),
    (re.compile(r"\bENUM\s*\([^)]*\)", re.I), "TEXT"),
    (re.compile(r"\bSET\s*\('[^)]*\)", re.I), "TEXT"),
    (re.compile(r"\bcharacter\s+varying(\(\d+\))?", re.I), "TEXT"),
    (re.compile(r"\btimestamp(\(\d+\))?\s+(with|without)\s+time\s+zone", re.I), "TIMESTAMP"),
    (re.compile(r"\bnextval\('[^']*'(::regclass)?\)", re.I), "NULL"),
    (re.compile(r"::[a-z_ ]+(\[\])?(\(\d+\))?", re.I), ""),
    (re.compile(r"\bpublic\.", re.I), ""),
    (re.compile(r"\bDEFERRABLE\s+INITIALLY\s+DEFERRED", re.I), ""),
]
_KEY_LINE = re.compile(
    r"^\s*(UNIQUE\s+KEY|UNIQUE\s+INDEX|KEY|INDEX|FULLTEXT\s+KEY|SPATIAL\s+KEY)\s+[`\"]?\w*[`\"]?\s*\(",
    re.I,
)


_PSQL_META = re.compile(r"^\\(?!\.)\S.*$", re.M)


def _split_statements(text: str) -> list[str]:
    r"""Split on ``;`` outside quotes and comments; COPY blocks become INSERTs.

    psql meta-commands (``\restrict``, ``\connect``, ``\unrestrict`` — pg_dump
    17 emits them) end at the newline, not at a semicolon, so they are removed
    up front; ``\.`` stays because it terminates a COPY block.
    """
    text = _PSQL_META.sub("", text)
    out: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                if i + 1 < n and text[i + 1] == quote:  # doubled quote
                    buf.append(quote)
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if text.startswith("--", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
            i += 1
            # a Postgres COPY ... FROM stdin; block follows until a lone "\."
            if re.match(r"^\s*COPY\s", stmt, re.I) and re.search(r"FROM\s+stdin", stmt, re.I):
                end = text.find("\n\\.", i)
                block = text[i:end if end != -1 else n]
                out.extend(_copy_to_inserts(stmt, block))
                i = n if end == -1 else end + 3
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def _copy_to_inserts(copy_stmt: str, block: str) -> list[str]:
    m = re.match(r"^\s*COPY\s+([\w.\"]+)\s*(\(([^)]*)\))?", copy_stmt, re.I)
    if not m:
        return []
    table = m.group(1).replace('"', "").split(".")[-1]
    cols = m.group(3)
    col_sql = f" ({cols})" if cols else ""
    inserts = []
    for line in block.strip("\n").splitlines():
        if not line or line == "\\.":
            continue
        values = []
        for raw in line.split("\t"):
            if raw == "\\N":
                values.append("NULL")
            else:
                cell = raw.replace("\\t", "\t").replace("\\n", "\n").replace("\\\\", "\\")
                values.append("'" + cell.replace("'", "''") + "'")
        inserts.append(f'INSERT INTO "{table}"{col_sql} VALUES ({", ".join(values)})')
    return inserts


def _convert_statement(stmt: str) -> str | None:
    """MySQL / Postgres syntax → what SQLite accepts; None = skip on purpose."""
    if _LINE_SKIP.match(stmt) or stmt.lstrip().startswith("\\"):
        return None
    s = stmt.replace("`", '"')
    if re.match(r"^\s*CREATE\s+TABLE", s, re.I):
        s = _MYSQL_TABLE_OPTS.sub(")", s)
        s = re.sub(r"\bIF\s+NOT\s+EXISTS\b", "IF NOT EXISTS", s, flags=re.I)
        lines = []
        for line in s.splitlines():
            if _KEY_LINE.match(line):
                if re.match(r"^\s*UNIQUE", line, re.I):
                    line = re.sub(r"^\s*UNIQUE\s+(KEY|INDEX)\s+[`\"]?\w*[`\"]?\s*", "  UNIQUE ", line, flags=re.I)
                else:
                    continue  # secondary indexes are dropped; queries still work
            lines.append(line)
        s = "\n".join(lines)
        # a dangling comma before the closing paren after dropped KEY lines
        s = re.sub(r",\s*\)", "\n)", s)
    for pattern, repl in _COL_NOISE:
        s = pattern.sub(repl, s)
    s = re.sub(r"\bINSERT\s+IGNORE\s+INTO\b", "INSERT OR IGNORE INTO", s, flags=re.I)
    s = re.sub(r"\bREPLACE\s+INTO\b", "INSERT OR REPLACE INTO", s, flags=re.I)
    s = re.sub(r"\bINSERT\s+INTO\s+ONLY\s+", "INSERT INTO ", s, flags=re.I)
    return s.strip()


def import_sql_dump(text: str, sqlite_path: str | Path) -> ImportReport:
    """Run a dump into a new SQLite file; keep going past statements that fail."""
    report = ImportReport()
    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        for raw in _split_statements(text):
            report.statements += 1
            stmt = _convert_statement(raw)
            if stmt is None:
                continue
            try:
                cur = conn.execute(stmt)
                report.executed += 1
                if re.match(r"^\s*INSERT", stmt, re.I) and cur.rowcount > 0:
                    report.rows += cur.rowcount
            except sqlite3.Error as exc:
                report.failed.append({"statement": stmt[:200], "error": str(exc)[:200]})
        conn.commit()
        report.tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
    finally:
        conn.close()
    return report


# -------------------------------------------------------------- uploads


def save_upload(upload_dir: str | Path, tenant_id: str, filename: str, data: bytes) -> Path:
    """Store an uploaded database file where the connector can open it."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_UPLOADS:
        raise ValidationError(f"unsupported file type {ext or '(none)'}; upload .sqlite, .db or .sql")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValidationError("that file is larger than the 512 MB limit")
    if ext != ".sql" and not data.startswith(_SQLITE_MAGIC):
        raise ValidationError("that file is not a SQLite database")
    folder = Path(upload_dir) / re.sub(r"[^\w.-]", "_", tenant_id)
    folder.mkdir(parents=True, exist_ok=True)
    stem = slug(Path(filename).stem) or "upload"
    target = folder / f"{stem}_{new_id('db')[3:11]}{'.db' if ext == '.sql' else ext}"
    if ext == ".sql":
        return target  # the caller imports the dump into this path
    target.write_bytes(data)
    return target


# --------------------------------------------------------- descriptions


def schema_summary(schema: dict, meanings: dict[str, str] | None = None) -> str:
    """A compact schema for a tool description: ``table(col type, …) ~rows``.

    One example row per table travels with it, so the model sees what values
    actually look like (``sku='AMOX-500'``) and writes the right filter the
    first time instead of exploring.
    """
    meanings = meanings or {}
    lines = []
    for t in schema.get("tables", []):
        cols = ", ".join(f"{c['name']} {c.get('type', '')}".strip() for c in t["columns"][:30])
        if len(t["columns"]) > 30:
            cols += ", …"
        rows = f" ~{t['row_estimate']} rows" if t.get("row_estimate") is not None else ""
        meaning = meanings.get(t["name"], "")
        line = f"{t['name']}({cols}){rows}"
        if meaning:
            line += f" — {meaning}"
        if t.get("sample"):
            example = ", ".join(f"{k}={v!r}" for k, v in list(t["sample"][0].items())[:8])
            line += f" e.g. {example[:160]}"
        lines.append(line)
    text = "\n".join(lines)
    if len(text) > SUMMARY_MAX_CHARS:
        text = text[:SUMMARY_MAX_CHARS] + "\n…"
    return text


def render_schema_doc(name: str, schema: dict, report: dict) -> str:
    """The database, described for the knowledge plane."""
    meanings = {t["name"]: t["meaning"] for t in report.get("tables", [])}
    lines = [f"{name} — database", report.get("summary", ""), ""]
    for t in schema.get("tables", []):
        head = f"Table {t['name']}"
        if t.get("row_estimate") is not None:
            head += f" (~{t['row_estimate']} rows)"
        if meanings.get(t["name"]):
            head += f": {meanings[t['name']]}"
        lines.append(head)
        lines.append("Columns: " + ", ".join(f"{c['name']} ({c.get('type', '')})" for c in t["columns"][:60]))
        if t.get("sample"):
            first = t["sample"][0]
            lines.append("Example row: " + "; ".join(f"{k}: {v}" for k, v in list(first.items())[:20]))
        lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------ query skill


def make_query_skill(spec: ConnectorSpec, connector: SqlConnector) -> Skill:
    """The assistant's own read-only window on a connected database."""
    meta = spec.metadata
    summary = meta.get("schema_summary", "")
    description = (
        f"Run a read-only SQL SELECT on the database '{spec.name}' "
        f"({connector.backend}). {meta.get('description', '')} "
        "Use it when a question needs figures from this database. Write standard "
        "SQL for this backend, one SELECT statement, with a LIMIT. Tables and "
        f"columns:\n{summary}"
    )[:8000]

    async def handler(principal: Principal, args: dict) -> SkillResult:
        sql = str(args.get("sql", ""))
        rows = await connector.query(sql, {}, row_limit=QUERY_ROW_LIMIT)
        return SkillResult(
            data={"rows": rows, "count": len(rows), "limit": QUERY_ROW_LIMIT},
            query_shown=sql.strip(),
        )

    return Skill(
        name=query_skill_name(spec),
        description=description,
        input_schema={
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "One read-only SELECT statement."},
                "purpose": {"type": "string", "description": "What the query is for, in a few words."},
            },
            "required": ["sql"],
            "additionalProperties": False,
        },
        handler=handler,
        required_data_class=DataClass(meta.get("data_class", DataClass.OPERATIONAL.value)),
        required_roles=frozenset(meta.get("required_roles", [])),
        tenant_id=spec.tenant_id,
    )


def query_skill_name(spec: ConnectorSpec) -> str:
    return "query_" + slug(spec.name)


# ---------------------------------------------------------------- service


class DatabaseService:
    def __init__(
        self,
        catalog: SkillCatalog,
        connectors: ConnectorStore,
        registry: SkillRegistry,
        ingestion: IngestionService,
        vectors: VectorStore,
        *,
        generator: Generator | None,
        upload_dir: str | Path,
        audit: AuditLog | None = None,
    ) -> None:
        self._catalog = catalog
        self._connectors = connectors
        self._registry = registry
        self._ingestion = ingestion
        self._vectors = vectors
        self._generator = generator
        self._upload_dir = Path(upload_dir)
        self._audit = audit or NullAuditLog()

    # ---- the guided flow ----------------------------------------------------

    async def test_connection(self, principal: Principal, *, kind: str, host: str, port: int | None,
                              database: str, username: str, password: str, ssl: bool = False) -> dict:
        self._require_author(principal)
        dsn = build_dsn(kind, host=host, port=port, database=database, username=username,
                        password=password, ssl=ssl)
        connector = SqlConnector(pg_dsn=dsn) if kind == POSTGRES else SqlConnector(mysql_dsn=dsn)
        await connector.test()
        schema = await connector.introspect(max_tables=200, sample_rows=0)
        return {"ok": True, "tables": schema["table_count"], "backend": connector.backend}

    async def connect(
        self,
        principal: Principal,
        *,
        name: str,
        kind: str,
        host: str = "",
        port: int | None = None,
        database: str = "",
        username: str = "",
        password: str = "",
        ssl: bool = False,
        data_class: DataClass = DataClass.OPERATIONAL,
        required_roles: tuple[str, ...] = (),
        free_query: bool = True,
        knowledge: bool = True,
        language: str = "ru",
        comment: str = "",
    ) -> dict:
        """Login details → tested connection → described schema → connector."""
        self._require_author(principal)
        if kind not in (POSTGRES, MYSQL):
            raise ValidationError("connect with login details works for postgres and mysql")
        dsn = build_dsn(kind, host=host, port=port, database=database, username=username,
                        password=password, ssl=ssl)
        return await self._onboard(
            principal, name=name, kind=kind, config={"dsn": dsn},
            data_class=data_class, required_roles=required_roles, free_query=free_query,
            knowledge=knowledge, language=language, comment=comment,
            source="connect", extra={"host": host, "database": database},
        )

    async def upload(
        self,
        principal: Principal,
        *,
        name: str,
        filename: str,
        data: bytes,
        data_class: DataClass = DataClass.OPERATIONAL,
        required_roles: tuple[str, ...] = (),
        free_query: bool = True,
        knowledge: bool = True,
        language: str = "ru",
        comment: str = "",
    ) -> dict:
        """A SQLite file or a SQL dump → a local read-only database."""
        self._require_author(principal)
        path = save_upload(self._upload_dir, principal.tenant_id, filename, data)
        extra: dict = {"filename": filename, "bytes": len(data)}
        if filename.lower().endswith(".sql"):
            report = import_sql_dump(data.decode("utf-8", errors="replace"), path)
            extra["import"] = report.to_dict()
            if not report.tables:
                path.unlink(missing_ok=True)
                raise ValidationError(
                    "no table could be created from that SQL file"
                    + (f" — first error: {report.failed[0]['error']}" if report.failed else "")
                )
        return await self._onboard(
            principal, name=name, kind=SQLITE, config={"path": str(path)},
            data_class=data_class, required_roles=required_roles, free_query=free_query,
            knowledge=knowledge, language=language, comment=comment,
            source="upload", extra=extra,
        )

    async def _onboard(self, principal, *, name, kind, config, data_class, required_roles,
                       free_query, knowledge, language, comment, source, extra) -> dict:
        if not name.strip():
            raise ValidationError("the database needs a name")
        if not can_access(principal, data_class):
            raise AccessDenied("you are not cleared for that data class and may not publish it")
        probe = ConnectorSpec(id="probe", tenant_id=principal.tenant_id, name=name, kind=kind, config=config)
        connector = build_connector(probe)
        assert isinstance(connector, SqlConnector)
        await connector.test()
        schema = await connector.introspect()
        report = await describe_schema(self._generator, schema, name=name, language=language, comment=comment)
        meanings = {t["name"]: t["meaning"] for t in report.get("tables", [])}
        metadata = {
            "source": source,
            "description": _one_liner(report, name),
            "summary": report.get("summary", ""),
            "table_meanings": meanings,
            "schema_summary": schema_summary(schema, meanings),
            "table_count": schema["table_count"],
            "data_class": data_class.value,
            "required_roles": list(required_roles),
            "free_query": bool(free_query),
            "knowledge": bool(knowledge),
            "language": language,
            **extra,
        }
        spec = self._catalog.create_connector(
            principal, name=name.strip(), kind=kind, config=config, metadata=metadata,
        )
        if knowledge:
            await self._write_doc(spec, schema, report)
        self._materialize(spec)
        return {"connector": spec.to_public_dict(), "schema": _public_schema(schema), "report": report}

    async def describe(self, principal: Principal, connector_id: str, *, comment: str = "",
                       language: str | None = None) -> dict:
        """Re-read the schema and re-describe it with the person's correction."""
        spec = self._get(principal, connector_id)
        connector = self._sql_connector(spec)
        schema = await connector.introspect()
        report = await describe_schema(
            self._generator, schema, name=spec.name,
            language=language or spec.metadata.get("language", "ru"), comment=comment,
            previous={"summary": spec.metadata.get("summary"), "tables": [
                {"name": k, "meaning": v} for k, v in spec.metadata.get("table_meanings", {}).items()
            ]},
        )
        meanings = {t["name"]: t["meaning"] for t in report.get("tables", [])}
        spec.metadata.update({
            "description": _one_liner(report, spec.name) or spec.metadata.get("description", ""),
            "summary": report.get("summary", ""),
            "table_meanings": meanings,
            "schema_summary": schema_summary(schema, meanings),
            "table_count": schema["table_count"],
        })
        if comment:
            spec.metadata["comment"] = comment
        self._connectors.update(spec)
        if spec.metadata.get("knowledge"):
            await self._write_doc(spec, schema, report)
        self._registry.unregister(spec.tenant_id, query_skill_name(spec))
        self._materialize(spec)
        self._log(principal, "connector_describe", spec.id, {"comment": comment[:120]})
        return {"connector": spec.to_public_dict(), "schema": _public_schema(schema), "report": report}

    async def schema(self, principal: Principal, connector_id: str) -> dict:
        spec = self._get(principal, connector_id)
        return _public_schema(await self._sql_connector(spec).introspect())

    async def set_options(self, principal: Principal, connector_id: str, *, name: str | None = None,
                          free_query: bool | None = None, knowledge: bool | None = None,
                          data_class: DataClass | None = None,
                          required_roles: tuple[str, ...] | None = None,
                          description: str | None = None) -> ConnectorSpec:
        spec = self._get(principal, connector_id)
        if name is not None and name.strip():
            spec.name = name.strip()
        if data_class is not None:
            if not can_access(principal, data_class):
                raise AccessDenied("you are not cleared for that data class")
            spec.metadata["data_class"] = data_class.value
        if required_roles is not None:
            spec.metadata["required_roles"] = list(required_roles)
        if description is not None:
            spec.metadata["description"] = description.strip()
        if free_query is not None:
            spec.metadata["free_query"] = bool(free_query)
        if knowledge is not None:
            spec.metadata["knowledge"] = bool(knowledge)
            if not knowledge and spec.metadata.get("document_id"):
                await self._vectors.delete_document(tenant_id=spec.tenant_id, document_id=spec.metadata["document_id"])
                spec.metadata["document_id"] = ""
            elif knowledge and not spec.metadata.get("document_id") and is_sql_kind(spec.kind):
                connector = self._sql_connector(spec)
                schema = await connector.introspect()
                await self._write_doc(spec, schema, {
                    "summary": spec.metadata.get("summary", ""),
                    "tables": [{"name": k, "meaning": v} for k, v in spec.metadata.get("table_meanings", {}).items()],
                })
        self._connectors.update(spec)
        self._registry.unregister(spec.tenant_id, query_skill_name(spec))
        self._materialize(spec)
        self._log(principal, "connector_update", spec.id, {"free_query": spec.metadata.get("free_query")})
        return spec

    async def delete(self, principal: Principal, connector_id: str) -> bool:
        spec = self._get(principal, connector_id)
        self._registry.unregister(spec.tenant_id, query_skill_name(spec))
        if spec.metadata.get("document_id"):
            await self._vectors.delete_document(tenant_id=spec.tenant_id, document_id=spec.metadata["document_id"])
        ok = self._catalog.delete_connector(principal, connector_id)
        if ok and spec.metadata.get("source") == "upload":
            try:
                Path(spec.config.get("path", "")).unlink(missing_ok=True)
            except OSError:
                pass
        return ok

    # ---- boot ---------------------------------------------------------------

    def load_all(self) -> tuple[int, list[str]]:
        loaded, errors = 0, []
        for spec in self._connectors.list_all():
            if not spec.metadata.get("free_query"):
                continue
            try:
                self._materialize(spec)
                loaded += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{spec.tenant_id}/{spec.name}: {exc}")
        return loaded, errors

    # ---- helpers ------------------------------------------------------------

    def _materialize(self, spec: ConnectorSpec) -> None:
        if not spec.metadata.get("free_query") or not is_sql_kind(spec.kind):
            return
        self._registry.register(make_query_skill(spec, self._sql_connector(spec)))

    def _sql_connector(self, spec: ConnectorSpec) -> SqlConnector:
        if not is_sql_kind(spec.kind):
            raise ValidationError("that connection is an API, not a database")
        connector = build_connector(spec)
        assert isinstance(connector, SqlConnector)
        return connector

    async def _write_doc(self, spec: ConnectorSpec, schema: dict, report: dict) -> None:
        text = render_schema_doc(spec.name, schema, report)
        doc = await self._ingestion.ingest_document(
            Principal(spec.tenant_id, "system:database", ("admin",)),
            title=f"{spec.name} — database", text=text,
            data_class=DataClass(spec.metadata.get("data_class", DataClass.OPERATIONAL.value)),
            source_uri=f"database:{spec.id}",
            metadata={"connector": spec.id},
        )
        spec.metadata["document_id"] = doc.id
        self._connectors.update(spec)

    def _get(self, principal: Principal, connector_id: str) -> ConnectorSpec:
        self._require_author(principal)
        spec = self._connectors.get(principal.tenant_id, connector_id)
        if spec is None:
            raise ConnectorNotFound(connector_id)
        return spec

    def _require_author(self, principal: Principal) -> None:
        if not can_author(principal):
            raise AccessDenied("connecting a database requires an admin/skill_author role")

    def _log(self, principal: Principal, action: str, resource: str, detail: dict) -> None:
        self._audit.record(AuditEvent(
            action=action, tenant_id=principal.tenant_id, user_id=principal.user_id,
            decision="allow", resource=resource, detail=detail,
        ))


def _one_liner(report: dict, name: str) -> str:
    """The sentence a skill is selected by: the model's, else the summary's first."""
    line = (report.get("suggested_description") or "").strip()
    if line:
        return line
    summary = (report.get("summary") or "").strip()
    first = summary.split(". ")[0].strip() if summary else ""
    return (first[:300] if first else f"Data from the {name} database")


def _public_schema(schema: dict) -> dict:
    return {
        "backend": schema.get("backend"),
        "table_count": schema.get("table_count"),
        "truncated": schema.get("truncated", False),
        "tables": [
            {
                "name": t["name"], "kind": t.get("kind"), "schema": t.get("schema", ""),
                "columns": t["columns"], "row_estimate": t.get("row_estimate"),
                "sample": t.get("sample", [])[:3],
            }
            for t in schema.get("tables", [])
        ],
    }


__all__ = [
    "DatabaseService", "ImportReport", "import_sql_dump", "make_query_skill",
    "query_skill_name", "render_schema_doc", "save_upload", "schema_summary",
]
