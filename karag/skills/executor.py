"""Skill executor — validates and runs a skill under the principal's authority.

Order of operations (all fail-closed):
  1. Resolve the skill *for this principal* (RBAC-aware). Unknown/forbidden ->
     ``SkillNotFound`` (no disclosure of privileged skills).
  2. Validate arguments against the skill's JSON schema.
  3. Run the verified handler with the principal (for row-level scoping).

A minimal, dependency-free JSON-schema check is used (types + required +
no-unknown-properties) — enough to keep malformed/injected arguments out of the
handler.
"""

from __future__ import annotations

from ..audit import AuditEvent, AuditLog, NullAuditLog
from ..domain import Principal
from ..errors import SkillNotFound, ValidationError
from .base import SkillResult
from .registry import SkillRegistry

_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def validate_arguments(schema: dict, args: dict) -> None:
    if not isinstance(args, dict):
        raise ValidationError("arguments must be an object")
    props: dict = schema.get("properties", {})
    required = schema.get("required", [])
    allow_extra = schema.get("additionalProperties", False)

    for key in required:
        if key not in args:
            raise ValidationError(f"missing required argument: {key}")

    for key, value in args.items():
        if key not in props:
            if allow_extra:
                continue
            raise ValidationError(f"unknown argument: {key}")
        expected = props[key].get("type")
        check = _TYPE_CHECKS.get(expected)
        if check is not None and not check(value):
            raise ValidationError(f"argument {key} must be of type {expected}")
        enum = props[key].get("enum")
        if enum is not None and value not in enum:
            raise ValidationError(f"argument {key} must be one of {enum}")


class SkillExecutor:
    def __init__(self, registry: SkillRegistry, audit: AuditLog | None = None) -> None:
        self._registry = registry
        self._audit = audit or NullAuditLog()

    async def execute(
        self, principal: Principal, name: str, arguments: dict
    ) -> SkillResult:
        skill = self._registry.resolve(principal, name)
        if skill is None or not skill.visible_to(principal):
            self._log(principal, name, "deny", {"reason": "not_visible"})
            raise SkillNotFound(name)

        try:
            validate_arguments(skill.input_schema, arguments)
        except ValidationError as exc:
            self._log(principal, name, "deny", {"reason": "invalid_arguments", "detail": str(exc)})
            raise

        result = await skill.handler(principal, arguments)
        self._log(principal, name, "allow", {"query_shown": result.query_shown})
        return result

    def _log(self, principal: Principal, name: str, decision: str, detail: dict) -> None:
        self._audit.record(
            AuditEvent(
                action="skill_execute",
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                decision=decision,
                resource=name,
                detail=detail,
            )
        )
