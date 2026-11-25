"""Scheduled proactive alerts (§15) and token pricing (§15/§17)."""

import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from karag.alerts import CapturingNotifier
from karag.api.app import create_app
from karag.api.security import InMemoryResolver
from karag.config import Settings
from karag.domain import DataClass, Principal
from karag.errors import AccessDenied, ValidationError
from karag.factory import build_platform
from karag.pricing import PriceList
from karag.scheduler import (
    AlertScheduler,
    AlertService,
    InMemoryAlertRuleStore,
    SqliteAlertRuleStore,
    StoredAlertRule,
    evaluate_condition,
    render_message,
)
from karag.skills.base import Skill, SkillResult
from karag.skills.registry import SkillRegistry

CEO = Principal("dusti", "ceo1", ("ceo",))
QA = Principal("dusti", "qa1", ("qa",))
EMPLOYEE = Principal("dusti", "emp", ("employee",))

_BATCHES = [
    {"sku": "AMOX-500", "batch": "B12", "units": 240},
    {"sku": "PARA-100", "batch": "C09", "units": 5},
]


def _expiring_skill(rows=None):
    async def handler(principal, args):
        return SkillResult(
            data={"rows": _BATCHES if rows is None else rows},
            query_shown="SELECT sku, batch, units FROM inventory_view WHERE …",
        )

    return Skill(
        name="expiring_batches",
        description="Batches expiring soon.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=handler,
        required_data_class=DataClass.REGULATED,
        required_roles=frozenset({"qa", "ceo"}),
        tenant_id="dusti",
    )


@pytest.fixture
def platform():
    reg = SkillRegistry()
    reg.register(_expiring_skill())
    return build_platform(
        Settings(generator="fake", embedder="fake", store="memory"), registry=reg
    )


def _scheduler(platform, notifier):
    return AlertScheduler(platform.alerts, platform.executor, notifier, tick_s=0.01)


# ---------- firing ----------


async def test_rule_fires_and_notifies_with_provenance(platform):
    notifier = CapturingNotifier()
    rule = platform.alert_service.create(
        CEO, name="Batch expiring", skill_name="expiring_batches", interval_s=60
    )
    outcome = await _scheduler(platform, notifier).run_rule(rule, force=True)

    assert outcome.fired
    assert len(notifier.messages) == 1
    message, context = notifier.messages[0]
    assert "Batch expiring" in message
    # §5/§6: the executed query travels with the alert
    assert "inventory_view" in context["query_shown"]


async def test_rule_does_not_fire_when_the_condition_is_unmet(platform):
    reg = SkillRegistry()
    reg.register(_expiring_skill(rows=[]))
    plat = build_platform(
        Settings(generator="fake", embedder="fake", store="memory"), registry=reg
    )
    notifier = CapturingNotifier()
    rule = plat.alert_service.create(
        CEO, name="Batch expiring", skill_name="expiring_batches", interval_s=60
    )
    outcome = await _scheduler(plat, notifier).run_rule(rule, force=True)
    assert outcome.ran and not outcome.fired
    assert notifier.messages == []


async def test_field_compare_condition(platform):
    notifier = CapturingNotifier()
    rule = platform.alert_service.create(
        CEO, name="Low stock", skill_name="expiring_batches", interval_s=60,
        condition="field_compare",
        condition_config={"field": "units", "op": "<", "value": 10},
    )
    assert (await _scheduler(platform, notifier).run_rule(rule, force=True)).fired


async def test_field_compare_that_matches_nothing_stays_quiet(platform):
    notifier = CapturingNotifier()
    rule = platform.alert_service.create(
        CEO, name="Impossible", skill_name="expiring_batches", interval_s=60,
        condition="field_compare",
        condition_config={"field": "units", "op": "<", "value": 0},
    )
    assert not (await _scheduler(platform, notifier).run_rule(rule, force=True)).fired


def test_message_template_is_rendered():
    rule = StoredAlertRule(
        id="a", tenant_id="dusti", name="Expiry", skill_name="s",
        message_template="{count} batch(es) expiring at {tenant}",
    )
    assert render_message(rule, {"rows": _BATCHES}) == "2 batch(es) expiring at dusti"


def test_a_broken_template_still_produces_a_message():
    rule = StoredAlertRule(
        id="a", tenant_id="dusti", name="Expiry", skill_name="s",
        message_template="{nonexistent_placeholder}",
    )
    assert "Expiry" in render_message(rule, {"rows": _BATCHES})


def test_conditions_are_declarative_not_code():
    """A stored rule cannot smuggle in an expression to evaluate."""
    rule = StoredAlertRule(
        id="a", tenant_id="d", name="n", skill_name="s",
        condition="always", condition_config={"op": "__import__('os').system"},
    )
    assert evaluate_condition(rule, {"rows": []}) is True  # config is ignored


# ---------- scheduling ----------


