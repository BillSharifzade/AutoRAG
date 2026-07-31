"""RBAC matrix: explicit grants, unions, and default-deny."""

from karag.domain import DataClass as DC
from karag.domain import Principal
from karag.rbac import can_access, can_ingest, visible_classes


def test_ceo_sees_all_classes(ceo):
    assert visible_classes(ceo) == frozenset(DC)


def test_hr_never_sees_financial(hr):
    assert can_access(hr, DC.HR)
    assert not can_access(hr, DC.FINANCIAL)


def test_finance_never_sees_hr(finance):
    assert can_access(finance, DC.FINANCIAL)
    assert not can_access(finance, DC.HR)


def test_employee_only_public_and_operational(employee):
    assert visible_classes(employee) == frozenset({DC.PUBLIC, DC.OPERATIONAL})


def test_no_roles_is_default_deny(nobody):
    assert visible_classes(nobody) == frozenset()
    for dc in DC:
        assert not can_access(nobody, dc)


def test_unknown_role_contributes_nothing():
    p = Principal(tenant_id="t", user_id="u", roles=("wizard",))
    assert visible_classes(p) == frozenset()


def test_role_union():
    p = Principal(tenant_id="t", user_id="u", roles=("hr", "finance"))
    assert visible_classes(p) == frozenset({DC.PUBLIC, DC.OPERATIONAL, DC.HR, DC.FINANCIAL})


def test_ingest_requires_role_and_clearance(employee, admin, hr):
    assert not can_ingest(employee, DC.PUBLIC)  # no ingest role
    assert can_ingest(admin, DC.FINANCIAL)  # admin cleared for all
    assert not can_ingest(hr, DC.FINANCIAL)  # hr can't ingest a class it can't read
