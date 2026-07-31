"""Minimal valid .docx writer (WordprocessingML) using only the stdlib.

Supports a bold title, body paragraphs, and a simple table — enough for a
formatted business report. Produced files open in Word / LibreOffice.
"""

from __future__ import annotations

from ._pkg import build_package, root_rels, xml_escape

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)


def _run(text: str, *, bold: bool = False) -> str:
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{xml_escape(text)}</w:t></w:r>'


def _para(text: str, *, bold: bool = False) -> str:
    return f"<w:p>{_run(text, bold=bold)}</w:p>"


def _cell(text: str, *, bold: bool = False) -> str:
    return (
        "<w:tc><w:tcPr><w:tcW w:w=\"0\" w:type=\"auto\"/></w:tcPr>"
        f"<w:p>{_run(text, bold=bold)}</w:p></w:tc>"
    )


def _table(headers: list[str], rows: list[list[object]]) -> str:
    trs = []
    if headers:
        trs.append("<w:tr>" + "".join(_cell(str(h), bold=True) for h in headers) + "</w:tr>")
    for row in rows:
        trs.append("<w:tr>" + "".join(_cell("" if c is None else str(c)) for c in row) + "</w:tr>")
    borders = (
        "<w:tblBorders>"
        + "".join(
            f'<w:{edge} w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
            for edge in ("top", "left", "bottom", "right", "insideH", "insideV")
        )
        + "</w:tblBorders>"
    )
    return f"<w:tbl><w:tblPr>{borders}</w:tblPr>{''.join(trs)}</w:tbl>"


def build_docx(
    *,
    title: str | None = None,
    paragraphs: list[str] | None = None,
    table_headers: list[str] | None = None,
    table_rows: list[list[object]] | None = None,
) -> bytes:
    body_parts: list[str] = []
    if title:
        body_parts.append(_para(title, bold=True))
    for p in paragraphs or []:
        body_parts.append(_para(p))
    if table_headers or table_rows:
        body_parts.append(_table(table_headers or [], table_rows or []))
    body_parts.append("<w:sectPr/>")

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{"".join(body_parts)}</w:body></w:document>'
    )
    parts: dict[str, str | bytes] = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": root_rels("word/document.xml"),
        "word/document.xml": document,
    }
    return build_package(parts)
