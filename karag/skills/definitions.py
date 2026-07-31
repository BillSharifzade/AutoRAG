"""Stored skill definitions — skills as *data*, not as code.

§5 of the concept doc calls the skill "the core of the product": a prepared,
parameterised query that a technical specialist "builds and tests once, after
which everyone uses it". That promise only holds if building one does not mean
editing Python and redeploying — so a skill is stored as a
:class:`SkillDefinition` row and materialised into a live
:class:`~karag.skills.base.Skill` at boot (and on every change).

Two shapes, matching §6's two connection methods:

* ``kind="sql"``  — a parameterised ``SELECT``/``WITH`` on a view, executed
  through :class:`~karag.connectors.sql.SqlConnector` (read-only, row-limited,
  timed out).
* ``kind="rest"`` — a GET against a company-exposed endpoint.

Definitions are validated at write time (read-only SQL, sane JSON schema,
declared parameters actually bound), so a broken skill is rejected when it is
created rather than when a manager asks a question.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

from ..connectors.sql import ReadOnlyViolation, assert_read_only
from ..domain import DataClass, new_id
from ..errors import NotFoundError, ValidationError

SQL = "sql"
REST = "rest"
KINDS = (SQL, REST)

# Named placeholders in a parameterised statement. SQLite uses ``:name``;
# psycopg uses ``%(name)s`` — a definition may target either backend, so both
# styles are recognised when checking that declared params are actually bound.
_BIND_NAMED = re.compile(r"(?<![:\w]):([a-zA-Z_]\w*)")
_BIND_PYFORMAT = re.compile(r"%\((\w+)\)s")

_ALLOWED_PARAM_TYPES = frozenset({"string", "integer", "number", "boolean"})
# tenant_id is bound by the platform, never declared or supplied by the model
_RESERVED_PARAMS = frozenset({"tenant_id"})


class SkillDefinitionNotFound(NotFoundError):
    pass


@dataclass
class SkillDefinition:
    """A stored, tenant-owned skill awaiting materialisation."""

    id: str
    tenant_id: str
    name: str
    description: str
    kind: str  # sql | rest
    connector_id: str
    param_schema: dict = field(default_factory=dict)
    # sql kind
    sql: str = ""
    # rest kind
    path: str = ""
    required_data_class: DataClass = DataClass.OPERATIONAL
    required_roles: tuple[str, ...] = ()
    row_limit: int | None = None
    inject_tenant: bool = True
    enabled: bool = True
    # a shared definition can be *copied* by another tenant (§15 skill library).
    # It is never executed across tenants — the copy binds the copier's own
    # connector, so no data path ever crosses a company boundary.
    shared: bool = False
    created_by: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "description": self.description,
            "kind": self.kind,
            "connector_id": self.connector_id,
            "param_schema": self.param_schema,
            "sql": self.sql,
            "path": self.path,
            "required_data_class": self.required_data_class.value,
            "required_roles": list(self.required_roles),
            "row_limit": self.row_limit,
            "inject_tenant": self.inject_tenant,
            "enabled": self.enabled,
            "shared": self.shared,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def validate_param_schema(schema: dict) -> None:
    """A skill's parameter schema must be a closed object of scalar params.

    Closed (``additionalProperties: false``) because the executor's validator
    rejects unknown arguments only when the schema says so — an open schema
    would let a model smuggle extra bindings into a query.
    """
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValidationError("param_schema must be a JSON-schema object")
    props = schema.get("properties")
    if not isinstance(props, dict):
        raise ValidationError("param_schema.properties must be an object")
    if schema.get("additionalProperties", False):
        raise ValidationError("param_schema must set additionalProperties: false")
    for pname, pspec in props.items():
        if pname in _RESERVED_PARAMS:
            raise ValidationError(
                f"{pname!r} is bound by the platform and must not be declared"
            )
        if not isinstance(pspec, dict):
            raise ValidationError(f"parameter {pname!r} must be an object")
        ptype = pspec.get("type")
        if ptype not in _ALLOWED_PARAM_TYPES:
            raise ValidationError(
                f"parameter {pname!r} type must be one of {sorted(_ALLOWED_PARAM_TYPES)}"
            )
    for req in schema.get("required", []):
        if req not in props:
            raise ValidationError(f"required parameter {req!r} is not declared")


def sql_bindings(sql: str) -> set[str]:
    """The named placeholders a statement expects, in either supported style."""
    return set(_BIND_NAMED.findall(sql)) | set(_BIND_PYFORMAT.findall(sql))


def validate_definition(defn: SkillDefinition) -> None:
    """Full pre-store validation — fail loudly at authoring time, not at ask time."""
    if not defn.name or not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", defn.name):
        raise ValidationError(
            "skill name must be snake_case, 3–64 chars, starting with a letter"
        )
    if not defn.description.strip():
        raise ValidationError("a skill needs a description — the model selects on it")
    if defn.kind not in KINDS:
        raise ValidationError(f"unknown skill kind {defn.kind!r}; expected one of {KINDS}")
    if not defn.connector_id:
        raise ValidationError("a skill must reference a connector")
    validate_param_schema(defn.param_schema)

    declared = set(defn.param_schema.get("properties", {}))

    if defn.kind == SQL:
        if not defn.sql.strip():
            raise ValidationError("sql skill requires a statement")
        try:
            assert_read_only(defn.sql)
        except ReadOnlyViolation as exc:
            # Re-raised as a validation error so the authoring UI shows it inline.
            raise ValidationError(f"query must be read-only: {exc}") from exc
        bound = sql_bindings(defn.sql)
        unknown = bound - declared - _RESERVED_PARAMS
        if unknown:
            raise ValidationError(
                "statement binds undeclared parameter(s): " + ", ".join(sorted(unknown))
            )
        unused = declared - bound
        if unused:
            raise ValidationError(
                "declared parameter(s) never used in the statement: "
                + ", ".join(sorted(unused))
            )
    else:  # REST
        if not defn.path.strip():
            raise ValidationError("rest skill requires a path")
        if "://" in defn.path:
            raise ValidationError("path must be relative to the connector base_url")


def new_definition(
    tenant_id: str,
    *,
    name: str,
    description: str,
    kind: str,
    connector_id: str,
    param_schema: dict | None = None,
    sql: str = "",
    path: str = "",
    required_data_class: DataClass = DataClass.OPERATIONAL,
    required_roles: tuple[str, ...] = (),
    row_limit: int | None = None,
    inject_tenant: bool = True,
    shared: bool = False,
    created_by: str = "",
) -> SkillDefinition:
    """Build and validate a definition (not yet stored)."""
    defn = SkillDefinition(
        id=new_id("skl"),
        tenant_id=tenant_id,
        name=name,
        description=description,
        kind=kind,
        connector_id=connector_id,
        param_schema=param_schema or {
            "type": "object", "properties": {}, "required": [],
            "additionalProperties": False,
        },
        sql=sql,
        path=path,
        required_data_class=required_data_class,
        required_roles=tuple(required_roles),
        row_limit=row_limit,
        inject_tenant=inject_tenant,
        shared=shared,
        created_by=created_by,
    )
    validate_definition(defn)
    return defn


class SkillDefinitionStore(Protocol):
    def create(self, defn: SkillDefinition) -> SkillDefinition: ...
    def update(self, defn: SkillDefinition) -> SkillDefinition: ...
    def get(self, tenant_id: str, skill_id: str) -> SkillDefinition | None: ...
    def list(self, tenant_id: str) -> list[SkillDefinition]: ...
    def list_all(self) -> list[SkillDefinition]: ...
    def list_shared(self) -> list[SkillDefinition]: ...
    def delete(self, tenant_id: str, skill_id: str) -> bool: ...


class InMemorySkillDefinitionStore:
    def __init__(self) -> None:
        self._by_id: dict[str, SkillDefinition] = {}

    def create(self, defn: SkillDefinition) -> SkillDefinition:
        self._by_id[defn.id] = defn
        return defn

    def update(self, defn: SkillDefinition) -> SkillDefinition:
        defn.updated_at = time.time()
        self._by_id[defn.id] = defn
        return defn

    def get(self, tenant_id: str, skill_id: str) -> SkillDefinition | None:
        d = self._by_id.get(skill_id)
        return d if d is not None and d.tenant_id == tenant_id else None

    def list(self, tenant_id: str) -> list[SkillDefinition]:
        return sorted(
            (d for d in self._by_id.values() if d.tenant_id == tenant_id),
            key=lambda d: d.created_at,
        )

    def list_all(self) -> list[SkillDefinition]:
        return sorted(self._by_id.values(), key=lambda d: d.created_at)

    def list_shared(self) -> list[SkillDefinition]:
        return sorted(
            (d for d in self._by_id.values() if d.shared),
            key=lambda d: d.created_at,
        )

    def delete(self, tenant_id: str, skill_id: str) -> bool:
        if self.get(tenant_id, skill_id) is None:
            return False
        del self._by_id[skill_id]
        return True


_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_definitions (
    id                 TEXT PRIMARY KEY,
    tenant_id          TEXT NOT NULL,
    name               TEXT NOT NULL,
    description        TEXT NOT NULL,
    kind               TEXT NOT NULL,
    connector_id       TEXT NOT NULL,
    param_schema       TEXT NOT NULL,
    sql                TEXT NOT NULL DEFAULT '',
    path               TEXT NOT NULL DEFAULT '',
    required_data_class TEXT NOT NULL,
    required_roles     TEXT NOT NULL DEFAULT '[]',
    row_limit          INTEGER,
    inject_tenant      INTEGER NOT NULL DEFAULT 1,
    enabled            INTEGER NOT NULL DEFAULT 1,
    shared             INTEGER NOT NULL DEFAULT 0,
    created_by         TEXT NOT NULL DEFAULT '',
    created_at         REAL NOT NULL,
    updated_at         REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS skill_definitions_tenant_name
    ON skill_definitions (tenant_id, name);
"""


