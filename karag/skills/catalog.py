"""Skill catalogue service — authoring, testing and publishing skills at runtime.

This is the "thin custom layer" §12 assigns to KIT: the *skill registry*. It
turns stored :class:`~karag.skills.definitions.SkillDefinition` rows into live
skills in the in-process :class:`~karag.skills.registry.SkillRegistry`, and
gives technical staff a governed CRUD path so §5's promise — "a technical
specialist builds and tests it once, then everyone uses it" — is true without a
redeploy.

Authorisation (all fail-closed, checked here rather than in the HTTP layer):

* Only a principal holding an **authoring role** may create/edit/delete a skill
  or a connector.
* An author may only assign a data class they are themselves cleared to read.
  Otherwise an ``hr`` author could mint a ``financial`` skill and read the
  results — the §7 trap, one level up.
* A definition, its connector and every execution stay inside one tenant.
* Sharing to the library exports the *definition*, never the connector: a
  copying tenant must bind its own data source, so no query ever runs against
  another company's database.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..audit import AuditEvent, AuditLog, NullAuditLog
from ..connectors.registry import (
    SQLITE,
    ConnectorNotFound,
    ConnectorSpec,
    ConnectorStore,
    SqlitePolicy,
    build_connector,
    new_connector,
    resolve_secret,
)
from ..connectors.rest import RestConnector
from ..connectors.sql import SqlConnector
from ..domain import DataClass, Principal
from ..errors import AccessDenied, ValidationError
from ..rbac import audience, can_access, within
from .agent_skill import SkillResource, make_agent_skill
from .base import Skill
from .definitions import (
    infer_param_schema,
    sql_bindings,
    AGENT,
    CONNECTOR_KINDS,
    REST,
    SQL,
    SkillDefinition,
    SkillDefinitionNotFound,
    SkillDefinitionStore,
    new_definition,
    validate_definition,
)
from .executor import validate_arguments
from .registry import SkillRegistry
from .rest_skill import make_rest_skill
from .sql_skill import make_sql_skill

# Roles allowed to author connectors and skills — the doc's "technical staff".
AUTHOR_ROLES: frozenset[str] = frozenset({"admin", "skill_author", "ceo"})


def can_author(principal: Principal) -> bool:
    return principal.has_any_role(AUTHOR_ROLES)


def _require_matching_connector(skill_kind: str, connector_kind: str) -> None:
    """A SQL lookup runs on a database, a REST lookup on an API — never crossed.

    Without this check the mismatch only surfaces when the model calls the
    skill, as an attribute error inside the turn.
    """
    is_sql_connector = connector_kind.startswith("sql_")
    if skill_kind == SQL and not is_sql_connector:
        raise ValidationError("a SQL lookup needs a database connection, not an API")
    if skill_kind == REST and is_sql_connector:
        raise ValidationError("a REST lookup needs an API connection, not a database")


@dataclass
class TestRun:
    """The result of trying a definition before publishing it."""

    ok: bool
    query_shown: str = ""
    data: object = None
    error: str = ""
    row_count: int | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "query_shown": self.query_shown,
            "data": self.data,
            "error": self.error,
            "row_count": self.row_count,
        }


class SkillCatalog:
    """CRUD + materialisation for stored connectors and skills."""

    def __init__(
        self,
        registry: SkillRegistry,
        definitions: SkillDefinitionStore,
        connectors: ConnectorStore,
        *,
        audit: AuditLog | None = None,
        sqlite_policy: SqlitePolicy | None = None,
    ) -> None:
        self._registry = registry
        self._defs = definitions
        self._connectors = connectors
        # which SQLite files a tenant may open (None: unrestricted, for tests
        # and embedded use; the platform always sets one)
        self.sqlite_policy = sqlite_policy
        self._audit = audit or NullAuditLog()

    # ---- connectors ------------------------------------------------------

    def create_connector(
        self,
        principal: Principal,
        *,
        name: str,
        kind: str,
        config: dict,
        row_limit: int = 1000,
        timeout_s: float = 5.0,
        metadata: dict | None = None,
    ) -> ConnectorSpec:
        self._require_author(principal, "connector_create", name)
        if kind == SQLITE and self.sqlite_policy is not None:
            try:
                self.sqlite_policy.check(principal.tenant_id, resolve_secret(str((config or {}).get("path", ""))))
            except AccessDenied:
                self._log(principal, "connector_create", "deny", name, {"kind": kind, "reason": "sqlite_path"})
                raise
        spec = new_connector(
            principal.tenant_id,
            name=name,
            kind=kind,
            config=config,
            row_limit=row_limit,
            timeout_s=timeout_s,
            created_by=principal.user_id,
            metadata=metadata,
        )
        self._connectors.create(spec)
        self._log(principal, "connector_create", "allow", spec.id, {"kind": kind})
        return spec

    def list_connectors(self, principal: Principal) -> list[ConnectorSpec]:
        self._require_author(principal, "connector_list", "")
        return self._connectors.list(principal.tenant_id)

    def delete_connector(self, principal: Principal, connector_id: str) -> bool:
        self._require_author(principal, "connector_delete", connector_id)
        # Refuse to orphan skills that still point at this data source.
        dependents = [
            d for d in self._defs.list(principal.tenant_id)
            if d.connector_id == connector_id
        ]
        if dependents:
            raise ValidationError(
                "connector is used by: " + ", ".join(d.name for d in dependents)
            )
        ok = self._connectors.delete(principal.tenant_id, connector_id)
        self._log(principal, "connector_delete", "allow" if ok else "deny", connector_id, {})
        return ok

    def _connector_for(self, tenant_id: str, connector_id: str) -> SqlConnector | RestConnector:
        spec = self._connectors.get(tenant_id, connector_id)
        if spec is None:
            raise ConnectorNotFound(connector_id)
        return build_connector(spec, self.sqlite_policy)

    # ---- skill definitions ----------------------------------------------

    def create_skill(
        self,
        principal: Principal,
        *,
        name: str,
        description: str,
        kind: str,
        connector_id: str = "",
        param_schema: dict | None = None,
        sql: str = "",
        path: str = "",
        instructions: str = "",
        resources: tuple[SkillResource, ...] = (),
        required_data_class: DataClass | None = None,
        required_roles: tuple[str, ...] = (),
        row_limit: int | None = None,
        inject_tenant: bool = True,
        shared: bool = False,
    ) -> SkillDefinition:
        self._require_author(principal, "skill_create", name)
        # A lookup must name a connector that exists *in this tenant* — this is
        # what stops a skill from being pointed at another company's data
        # source. An agent skill reaches no data source, so it names none.
        floor: list[DataClass] = []
        if kind in CONNECTOR_KINDS:
            spec = self._connectors.get(principal.tenant_id, connector_id)
            if spec is None:
                raise ConnectorNotFound(connector_id)
            _require_matching_connector(kind, spec.kind)
            floor = _data_floor(spec, sql if kind == SQL else "")
        else:
            connector_id = ""
        if required_data_class is None:
            # Not stated: the skill inherits the audience of what it reads.
            required_data_class = _inherit(floor, required_roles)
        self._require_class_clearance(principal, required_data_class, "skill_create", name)
        _require_within_floor(required_data_class, floor, required_roles)
        self._require_free_name(principal.tenant_id, name)
        if kind == SQL and not param_schema:
            param_schema = infer_param_schema(sql)

        defn = new_definition(
            principal.tenant_id,
            name=name,
            description=description,
            kind=kind,
            connector_id=connector_id,
            param_schema=param_schema,
            sql=sql,
            path=path,
            instructions=instructions,
            resources=tuple(resources),
            required_data_class=required_data_class,
            required_roles=tuple(required_roles),
            row_limit=row_limit,
            inject_tenant=inject_tenant,
            shared=shared,
            created_by=principal.user_id,
        )
        self._defs.create(defn)
        self._materialize(defn)
        self._log(
            principal, "skill_create", "allow", defn.id,
            {"name": name, "kind": kind, "data_class": required_data_class.value},
        )
        return defn

    def update_skill(
        self, principal: Principal, skill_id: str, **changes
    ) -> SkillDefinition:
        self._require_author(principal, "skill_update", skill_id)
        defn = self._defs.get(principal.tenant_id, skill_id)
        if defn is None:
            raise SkillDefinitionNotFound(skill_id)

        old_name = defn.name
        for key, value in changes.items():
            if value is None or not hasattr(defn, key):
                continue
            if key == "required_data_class":
                value = DataClass(value) if not isinstance(value, DataClass) else value
                self._require_class_clearance(principal, value, "skill_update", skill_id)
            if key == "required_roles":
                value = tuple(value)
            if key == "resources":
                value = tuple(
                    r if isinstance(r, SkillResource) else SkillResource.from_dict(r)
                    for r in value
                )
            setattr(defn, key, value)

        # Checked against the *final* kind, not the order the fields arrived in:
        # a skill switched to `agent` no longer needs a connector, and one
        # switched to `sql` must have a real one before it is stored.
        if defn.kind in CONNECTOR_KINDS:
            spec = self._connectors.get(principal.tenant_id, defn.connector_id)
            if spec is None:
                raise ConnectorNotFound(defn.connector_id)
            _require_matching_connector(defn.kind, spec.kind)
            _require_within_floor(
                defn.required_data_class,
                _data_floor(spec, defn.sql if defn.kind == SQL else ""),
                defn.required_roles,
            )
        else:
            defn.connector_id = ""
        if defn.name != old_name:
            self._require_free_name(principal.tenant_id, defn.name)
        if defn.kind == SQL and not (defn.param_schema or {}).get("properties") \
                and sql_bindings(defn.sql) - {"tenant_id"}:
            defn.param_schema = infer_param_schema(defn.sql)

        validate_definition(defn)
        self._defs.update(defn)
        # A rename leaves the old tool name registered; drop it first.
        if defn.name != old_name:
            self._registry.unregister(defn.tenant_id, old_name)
        self._materialize(defn)
        self._log(principal, "skill_update", "allow", defn.id, {"name": defn.name})
        return defn

    def delete_skill(self, principal: Principal, skill_id: str) -> bool:
        self._require_author(principal, "skill_delete", skill_id)
        defn = self._defs.get(principal.tenant_id, skill_id)
        if defn is None:
            return False
        self._defs.delete(principal.tenant_id, skill_id)
        self._registry.unregister(defn.tenant_id, defn.name)
        self._log(principal, "skill_delete", "allow", skill_id, {"name": defn.name})
        return True

    def get_skill(self, principal: Principal, skill_id: str) -> SkillDefinition:
        self._require_author(principal, "skill_get", skill_id)
        defn = self._defs.get(principal.tenant_id, skill_id)
        if defn is None:
            raise SkillDefinitionNotFound(skill_id)
        return defn

    def list_skills(self, principal: Principal) -> list[SkillDefinition]:
        """Every definition in the tenant — the *authoring* view.

        Note this is deliberately not the same as the model's catalogue: what a
        given user may actually call still comes from ``registry.visible_for``.
        """
        self._require_author(principal, "skill_list", "")
        return self._defs.list(principal.tenant_id)

    # ---- the skill library (§15: reuse across companies) ------------------

    def list_library(self, principal: Principal) -> list[SkillDefinition]:
        """Shared definitions published by any tenant, as reusable templates."""
        self._require_author(principal, "library_list", "")
        return [
            d for d in self._defs.list_shared() if d.tenant_id != principal.tenant_id
        ]

    def import_from_library(
        self,
        principal: Principal,
        source_skill_id: str,
        *,
        connector_id: str = "",
        name: str | None = None,
    ) -> SkillDefinition:
        """Copy a shared definition into this tenant, bound to *its own* connector.

        The template travels; the data path does not. The copy is an ordinary
        local definition afterwards — editable, deletable, and executing only
        against the importing tenant's connector. An agent skill has no data
        path at all, so it copies whole and needs no connector.
        """
        self._require_author(principal, "library_import", source_skill_id)
        source = next(
            (d for d in self._defs.list_shared() if d.id == source_skill_id), None
        )
        if source is None:
            raise SkillDefinitionNotFound(source_skill_id)
        self._require_class_clearance(
            principal, source.required_data_class, "library_import", source_skill_id
        )
        return self.create_skill(
            principal,
            name=name or source.name,
            description=source.description,
            kind=source.kind,
            connector_id=connector_id,
            param_schema=source.param_schema,
            sql=source.sql,
            path=source.path,
            instructions=source.instructions,
            resources=tuple(source.resources),
            required_data_class=source.required_data_class,
            required_roles=source.required_roles,
            row_limit=source.row_limit,
            inject_tenant=source.inject_tenant,
        )

    # ---- test before publish (§5 "builds and tests once") ------------------

    async def test_skill(
        self, principal: Principal, skill_id: str, arguments: dict
    ) -> TestRun:
        """Run a stored skill as the author, reporting the query and result.

        This is the authoring loop: the specialist sees exactly what the query
        returns before any manager relies on it. It goes through the same
        connector guardrails as production traffic.
        """
        self._require_author(principal, "skill_test", skill_id)
        defn = self._defs.get(principal.tenant_id, skill_id)
        if defn is None:
            raise SkillDefinitionNotFound(skill_id)
        self._require_class_clearance(
            principal, defn.required_data_class, "skill_test", skill_id
        )
        try:
            skill = self.build_skill(defn)
            # Validate against the *materialised* skill's schema: for a lookup
            # that is the declared param schema, and for an agent skill it is
            # the open/read-a-bundled-file schema the model actually sees.
            validate_arguments(skill.input_schema, arguments)
            result = await skill.handler(principal, arguments)
        except Exception as exc:  # surfaced to the author, never to the model
            self._log(principal, "skill_test", "deny", skill_id, {"error": str(exc)})
            return TestRun(ok=False, error=f"{type(exc).__name__}: {exc}")

        rows = None
        if isinstance(result.data, dict) and isinstance(result.data.get("rows"), list):
            rows = len(result.data["rows"])
        self._log(principal, "skill_test", "allow", skill_id, {"rows": rows})
        return TestRun(
            ok=True, query_shown=result.query_shown, data=result.data, row_count=rows
        )

    # ---- materialisation -------------------------------------------------

    def build_skill(self, defn: SkillDefinition) -> Skill:
        """Turn one stored definition into an executable Skill."""
        if defn.kind == AGENT:
            # No connector is resolved: an agent skill has no data path, so it
            # cannot fail to load because a database is unreachable.
            return make_agent_skill(
                name=defn.name,
                description=defn.description,
                instructions=defn.instructions,
                resources=tuple(defn.resources),
                required_data_class=defn.required_data_class,
                required_roles=frozenset(defn.required_roles),
                tenant_id=defn.tenant_id,
            )

        connector = self._connector_for(defn.tenant_id, defn.connector_id)
        common = {
            "name": defn.name,
            "description": defn.description,
            "param_schema": defn.param_schema,
            "required_data_class": defn.required_data_class,
            "required_roles": frozenset(defn.required_roles),
            "tenant_id": defn.tenant_id,
            "inject_tenant": defn.inject_tenant,
        }
        if defn.kind == SQL:
            return make_sql_skill(
                sql=defn.sql, connector=connector, row_limit=defn.row_limit, **common
            )
        if defn.kind == REST:
            return make_rest_skill(path=defn.path, connector=connector, **common)
        raise ValidationError(f"unknown skill kind {defn.kind!r}")

    def _materialize(self, defn: SkillDefinition) -> None:
        if not defn.enabled:
            self._registry.unregister(defn.tenant_id, defn.name)
            return
        self._registry.register(self.build_skill(defn))

    def load_all(self) -> tuple[int, list[str]]:
        """Materialise every stored definition at boot.

        Returns ``(loaded, errors)``. A single broken definition (missing
        connector, unset env var) must not stop the platform from starting, so
        failures are collected and reported rather than raised.
        """
        loaded = 0
        errors: list[str] = []
        for defn in self._defs.list_all():
            if not defn.enabled:
                continue
            try:
                self._registry.register(self.build_skill(defn))
                loaded += 1
            except Exception as exc:
                errors.append(f"{defn.tenant_id}/{defn.name}: {exc}")
        return loaded, errors

    # ---- guards ----------------------------------------------------------

    def _require_free_name(self, tenant_id: str, name: str) -> None:
        """A tenant skill may not shadow a platform-wide tool.

        Two tools with one name reach the model as duplicates, which the
        provider rejects — and the one that would win is the tenant's, which
        could quietly replace ``create_spreadsheet`` with something else.
        """
        if self._registry.get("*", name) is not None:
            raise ValidationError(
                f"{name!r} is the name of a built-in tool; choose another name"
            )

    def _require_author(self, principal: Principal, action: str, resource: str) -> None:
        if not can_author(principal):
            self._log(principal, action, "deny", resource, {"reason": "not_an_author"})
            raise AccessDenied("authoring a skill requires an admin/skill_author role")

    def _require_class_clearance(
        self, principal: Principal, data_class: DataClass, action: str, resource: str
    ) -> None:
        if not can_access(principal, data_class):
            self._log(
                principal, action, "deny", resource,
                {"reason": "class_not_cleared", "data_class": data_class.value},
            )
            raise AccessDenied(
                f"you are not cleared for {data_class.value} data and may not "
                "create a skill that exposes it"
            )

    def _log(
        self, principal: Principal, action: str, decision: str, resource: str, detail: dict
    ) -> None:
        self._audit.record(
            AuditEvent(
                action=action,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                decision=decision,
                resource=resource,
                detail=detail,
            )
        )


# ---- what a lookup reads decides who it may be offered to ------------------


def _data_floor(spec, sql: str = "") -> list[DataClass]:
    """The classes of the data a lookup on ``spec`` reads: the connection's
    own audience (set when it was connected through the Data page) and, for
    SQL, the audience of every narrowed table the statement names. A hidden
    table may not be named at all."""
    from ..integrations.dbsetup import sql_identifiers, table_classes  # noqa: PLC0415 (cycle)

    meta = spec.metadata or {}
    floor: list[DataClass] = []
    if meta.get("data_class"):
        try:
            floor.append(DataClass(meta["data_class"]))
        except ValueError:
            floor.append(DataClass.most_restrictive())
    if sql:
        named = set(sql_identifiers(sql))
        hidden = sorted(named & {str(t).lower() for t in meta.get("hidden_tables") or []})
        if hidden:
            raise ValidationError(
                "this database hides " + ", ".join(hidden) + " from the assistant; "
                "a lookup may not read it either"
            )
        floor += [klass for table, klass in table_classes(meta).items() if table in named]
    return floor


def _inherit(floor: list[DataClass], roles: tuple[str, ...] = ()) -> DataClass:
    """The audience a lookup gets when its author does not state one: the
    narrowest of what it reads. No floor (a connector registered by hand)
    keeps the old default."""
    if not floor:
        return DataClass.OPERATIONAL
    for candidate in floor:
        if _fits(candidate, floor, roles):
            return candidate
    raise ValidationError(_mixed_message(floor))


def _fits(chosen: DataClass, floor: list[DataClass], roles: tuple[str, ...]) -> bool:
    """Whether everyone the lookup is offered to may read every part of the
    data. Either the class itself is within each part's audience, or the
    lookup is limited to roles that are cleared for every part (a lookup on an
    HR-narrowed table in a financial database fits no single class, but
    "ceo, admin" are cleared for both)."""
    if all(within(chosen, c) for c in floor):
        return True
    return bool(roles) and all(set(roles) <= audience(c) for c in floor)


def _mixed_message(floor: list[DataClass]) -> str:
    common = set.intersection(*(set(audience(c)) for c in floor)) - {"platform_admin", "karag_engineer"}
    hint = f" (for example: {', '.join(sorted(common))})" if common else ""
    return (
        "this lookup reads data with different audiences ("
        + ", ".join(sorted({c.value for c in floor}))
        + ") and no single one covers them all — limit it to roles cleared for "
        f"every part{hint}, or split it into separate lookups"
    )


def _require_within_floor(
    chosen: DataClass, floor: list[DataClass], roles: tuple[str, ...] = ()
) -> None:
    """A lookup may narrow the audience of the data it reads, never widen it:
    offering payroll rows to everyone through an "operational" skill would
    undo the class the connection (or table) was given."""
    if not floor or _fits(chosen, floor, tuple(roles)):
        return
    wider = sorted({c.value for c in floor if not within(chosen, c)})
    if len(set(floor)) > 1 and not any(all(within(c, o) for o in floor) for c in floor):
        raise ValidationError(_mixed_message(floor))
    raise ValidationError(
        f"the data this lookup reads is limited to {', '.join(wider)}; "
        f"a {chosen.value} lookup would show it to people outside that audience"
    )
