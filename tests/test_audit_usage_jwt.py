"""Audit trail, usage metering, and JWT auth."""

import time

import pytest

from karag.api.jwt_auth import JwtResolver, issue_jwt
from karag.audit import InMemoryAuditLog, JsonlAuditLog
from karag.config import Settings
from karag.domain import DataClass, Principal
from karag.errors import AccessDenied
from karag.factory import build_platform
from karag.skills.registry import SkillRegistry
from karag.skills.samples import sales_by_store_skill


# ---- audit ----
async def test_audit_records_ingest_retrieve_ask_and_denials():
    audit = InMemoryAuditLog()
    reg = SkillRegistry(); reg.register(sales_by_store_skill(tenant_id="koinoti"))
    plat = build_platform(
        Settings(generator="fake", embedder="fake", store="memory"),
        registry=reg, audit=audit,
    )
    admin = Principal("koinoti", "admin", ("admin",))
    employee = Principal("koinoti", "emp", ("employee",))
    hr = Principal("koinoti", "hr", ("hr",))

    await plat.ingestion.ingest_document(
        admin, title="Policy", text="Return within 14 days.", data_class=DataClass.PUBLIC)
    await plat.orchestrator.ask(employee, "What is the policy?")
    # HR tries the finance skill (denied — not visible)
    await plat.orchestrator.ask(hr, "sales store_id=5 date=2026-07-20")

    actions = [e.action for e in audit.events]
    assert "ingest" in actions and "retrieve" in actions and "ask" in actions
    # ingest allowed
    assert any(e.action == "ingest" and e.decision == "allow" for e in audit.events)
    # every event is tenant-scoped
    assert all(e.tenant_id == "koinoti" for e in audit.events)


async def test_audit_logs_skill_deny():
    audit = InMemoryAuditLog()
    reg = SkillRegistry(); reg.register(sales_by_store_skill(tenant_id="koinoti"))
    plat = build_platform(
        Settings(generator="fake", embedder="fake", store="memory"),
        registry=reg, audit=audit,
    )
    finance = Principal("koinoti", "fin", ("finance",))
    # missing 'date' -> validation deny recorded
    await plat.orchestrator.ask(finance, "sales store_id=5")
    assert any(
        e.action == "skill_execute" and e.decision == "deny" for e in audit.events
    )


def test_jsonl_audit_sink(tmp_path):
    p = tmp_path / "audit.jsonl"
    log = JsonlAuditLog(str(p))
    from karag.audit import AuditEvent
    log.record(AuditEvent(action="ask", tenant_id="t", user_id="u", decision="allow"))
    log.record(AuditEvent(action="ingest", tenant_id="t", user_id="u", decision="deny"))
    lines = p.read_text().strip().splitlines()
    assert len(lines) == 2
    assert '"action": "ask"' in lines[0]


# ---- usage ----
async def test_usage_metering_counts_requests():
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    p = Principal("koinoti", "u", ("employee",))
    for _ in range(3):
        await plat.orchestrator.ask(p, "hello")
    assert plat.usage.tenant_totals("koinoti").requests == 3
    assert plat.usage.user_totals("koinoti", "u").requests == 3


# ---- jwt ----
def test_jwt_roundtrip():
    r = JwtResolver("s3cret")
    tok = issue_jwt("s3cret", {"tenant": "koinoti", "sub": "ceo1", "roles": ["ceo"]})
    p = r.resolve(tok)
    assert p == Principal("koinoti", "ceo1", ("ceo",))


def test_jwt_rejects_tampered_signature():
    tok = issue_jwt("s3cret", {"tenant": "t", "sub": "u", "roles": ["hr"]})
    r = JwtResolver("s3cret")
    # flip a char in the payload segment
    head, body, sig = tok.split(".")
    tampered = f"{head}.{body[:-1]}{'A' if body[-1] != 'A' else 'B'}.{sig}"
    with pytest.raises(AccessDenied):
        r.resolve(tampered)


def test_jwt_rejects_wrong_secret():
    tok = issue_jwt("s3cret", {"tenant": "t", "sub": "u", "roles": []})
    with pytest.raises(AccessDenied):
        JwtResolver("different").resolve(tok)


def test_jwt_rejects_expired():
    tok = issue_jwt("s3cret", {"tenant": "t", "sub": "u", "roles": []}, ttl_seconds=-1)
    with pytest.raises(AccessDenied):
        JwtResolver("s3cret").resolve(tok)


def test_jwt_string_roles():
    tok = issue_jwt("s3cret", {"tenant": "t", "sub": "u", "roles": "hr finance"})
    p = JwtResolver("s3cret").resolve(tok)
    assert set(p.roles) == {"hr", "finance"}
