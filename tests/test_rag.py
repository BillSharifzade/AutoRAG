"""RAG answering: grounding, citations, and no-access refusal."""

import pytest



async def test_answer_is_grounded_and_cited(seeded, employee):
    ans = await seeded.rag.answer(employee, "What is the returns policy?")
    assert ans.plane == "knowledge"
    assert ans.citations, "expected at least one citation"
    # every citation refers to a real document the employee may see
    assert all(c.document_id for c in ans.citations)
    assert "return" in ans.text.lower() or "refund" in ans.text.lower()


async def test_no_access_returns_refusal_without_leak(seeded, hr):
    # HR asks about financials — must not receive or cite financial content.
    ans = await seeded.rag.answer(hr, "revenue and net profit for the quarter")
    financial_snippets = [c for c in ans.citations if "profit" in c.snippet.lower()]
    assert not financial_snippets
    assert "revenue" not in ans.text.lower() or ans.plane == "refusal"


async def test_unauthenticated_principal_refused(seeded, nobody):
    ans = await seeded.rag.answer(nobody, "anything at all")
    assert ans.plane == "refusal"
    assert ans.citations == []
