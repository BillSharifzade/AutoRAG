"""Live smoke test against Claude Opus 4.8 + a real embedder.

Requires an API key and network — NOT run by the offline suite. Use it to
validate the production path end to end:

    pip install anthropic httpx
    export ANTHROPIC_API_KEY=sk-ant-...
    # embedder: 'ollama' (free local), 'openai', or 'voyage'
    export KARAG_GENERATOR=anthropic KARAG_EMBEDDER=ollama KARAG_EMBED_DIM=768
    # for openai/voyage also export OPENAI_API_KEY / VOYAGE_API_KEY
    PYTHONPATH=. python scripts/smoke_claude.py

It runs the same scenarios as scripts/demo.py, but against the real model, so
you can confirm Claude's tool-use extraction and grounded answers behave as the
offline fake predicted.
"""

from __future__ import annotations

import asyncio
import os
import sys

from karag.config import Settings
from karag.domain import DataClass, Principal
from karag.factory import build_platform
from karag.skills.registry import SkillRegistry
from karag.skills.samples import sales_by_store_skill, sales_report_skill


async def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set — see the module docstring.")

    settings = Settings.from_env()
    settings = Settings(**{**settings.__dict__, "generator": "anthropic"})
    print(f"generator={settings.generator} model={settings.anthropic_model} "
          f"embedder={settings.embedder} store={settings.store}")

    reg = SkillRegistry()
    reg.register(sales_by_store_skill(tenant_id="koinoti"))
    reg.register(sales_report_skill(tenant_id="koinoti"))
    plat = build_platform(settings, registry=reg)

    admin = Principal("koinoti", "admin", ("admin",))
    finance = Principal("koinoti", "fin", ("finance",))
    hr = Principal("koinoti", "hr", ("hr",))

    await plat.ingestion.ingest_document(
        admin, title="Returns Policy",
        text="Customers may return unopened goods within 14 days for a refund.",
        data_class=DataClass.PUBLIC,
    )
    await plat.ingestion.ingest_document(
        admin, title="Q2 Financials",
        text="Confidential revenue and net profit figures for the quarter.",
        data_class=DataClass.FINANCIAL,
    )

    print("\n[knowledge] employee-style policy question:")
    ans = await plat.rag.answer(finance, "What is the returns policy?")
    print("  ", ans.text)
    print("   citations:", [c.title for c in ans.citations])

    print("\n[data] finance asks a live figure (natural language):")
    ans = await plat.orchestrator.ask(
        finance, "What were sales for store 5 on 2026-07-20?"
    )
    print("   plane:", ans.plane, "skills:", ans.skills_used)
    print("   ", ans.text)
    print("   query shown:", ans.queries_shown)

    print("\n[rbac] HR asks about financials (must not leak):")
    ans = await plat.orchestrator.ask(hr, "What was net profit for the quarter?")
    print("   plane:", ans.plane, "skills:", ans.skills_used)
    print("   ", ans.text)

    print("\n[office] finance asks for an Excel report:")
    ans = await plat.orchestrator.ask(
        finance, "Generate an xlsx sales report for store 5."
    )
    for art in ans.artifacts:
        print(f"   artifact: {art.filename} ({len(art.content)} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