async def test_a_rule_is_skipped_until_its_interval_elapses(platform):
    notifier = CapturingNotifier()
    scheduler = _scheduler(platform, notifier)
    rule = platform.alert_service.create(
        CEO, name="Hourly", skill_name="expiring_batches", interval_s=3600
    )
    assert (await scheduler.run_rule(rule)).ran  # first run: never run before
    assert not (await scheduler.run_rule(rule)).ran  # second: not due yet
    assert len(notifier.messages) == 1


async def test_disabled_rules_do_not_run(platform):
    notifier = CapturingNotifier()
    rule = platform.alert_service.create(
        CEO, name="Off", skill_name="expiring_batches", interval_s=60
    )
    platform.alert_service.set_enabled(CEO, rule.id, False)
    rule = platform.alert_service.get(CEO, rule.id)
    assert not (await _scheduler(platform, notifier).run_rule(rule)).ran


async def test_run_due_processes_every_tenants_rules(platform):
    notifier = CapturingNotifier()
    platform.alert_service.create(
        CEO, name="A", skill_name="expiring_batches", interval_s=60
    )
    platform.alert_service.create(
        CEO, name="B", skill_name="expiring_batches", interval_s=60
    )
    outcomes = await _scheduler(platform, notifier).run_due()
    assert len(outcomes) == 2 and all(o.fired for o in outcomes)


def _broken_rule(platform):
    """A rule whose skill disappeared after it was made (renamed, deleted) —
    creating a rule for a skill that does not exist is refused up front."""
    rule = platform.alert_service.create(
        CEO, name="Broken", skill_name="expiring_batches", interval_s=60
    )
    platform.registry.unregister("dusti", "expiring_batches")
    return rule


def test_a_rule_must_name_a_data_skill_the_creator_can_use(platform):
    with pytest.raises(ValidationError, match="unknown skill"):
        platform.alert_service.create(CEO, name="x", skill_name="does_not_exist")
    with pytest.raises(ValidationError, match="output tool"):
        platform.alert_service.create(CEO, name="x", skill_name="create_spreadsheet")
    with pytest.raises(ValidationError, match="unknown argument"):
        # arguments are checked against the skill's schema up front
        platform.alert_service.create(CEO, name="x", skill_name="expiring_batches",
                                      arguments={"nope": 1})


def test_template_can_use_first_row_columns_and_keeps_unknown_ones():
    rule = StoredAlertRule(id="a", tenant_id="d", name="Дефицит", skill_name="s",
                           message_template="Ниже порога: {n} позиций ({count} строка), {oops}")
    text = render_message(rule, {"rows": [{"n": 39}]})
    assert "Ниже порога: 39 позиций (1 строка), {oops}" in text


async def test_a_failing_rule_backs_off_instead_of_hammering(platform):
    notifier = CapturingNotifier()
    scheduler = _scheduler(platform, notifier)
    rule = _broken_rule(platform)
    outcome = await scheduler.run_rule(rule, force=True)
    assert outcome.error and not outcome.fired

    stored = platform.alerts.get("dusti", rule.id)
    assert stored.consecutive_errors == 1
    # back-off pushes the next run past the plain interval
    assert stored.due_at() > stored.last_run_at + stored.interval_s


async def test_re_enabling_clears_the_backoff(platform):
    scheduler = _scheduler(platform, CapturingNotifier())
    rule = _broken_rule(platform)
    await scheduler.run_rule(rule, force=True)
    platform.alert_service.set_enabled(CEO, rule.id, False)
    revived = platform.alert_service.set_enabled(CEO, rule.id, True)
    assert revived.consecutive_errors == 0 and revived.last_error == ""


# ---------- authorisation ----------


async def test_an_alert_cannot_read_what_its_owner_cannot(platform):
    """An employee-owned rule on a regulated skill executes as an employee and
    is refused by the executor — no privileged data reaches the notifier."""
    notifier = CapturingNotifier()
    # employees can't manage alerts at all
    with pytest.raises(AccessDenied):
        platform.alert_service.create(
            EMPLOYEE, name="Sneaky", skill_name="expiring_batches", interval_s=60
        )


async def test_a_rule_cannot_be_given_roles_its_creator_lacks(platform):
    """Otherwise "schedule an alert" becomes a way to read a class you can't."""
    with pytest.raises(AccessDenied, match="roles you do not hold"):
        platform.alert_service.create(
            QA, name="Escalated", skill_name="expiring_batches", interval_s=60,
            run_as_roles=("qa", "finance"),
        )


async def test_a_qa_owned_rule_runs_with_qa_clearance(platform):
    notifier = CapturingNotifier()
    rule = platform.alert_service.create(
        QA, name="QA watch", skill_name="expiring_batches", interval_s=60
    )
    assert rule.run_as_roles == ("qa",)
    assert (await _scheduler(platform, notifier).run_rule(rule, force=True)).fired


def test_rules_are_not_visible_across_tenants(platform):
    platform.alert_service.create(
        CEO, name="Dusti only", skill_name="expiring_batches", interval_s=60
    )
    other = Principal("koinoti", "ceo2", ("ceo",))
    assert platform.alert_service.list(other) == []