class SqliteSkillDefinitionStore:
    """Durable skill catalogue — the registry survives a restart."""

    def __init__(self, path: str = "karag_app.db") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def create(self, defn: SkillDefinition) -> SkillDefinition:
        with self._lock, self._conn:
            try:
                self._conn.execute(_INSERT, _params(defn))
            except sqlite3.IntegrityError as exc:
                raise ValidationError(
                    f"a skill named {defn.name!r} already exists for this tenant"
                ) from exc
        return defn

    def update(self, defn: SkillDefinition) -> SkillDefinition:
        defn.updated_at = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE skill_definitions SET name=?, description=?, kind=?,"
                " connector_id=?, param_schema=?, sql=?, path=?,"
                " required_data_class=?, required_roles=?, row_limit=?,"
                " inject_tenant=?, enabled=?, shared=?, updated_at=?"
                " WHERE id=? AND tenant_id=?",
                (
                    defn.name, defn.description, defn.kind, defn.connector_id,
                    json.dumps(defn.param_schema), defn.sql, defn.path,
                    defn.required_data_class.value, json.dumps(list(defn.required_roles)),
                    defn.row_limit, int(defn.inject_tenant), int(defn.enabled),
                    int(defn.shared), defn.updated_at, defn.id, defn.tenant_id,
                ),
            )
        return defn

    def get(self, tenant_id: str, skill_id: str) -> SkillDefinition | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM skill_definitions WHERE id=? AND tenant_id=?",
                (skill_id, tenant_id),
            ).fetchone()
        return _row_to_defn(row) if row else None

    def list(self, tenant_id: str) -> list[SkillDefinition]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM skill_definitions WHERE tenant_id=? ORDER BY created_at",
                (tenant_id,),
            ).fetchall()
        return [_row_to_defn(r) for r in rows]

    def list_all(self) -> list[SkillDefinition]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM skill_definitions ORDER BY created_at"
            ).fetchall()
        return [_row_to_defn(r) for r in rows]

    def list_shared(self) -> list[SkillDefinition]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM skill_definitions WHERE shared=1 ORDER BY created_at"
            ).fetchall()
        return [_row_to_defn(r) for r in rows]

    def delete(self, tenant_id: str, skill_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM skill_definitions WHERE id=? AND tenant_id=?",
                (skill_id, tenant_id),
            )
        return cur.rowcount > 0


