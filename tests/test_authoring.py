"""Authoring skills: model-composed content rendered to files by verified code."""

from karag.domain import DataClass, Principal
from karag.office.pdf import build_pdf
from karag.skills.authoring import authoring_skills

P = Principal("koinoti", "u1", ("employee",))


def _skill(name):
    return next(s for s in authoring_skills() if s.name == name)


async def test_write_file_produces_named_text_artifact():
    r = await _skill("write_file").handler(
        P, {"filename": "hello.py", "content": "print('hi')\n"}
    )
    assert r.artifact.filename == "hello.py"
    assert r.artifact.content == b"print('hi')\n"


async def test_write_file_forces_safe_text_extension():
    r = await _skill("write_file").handler(
        P, {"filename": "../evil.exe", "content": "x"}
    )
    assert "/" not in r.artifact.filename
    assert r.artifact.filename.endswith(".txt")


async def test_create_spreadsheet_xlsx_magic():
    r = await _skill("create_spreadsheet").handler(
        P, {"title": "Prices", "headers": ["sku", "price"], "rows": [["A", 10]]}
    )
    assert r.artifact.filename.endswith(".xlsx")
    assert r.artifact.content[:2] == b"PK"  # zip container


async def test_create_document_docx_magic():
    r = await _skill("create_document").handler(
        P, {"title": "Политика", "paragraphs": ["Абзац первый.", "Абзац второй."]}
    )
    assert r.artifact.filename.endswith(".docx")
    assert r.artifact.content[:2] == b"PK"


async def test_create_presentation_pptx_magic():
    r = await _skill("create_presentation").handler(
        P,
        {
            "title": "Roadmap",
            "slides": [{"title": "Q3", "bullets": ["Ship", "Sell"]}],
        },
    )
    assert r.artifact.filename.endswith(".pptx")
    assert r.artifact.content[:2] == b"PK"
    assert r.data["slides"] == 2  # cover + 1


async def test_create_pdf_valid_structure():
    r = await _skill("create_pdf").handler(
        P, {"title": "Summary", "paragraphs": ["Hello world. " * 200]}
    )
    pdf = r.artifact.content
    assert pdf.startswith(b"%PDF-1.4")
    assert b"%%EOF" in pdf
    assert pdf.count(b"/Type /Page ") >= 1


def test_pdf_multipage_and_escaping():
    pdf = build_pdf("T(itle)", ["line " * 40] * 120)
    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.count(b"/Type /Page ") > 1  # spilled onto multiple pages
    assert rb"T\(itle\)" in pdf


def test_authoring_skills_are_public_and_global():
    for s in authoring_skills():
        assert s.required_data_class == DataClass.PUBLIC
        assert s.tenant_id == "*"
        assert s.visible_to(P)
