"""Document ingestion: extract text from real files (round-trips with writers)."""

import pytest

from karag.config import Settings
from karag.domain import DataClass, Principal
from karag.factory import build_platform
from karag.ingestion import extract_text
from karag.ingestion.readers import UnsupportedFormat
from karag.office.docx import build_docx
from karag.office.pptx import build_pptx
from karag.office.xlsx import build_xlsx


def test_extract_txt_md_csv():
    assert extract_text("a.txt", b"hello world") == "hello world"
    assert extract_text("a.md", b"# Title\n\nbody") == "# Title\n\nbody"
    assert "a, b" in extract_text("a.csv", b"a,b\n1,2")


def test_extract_docx_roundtrip():
    data = build_docx(title="Returns Policy", paragraphs=["Refund within 14 days."],
                      table_headers=["store", "total"], table_rows=[[5, 18450]])
    text = extract_text("doc.docx", data)
    assert "Returns Policy" in text
    assert "Refund within 14 days." in text
    assert "18450" in text


def test_extract_xlsx_roundtrip():
    data = build_xlsx({"Report": [["store", "total"], [5, 18450]]})
    text = extract_text("book.xlsx", data)
    assert "store" in text and "18450" in text


def test_extract_pptx_roundtrip():
    data = build_pptx([{"title": "Quarterly", "bullets": ["revenue up", "profit up"]}])
    text = extract_text("deck.pptx", data)
    assert "Quarterly" in text and "revenue up" in text


def test_unsupported_format():
    with pytest.raises(UnsupportedFormat):
        extract_text("photo.heic", b"...")


async def test_ingest_file_into_platform():
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    admin = Principal("koinoti", "admin", ("admin",))
    data = build_xlsx({"Sheet": [["metric", "value"], ["revenue", 4200000]]})
    doc = await plat.ingestion.ingest_file(
        admin, filename="q2.xlsx", data=data, data_class=DataClass.FINANCIAL
    )
    assert doc.metadata["filename"] == "q2.xlsx"
    assert await plat.store.count(tenant_id="koinoti") >= 1
