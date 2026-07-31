"""Skills data plane: registry visibility, executor RBAC, arg validation."""

import pytest

from karag.domain import DataClass as DC
from karag.domain import Principal
from karag.errors import SkillNotFound, ValidationError
from karag.skills.executor import SkillExecutor, validate_arguments
from karag.skills.registry import SkillRegistry
from karag.skills.samples import sales_by_store_skill



def _registry():
    r = SkillRegistry()
    r.register(sales_by_store_skill(tenant_id="koinoti"))
    return r


def test_finance_skill_visible_to_finance(finance):
    reg = _registry()
    names = {s.name for s in reg.visible_for(finance)}
    assert "sales_by_store" in names


def test_finance_skill_hidden_from_hr(hr):
    reg = _registry()
    assert reg.visible_for(hr) == []  # wrong role and no financial clearance


def test_finance_skill_hidden_cross_tenant(other_tenant_ceo):
    # skill is owned by koinoti; an evar principal can't see it
    reg = _registry()
    assert reg.visible_for(other_tenant_ceo) == []


async def test_executor_runs_for_authorized(finance):
    ex = SkillExecutor(_registry())
    res = await ex.execute(finance, "sales_by_store", {"store_id": 5, "date": "2026-07-20"})
    assert res.data["total_sales"] == 18450
    assert "sales_view" in res.query_shown  # provenance is surfaced


async def test_executor_denies_unauthorized_as_not_found(hr):
    ex = SkillExecutor(_registry())
    # HR is neither in the required role nor cleared -> looks like it doesn't exist
    with pytest.raises(SkillNotFound):
        await ex.execute(hr, "sales_by_store", {"store_id": 5, "date": "2026-07-20"})


async def test_executor_validates_arguments(finance):
    ex = SkillExecutor(_registry())
    with pytest.raises(ValidationError):
        await ex.execute(finance, "sales_by_store", {"store_id": 5})  # missing date


def test_schema_validation_rules():
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer"}, "mode": {"type": "string", "enum": ["a", "b"]}},
        "required": ["n"],
        "additionalProperties": False,
    }
    validate_arguments(schema, {"n": 3, "mode": "a"})  # ok
    with pytest.raises(ValidationError):
        validate_arguments(schema, {"n": "three"})  # wrong type
    with pytest.raises(ValidationError):
        validate_arguments(schema, {"n": 3, "extra": 1})  # unknown property
    with pytest.raises(ValidationError):
        validate_arguments(schema, {"n": 3, "mode": "z"})  # bad enum
    with pytest.raises(ValidationError):
        validate_arguments(schema, {})  # missing required


async def test_bool_not_accepted_as_integer(finance):
    # guards against Python's bool-is-int trap
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    with pytest.raises(ValidationError):
        validate_arguments(schema, {"n": True})
