"""Cost control: per-user rate limit and per-tenant monthly budget."""

from __future__ import annotations

import calendar

import pytest
from fastapi.testclient import TestClient

from karag.api.app import create_app
from karag.api.security import InMemoryResolver
from karag.budget import UsageGuard
from karag.config import Settings
from karag.domain import Principal
from karag.errors import AccessDenied, BudgetExceeded, RateLimited
from karag.factory import build_platform
from karag.pricing import PriceList
from karag.tenants import InMemoryDirectory, Tenant
from karag.usage import SqliteUsageRecorder, UsageRecorder, month_bounds, month_key

EMP = Principal("koinoti", "emp", ("employee",))
OPS = Principal("kit", "ops", ("platform_admin",))
ADMIN = Principal("koinoti", "adm", ("admin",))
PRICES = PriceList({"m": (1_000.0, 0.0)})  # $1 per 1k input tokens: easy maths


class Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


NOV = calendar.timegm((2026, 11, 20, 12, 0, 0))


def test_rate_limit_is_a_sliding_minute_per_user():
    clock = Clock(NOV)
    guard = UsageGuard(UsageRecorder(), PRICES, per_minute=3, clock=clock)
    for _ in range(3):
        guard.check(EMP)
    with pytest.raises(RateLimited) as exc:
        guard.check(EMP)
    assert 1 <= exc.value.retry_after <= 61
    guard.check(Principal("koinoti", "someone-else", ("employee",)))  # per user
    clock.t += 61
    guard.check(EMP)  # the window has moved on


def test_budget_blocks_once_spent_and_resets_next_month(monkeypatch):
    clock = Clock(NOV)
    usage = UsageRecorder()
    monkeypatch.setattr("karag.usage.time.time", clock)
    guard = UsageGuard(usage, PRICES, default_budget_usd=5.0, per_minute=0, clock=clock)
    usage.record(tenant_id="koinoti", user_id="emp", usage={"input_tokens": 4000}, model="m")
    guard.check(EMP)  # $4 of $5
    usage.record(tenant_id="koinoti", user_id="emp", usage={"input_tokens": 1500}, model="m")
    guard.forget_spend("koinoti")
    with pytest.raises(BudgetExceeded, match=r"\$5\.00"):
        guard.check(EMP)
    assert guard.status("koinoti")["remaining_usd"] == 0
    clock.t = calendar.timegm((2026, 12, 1, 0, 0, 1))
    guard.check(EMP)  # a new month, a new budget
    assert guard.status("koinoti") == {
        "month": "2026-12", "budget_usd": 5.0, "spent_usd": 0.0, "remaining_usd": 5.0,
    }


def test_a_tenant_setting_overrides_the_default_budget():
    directory = InMemoryDirectory()
    directory.create_tenant(Tenant(id="koinoti", name="Koinoti", settings={"monthly_budget_usd": 50}))
    guard = UsageGuard(UsageRecorder(), PRICES, directory=directory, default_budget_usd=5.0)
    assert guard.budget_for("koinoti") == 50.0
    assert guard.budget_for("unknown") == 5.0


def test_sqlite_usage_counts_only_the_month_asked(tmp_path, monkeypatch):
    rec = SqliteUsageRecorder(str(tmp_path / "u.db"))
    for ts, n in ((calendar.timegm((2026, 10, 31, 23, 0, 0)), 100), (NOV, 7)):
        monkeypatch.setattr("karag.usage.time.time", lambda ts=ts: ts)
        rec.record(tenant_id="koinoti", user_id="u", usage={"input_tokens": n}, model="m")
    assert rec.tenant_month_by_model("koinoti", "2026-11")["m"].input_tokens == 7
    assert month_key(NOV) == "2026-11"
    start, end = month_bounds("2026-12")
    assert month_key(start) == "2026-12" and month_key(end) == "2027-01"


def test_only_a_platform_operator_sets_a_budget():
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    plat.directory.create_tenant(Tenant(id="koinoti", name="Koinoti"))
    with pytest.raises(AccessDenied):
        plat.directory_service.set_tenant_budget(ADMIN, "koinoti", 1000.0)
    assert plat.directory_service.set_tenant_budget(OPS, "koinoti", 120.0)
    assert plat.directory.get_tenant("koinoti").settings["monthly_budget_usd"] == 120.0
    assert plat.directory_service.set_tenant_budget(OPS, "koinoti", None)
    assert "monthly_budget_usd" not in plat.directory.get_tenant("koinoti").settings


def test_http_answers_429_for_both_limits():
    plat = build_platform(Settings(
        generator="fake", embedder="fake", store="memory", rate_limit_per_minute=2,
        tenant_monthly_budget_usd=100.0,
    ))
    plat.directory.create_tenant(Tenant(id="koinoti", name="Koinoti"))
    client = TestClient(create_app(plat, InMemoryResolver({"t_emp": EMP, "t_ops": OPS})))
    auth = {"Authorization": "Bearer t_emp"}

    assert client.post("/v1/ask", json={"query": "hello there"}, headers=auth).status_code == 200
    assert client.post("/v1/ask", json={"query": "hello again"}, headers=auth).status_code == 200
    r = client.post("/v1/ask", json={"query": "third"}, headers=auth)
    assert r.status_code == 429 and r.json()["code"] == "rate_limited"
    assert int(r.headers["Retry-After"]) >= 1

    plat.guard._per_minute = 0
    ops = {"Authorization": "Bearer t_ops"}
    r = client.patch("/v1/tenants/koinoti", json={"monthly_budget_usd": 0}, headers=ops)
    assert r.status_code == 200 and r.json()["budget"]["budget_usd"] == 0
    r = client.post("/v1/ask", json={"query": "anything"}, headers=auth)
    assert r.status_code == 429 and r.json()["code"] == "budget_exceeded"
    usage = client.get("/v1/usage", headers=auth).json()
    assert usage["budget"]["budget_usd"] == 0
    tenants = client.get("/v1/tenants", headers=ops).json()["tenants"]
    assert tenants[0]["budget"]["month"]
    # an explicit null removes the cap
    client.patch("/v1/tenants/koinoti", json={"monthly_budget_usd": None}, headers=ops)
    assert client.post("/v1/ask", json={"query": "anything"}, headers=auth).status_code == 200
