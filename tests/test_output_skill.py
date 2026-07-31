"""Phase 1.5: an output skill returns a real Office file, under RBAC."""

import io
import zipfile

import pytest

from karag.config import Settings
from karag.domain import Principal
from karag.factory import build_platform
from karag.skills.registry import SkillRegistry
from karag.skills.samples import sales_report_skill


def _platform():
    reg = SkillRegistry()
    reg.register(sales_report_skill(tenant_id="koinoti"))
    return build_platform(
        Settings(generator="fake", embedder="fake", store="memory"), registry=reg
    )


async def test_finance_gets_xlsx_artifact():
    plat = _platform()
    finance = Principal("koinoti", "fin", ("finance",))
    ans = await plat.orchestrator.ask(
        finance, "generate report store_id=5 format=xlsx"
    )
    assert "sales_report_file" in ans.skills_used
    assert len(ans.artifacts) == 1
    art = ans.artifacts[0]
    assert art.filename.endswith(".xlsx")
    assert art.content[:2] == b"PK"
    # the generated workbook really contains the verified figures
    zf = zipfile.ZipFile(io.BytesIO(art.content))
    sheet = zf.read("xl/worksheets/sheet1.xml").decode()
    assert "<v>18450</v>" in sheet
    # provenance surfaced, model never saw the bytes
    assert any("sales_view" in q for q in ans.queries_shown)


async def test_employee_cannot_generate_report():
    plat = _platform()
    emp = Principal("koinoti", "emp", ("employee",))
    ans = await plat.orchestrator.ask(
        emp, "generate report store_id=5 format=xlsx"
    )
    assert ans.skills_used == []
    assert ans.artifacts == []