_INSERT = (
    "INSERT INTO skill_definitions (id, tenant_id, name, description, kind,"
    " connector_id, param_schema, sql, path, required_data_class, required_roles,"
    " row_limit, inject_tenant, enabled, shared, created_by, created_at, updated_at)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def _params(d: SkillDefinition) -> tuple:
    return (
        d.id, d.tenant_id, d.name, d.description, d.kind, d.connector_id,
        json.dumps(d.param_schema), d.sql, d.path, d.required_data_class.value,
        json.dumps(list(d.required_roles)), d.row_limit, int(d.inject_tenant),
        int(d.enabled), int(d.shared), d.created_by, d.created_at, d.updated_at,
    )


def _row_to_defn(row: sqlite3.Row) -> SkillDefinition:
    return SkillDefinition(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        description=row["description"],
        kind=row["kind"],
        connector_id=row["connector_id"],
        param_schema=json.loads(row["param_schema"]),
        sql=row["sql"],
        path=row["path"],
        required_data_class=DataClass(row["required_data_class"]),
        required_roles=tuple(json.loads(row["required_roles"])),
        row_limit=row["row_limit"],
        inject_tenant=bool(row["inject_tenant"]),
        enabled=bool(row["enabled"]),
        shared=bool(row["shared"]),
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
