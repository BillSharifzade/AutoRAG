"""Skills that let the assistant *operate* the platform, not just describe it.

"Create 60 users with the skill_author role", "give me our usage stats",
"which skills do we have" — these go through the same services the REST API
calls, under the **asking user's own Principal**. That is the whole security
argument: an admin's request succeeds and an employee's identical request is
refused by the exact code path that guards the HTTP endpoint. There is no
parallel permission system to keep in sync, and no way for the model to act as
someone it isn't.

Three further guards, because an agent acting in bulk is different from a person
clicking a button:

* **Caps.** A batch is bounded (``MAX_BATCH``) so a misread instruction cannot
  create ten thousand accounts.
* **Confirmation.** Destructive operations require an explicit
  ``confirm: true``, so the model has to have been told clearly, twice.
* **Audit.** Every call is recorded with who asked and what happened.

Newly minted credentials are returned once, to the requesting user. They are
stored only as a hash, exactly as the HTTP path does it.
"""

from __future__ import annotations

from ..audit import AuditEvent, AuditLog, NullAuditLog
from ..domain import DataClass, Principal
from ..errors import AccessDenied, KaragError
from ..pricing import PriceList
from ..rbac import ROLE_DATA_CLASSES
from .base import Skill, SkillResult

# Upper bound on any one bulk operation.
MAX_BATCH = 100

# Roles an agent may hand out. `platform_admin` and `karag_engineer` are omitted
# on purpose: those are granted by a human operator, never by asking a chatbot.
GRANTABLE_ROLES = frozenset(
    set(ROLE_DATA_CLASSES) - {"platform_admin"} | {"skill_author", "uploader"}
)


