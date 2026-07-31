"""Proactive alert engine: fires through a notifier only when the rule matches."""

from karag.alerts import AlertEngine, AlertRule, CapturingNotifier
from karag.domain import Principal
from karag.skills.executor import SkillExecutor
from karag.skills.registry import SkillRegistry
from karag.skills.samples import expiring_batches_skill


def _engine():
    reg = SkillRegistry(); reg.register(expiring_batches_skill(tenant_id="dusti"))
    cap = CapturingNotifier()
    return AlertEngine(SkillExecutor(reg), cap), cap


async def test_alert_fires_when_condition_met():
    engine, cap = _engine()
    qa = Principal("dusti", "system", ("qa",))
    rule = AlertRule(
        name="expiring-soon", principal=qa, skill_name="expiring_batches",
        arguments={"within_days": 30},
        condition=lambda data: len(data.get("batches", [])) > 0,
        message=lambda data: f"{len(data['batches'])} batches expiring soon",
    )
    fired = await engine.run_once(rule)
    assert fired is True
    assert len(cap.messages) == 1
    msg, ctx = cap.messages[0]
    assert "batches expiring soon" in msg
    assert ctx["tenant_id"] == "dusti" and ctx["skill"] == "expiring_batches"


async def test_alert_silent_when_condition_not_met():
    engine, cap = _engine()
    qa = Principal("dusti", "system", ("qa",))
    rule = AlertRule(
        name="none", principal=qa, skill_name="expiring_batches",
        arguments={"within_days": 999},  # no data for this horizon
        condition=lambda data: len(data.get("batches", [])) > 0,
    )
    fired = await engine.run_once(rule)
    assert fired is False
    assert cap.messages == []


async def test_alert_respects_rbac():
    # an underprivileged system principal can't run the regulated skill
    import pytest
    from karag.errors import SkillNotFound
    engine, _ = _engine()
    emp = Principal("dusti", "system", ("employee",))
    rule = AlertRule(name="x", principal=emp, skill_name="expiring_batches",
                     arguments={"within_days": 30})
    with pytest.raises(SkillNotFound):
        await engine.run_once(rule)
