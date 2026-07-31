"""End-to-end KARAG demo on the free/offline fake gateway.

Run:  .venv/bin/python scripts/demo.py

Exercises: multi-tenant ingest, RBAC-filtered knowledge answers with citations,
the verified-skills data plane with provenance, and access denials — all
deterministic, no network, no API key.
"""

from __future__ import annotations

import asyncio

from karag.config import Settings
from karag.domain import DataClass, Principal
from karag.factory import build_platform
from karag.skills.registry import SkillRegistry
from karag.skills.samples import (
    expiring_batches_skill,
    sales_by_store_skill,
    sales_report_skill,
)


def line(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


async def main() -> None:
    reg = SkillRegistry()
    reg.register(sales_by_store_skill(tenant_id="koinoti"))
    reg.register(sales_report_skill(tenant_id="koinoti"))
    reg.register(expiring_batches_skill(tenant_id="dusti"))
    # Persistent SQLite store (stdlib) instead of pure in-memory, to prove it too.
    plat = build_platform(
        Settings(generator="fake", embedder="fake", store="sqlite", sqlite_path=":memory:"),
        registry=reg,
    )

    admin = Principal("koinoti", "admin", ("admin",))
    ceo = Principal("koinoti", "ceo", ("ceo",))
    hr = Principal("koinoti", "hr", ("hr",))
    finance = Principal("koinoti", "fin", ("finance",))
    employee = Principal("koinoti", "emp", ("employee",))

    line("1. INGEST (koinoti) — documents across data classes")
    for title, text, klass in [
        ("Returns Policy", "Customers may return unopened goods within 14 days.", DataClass.PUBLIC),
        ("Q2 Financials", "Confidential revenue and net profit for the quarter.", DataClass.FINANCIAL),
        ("Comp Bands", "Confidential HR salary bands for staff.", DataClass.HR),
    ]:
        doc = await plat.ingestion.ingest_document(admin, title=title, text=text, data_class=klass)
        print(f"  ingested {doc.title:16} class={doc.data_class.value}")

    line("2. KNOWLEDGE PLANE — employee asks a policy question")
    ans = await plat.orchestrator.ask(employee, "What is our returns policy?")
    print(f"  plane={ans.plane}  answer={ans.text!r}")
    print(f"  citations: {[c.title for c in ans.citations]}")

    line("3. RBAC — HR asks about financials (must NOT leak the number)")
    ans = await plat.orchestrator.ask(hr, "revenue and net profit for the quarter")
    print(f"  plane={ans.plane}  answer={ans.text!r}")
    print(f"  leaked 'profit'? {'profit' in ans.text.lower()}")

    line("4. DATA PLANE — finance asks a live figure via a verified skill")
    ans = await plat.orchestrator.ask(finance, "sales report store_id=5 date=2026-07-20")
    print(f"  plane={ans.plane}  skills_used={ans.skills_used}")
    print(f"  answer={ans.text!r}")
    print(f"  query shown (provenance): {ans.queries_shown}")

    line("5. RBAC on skills — employee tries the same data query")
    ans = await plat.orchestrator.ask(employee, "sales report store_id=5 date=2026-07-20")
    print(f"  skills_used={ans.skills_used}  (finance skill was never offered)")
    print(f"  leaked '18450'? {'18450' in ans.text}")

    line("6. CEO sees everything in their own tenant")
    ans = await plat.orchestrator.ask(ceo, "revenue and net profit for the quarter")
    print(f"  plane={ans.plane}  citations: {[c.title for c in ans.citations]}")

    line("7. OFFICE OUTPUT (Phase 1.5) — finance generates a ready .xlsx report")
    ans = await plat.orchestrator.ask(finance, "generate report store_id=5 format=xlsx")
    for art in ans.artifacts:
        print(f"  artifact: {art.filename}  {art.mime}  ({len(art.content)} bytes)")
        with open(art.filename, "wb") as fh:
            fh.write(art.content)
        print(f"  wrote {art.filename} to disk (opens in Excel/LibreOffice)")

    print("\nDemo complete — every plane and guard exercised offline.\n")


if __name__ == "__main__":
    asyncio.run(main())
