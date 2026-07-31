"""Office generation: files must be valid OOXML/zip and contain the data."""

import io
import zipfile

from karag.office import OfficeService
from karag.office.docx import build_docx
from karag.office.xlsx import build_xlsx


def _open(content: bytes) -> zipfile.ZipFile:
    assert content[:2] == b"PK"  # zip magic
    assert zipfile.is_zipfile(io.BytesIO(content))
    return zipfile.ZipFile(io.BytesIO(content))


def test_xlsx_is_valid_and_contains_data():
    content = build_xlsx({"Report": [["store", "total"], [5, 18450]]})
    zf = _open(content)
    names = set(zf.namelist())
    assert "[Content_Types].xml" in names
    assert "xl/workbook.xml" in names
    sheet = zf.read("xl/worksheets/sheet1.xml").decode()
    assert "store" in sheet  # inline string header
    assert "<v>18450</v>" in sheet  # numeric cell, not a string


def test_xlsx_multiple_sheets():
    content = build_xlsx({"A": [["x"]], "B": [["y"]]})
    zf = _open(content)
    assert "xl/worksheets/sheet2.xml" in zf.namelist()
    wb = zf.read("xl/workbook.xml").decode()
    assert 'name="A"' in wb and 'name="B"' in wb


def test_docx_is_valid_and_contains_text():
    content = build_docx(
        title="Q2 Report",
        paragraphs=["Summary line."],
        table_headers=["store", "total"],
        table_rows=[[5, 18450]],
    )
    zf = _open(content)
    doc = zf.read("word/document.xml").decode()
    assert "Q2 Report" in doc
    assert "Summary line." in doc
    assert "18450" in doc
    assert "<w:tbl>" in doc  # table present


def test_service_formats_and_filenames():
    svc = OfficeService()
    xlsx = svc.report(title="Sales / Q2", headers=["a"], rows=[[1]], fmt="xlsx")
    assert xlsx.filename == "Sales_Q2.xlsx"
    assert xlsx.mime.endswith("spreadsheetml.sheet")
    assert xlsx.content[:2] == b"PK"

    csv = svc.report(title="Sales", headers=["a", "b"], rows=[[1, 2]], fmt="csv")
    assert csv.content.decode().splitlines() == ["a,b", "1,2"]
    assert csv.filename == "Sales.csv"

    docx = svc.report(title="Doc", headers=["a"], rows=[[1]], fmt="docx")
    assert docx.mime.endswith("wordprocessingml.document")