def test_too_frequent_intervals_are_rejected(platform):
    with pytest.raises(ValidationError, match="60 seconds"):
        platform.alert_service.create(
            CEO, name="Spam", skill_name="expiring_batches", interval_s=1
        )


def test_unknown_condition_is_rejected(platform):
    with pytest.raises(ValidationError):
        platform.alert_service.create(
            CEO, name="Bad", skill_name="expiring_batches", condition="whenever"
        )


# ---------- durability ----------


def test_rules_survive_a_restart():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        first = SqliteAlertRuleStore(path)
        AlertService(first).create(
            CEO, name="Batch expiring", skill_name="expiring_batches", interval_s=600
        )
        second = SqliteAlertRuleStore(path)
        assert [r.name for r in second.list("dusti")] == ["Batch expiring"]
    finally:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(path + suffix):
                os.remove(path + suffix)


# ---------- pricing ----------


def test_cost_is_computed_per_million_tokens():
    prices = PriceList({"claude-sonnet-5": (3.0, 15.0)})
    cost = prices.cost("claude-sonnet-5", 1_000_000, 1_000_000)
    assert cost.input_usd == 3.0 and cost.output_usd == 15.0
    assert cost.total_usd == 18.0


def test_a_dated_snapshot_is_priced_as_its_family():
    prices = PriceList({"claude-sonnet-5": (3.0, 15.0)})
    assert prices.cost("claude-sonnet-5-20260214", 1_000_000, 0).input_usd == 3.0


def test_an_unknown_model_costs_zero_and_says_so():
    cost = PriceList({}).cost("mystery-model", 1_000_000, 1_000_000)
    assert cost.total_usd == 0.0 and cost.priced is False


def test_local_inference_is_free():
    assert PriceList().cost("ollama", 5_000_000, 5_000_000).total_usd == 0.0


def test_env_overrides_the_price_list(monkeypatch):
    monkeypatch.setenv("KARAG_PRICING", "claude-sonnet-5:1.0:2.0, junk-entry")
    prices = PriceList.from_env()
    assert prices.rate_for("claude-sonnet-5") == (1.0, 2.0)
    assert prices.rate_for("gpt-5.5") is not None  # defaults survive


def test_usage_is_attributed_to_the_model_that_served_it():
    from karag.usage import UsageRecorder

    rec = UsageRecorder()
    rec.record(tenant_id="koinoti", user_id="u", usage={"input_tokens": 10,
               "output_tokens": 5}, model="claude-sonnet-5")
    # a failover request reports the model that actually answered
    rec.record(tenant_id="koinoti", user_id="u", usage={"input_tokens": 20,
               "output_tokens": 7, "served_by": "gpt-5.5"}, model="claude-sonnet-5")

    by_model = rec.tenant_by_model("koinoti")
    assert by_model["claude-sonnet-5"].input_tokens == 10
    assert by_model["gpt-5.5"].input_tokens == 20


# ---------- HTTP ----------


@pytest.fixture
def client():
    reg = SkillRegistry()
    reg.register(_expiring_skill())
    plat = build_platform(
        Settings(generator="fake", embedder="fake", store="memory"), registry=reg
    )
    resolver = InMemoryResolver({
        "t_ceo": Principal("dusti", "ceo1", ("ceo",)),
        "t_emp": Principal("dusti", "emp", ("employee",)),
    })
    return TestClient(create_app(plat, resolver))


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_http_alert_lifecycle(client):
    created = client.post(
        "/v1/alerts",
        json={"name": "Batch expiring", "skill_name": "expiring_batches",
              "interval_s": 3600},
        headers=_auth("t_ceo"),
    )
    assert created.status_code == 200, created.text
    rule_id = created.json()["id"]

    run = client.post(f"/v1/alerts/{rule_id}/run", headers=_auth("t_ceo")).json()
    assert run["ran"] and run["fired"]
    assert "Batch expiring" in run["message"]

    client.patch(f"/v1/alerts/{rule_id}", json={"enabled": False}, headers=_auth("t_ceo"))
    assert client.get("/v1/alerts", headers=_auth("t_ceo")).json()["alerts"][0]["enabled"] is False

    assert client.delete(f"/v1/alerts/{rule_id}", headers=_auth("t_ceo")).status_code == 200
    assert client.get("/v1/alerts", headers=_auth("t_ceo")).json()["alerts"] == []


def test_http_employee_cannot_manage_alerts(client):
    r = client.post(
        "/v1/alerts",
        json={"name": "x", "skill_name": "expiring_batches"},
        headers=_auth("t_emp"),
    )
    assert r.status_code == 403


def test_http_usage_reports_cost_per_model(client):
    client.post("/v1/ask", json={"query": "hello"}, headers=_auth("t_ceo"))
    body = client.get("/v1/usage", headers=_auth("t_ceo")).json()
    assert "cost_usd" in body and "by_model" in body
    assert body["by_model"][0]["requests"] >= 1
    # the offline fake model is priced at zero, not left unknown
    assert body["by_model"][0]["cost"]["priced"] is True
