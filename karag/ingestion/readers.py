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


def read_csv(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    return "\n".join(", ".join(row) for row in reader)


def read_docx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        parts = [n for n in zf.namelist() if n == "word/document.xml" or
                 (n.startswith("word/") and n.endswith(".xml") and "document" in n)]
        chunks: list[str] = []
        for name in parts or ["word/document.xml"]:
            if name in zf.namelist():
                # each <w:p> is a paragraph -> join its runs, then newline
                root = ET.fromstring(zf.read(name))
                for para in root.iter():
                    if _localname(para.tag) == "p":
                        runs = [el.text for el in para.iter()
                                if _localname(el.tag) == "t" and el.text]
                        if runs:
                            chunks.append("".join(runs))
        return "\n".join(chunks)


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
        sheets = sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        lines: list[str] = []
        for sheet in sheets:
            root = ET.fromstring(zf.read(sheet))
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
                    lines.append(", ".join(cells))
        return "\n".join(lines)


def read_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # noqa: PLC0415
    except ImportError as exc:
        raise UnsupportedFormat(
            "PDF ingestion requires pypdf: pip install pypdf"
        ) from exc
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


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
