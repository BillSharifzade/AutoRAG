"""Minimal valid .xlsx writer (SpreadsheetML) using only the stdlib.

Supports multiple sheets, string cells (inline strings) and numeric cells.
Produced files open in Excel / LibreOffice / Google Sheets.
"""

from __future__ import annotations

from numbers import Real

from ._pkg import build_package, col_letter, root_rels, xml_escape

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    "{sheet_overrides}</Types>"
)

_SHEET_OVERRIDE = (
    '<Override PartName="/xl/worksheets/sheet{n}.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
)


def _is_number(v: object) -> bool:
    return isinstance(v, Real) and not isinstance(v, bool)


def _cell(ref: str, value: object) -> str:
    if value is None or value == "":
        return f'<c r="{ref}"/>'
    if _is_number(value):
        return f'<c r="{ref}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{xml_escape(value)}</t></is></c>'


def _sheet_xml(rows: list[list[object]]) -> str:
    body = []
    for r, row in enumerate(rows, start=1):
        cells = "".join(_cell(f"{col_letter(c)}{r}", v) for c, v in enumerate(row, start=1))
        body.append(f'<row r="{r}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(body)}</sheetData></worksheet>'
    )


def build_xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    """``sheets`` maps a sheet name to a list of rows (each a list of cells)."""
    if not sheets:
        sheets = {"Sheet1": []}

    names = list(sheets)
    overrides = "".join(_SHEET_OVERRIDE.format(n=i) for i in range(1, len(names) + 1))

    sheet_tags = "".join(
        f'<sheet name="{xml_escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, name in enumerate(names, start=1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheet_tags}</sheets></workbook>"
    )
    wb_rels_items = "".join(
        f'<Relationship Id="rId{i}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(names) + 1)
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{wb_rels_items}</Relationships>"
    )

    parts: dict[str, str | bytes] = {
        "[Content_Types].xml": _CONTENT_TYPES.format(sheet_overrides=overrides),
        "_rels/.rels": root_rels("xl/workbook.xml"),
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": wb_rels,
    }
    for i, name in enumerate(names, start=1):
        parts[f"xl/worksheets/sheet{i}.xml"] = _sheet_xml(sheets[name])
    return build_package(parts)
