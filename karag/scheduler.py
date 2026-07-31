"""Alert scheduling — the part of §15's "proactive alerts" that actually runs.

:mod:`karag.alerts` can evaluate a rule and notify; nothing was calling it on a
cadence, and rules lived only in the memory of whoever constructed them. This
module supplies the two missing halves:

* :class:`StoredAlertRule` + a store, so "batch expiring" survives a restart and
  can be managed through the API instead of a code change.
* :class:`AlertScheduler`, an asyncio loop that evaluates due rules, records the
  outcome, and backs off a rule that keeps failing.

The concept doc names n8n for this. KARAG runs it in-process instead: the rules
execute verified skills through the same RBAC-checked executor as a chat
request, so an alert can never read what its principal could not — which an
external orchestrator holding its own credentials would make easy to get wrong.

A rule's *condition* is deliberately not arbitrary code. It is a small declared
comparison (``rows_returned > 0``, ``field x >= n``) evaluated here, so storing
a rule can never become storing a script.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

from .alerts import Notifier
from .audit import AuditEvent, AuditLog, NullAuditLog
from .domain import Principal, new_id
from .errors import AccessDenied, NotFoundError, ValidationError
from .skills.executor import SkillExecutor

# Declared conditions. Anything else is rejected at authoring time.
ROWS_RETURNED = "rows_returned"
FIELD_COMPARE = "field_compare"
ALWAYS = "always"
CONDITIONS = (ROWS_RETURNED, FIELD_COMPARE, ALWAYS)

_OPERATORS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}

# A rule that errors repeatedly is backed off rather than retried every tick.
_MAX_BACKOFF_S = 3600.0


class AlertRuleNotFound(NotFoundError):
    pass


@dataclass
class StoredAlertRule:
    """A scheduled, verified check owned by one tenant."""

    id: str
    tenant_id: str
    name: str
    skill_name: str
    arguments: dict = field(default_factory=dict)
    # who the rule runs as. Its roles bound what the alert can read.
    run_as_user: str = "system"
    run_as_roles: tuple[str, ...] = ()
    interval_s: float = 3600.0
    condition: str = ROWS_RETURNED
    # field_compare: {"field": "units", "op": "<", "value": 10}
    condition_config: dict = field(default_factory=dict)
    message_template: str = ""
    channel: str = "default"
    enabled: bool = True
    last_run_at: float = 0.0
    last_fired_at: float = 0.0
    last_error: str = ""
    consecutive_errors: int = 0
    created_by: str = ""
    created_at: float = field(default_factory=time.time)

    def principal(self) -> Principal:
        return Principal(
            tenant_id=self.tenant_id,
            user_id=self.run_as_user,
            roles=tuple(self.run_as_roles),
        )

    def due_at(self) -> float:
        """Next run time, including exponential back-off after failures."""
        if not self.last_run_at:
            return 0.0
        interval = self.interval_s
        if self.consecutive_errors:
            interval = min(
                self.interval_s * (2 ** self.consecutive_errors), _MAX_BACKOFF_S
            )
        return self.last_run_at + interval

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "skill_name": self.skill_name,
            "arguments": self.arguments,
            "run_as_user": self.run_as_user,
            "run_as_roles": list(self.run_as_roles),
            "interval_s": self.interval_s,
            "condition": self.condition,
            "condition_config": self.condition_config,
            "message_template": self.message_template,
            "channel": self.channel,
            "enabled": self.enabled,
            "last_run_at": self.last_run_at,
            "last_fired_at": self.last_fired_at,
            "last_error": self.last_error,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


def validate_rule(rule: StoredAlertRule) -> None:
    if not rule.name.strip():
        raise ValidationError("an alert rule needs a name")
    if not rule.skill_name.strip():
        raise ValidationError("an alert rule must reference a skill")
    if rule.interval_s < 60:
        raise ValidationError("interval must be at least 60 seconds")
    if rule.condition not in CONDITIONS:
        raise ValidationError(f"condition must be one of {CONDITIONS}")
    if rule.condition == FIELD_COMPARE:
        cfg = rule.condition_config
        if not cfg.get("field"):
            raise ValidationError("field_compare requires condition_config.field")
        if cfg.get("op") not in _OPERATORS:
            raise ValidationError(
                f"field_compare op must be one of {sorted(_OPERATORS)}"
            )
        if "value" not in cfg:
            raise ValidationError("field_compare requires condition_config.value")


def _rows(data: object) -> list:
    if isinstance(data, dict):
        rows = data.get("rows")
        if isinstance(rows, list):
            return rows
        return [data]
    if isinstance(data, list):
        return data
    return [data] if data is not None else []


def evaluate_condition(rule: StoredAlertRule, data: object) -> bool:
    """Decide whether a rule fires, from declared config only — never eval."""
    if rule.condition == ALWAYS:
        return True
    rows = _rows(data)
    if rule.condition == ROWS_RETURNED:
        cfg = rule.condition_config or {}
        op = _OPERATORS.get(cfg.get("op", ">"), _OPERATORS[">"])
        return bool(op(len(rows), cfg.get("value", 0)))
    if rule.condition == FIELD_COMPARE:
        cfg = rule.condition_config
        op = _OPERATORS[cfg["op"]]
        target = cfg["value"]
        for row in rows:
            if not isinstance(row, dict) or cfg["field"] not in row:
                continue
            value = row[cfg["field"]]
            try:
                if op(value, target):
                    return True
            except TypeError:
                continue  # incomparable types are simply not a match
    return False


def render_message(rule: StoredAlertRule, data: object) -> str:
    rows = _rows(data)
    if rule.message_template:
        try:
            return rule.message_template.format(
                name=rule.name, count=len(rows), tenant=rule.tenant_id,
                skill=rule.skill_name, rows=rows,
            )
        except (KeyError, IndexError):
            pass  # a bad placeholder must not suppress the alert
    return f"[{rule.tenant_id}] {rule.name}: {len(rows)} row(s) matched {rule.skill_name}"


class AlertRuleStore(Protocol):
    def create(self, rule: StoredAlertRule) -> StoredAlertRule: ...
    def update(self, rule: StoredAlertRule) -> StoredAlertRule: ...
    def get(self, tenant_id: str, rule_id: str) -> StoredAlertRule | None: ...
    def list(self, tenant_id: str) -> list[StoredAlertRule]: ...
    def list_all(self) -> list[StoredAlertRule]: ...
    def delete(self, tenant_id: str, rule_id: str) -> bool: ...


class InMemoryAlertRuleStore:
    def __init__(self) -> None:
        self._by_id: dict[str, StoredAlertRule] = {}

    def create(self, rule: StoredAlertRule) -> StoredAlertRule:
        self._by_id[rule.id] = rule
        return rule

    def update(self, rule: StoredAlertRule) -> StoredAlertRule:
        self._by_id[rule.id] = rule
        return rule

    def get(self, tenant_id: str, rule_id: str) -> StoredAlertRule | None:
        r = self._by_id.get(rule_id)
        return r if r is not None and r.tenant_id == tenant_id else None

    def list(self, tenant_id: str) -> list[StoredAlertRule]:
        return sorted(
            (r for r in self._by_id.values() if r.tenant_id == tenant_id),
            key=lambda r: r.created_at,
        )

    def list_all(self) -> list[StoredAlertRule]:
        return sorted(self._by_id.values(), key=lambda r: r.created_at)

    def delete(self, tenant_id: str, rule_id: str) -> bool:
        if self.get(tenant_id, rule_id) is None:
            return False
        del self._by_id[rule_id]
        return True


_SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_rules (
    id                TEXT PRIMARY KEY,
    tenant_id         TEXT NOT NULL,
    name              TEXT NOT NULL,
    skill_name        TEXT NOT NULL,
    arguments         TEXT NOT NULL DEFAULT '{}',
    run_as_user       TEXT NOT NULL DEFAULT 'system',
    run_as_roles      TEXT NOT NULL DEFAULT '[]',
    interval_s        REAL NOT NULL DEFAULT 3600,
    condition         TEXT NOT NULL DEFAULT 'rows_returned',
    condition_config  TEXT NOT NULL DEFAULT '{}',
    message_template  TEXT NOT NULL DEFAULT '',
    channel           TEXT NOT NULL DEFAULT 'default',
    enabled           INTEGER NOT NULL DEFAULT 1,
    last_run_at       REAL NOT NULL DEFAULT 0,
    last_fired_at     REAL NOT NULL DEFAULT 0,
    last_error        TEXT NOT NULL DEFAULT '',
    consecutive_errors INTEGER NOT NULL DEFAULT 0,
    created_by        TEXT NOT NULL DEFAULT '',
    created_at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS alert_rules_tenant ON alert_rules (tenant_id, created_at);
"""


