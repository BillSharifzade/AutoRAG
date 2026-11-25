"""Extract plain text from documents for indexing.

OOXML formats are zip packages of XML; we pull the human-readable text nodes
(``w:t`` for Word, inline/shared strings for Excel, ``a:t`` for PowerPoint)
using stdlib XML parsing. Round-trips with ``karag.office`` writers and reads
real-world files too (Excel shared strings are handled).
"""

from __future__ import annotations

import csv
import io
import os
import re
import zipfile
from xml.etree import ElementTree as ET

from ..errors import KaragError

SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".docx", ".xlsx", ".pptx", ".pdf"}


class UnsupportedFormat(KaragError):
    pass


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text_of(data: bytes, wanted: set[str]) -> list[str]:
    """Return the concatenated text of every element whose local name is wanted."""
    out: list[str] = []
    root = ET.fromstring(data)
    for el in root.iter():
        if _localname(el.tag) in wanted and el.text:
            out.append(el.text)
    return out


def read_txt(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _looks_like_header(row: list[str]) -> bool:
    cells = [c.strip() for c in row]
    filled = [c for c in cells if c]
    if len(filled) < 2 or len(filled) < len(cells) * 0.6:
        return False
    numeric = sum(1 for c in filled if re.fullmatch(r"[-+]?[\d\s.,%]+", c))
    return numeric == 0


def rows_as_text(rows: list[list[str]]) -> str:
    """Spreadsheet rows as text that still makes sense one line at a time.

    With a header row, every data row becomes ``Header: value; Header: value``,
    so a passage cut from the middle of a long sheet still says what each
    number is. Without one, cells are joined with commas as before.
    """
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if len(rows) >= 2 and _looks_like_header(rows[0]):
        header = [c.strip() for c in rows[0]]
        lines = []
        for r in rows[1:]:
            pairs = [
                f"{header[i] or f'col{i + 1}'}: {v.strip()}"
                for i, v in enumerate(r) if (v or "").strip() and i < len(header)
            ]
            pairs += [v.strip() for v in r[len(header):] if (v or "").strip()]
            if pairs:
                lines.append("; ".join(pairs))
        return "\n".join(lines)
    return "\n".join(", ".join(r) for r in rows)


def read_csv(data: bytes) -> str:
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return rows_as_text(list(csv.reader(io.StringIO(text), dialect)))


_HEADING_STYLE = re.compile(r"^(?:heading|заголовок)\s*(\d)$", re.IGNORECASE)


def _heading_level(para) -> int:
    """1-6 for a Word heading paragraph (style or outline level), else 0."""
    for el in para.iter():
        name = _localname(el.tag)
        if name in ("pStyle", "outlineLvl"):
            val = next((v for k, v in el.attrib.items() if _localname(k) == "val"), "")
            if name == "outlineLvl" and val.isdigit() and int(val) < 6:
                return int(val) + 1
            if val.lower() in ("title", "заголовок"):
                return 1
            m = _HEADING_STYLE.match(val.replace(" ", ""))
            if m:
                return min(int(m.group(1)), 6)
            if val.isdigit() and 1 <= int(val) <= 6:  # localised Word style ids
                return int(val)
    return 0


def _para_text(para) -> str:
    return "".join(
        el.text for el in para.iter() if _localname(el.tag) == "t" and el.text
    )


def _docx_blocks(node, out: list[str]) -> None:
    for child in node:
        name = _localname(child.tag)
        if name == "p":
            text = _para_text(child)
            if text.strip():
                level = _heading_level(child)
                out.append(("#" * level + " " + text) if level else text)
        elif name == "tbl":
            rows = []
            for tr in child.iter():
                if _localname(tr.tag) != "tr":
                    continue
                cells = [
                    " ".join(_para_text(p) for p in tc.iter() if _localname(p.tag) == "p").strip()
                    for tc in tr if _localname(tc.tag) == "tc"
                ]
                if any(cells):
                    rows.append(cells)
            if rows:
                width = max(len(r) for r in rows)
                lines = ["| " + " | ".join(r + [""] * (width - len(r))) + " |" for r in rows]
                lines.insert(1, "|" + " --- |" * width)
                out.append("\n".join(lines))
        elif name not in ("sectPr",):
            _docx_blocks(child, out)  # sdt, customXml… — look inside


def read_docx(data: bytes) -> str:
    """Paragraphs in order, Word headings as Markdown ``#`` lines and tables
    as Markdown tables, so chunking can keep each passage's section."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        if "word/document.xml" not in zf.namelist():
            return ""
        root = ET.fromstring(zf.read("word/document.xml"))
        body = next((el for el in root if _localname(el.tag) == "body"), root)
        blocks: list[str] = []
        _docx_blocks(body, blocks)
        return "\n".join(blocks)


def read_pptx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        slides = sorted(
            n for n in zf.namelist()
            if re.match(r"ppt/slides/slide\d+\.xml$", n)
        )
        chunks: list[str] = []
        for name in slides:
            chunks.extend(_text_of(zf.read(name), {"t"}))
        return "\n".join(chunks)


def _sheet_names(zf: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(zf.read("xl/workbook.xml"))
    except KeyError:
        return []
    return [el.attrib.get("name", "") for el in root.iter() if _localname(el.tag) == "sheet"]


def read_xlsx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root:
                if _localname(si.tag) == "si":
                    shared.append("".join(
                        t.text or "" for t in si.iter() if _localname(t.tag) == "t"
                    ))
        sheets = sorted(
            (n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
            key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)),
        )
        titles = _sheet_names(zf)
        parts: list[str] = []
        for idx, sheet in enumerate(sheets):
            root = ET.fromstring(zf.read(sheet))
            rows: list[list[str]] = []
            for row in root.iter():
                if _localname(row.tag) != "row":
                    continue
                cells: list[str] = []
                for c in row:
                    if _localname(c.tag) != "c":
                        continue
                    ctype = c.attrib.get("t")
                    if ctype == "s":  # shared string index
                        v = next((x.text for x in c if _localname(x.tag) == "v"), None)
                        cells.append(shared[int(v)] if v is not None and v.isdigit() else "")
                    elif ctype == "inlineStr":
                        cells.append("".join(
                            t.text or "" for t in c.iter() if _localname(t.tag) == "t"
                        ))
                    else:  # number or plain
                        v = next((x.text for x in c if _localname(x.tag) == "v"), None)
                        cells.append(v or "")
                if any(cells):
                    rows.append(cells)
            if not rows:
                continue
            body = rows_as_text(rows)
            if len(sheets) > 1 or (idx < len(titles) and titles[idx]):
                name = titles[idx] if idx < len(titles) and titles[idx] else f"Sheet {idx + 1}"
                body = f"# {name}\n{body}"
            parts.append(body)
        return "\n\n".join(parts)


def read_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # noqa: PLC0415
    except ImportError as exc:
        raise UnsupportedFormat(
            "PDF ingestion requires pypdf: pip install pypdf"
        ) from exc
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def pdf_page_count(data: bytes) -> int:
    try:
        from pypdf import PdfReader  # noqa: PLC0415
    except ImportError:
        return 1
    try:
        return len(PdfReader(io.BytesIO(data)).pages)
    except Exception:  # noqa: BLE001 — a damaged file still gets one page
        return 1


_DISPATCH = {
    ".txt": read_txt,
    ".md": read_txt,
    ".csv": read_csv,
    ".docx": read_docx,
    ".xlsx": read_xlsx,
    ".pptx": read_pptx,
    ".pdf": read_pdf,
}


def extract_text(filename: str, data: bytes) -> str:
    ext = os.path.splitext(filename)[1].lower()
    reader = _DISPATCH.get(ext)
    if reader is None:
        raise UnsupportedFormat(f"unsupported file type: {ext or '(none)'}")
    return reader(data).strip()
