"""Example verified skills, mirroring the concept doc's use cases.

These stand in for real read-only DB views / APIs. In production each handler
would run a parameterized query against a read replica; here they return fixed,
deterministic data so the whole data plane can be tested offline.
"""

from __future__ import annotations

from ..domain import DataClass, Principal
from ..office import OfficeService
from .base import Skill, SkillResult

_office = OfficeService()

# A tiny fake "read replica".
_SALES = {
    ("koinoti", 5, "2026-07-20"): 18450,
    ("koinoti", 5, "2026-07-19"): 17200,
    ("evar", 1, "2026-07-20"): 9300,
}
_EXPIRING = {
    ("dusti", 30): [
        {"sku": "AMOX-500", "batch": "B12", "expires": "2026-08-05", "units": 240},
        {"sku": "PARA-100", "batch": "C09", "expires": "2026-08-12", "units": 500},
    ]
}


async def _sales_by_store(principal: Principal, args: dict) -> SkillResult:
    key = (principal.tenant_id, args["store_id"], args["date"])
    total = _SALES.get(key)
    query = (
        "SELECT SUM(amount) FROM sales_view "
        f"WHERE tenant='{principal.tenant_id}' "
        f"AND store_id={args['store_id']} AND day='{args['date']}'"
    )
    return SkillResult(
        data={"store_id": args["store_id"], "date": args["date"], "total_sales": total},
        query_shown=query,
    )


async def _expiring_batches(principal: Principal, args: dict) -> SkillResult:
    within = args.get("within_days", 30)
    rows = _EXPIRING.get((principal.tenant_id, within), [])
    query = (
        "SELECT sku, batch, expires, units FROM inventory_view "
        f"WHERE tenant='{principal.tenant_id}' "
        f"AND expires <= now() + interval '{within} days'"
    )
    return SkillResult(data={"batches": rows}, query_shown=query)


async def _sales_report_file(principal: Principal, args: dict) -> SkillResult:
    """Output skill (Phase 1.5): a verified query rendered as a ready Office file."""
    fmt = args.get("format", "xlsx")
    days = [
        (principal.tenant_id, args["store_id"], d)
        for d in ("2026-07-19", "2026-07-20")
    ]
    headers = ["store_id", "date", "total_sales"]
    rows = [[t[1], t[2], _SALES.get(t)] for t in days]
    title = f"Sales report store {args['store_id']}"
    artifact = _office.report(title=title, headers=headers, rows=rows, fmt=fmt)
    query = (
        "SELECT store_id, day, SUM(amount) FROM sales_view "
        f"WHERE tenant='{principal.tenant_id}' AND store_id={args['store_id']} "
        "GROUP BY store_id, day"
    )
    return SkillResult(
        data={"rows": len(rows), "title": title},
        query_shown=query,
        artifact=artifact,
    )


def sales_report_skill(tenant_id: str = "*") -> Skill:
    return Skill(
        name="sales_report_file",
        description="Generate a formatted sales report as an Office file (xlsx/docx/csv).",
        input_schema={
            "type": "object",
            "properties": {
                "store_id": {"type": "integer", "description": "Store identifier"},
                "format": {"type": "string", "enum": ["xlsx", "docx", "pptx", "csv"]},
            },
            "required": ["store_id"],
            "additionalProperties": False,
        },
        handler=_sales_report_file,
        required_data_class=DataClass.FINANCIAL,
        required_roles=frozenset({"finance", "ceo"}),
        tenant_id=tenant_id,
    )


def sales_by_store_skill(tenant_id: str = "*") -> Skill:
    return Skill(
        name="sales_by_store",
        description="Return total sales for a store on a given date.",
        input_schema={
            "type": "object",
            "properties": {
                "store_id": {"type": "integer", "description": "Store identifier"},
                "date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
            },
            "required": ["store_id", "date"],
            "additionalProperties": False,
        },
        handler=_sales_by_store,
        required_data_class=DataClass.FINANCIAL,
        required_roles=frozenset({"finance", "ceo"}),
        tenant_id=tenant_id,
    )


def expiring_batches_skill(tenant_id: str = "*") -> Skill:
    return Skill(
        name="expiring_batches",
        description="List medication batches expiring within N days.",
        input_schema={
            "type": "object",
            "properties": {
                "within_days": {"type": "integer", "description": "Horizon in days"},
            },
            "required": ["within_days"],
            "additionalProperties": False,
        },
        handler=_expiring_batches,
        required_data_class=DataClass.REGULATED,
        required_roles=frozenset({"qa", "ceo"}),
        tenant_id=tenant_id,
    )