class SqliteAlertRuleStore:
    def __init__(self, path: str = "karag_app.db") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def create(self, rule: StoredAlertRule) -> StoredAlertRule:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO alert_rules (id, tenant_id, name, skill_name, arguments,"
                " run_as_user, run_as_roles, interval_s, condition, condition_config,"
                " message_template, channel, enabled, last_run_at, last_fired_at,"
                " last_error, consecutive_errors, created_by, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                _params(rule),
            )
        return rule

    def update(self, rule: StoredAlertRule) -> StoredAlertRule:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE alert_rules SET name=?, skill_name=?, arguments=?,"
                " run_as_user=?, run_as_roles=?, interval_s=?, condition=?,"
                " condition_config=?, message_template=?, channel=?, enabled=?,"
                " last_run_at=?, last_fired_at=?, last_error=?, consecutive_errors=?"
                " WHERE id=? AND tenant_id=?",
                (
                    rule.name, rule.skill_name, json.dumps(rule.arguments),
                    rule.run_as_user, json.dumps(list(rule.run_as_roles)),
                    rule.interval_s, rule.condition, json.dumps(rule.condition_config),
                    rule.message_template, rule.channel, int(rule.enabled),
                    rule.last_run_at, rule.last_fired_at, rule.last_error,
                    rule.consecutive_errors, rule.id, rule.tenant_id,
                ),
            )
        return rule

    def get(self, tenant_id: str, rule_id: str) -> StoredAlertRule | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM alert_rules WHERE id=? AND tenant_id=?",
                (rule_id, tenant_id),
            ).fetchone()
        return _row_to_rule(row) if row else None

    def list(self, tenant_id: str) -> list[StoredAlertRule]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM alert_rules WHERE tenant_id=? ORDER BY created_at",
                (tenant_id,),
            ).fetchall()
        return [_row_to_rule(r) for r in rows]

    def list_all(self) -> list[StoredAlertRule]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM alert_rules ORDER BY created_at"
            ).fetchall()
        return [_row_to_rule(r) for r in rows]

    def delete(self, tenant_id: str, rule_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM alert_rules WHERE id=? AND tenant_id=?",
                (rule_id, tenant_id),
            )
        return cur.rowcount > 0


