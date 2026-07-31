"""End-to-end orchestration across both planes with RBAC + provenance."""

import pytest



async def test_knowledge_query_returns_citations(seeded, employee):
    ans = await seeded.orchestrator.ask(employee, "What is our returns policy?")
    assert ans.plane in ("knowledge", "mixed")
    assert ans.citations
    assert not ans.skills_used


async def test_data_plane_skill_call_with_provenance(seeded, finance):
    # kv contract drives the deterministic fake to call the finance skill.
    ans = await seeded.orchestrator.ask(
        finance, "sales report store_id=5 date=2026-07-20"
    )
    assert "sales_by_store" in ans.skills_used
    assert ans.plane in ("data", "mixed")
    assert any("sales_view" in q for q in ans.queries_shown)  # executed query shown
    assert "18450" in ans.text  # the verified number, not a hallucination


async def test_unauthorized_skill_is_never_offered(seeded, hr):
    # HR cannot see the finance skill, so even a data-shaped query can't run it.
    ans = await seeded.orchestrator.ask(
        hr, "sales report store_id=5 date=2026-07-20"
    )
    assert ans.skills_used == []
    assert "18450" not in ans.text  # no leak of the financial figure


async def test_cross_tenant_skill_invisible(seeded, other_tenant_ceo):
    ans = await seeded.orchestrator.ask(
        other_tenant_ceo, "sales report store_id=1 date=2026-07-20"
    )
    assert ans.skills_used == []


async def test_regulated_skill_requires_qa_or_ceo():
    # Build a dusti tenant platform with the regulated skill.
    from karag.config import Settings
    from karag.domain import Principal
    from karag.factory import build_platform
    from karag.skills.registry import SkillRegistry
    from karag.skills.samples import expiring_batches_skill

    reg = SkillRegistry()
    reg.register(expiring_batches_skill(tenant_id="dusti"))
    plat = build_platform(
        Settings(generator="fake", embedder="fake", store="memory"), registry=reg
    )
    qa = Principal(tenant_id="dusti", user_id="qa1", roles=("qa",))
    emp = Principal(tenant_id="dusti", user_id="e", roles=("employee",))

    ok = await plat.orchestrator.ask(qa, "expiring batches within_days=30")
    assert "expiring_batches" in ok.skills_used
    assert "AMOX-500" in ok.text

    blocked = await plat.orchestrator.ask(emp, "expiring batches within_days=30")
    assert blocked.skills_used == []