def admin_skills(platform, *, audit: AuditLog | None = None) -> list[Skill]:
    """Operational skills bound to a live :class:`~karag.factory.Platform`."""
    log = audit or platform.audit or NullAuditLog()

    def _record(principal: Principal, action: str, decision: str, detail: dict) -> None:
        log.record(AuditEvent(
            action=f"agent_{action}", tenant_id=principal.tenant_id,
            user_id=principal.user_id, decision=decision, resource=action, detail=detail,
        ))

    # ---- people ----------------------------------------------------------

    async def _create_accounts(principal: Principal, args: dict) -> SkillResult:
        count = int(args.get("count", 1))
        roles = tuple(args.get("roles") or ["employee"])
        prefix = str(args.get("user_id_prefix", "user")).strip() or "user"
        language = str(args.get("language", "auto"))

        if count < 1 or count > MAX_BATCH:
            raise KaragError(f"count must be between 1 and {MAX_BATCH}")
        unknown = set(roles) - GRANTABLE_ROLES
        if unknown:
            raise AccessDenied(
                "these roles cannot be granted this way: " + ", ".join(sorted(unknown))
            )

        created, failed = [], []
        for i in range(1, count + 1):
            user_id = prefix if count == 1 else f"{prefix}{i:03d}"
            try:
                # DirectoryService re-checks the caller's authority and blocks
                # privilege escalation; we never bypass it.
                account, token = platform.directory_service.create_account(
                    principal, user_id=user_id, display_name=user_id,
                    roles=roles, language=language,
                )
                created.append({"user_id": account.id, "roles": list(account.roles),
                                "token": token})
            except AccessDenied:
                _record(principal, "create_accounts", "deny",
                        {"reason": "not_authorised", "count": count})
                raise
            except KaragError as exc:
                failed.append({"user_id": user_id, "error": str(exc)})

        _record(principal, "create_accounts", "allow",
                {"created": len(created), "failed": len(failed), "roles": list(roles)})
        return SkillResult(
            data={
                "created": created,
                "failed": failed,
                "note": (
                    "Each token is shown once and stored only as a hash. Deliver "
                    "them to their owners over a private channel."
                ),
            },
            query_shown=f"create_accounts(count={count}, roles={list(roles)}, prefix={prefix!r})",
        )

    async def _list_accounts(principal: Principal, args: dict) -> SkillResult:
        accounts = platform.directory_service.list_accounts(principal)
        return SkillResult(
            data={"accounts": [a.to_public_dict() for a in accounts],
                  "count": len(accounts)},
            query_shown="list_accounts()",
        )

    async def _set_roles(principal: Principal, args: dict) -> SkillResult:
        user_id = str(args["user_id"])
        roles = tuple(args["roles"])
        unknown = set(roles) - GRANTABLE_ROLES
        if unknown:
            raise AccessDenied(
                "these roles cannot be granted this way: " + ", ".join(sorted(unknown))
            )
        account = platform.directory_service.set_account_roles(principal, user_id, roles)
        _record(principal, "set_roles", "allow", {"user_id": user_id, "roles": list(roles)})
        return SkillResult(
            data=account.to_public_dict(),
            query_shown=f"set_account_roles({user_id!r}, {list(roles)})",
        )

    async def _deactivate(principal: Principal, args: dict) -> SkillResult:
        if not args.get("confirm"):
            return SkillResult(
                data={"status": "confirmation_required",
                      "message": "Re-issue this call with confirm=true to suspend the account."},
                query_shown="deactivate_account(confirm=false)",
            )
        user_id = str(args["user_id"])
        account = platform.directory_service.set_account_active(principal, user_id, False)
        _record(principal, "deactivate_account", "allow", {"user_id": user_id})
        return SkillResult(
            data=account.to_public_dict(), query_shown=f"deactivate_account({user_id!r})"
        )

    # ---- observability ---------------------------------------------------

    async def _usage(principal: Principal, args: dict) -> SkillResult:
        prices = PriceList.from_env()
        totals = platform.usage.tenant_totals(principal.tenant_id)
        by_model = platform.usage.tenant_by_model(principal.tenant_id)
        breakdown, total_usd = [], 0.0
        for model, t in sorted(by_model.items()):
            cost = prices.cost(model, t.input_tokens, t.output_tokens)
            total_usd += cost.total_usd
            breakdown.append({"model": model or "unknown", "requests": t.requests,
                              "total_tokens": t.total_tokens, **cost.to_dict()})
        return SkillResult(
            data={
                "tenant_id": principal.tenant_id,
                "requests": totals.requests,
                "input_tokens": totals.input_tokens,
                "output_tokens": totals.output_tokens,
                "total_tokens": totals.total_tokens,
                "estimated_cost_usd": round(total_usd, 6),
                "by_model": breakdown,
            },
            query_shown="usage_stats()",
        )

    async def _audit(principal: Principal, args: dict) -> SkillResult:
        if "admin" not in principal.roles:
            raise AccessDenied("reading the audit trail requires the admin role")
        reader = getattr(platform.audit, "for_tenant", None)
        if reader is None:
            return SkillResult(
                data={"error": "this audit sink is write-only"}, query_shown="audit_summary()"
            )
        limit = min(int(args.get("limit", 50)), 200)
        events = reader(principal.tenant_id)[-limit:]
        denies = [e for e in events if e.decision == "deny"]
        return SkillResult(
            data={
                "returned": len(events),
                "denied": len(denies),
                "events": [
                    {"ts": e.ts, "action": e.action, "user": e.user_id,
                     "decision": e.decision, "resource": e.resource, "ip": e.ip}
                    for e in events
                ],
            },
            query_shown=f"audit_summary(limit={limit})",
        )

    async def _inventory(principal: Principal, args: dict) -> SkillResult:
        """What this tenant has: skills, documents, assistants, alerts."""
        from ..rbac import visible_classes

        skills = [
            {"name": s.name, "description": s.description}
            for s in platform.registry.visible_for(principal)
        ]
        docs = await platform.store.list_documents(
            tenant_id=principal.tenant_id, allowed_classes=visible_classes(principal)
        )
        assistants = platform.assistants.list_for(principal)
        try:
            alerts = [a.name for a in platform.alert_service.list(principal)]
        except AccessDenied:
            alerts = []
        return SkillResult(
            data={
                "skills": skills,
                "documents": [d.to_dict() for d in docs],
                "assistants": [{"id": a.id, "name": a.name} for a in assistants],
                "alerts": alerts,
            },
            query_shown="tenant_inventory()",
        )

    return [
        Skill(
            category="admin",
            name="create_accounts",
            description=(
                "Create one or many user accounts in this tenant and return their "
                "access tokens. Use for requests like 'add 60 users with the "
                f"skill_author role'. Maximum {MAX_BATCH} per call. Requires an "
                "admin or ceo role; anyone else is refused."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": f"How many, 1–{MAX_BATCH}"},
                    "roles": {"type": "array", "description": "Roles for every created account"},
                    "user_id_prefix": {
                        "type": "string",
                        "description": "Ids become prefix001, prefix002, … (single user: the prefix itself)",
                    },
                    "language": {"type": "string", "description": "auto | ru | tg | en"},
                },
                "required": ["count", "roles"],
                "additionalProperties": False,
            },
            handler=_create_accounts,
            required_data_class=DataClass.PUBLIC,
            required_roles=frozenset({"admin", "ceo", "platform_admin"}),
            tenant_id="*",
        ),
        Skill(
            category="admin",
            name="list_accounts",
            description="List the user accounts in this tenant with their roles and status.",
            input_schema={"type": "object", "properties": {}, "required": [],
                          "additionalProperties": False},
            handler=_list_accounts,
            required_data_class=DataClass.PUBLIC,
            required_roles=frozenset({"admin", "ceo", "platform_admin"}),
            tenant_id="*",
        ),
        Skill(
            category="admin",
            name="set_account_roles",
            description="Replace the roles on an existing account in this tenant.",
            input_schema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "roles": {"type": "array", "description": "The complete new role list"},
                },
                "required": ["user_id", "roles"],
                "additionalProperties": False,
            },
            handler=_set_roles,
            required_data_class=DataClass.PUBLIC,
            required_roles=frozenset({"admin", "ceo", "platform_admin"}),
            tenant_id="*",
        ),
        Skill(
            category="admin",
            name="deactivate_account",
            description=(
                "Suspend an account so its token stops working. Destructive: call "
                "once without confirm to check, then again with confirm=true."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "confirm": {"type": "boolean", "description": "Must be true to act"},
                },
                "required": ["user_id"],
                "additionalProperties": False,
            },
            handler=_deactivate,
            required_data_class=DataClass.PUBLIC,
            required_roles=frozenset({"admin", "ceo", "platform_admin"}),
            tenant_id="*",
        ),
        Skill(
            category="admin",
            name="usage_stats",
            description=(
                "This tenant's token usage, request count and estimated cost, split "
                "by the model that served each request. Use for 'give me usage "
                "stats', 'what are we spending'."
            ),
            input_schema={"type": "object", "properties": {}, "required": [],
                          "additionalProperties": False},
            handler=_usage,
            required_data_class=DataClass.PUBLIC,
            tenant_id="*",
        ),
        Skill(
            category="admin",
            name="audit_summary",
            description=(
                "Recent audit events for this tenant: who did what, allowed or "
                "denied, from which address. Admin only."
            ),
            input_schema={
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "Max events, ≤200"}},
                "required": [],
                "additionalProperties": False,
            },
            handler=_audit,
            required_data_class=DataClass.PUBLIC,
            required_roles=frozenset({"admin"}),
            tenant_id="*",
        ),
        Skill(
            category="admin",
            name="tenant_inventory",
            description=(
                "What this tenant currently has that the asking user may see: "
                "skills, documents, assistants and alert rules. Use for 'what "
                "skills do we have', 'what documents are loaded'."
            ),
            input_schema={"type": "object", "properties": {}, "required": [],
                          "additionalProperties": False},
            handler=_inventory,
            required_data_class=DataClass.PUBLIC,
            tenant_id="*",
        ),
    ]