def _params(r: StoredAlertRule) -> tuple:
    return (
        r.id, r.tenant_id, r.name, r.skill_name, json.dumps(r.arguments),
        r.run_as_user, json.dumps(list(r.run_as_roles)), r.interval_s,
        r.condition, json.dumps(r.condition_config), r.message_template,
        r.channel, int(r.enabled), r.last_run_at, r.last_fired_at,
        r.last_error, r.consecutive_errors, r.created_by, r.created_at,
    )


def _row_to_rule(row: sqlite3.Row) -> StoredAlertRule:
    return StoredAlertRule(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        skill_name=row["skill_name"],
        arguments=json.loads(row["arguments"]),
        run_as_user=row["run_as_user"],
        run_as_roles=tuple(json.loads(row["run_as_roles"])),
        interval_s=row["interval_s"],
        condition=row["condition"],
        condition_config=json.loads(row["condition_config"]),
        message_template=row["message_template"],
        channel=row["channel"],
        enabled=bool(row["enabled"]),
        last_run_at=row["last_run_at"],
        last_fired_at=row["last_fired_at"],
        last_error=row["last_error"],
        consecutive_errors=row["consecutive_errors"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


@dataclass
class RunOutcome:
    rule_id: str
    ran: bool
    fired: bool = False
    error: str = ""
    message: str = ""


class AlertService:
    """CRUD for alert rules, authorised like any other admin surface."""

    # §3 puts expiry/deviation monitoring under QA at Dusti Pharma, so QA owns
    # its own alerts. The gate is about who may *schedule* work, not what they
    # may read — a rule is still capped at its creator's own roles below.
    MANAGE_ROLES = frozenset({"admin", "ceo", "skill_author", "qa", "finance"})

    def __init__(self, store: AlertRuleStore, *, audit: AuditLog | None = None) -> None:
        self._store = store
        self._audit = audit or NullAuditLog()

    def create(
        self,
        principal: Principal,
        *,
        name: str,
        skill_name: str,
        arguments: dict | None = None,
        interval_s: float = 3600.0,
        condition: str = ROWS_RETURNED,
        condition_config: dict | None = None,
        message_template: str = "",
        channel: str = "default",
        run_as_roles: tuple[str, ...] | None = None,
    ) -> StoredAlertRule:
        self._require_manager(principal)
        # The rule runs as its creator's roles by default and may never be given
        # roles the creator does not hold — otherwise "schedule an alert" would
        # be a way to read a class you are not cleared for.
        roles = tuple(run_as_roles) if run_as_roles is not None else principal.roles
        extra = set(roles) - set(principal.roles)
        if extra:
            raise AccessDenied(
                "an alert cannot run with roles you do not hold: " + ", ".join(sorted(extra))
            )
        rule = StoredAlertRule(
            id=new_id("alert"),
            tenant_id=principal.tenant_id,
            name=name,
            skill_name=skill_name,
            arguments=arguments or {},
            run_as_user=principal.user_id,
            run_as_roles=roles,
            interval_s=interval_s,
            condition=condition,
            condition_config=condition_config or {},
            message_template=message_template,
            channel=channel,
            created_by=principal.user_id,
        )
        validate_rule(rule)
        self._store.create(rule)
        self._audit.record(AuditEvent(
            action="alert_create", tenant_id=principal.tenant_id,
            user_id=principal.user_id, decision="allow", resource=rule.id,
            detail={"name": name, "skill": skill_name, "interval_s": interval_s},
        ))
        return rule

    def list(self, principal: Principal) -> list[StoredAlertRule]:
        self._require_manager(principal)
        return self._store.list(principal.tenant_id)

    def get(self, principal: Principal, rule_id: str) -> StoredAlertRule:
        self._require_manager(principal)
        rule = self._store.get(principal.tenant_id, rule_id)
        if rule is None:
            raise AlertRuleNotFound(rule_id)
        return rule

    def set_enabled(
        self, principal: Principal, rule_id: str, enabled: bool
    ) -> StoredAlertRule:
        rule = self.get(principal, rule_id)
        rule.enabled = enabled
        if enabled:
            rule.consecutive_errors = 0  # a manual re-enable clears back-off
            rule.last_error = ""
        return self._store.update(rule)

    def delete(self, principal: Principal, rule_id: str) -> bool:
        self._require_manager(principal)
        ok = self._store.delete(principal.tenant_id, rule_id)
        if ok:
            self._audit.record(AuditEvent(
                action="alert_delete", tenant_id=principal.tenant_id,
                user_id=principal.user_id, decision="allow", resource=rule_id,
            ))
        return ok

    def _require_manager(self, principal: Principal) -> None:
        if not (self.MANAGE_ROLES & set(principal.roles)):
            raise AccessDenied("managing alerts requires an admin role")


class AlertScheduler:
    """Evaluates due rules on a cadence and notifies when they fire."""

    def __init__(
        self,
        store: AlertRuleStore,
        executor: SkillExecutor,
        notifiers: dict[str, Notifier] | Notifier,
        *,
        audit: AuditLog | None = None,
        tick_s: float = 30.0,
    ) -> None:
        self._store = store
        self._executor = executor
        self._notifiers = (
            notifiers if isinstance(notifiers, dict) else {"default": notifiers}
        )
        self._audit = audit or NullAuditLog()
        self._tick_s = tick_s
        self._stop = asyncio.Event()

    async def run_rule(self, rule: StoredAlertRule, *, force: bool = False) -> RunOutcome:
        """Evaluate one rule now. ``force`` ignores the schedule (manual test)."""
        if not force and (not rule.enabled or time.time() < rule.due_at()):
            return RunOutcome(rule_id=rule.id, ran=False)

        rule.last_run_at = time.time()
        try:
            result = await self._executor.execute(
                rule.principal(), rule.skill_name, rule.arguments
            )
        except Exception as exc:
            rule.last_error = f"{type(exc).__name__}: {exc}"
            rule.consecutive_errors += 1
            self._store.update(rule)
            self._audit.record(AuditEvent(
                action="alert_run", tenant_id=rule.tenant_id, user_id=rule.run_as_user,
                decision="deny", resource=rule.id, detail={"error": rule.last_error},
            ))
            return RunOutcome(rule_id=rule.id, ran=True, error=rule.last_error)

        rule.last_error = ""
        rule.consecutive_errors = 0
        fired = evaluate_condition(rule, result.data)
        message = ""
        if fired:
            rule.last_fired_at = rule.last_run_at
            message = render_message(rule, result.data)
            notifier = self._notifiers.get(rule.channel) or self._notifiers.get("default")
            if notifier is not None:
                await notifier.notify(
                    message,
                    {
                        "rule": rule.name,
                        "rule_id": rule.id,
                        "tenant_id": rule.tenant_id,
                        "skill": rule.skill_name,
                        # provenance travels with the alert, per §5/§6
                        "query_shown": result.query_shown,
                        "data": result.data,
                    },
                )
        self._store.update(rule)
        self._audit.record(AuditEvent(
            action="alert_run", tenant_id=rule.tenant_id, user_id=rule.run_as_user,
            decision="allow", resource=rule.id, detail={"fired": fired},
        ))
        return RunOutcome(rule_id=rule.id, ran=True, fired=fired, message=message)

    async def run_due(self) -> list[RunOutcome]:
        """One pass over every stored rule; returns the outcomes that ran."""
        outcomes: list[RunOutcome] = []
        for rule in self._store.list_all():
            outcome = await self.run_rule(rule)
            if outcome.ran:
                outcomes.append(outcome)
        return outcomes

    async def run_forever(self) -> None:
        """The long-running loop. Cancel-safe; one bad tick never kills it."""
        while not self._stop.is_set():
            try:
                await self.run_due()
            except Exception as exc:  # pragma: no cover - defensive
                self._audit.record(AuditEvent(
                    action="alert_tick", tenant_id="*", user_id="scheduler",
                    decision="deny", resource="scheduler", detail={"error": str(exc)},
                ))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._tick_s)
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()
