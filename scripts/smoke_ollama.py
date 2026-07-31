"""Live end-to-end smoke against a real free model (Ollama).

Reads provider config from the environment (KARAG_GENERATOR=ollama etc.) and
runs the same scenarios as the offline demo, but on an actual LLM: knowledge
RAG with citations, the data-plane skill call, RBAC no-leak, and Office output.
"""

from __future__ import annotations

import asyncio

from karag.config import Settings
from karag.domain import DataClass, Principal
from karag.factory import build_platform
from karag.skills.registry import SkillRegistry
from karag.skills.samples import sales_by_store_skill, sales_report_skill


def line(t: str) -> None:
    print(f"\n{'=' * 68}\n{t}\n{'=' * 68}")


async def main() -> None:
    s = Settings.from_env()
    print(f"generator={s.generator} chat={s.ollama_chat_model} "
          f"embedder={s.embedder} embed={s.ollama_embed_model}/{s.ollama_embed_dim} store={s.store}")

    reg = SkillRegistry()
    reg.register(sales_by_store_skill(tenant_id="koinoti"))
    reg.register(sales_report_skill(tenant_id="koinoti"))
    plat = build_platform(s, registry=reg)

    admin = Principal("koinoti", "admin", ("admin",))
    finance = Principal("koinoti", "fin", ("finance",))
    hr = Principal("koinoti", "hr", ("hr",))

    await plat.ingestion.ingest_document(
        admin, title="Returns Policy",
        text="Customers may return unopened goods within 14 days for a full refund. "
             "Opened goods are non-refundable except for manufacturing defects.",
        data_class=DataClass.PUBLIC)
    await plat.ingestion.ingest_document(
        admin, title="Warehouse SOP",
        text="Stock transfers between warehouses require a signed movement note and "
             "same-day system entry.",
        data_class=DataClass.OPERATIONAL)
    await plat.ingestion.ingest_document(
        admin, title="Q2 Financials",
        text="Confidential: Q2 revenue was 4.2M and net profit was 610K somoni.",
        data_class=DataClass.FINANCIAL)

    line("1. KNOWLEDGE — finance asks a policy question (RAG + citations)")
    ans = await plat.rag.answer(finance, "What is the returns policy for opened goods?")
    print("  answer:", ans.text.strip()[:400])
    print("  citations:", [c.title for c in ans.citations])

    line("2. DATA PLANE — finance asks a live figure (model must call the skill)")
    ans = await plat.orchestrator.ask(
        finance, "Use the sales tool to get sales for store_id=5 on date=2026-07-20.")
    print("  plane:", ans.plane, "| skills_used:", ans.skills_used)
    print("  answer:", ans.text.strip()[:300])
    print("  query shown:", ans.queries_shown)

    line("3. RBAC — HR asks about financials (must NOT leak 610K / 4.2M)")
    ans = await plat.orchestrator.ask(hr, "What was Q2 revenue and net profit?")
    print("  plane:", ans.plane, "| skills_used:", ans.skills_used)
    print("  answer:", ans.text.strip()[:300])
    leaked = ("610" in ans.text) or ("4.2" in ans.text)
    print("  LEAKED financial figure?", leaked)

    line("4. OFFICE — finance requests an .xlsx report (output skill)")
    ans = await plat.orchestrator.ask(
        finance, "Generate a sales report file for store_id=5 with format=xlsx.")
    print("  skills_used:", ans.skills_used)
    for art in ans.artifacts:
        print(f"  artifact: {art.filename} {art.mime} ({len(art.content)} bytes, PK={art.content[:2]==b'PK'})")

    print("\nLive-model smoke complete.\n")


if __name__ == "__main__":
    asyncio.run(main())
